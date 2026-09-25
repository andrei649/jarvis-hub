"""H586, the first review (review-H586) — its findings, pinned.

- m1: a slow vision model was reported as "no hub" after the client's 30 s. The describe
  call waits VISION_TIMEOUT (the hub gives the model 180 s), and a timeout after the
  status answered is a failed turn, not a missing hub.
- m2: the clipboard reader's output was buffered whole before the 4 MiB check. It is read
  up to the bound and the reader is killed past it.
- m3: an image the route refuses came back as "Unprocessable Entity", with the images
  echoed in the body. The route answers {error, reason} with the first reason only.
- m4: Windows PowerShell comes from the system directory, never the current one.
- m5: the survivors: a status without local or destination, the bounded read, exactly
  4 MiB, GIF87a, ~ paths, receipts on no-hub and interrupt, --json and plain empty
  answers, the argv per platform.
- m6: macOS without pngpaste (osascript) and WSL (PowerShell interop).
- nits: --remote-vision alone is refused; the address is compared as the hub names it;
  "the hub's machine"; the reply is checked like the HUD's.
"""

from __future__ import annotations

import base64
import json
import sys

import pytest

from agents.cli import nerva
from agents.cli.client import HubError, HubUnavailable
from tests.test_composer_vision import PNG, body, setup  # noqa: F401  (a fixture)
from tests.test_nerva_chat_image import LOCAL, PNG_BYTES, REMOTE, Fake, Routed, _run


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "shot.png"
    path.write_bytes(PNG_BYTES)
    return path


# ── m1: a slow model is not a missing hub ────────────────────────────────────────

def test_a_model_that_times_out_is_a_failed_turn_not_a_missing_hub(png, tmp_path):
    receipt = tmp_path / "u.json"
    hub = Fake(error=HubUnavailable("http://127.0.0.1:8080", "timed out"))
    code, out, err = _run(["-z", "--image", str(png), "--usage-file", str(receipt), "x"], hub)
    assert code == nerva.EXIT_FAILED and out == "" and "did not answer within 240 s" in err
    assert json.loads(receipt.read_text())["status"] == "failed"


def test_the_describe_call_waits_longer_than_the_hub_gives_the_model():
    assert nerva.VISION_TIMEOUT > 180


def test_the_client_passes_a_calls_own_timeout():
    from agents.cli.client import HubClient

    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    client = HubClient("http://127.0.0.1:8080", opener=lambda req, timeout: seen.append(timeout) or Response())
    client.post("/x", {}, timeout=240.0)
    client.post("/x", {})
    assert seen == [240.0, 30.0]


@pytest.mark.parametrize("where", ["status", "describe"])
def test_a_missing_hub_keeps_its_receipt(png, tmp_path, where):
    receipt = tmp_path / "u.json"

    class Gone(Fake):
        def get(self, path):
            if where == "status":
                raise HubUnavailable("http://127.0.0.1:8080", "refused")
            return super().get(path)

    hub = Gone(error=HubUnavailable("http://127.0.0.1:8080", "refused") if where == "describe" else None)
    code, _out, _err = _run(["-z", "--image", str(png), "--usage-file", str(receipt), "x"], hub)
    assert code == nerva.EXIT_NO_HUB and json.loads(receipt.read_text())["status"] == "no_hub"


def test_an_interrupt_keeps_its_receipt(png, tmp_path):
    receipt = tmp_path / "u.json"
    hub = Fake(error=KeyboardInterrupt())
    code, _out, _err = _run(["-z", "--image", str(png), "--usage-file", str(receipt), "x"], hub)
    assert code == nerva.EXIT_INTERRUPTED
    assert json.loads(receipt.read_text())["status"] == "interrupted"


# ── m2: the clipboard is bounded while it is read ────────────────────────────────

def test_a_reader_that_says_too_much_is_cut_off():
    code, out, why = nerva._run_reader(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * (8 << 20))"], 1024)
    assert len(out) == 1025 and why == "" and code is None


