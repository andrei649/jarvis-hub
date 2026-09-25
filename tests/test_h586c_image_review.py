"""H586, the second review (review-H586b) — its findings, pinned.

- B1: a clipboard image cut off at the bound read as "no image". It is "larger than
  4 MiB" again.
- B2: a descendant of the reader holding the pipe stretched the 10 s deadline. On POSIX
  the reader runs in its own session, the pipe is read against a monotonic deadline,
  and the whole group is killed; an interrupt kills it too.
- B3: the Windows fallback walks the absolute PATH entries itself (shutil.which puts the
  current directory back on Windows).
- B4: the survivors: the status read's 403 and failures, the --json receipt, the real
  reader's exit code and kill, WSL detection.
- nits: hub text filtered; a user name, query or fragment in --remote-vision refused; a
  receipt on an interrupted clipboard read; the field in a validation reason.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

from agents.cli import nerva
from agents.cli.client import HubError
from tests.test_nerva_chat_image import PNG_BYTES, REMOTE, Fake, _run

posix = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "shot.png"
    path.write_bytes(PNG_BYTES)
    return path


# ── B1 ───────────────────────────────────────────────────────────────────────────

def test_a_clipboard_image_over_the_bound_says_so(monkeypatch):
    monkeypatch.setattr(nerva, "_clipboard_command", lambda *a, **k: ["xclip"])
    over = PNG_BYTES[:8] + b"\x00" * nerva.VISION_MAX_BYTES
    monkeypatch.setattr(nerva, "_run_reader", lambda argv, limit, deadline=10.0: (None, over[: limit + 1], ""))
    assert nerva._clipboard_image({}) == (None, "--clipboard-image: the image is larger than 4 MiB")


@posix
def test_a_real_reader_over_the_bound_says_larger(monkeypatch, tmp_path):
    reader = tmp_path / "xclip"
    reader.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write({PNG_BYTES[:8]!r} + b'0' * (5 << 20))\n")
    reader.chmod(0o755)
    monkeypatch.setattr(nerva, "_clipboard_command", lambda *a, **k: [str(reader)])
    raw, why = nerva._clipboard_image({})
    assert raw is None and "larger than 4 MiB" in why


# ── B2 ───────────────────────────────────────────────────────────────────────────

@posix
def test_a_descendant_holding_the_pipe_never_stretches_the_deadline():
    started = time.monotonic()
    code, out, why = nerva._run_reader(["/bin/sh", "-c", "printf abc; (sleep 20) & sleep 20"], 1024, deadline=1)
    assert time.monotonic() - started < 6
    assert code is None and "did not answer within 1 s" in why


@posix
def test_a_reader_that_exits_with_a_descendant_still_holding_the_pipe_is_cut(tmp_path):
    started = time.monotonic()
    code, out, why = nerva._run_reader(["/bin/sh", "-c", "printf abc; (sleep 20) & exit 0"], 1024, deadline=1)
    assert time.monotonic() - started < 6 and "did not answer" in why


@posix
def test_the_whole_group_is_killed(tmp_path):
    marker = tmp_path / "alive"
    script = f"(sleep 3; touch {marker}) & sleep 30"
    nerva._run_reader(["/bin/sh", "-c", script], 1024, deadline=0.5)
    time.sleep(4)
    assert not marker.exists()                        # the descendant died with its group


@posix
def test_the_real_reader_exit_code_is_returned():
    code, out, why = nerva._run_reader([sys.executable, "-c", "import sys; sys.stdout.write('x'); sys.exit(3)"], 10)
    assert (code, out, why) == (3, b"x", "")


@posix
def test_a_reader_past_the_bound_is_killed(tmp_path):
    marker = tmp_path / "after"
    code, out, why = nerva._run_reader(
        [sys.executable, "-c",
         f"import sys, time, pathlib; sys.stdout.buffer.write(b'z' * 4096); sys.stdout.flush(); "
         f"time.sleep(2); pathlib.Path({str(marker)!r}).touch()"], 1024, deadline=10)
    time.sleep(3)
    assert len(out) == 1025 and why == "" and not marker.exists()


@posix
def test_an_interrupt_kills_the_reader(tmp_path, monkeypatch):
    import selectors

    marker = tmp_path / "after"
    real = selectors.DefaultSelector

    class Interrupting(real):
        def select(self, timeout=None):
            raise KeyboardInterrupt

    monkeypatch.setattr(selectors, "DefaultSelector", Interrupting)
    with pytest.raises(KeyboardInterrupt):
        nerva._run_reader([sys.executable, "-c",
                           f"import time, pathlib; time.sleep(2); pathlib.Path({str(marker)!r}).touch()"],
                          10, deadline=10)
    time.sleep(3)
    assert not marker.exists()


# ── B3 ───────────────────────────────────────────────────────────────────────────

def test_the_windows_fallback_finds_pwsh_in_an_absolute_entry(tmp_path):
    ps = tmp_path / "ps" / "pwsh.exe"
    env = {"PATH": f"{tmp_path / 'none'}{os.pathsep}{tmp_path / 'ps'}", "SystemRoot": str(tmp_path / "win")}
    argv = nerva._clipboard_command("win32", env, lambda *a, **k: pytest.fail("no which"),
                                    exists=lambda p: p == str(ps))
    assert argv[0] == str(ps)


# ── B4 ───────────────────────────────────────────────────────────────────────────

class StatusFails(Fake):
    def __init__(self, error):
        super().__init__()
        self.status_error = error

    def get(self, path):
        self.calls.append(("GET", path, None))
        raise self.status_error


def test_a_refused_status_read_is_an_auth_exit(png, tmp_path):
    receipt = tmp_path / "u.json"
    code, _out, _err = _run(["-z", "--image", str(png), "--usage-file", str(receipt), "x"],
                            StatusFails(HubError(403, "user routes disabled from network")))
    assert code == nerva.EXIT_AUTH and json.loads(receipt.read_text())["status"] == "unauthorised"


@pytest.mark.parametrize("status", [404, 500])
def test_a_failed_status_read_is_a_failed_turn_with_a_receipt(png, tmp_path, status):
    receipt = tmp_path / "u.json"
    code, _out, err = _run(["-z", "--image", str(png), "--usage-file", str(receipt), "x"],
                           StatusFails(HubError(status, "no such route")))
    assert code == nerva.EXIT_FAILED and "no such route" in err
    assert json.loads(receipt.read_text())["status"] == "failed"


def test_an_empty_json_answer_is_not_completed_in_the_receipt(png, tmp_path):
    receipt = tmp_path / "u.json"
    code, _out, _err = _run(["--json", "--image", str(png), "--usage-file", str(receipt), "x"], Fake(answer=" "))
    report = json.loads(receipt.read_text())
    assert code == nerva.EXIT_OK and report["completed"] is False and report["status"] == "refused"


@pytest.mark.parametrize("text,wsl", [("Linux version 5.15.90.1-microsoft-standard-WSL2", True),
                                      ("Linux version 6.8.0-generic", False)])
def test_wsl_is_read_from_proc_version(monkeypatch, text, wsl):
    from pathlib import Path

    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if str(self) == "/proc/version":
            return text
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert nerva._is_wsl() is wsl


def test_wsl_falls_back_to_the_path_powershell():
    argv = nerva._clipboard_command("linux", {}, lambda name, path=None: f"/c/{name}" if name == "powershell.exe" else None,
                                    wsl=True, exists=lambda p: False)
    assert argv[0] == "/c/powershell.exe"


# ── nits ─────────────────────────────────────────────────────────────────────────

def test_hub_text_is_filtered_before_the_terminal(png):
    code, _out, err = _run(["-z", "--image", str(png), "x"], Fake(error=HubError(502, "\x1b]0;pwned\x07\x1b[2Jbad")))
    assert code == nerva.EXIT_FAILED and "\x1b" not in err and "\x07" not in err and "bad" in err


@pytest.mark.parametrize("spelling", ["https://127.0.0.1@vision.example/v1", "https://u:p@vision.example/v1",
                                      "https://vision.example/v1?x=1", "https://vision.example/v1#f"])
def test_a_look_alike_acknowledgement_is_refused(png, spelling):
    hub = Fake(status=REMOTE)
    code, _out, err = _run(["-z", "--image", str(png), "--remote-vision", spelling, "x"], hub)
    assert code == nerva.EXIT_USAGE and hub.calls == [] and "plain http(s) address" in err


def test_an_interrupted_clipboard_read_keeps_its_receipt(monkeypatch, tmp_path):
    receipt = tmp_path / "u.json"

    def interrupted(environ):
        raise KeyboardInterrupt

    monkeypatch.setattr(nerva, "_clipboard_image", interrupted)
    code, _out, _err = _run(["-z", "--clipboard-image", "--usage-file", str(receipt), "x"], Fake())
    assert code == nerva.EXIT_INTERRUPTED and json.loads(receipt.read_text())["status"] == "interrupted"


def test_a_validation_reason_names_its_field():
    import io
    import urllib.error

    from agents.cli.client import _error_reason

    payload = json.dumps({"detail": [{"loc": ["body", "prompt"], "msg": "Field required"}]})
    exc = urllib.error.HTTPError("http://h/x", 422, "Unprocessable Entity", {}, io.BytesIO(payload.encode()))
    assert _error_reason(exc) == "prompt: Field required"