def test_the_bound_is_reached_without_waiting_for_the_reader_to_finish():
    # A reader that says too much and then keeps its pipe open: the read stops at the
    # bound, never waiting for an end that does not come.
    code, out, why = nerva._run_reader(
        [sys.executable, "-c",
         "import sys, time; sys.stdout.buffer.write(b'z' * 4096); sys.stdout.flush(); time.sleep(30)"],
        1024, deadline=5)
    assert len(out) == 1025 and why == ""


def test_a_reader_within_the_bound_is_read_whole():
    code, out, why = nerva._run_reader(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'y' * 100)"], 1024)
    assert (code, out, why) == (0, b"y" * 100, "")


def test_a_reader_that_hangs_is_killed_at_the_deadline():
    code, out, why = nerva._run_reader([sys.executable, "-c", "import time; time.sleep(30)"],
                                       1024, deadline=0.5)
    assert code is None and out == b"" and "did not answer within 0.5 s" in why


def test_a_reader_that_cannot_start_says_so():
    code, _out, why = nerva._run_reader(["/nonexistent/reader"], 10)
    assert code is None and "failed" in why


# ── m3: the route's refusal carries its reason, not the images ───────────────────

def test_a_raster_the_route_refuses_says_why(setup, tmp_path):  # noqa: F811
    bad = tmp_path / "trunc.png"
    bad.write_bytes(PNG_BYTES[:8] + b"\x00" * 64)                  # PNG magic, no image
    hub = Routed(setup.client)
    code, out, err = _run(["-z", "--image", str(bad), "what?"], hub)
    assert code == nerva.EXIT_FAILED and out == ""
    assert "invalid, animated or excessive raster image" in err and setup.calls == []


def test_the_routes_refusal_never_echoes_the_images(setup):  # noqa: F811
    payload = body(setup)
    payload["images"] = ["data:image/png;base64," + base64.b64encode(PNG_BYTES[:8] + b"\x00" * 4096).decode()]
    response = setup.client.post("/api/vlm/composer/describe", json=payload)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid, animated or excessive raster image",
                               "reason": "vlm_invalid_request"}


def test_the_client_reads_a_validation_reason():
    import io
    import urllib.error

    from agents.cli.client import _error_reason

    payload = json.dumps({"detail": [{"msg": "Value error, image exceeds 4 MiB", "input": "x" * 999}]})
    exc = urllib.error.HTTPError("http://h/x", 422, "Unprocessable Entity", {}, io.BytesIO(payload.encode()))
    assert _error_reason(exc) == "image exceeds 4 MiB"


# ── m4, m6: the reader per platform ──────────────────────────────────────────────

def _which(tools):
    return lambda name, path=None: f"/usr/bin/{name}" if name in tools else None


def test_windows_powershell_comes_from_the_system_directory():
    system = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    argv = nerva._clipboard_command("win32", {"SystemRoot": "C:\\Windows"}, _which({"powershell"}),
                                    exists=lambda path: path.replace("/", "\\") == system)
    assert argv[0].replace("/", "\\") == system
    assert argv[1:4] == ["-NoProfile", "-STA", "-Command"] and argv[4] == nerva._POWERSHELL_CLIPBOARD
    assert "ImageFormat]::Png" in argv[4] and "OpenStandardOutput" in argv[4]


def test_the_current_directory_is_never_searched_for_powershell(tmp_path, monkeypatch):
    # review-H586b B3: the PATH entries are walked directly; shutil.which would put the
    # current directory back on Windows whatever path it is given.
    monkeypatch.chdir(tmp_path)
    looked = []

    def exists(path):
        looked.append(path)
        return False

    env = {"PATH": f".{nerva.os.pathsep}{tmp_path}{nerva.os.pathsep}relative{nerva.os.pathsep}/opt/ps"}
    never = lambda *a, **k: pytest.fail("shutil.which must not be asked")  # noqa: E731
    assert nerva._clipboard_command("win32", env, never, exists=exists) is None
    searched = {nerva.os.path.dirname(p) for p in looked[1:]}           # [0] is the system copy
    assert searched == {"/opt/ps"}


def test_macos_without_pngpaste_uses_osascript():
    argv = nerva._clipboard_command("darwin", {}, _which({"osascript"}))
    assert argv == ["osascript", "-e", "the clipboard as «class PNGf»"]
    assert nerva._clipboard_command("darwin", {}, _which({"pngpaste", "osascript"})) == ["pngpaste", "-"]


def test_wsl_uses_windows_powershell_through_interop():
    argv = nerva._clipboard_command("linux", {}, _which(set()), wsl=True, exists=lambda p: True)
    assert argv[0] == nerva._WSL_POWERSHELL and argv[4] == nerva._POWERSHELL_CLIPBOARD
    assert nerva._clipboard_command("linux", {}, _which(set()), wsl=False, exists=lambda p: True) is None
    wayland = nerva._clipboard_command("linux", {"WAYLAND_DISPLAY": "w"}, _which({"wl-paste"}), wsl=True)
    assert wayland == ["wl-paste", "--no-newline", "--type", "image/png"]


def _clip(monkeypatch, argv, stdout, code=0):
    monkeypatch.setattr(nerva, "_clipboard_command", lambda *a, **k: argv)
    monkeypatch.setattr(nerva, "_run_reader", lambda argv, limit, deadline=10.0: (code, stdout[: limit + 1], ""))


def test_osascripts_hex_is_decoded(monkeypatch):
    _clip(monkeypatch, ["osascript", "-e", "x"], ("«data PNGf" + PNG_BYTES.hex().upper() + "»\n").encode())
    assert nerva._clipboard_image({}) == (PNG_BYTES, "")


@pytest.mark.parametrize("said", [b"", b"garbage", "«data TIFF0000»".encode(), "«data PNGfZZ»".encode()],
                         ids=["empty", "garbage", "tiff", "bad-hex"])
def test_osascript_without_a_png_is_no_image(monkeypatch, said):
    _clip(monkeypatch, ["osascript", "-e", "x"], said)
    raw, why = nerva._clipboard_image({})
    assert raw is None and "no image" in why


def test_osascripts_bound_counts_its_hex(monkeypatch):
    seen = []

    def reader(argv, limit, deadline=10.0):
        seen.append(limit)
        return 0, b"", ""

    monkeypatch.setattr(nerva, "_clipboard_command", lambda *a, **k: ["osascript", "-e", "x"])
    monkeypatch.setattr(nerva, "_run_reader", reader)
    nerva._clipboard_image({})
    monkeypatch.setattr(nerva, "_clipboard_command", lambda *a, **k: ["xclip"])
    nerva._clipboard_image({})
    assert seen == [2 * nerva.VISION_MAX_BYTES + 64, nerva.VISION_MAX_BYTES]


def test_a_reader_that_timed_out_is_named(monkeypatch):
    monkeypatch.setattr(nerva, "_clipboard_command", lambda *a, **k: ["xclip"])
    monkeypatch.setattr(nerva, "_run_reader", lambda *a, **k: (None, b"", "xclip did not answer within 10 s"))
    assert nerva._clipboard_image({}) == (None, "--clipboard-image: xclip did not answer within 10 s")


# ── m5: the survivors ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("missing", ["local", "destination", "binding"])
def test_an_incomplete_status_sends_nothing(png, missing):
    status = {k: v for k, v in REMOTE.items() if k != missing}
    hub = Fake(status=status)
    code, _out, err = _run(["-z", "--image", str(png), "x"], hub)
    assert code == nerva.EXIT_FAILED and "incomplete" in err and len(hub.calls) == 1


def test_an_image_of_exactly_4_mib_is_sent(tmp_path):
    exact = tmp_path / "exact.png"
    exact.write_bytes(PNG_BYTES[:8] + b"\x00" * (nerva.VISION_MAX_BYTES - 8))
    hub = Fake()
    assert _run(["-z", "--image", str(exact), "x"], hub)[0] == nerva.EXIT_OK


def test_the_file_is_read_no_further_than_the_bound(tmp_path, monkeypatch):
    big = tmp_path / "big.png"
    big.write_bytes(PNG_BYTES[:8] + b"\x00" * (3 * nerva.VISION_MAX_BYTES))
    sizes = []
    real = nerva.os.fdopen

    def fdopen(fd, mode):
        fh = real(fd, mode)
        read = fh.read

        class Spy:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                fh.close()
                return False

            def read(self, n=-1):
                sizes.append(n)
                return read(n)

        return Spy()

    monkeypatch.setattr(nerva.os, "fdopen", fdopen)
    raw, why = nerva._read_image(str(big))
    assert raw is None and "larger than 4 MiB" in why and sizes == [nerva.VISION_MAX_BYTES + 1]


def test_gif87a_and_a_home_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "old.gif").write_bytes(b"GIF87a" + b"\x00" * 16)
    hub = Fake()
    assert _run(["-z", "--image", "~/old.gif", "x"], hub)[0] == nerva.EXIT_OK
    assert hub.calls[1][2]["images"][0].startswith("data:image/gif;base64,")


def test_a_fifo_is_not_a_file_and_never_blocks(tmp_path):
    if not hasattr(nerva.os, "mkfifo"):
        pytest.skip("POSIX named pipes")
    fifo = tmp_path / "pipe.png"
    nerva.os.mkfifo(fifo)
    assert nerva._read_image(str(fifo)) == (None, f"--image {fifo}: not a file")


def test_an_empty_answer_without_z_exits_0_on_both_outputs(png):
    for flags in ([], ["--json"]):
        hub = Fake(answer="\x1b[2J ")
        code, _out, _err = _run([*flags, "--image", str(png), "x"], hub)
        assert code == nerva.EXIT_OK


def test_the_routes_own_403_is_a_failed_turn_not_an_auth_one(png):
    hub = Fake(error=HubError(403, "Acknowledge the remote vision destination"))
    code, _out, err = _run(["-z", "--image", str(png), "x"], hub)
    assert code == nerva.EXIT_FAILED and "Acknowledge" in err


# ── nits ─────────────────────────────────────────────────────────────────────────

def test_remote_vision_without_images_is_refused():
    hub = Fake()
    code, _out, err = _run(["-z", "--remote-vision", "https://vision.example/v1", "hi"], hub)
    assert code == nerva.EXIT_USAGE and "only to an image turn" in err and hub.calls == []


@pytest.mark.parametrize("spelling", ["https://vision.example/v1/", "HTTPS://Vision.Example/v1",
                                      "https://vision.example:443/v1"])
def test_the_acknowledgement_matches_the_address_as_the_hub_names_it(png, spelling):
    hub = Fake(status=REMOTE)
    assert _run(["-z", "--image", str(png), "--remote-vision", spelling, "x"], hub)[0] == nerva.EXIT_OK


@pytest.mark.parametrize("spelling", ["https://vision.example/v2", "http://vision.example/v1",
                                      "https://vision.example:8443/v1", "vision.example", ""])
def test_another_address_is_not_the_acknowledgement(png, spelling):
    hub = Fake(status=REMOTE)
    code, _out, _err = _run(["-z", "--image", str(png), "--remote-vision", spelling, "x"], hub)
    assert code == nerva.EXIT_USAGE and all(p != "/api/vlm/composer/describe" for _m, p, _b in hub.calls)


def test_an_acknowledgement_for_a_local_model_is_noted(png):
    code, _out, err = _run(["-z", "--image", str(png), "--remote-vision", "https://x.example/", "x"], Fake(status=LOCAL))
    assert code == nerva.EXIT_OK and "not needed" in err


@pytest.mark.parametrize("reply", [None, "text", {"ok": False, "response": "x"}, {"ok": True},
                                   {"ok": True, "response": 5}])
def test_a_malformed_reply_is_a_failed_turn(png, reply):
    class Odd(Fake):
        def post(self, path, body=None, *, timeout=None):
            self.calls.append(("POST", path, body))
            return reply

    code, out, err = _run(["-z", "--image", str(png), "x"], Odd())
    assert code == nerva.EXIT_FAILED and out == "" and "malformed" in err


def test_an_answer_past_the_display_limit_is_refused(png):
    hub = Fake(answer="a" * (nerva.VISION_MAX_ANSWER + 1))
    code, out, err = _run(["-z", "--image", str(png), "x"], hub)
    assert code == nerva.EXIT_FAILED and out == "" and "128 KiB" in err
    assert _run(["-z", "--image", str(png), "x"], Fake(answer="a" * nerva.VISION_MAX_ANSWER))[0] == nerva.EXIT_OK
