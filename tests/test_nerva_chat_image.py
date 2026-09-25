"""H586 — the terminal's image turn: `nerva chat --image PATH` and `--clipboard-image`.

The HUD composer's vision turn, from a terminal: the images and the question go to the
hub's vision route (POST /api/vlm/composer/describe) and never to /chat, the destination
the hub reports is bound into the request, and a destination off this machine is used
only when --remote-vision names it.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.cli import nerva
from agents.cli.client import HubError
from tests.test_composer_vision import PNG, setup  # noqa: F401  (a fixture)

PNG_BYTES = base64.b64decode(PNG.partition(",")[2])
GIF_BYTES = b"GIF89a" + b"\x00" * 16
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 "
LOCAL = {"configured": True, "destination": "http://127.0.0.1:1234/v1", "binding": "b" * 64,
         "model": "vision-test", "backend": "custom", "local": True, "reachable": None}
REMOTE = {**LOCAL, "destination": "https://vision.example/v1", "local": False}


class Fake:
    """A hub that records every request."""

    def __init__(self, status=LOCAL, answer="A screenshot.", error=None):
        self.status, self.answer, self.error = status, answer, error
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        return self.status

    def post(self, path, body=None, *, timeout=None):
        self.calls.append(("POST", path, body))
        self.timeout = timeout
        if self.error:
            raise self.error
        return {"ok": True, "response": self.answer, "model": "vision-test", "local": True}


class Routed:
    """The CLI's client over the real app (TestClient), errors as HubError."""

    def __init__(self, client):
        self.client, self.paths = client, []

    def _answer(self, response):
        if response.status_code >= 400:
            raise HubError(response.status_code, response.json().get("error", ""))
        return response.json()

    def get(self, path):
        self.paths.append(path)
        return self._answer(self.client.get(path))

    def post(self, path, body=None, *, timeout=None):
        self.paths.append(path)
        return self._answer(self.client.post(path, json=body))


def _run(argv, hub, environ=None):
    out, err = io.StringIO(), io.StringIO()
    ctx = nerva.Context(environ=environ or {}, out=out, err=err, client_factory=lambda env: hub)
    code = nerva.main(["chat", *argv], context=ctx)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "shot.jpg"                     # the name says JPEG; the bytes are PNG
    path.write_bytes(PNG_BYTES)
    return path


# ── the turn ─────────────────────────────────────────────────────────────────────

def test_an_image_turn_goes_to_the_vision_route_never_to_chat(png):
    hub = Fake()
    code, out, err = _run(["-z", "--image", str(png), "what is shown?"], hub)
    assert code == nerva.EXIT_OK and out == "A screenshot.\n"
    assert [(m, p) for m, p, _ in hub.calls] == [("GET", "/api/vlm/composer/status"),
                                                 ("POST", "/api/vlm/composer/describe")]
    body = hub.calls[1][2]
    assert body["images"] == [PNG] and body["prompt"] == "what is shown?"
    assert body["expected_destination"] == LOCAL["destination"] and body["expected_binding"] == "b" * 64
    assert body["remote_ack"] is False
    assert "vision-test" in err and "on the hub's machine" in err
    assert hub.timeout == nerva.VISION_TIMEOUT


def test_the_real_route_answers_the_cli(setup, png):  # noqa: F811
    hub = Routed(setup.client)
    code, out, _err = _run(["-z", "--image", str(png), "what is shown?"], hub)
    assert code == nerva.EXIT_OK and out == "A screenshot.\n"
    assert "/chat" not in hub.paths
    assert setup.calls and setup.calls[0][3] == "what is shown?" and setup.calls[0][4] == [PNG_BYTES]


def test_a_model_changed_in_between_is_refused_by_the_route(setup, png, monkeypatch):  # noqa: F811
    hub = Routed(setup.client)
    real_get = hub.get

    def get(path):
        answer = real_get(path)
        setup.config = replace(setup.config, model="another-model")   # changed after the review
        return answer

    monkeypatch.setattr(hub, "get", get)
    code, out, err = _run(["-z", "--image", str(png), "what is shown?"], hub)
    assert code == nerva.EXIT_FAILED and out == "" and "changed" in err
    assert setup.calls == []


def test_every_image_kind_is_sent_as_its_bytes_say(tmp_path):
    paths = []
    for name, raw in (("a.png", PNG_BYTES), ("b.gif", GIF_BYTES), ("c.webp", WEBP_BYTES),
                      ("d.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 8)):
        (tmp_path / name).write_bytes(raw)
        paths += ["--image", str(tmp_path / name)]
    hub = Fake()
    assert _run(["-z", *paths, "compare"], hub)[0] == nerva.EXIT_OK
    kinds = [uri.partition(";")[0] for uri in hub.calls[1][2]["images"]]
    assert kinds == ["data:image/png", "data:image/gif", "data:image/webp", "data:image/jpeg"]


# ── a destination off this machine ───────────────────────────────────────────────

def test_a_remote_destination_is_refused_without_its_acknowledgement(png):
    hub = Fake(status=REMOTE)
    code, out, err = _run(["-z", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_USAGE and out == ""
    assert "https://vision.example/v1" in err and "--remote-vision" in err
    assert all(path != "/api/vlm/composer/describe" for _m, path, _b in hub.calls)


def test_a_remote_acknowledgement_names_the_destination(png):
    hub = Fake(status=REMOTE)
    code, _out, _err = _run(["-z", "--image", str(png), "--remote-vision", "https://other.example/v1",
                             "what?"], hub)
    assert code == nerva.EXIT_USAGE and len(hub.calls) == 1
    code, out, err = _run(["-z", "--image", str(png), "--remote-vision", "https://vision.example/v1",
                           "what?"], hub)
    assert code == nerva.EXIT_OK and out == "A screenshot.\n" and "off the hub's machine" in err
    assert hub.calls[-1][2]["remote_ack"] is True


# ── refusals before any request ──────────────────────────────────────────────────

@pytest.mark.parametrize("flag", [["--agent", "athena"], ["--session", "s1"], ["--reasoning", "low"]])
def test_an_image_turn_takes_no_agent_session_or_reasoning(png, flag):
    hub = Fake()
    code, _out, err = _run(["-z", "--image", str(png), *flag, "what?"], hub)
    assert code == nerva.EXIT_USAGE and hub.calls == [] and flag[0] in err


def test_files_that_are_not_images_are_refused(tmp_path):
    text = tmp_path / "notes.png"
    text.write_text("not an image")
    big = tmp_path / "big.png"
    big.write_bytes(PNG_BYTES[:8] + b"\x00" * nerva.VISION_MAX_BYTES)
    wav = tmp_path / "sound.webp"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")              # RIFF, but not WebP
    for path, said in ((text, "not a PNG"), (wav, "not a PNG"), (big, "larger than 4 MiB"),
                       (tmp_path / "missing.png", "not a file"), (tmp_path, "not a file")):
        hub = Fake()
        code, _out, err = _run(["-z", "--image", str(path), "what?"], hub)
        assert code == nerva.EXIT_USAGE and said in err and hub.calls == []


def test_at_most_eight_images(png):
    hub = Fake()
    code, _out, err = _run(["-z", *(["--image", str(png)] * 9), "what?"], hub)
    assert code == nerva.EXIT_USAGE and "up to 8" in err and hub.calls == []
    assert _run(["-z", *(["--image", str(png)] * 8), "what?"], hub)[0] == nerva.EXIT_OK


def test_the_question_is_bounded_as_the_route_bounds_it(png):
    hub = Fake()
    code, _out, err = _run(["-z", "--image", str(png), "x" * 4001], hub)
    assert code == nerva.EXIT_USAGE and "4,000" in err and hub.calls == []
    assert _run(["-z", "--image", str(png), "x" * 4000], hub)[0] == nerva.EXIT_OK


# ── what the hub answers ─────────────────────────────────────────────────────────

def test_no_vision_model_is_a_failed_turn(png):
    hub = Fake(status={"configured": False, "reason": "vlm_not_configured"})
    code, out, err = _run(["-z", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_FAILED and out == "" and "no vision model" in err
    assert len(hub.calls) == 1


def test_a_route_refusal_is_a_failed_turn_with_its_reason(png):
    hub = Fake(error=HubError(502, "Vision analysis failed"))
    code, out, err = _run(["-z", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_FAILED and out == "" and "Vision analysis failed" in err


def test_an_unauthorised_turn_exits_as_one(png):
    hub = Fake(error=HubError(401, "user token required"))
    code, _out, _err = _run(["-z", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_AUTH


def test_an_empty_answer_is_not_an_answer(png):
    hub = Fake(answer="\x1b[2J  ")
    code, out, err = _run(["-z", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_FAILED and out == "" and "empty answer" in err


def test_the_receipt_and_json(png, tmp_path):
    receipt = tmp_path / "spend.json"
    hub = Fake()
    assert _run(["-z", "--image", str(png), "--usage-file", str(receipt), "what?"], hub)[0] == nerva.EXIT_OK
    report = json.loads(receipt.read_text())
    assert report["status"] == "completed" and report["completed"] is True
    code, out, _err = _run(["--json", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_OK and json.loads(out)["response"] == "A screenshot."


# ── the clipboard ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("platform,environ,tools,first", [
    ("darwin", {}, {"pngpaste"}, "pngpaste"),
    ("win32", {"PATH": "/opt/ps"}, {"powershell"}, "powershell"),
    ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, {"wl-paste", "xclip"}, "wl-paste"),
    ("linux", {"DISPLAY": ":0"}, {"wl-paste", "xclip"}, "xclip"),
    ("linux", {}, {"wl-paste", "xclip"}, None),
    ("darwin", {}, set(), None),
])
def test_the_clipboard_reader_is_the_platforms_own(platform, environ, tools, first):
    argv = nerva._clipboard_command(platform, environ,
                                    lambda name, path=None: f"/bin/{name}" if name in tools else None,
                                    exists=lambda path: (platform.startswith("win") and "powershell" in tools
                                                         and path.endswith("powershell.exe")))
    assert (argv[0].replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".exe") if argv else None) == first


def _clipboard(monkeypatch, stdout, returncode=0):
    import shutil

    ran = []

    def reader(argv, limit, deadline=10.0):
        ran.append((argv, limit, deadline))
        return returncode, stdout[: limit + 1], ""

    monkeypatch.setattr(nerva.sys, "platform", "linux")
    monkeypatch.setattr(nerva, "_is_wsl", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda name, path=None: f"/usr/bin/{name}")
    monkeypatch.setattr(nerva, "_run_reader", reader)
    return ran


def test_the_clipboard_image_is_attached(monkeypatch):
    ran = _clipboard(monkeypatch, PNG_BYTES)
    hub = Fake()
    code, out, _err = _run(["-z", "--clipboard-image", "what?"], hub, environ={"DISPLAY": ":0"})
    assert code == nerva.EXIT_OK and out == "A screenshot.\n"
    assert hub.calls[1][2]["images"] == [PNG]
    argv, limit, deadline = ran[0]
    assert argv == ["xclip", "-selection", "clipboard", "-target", "image/png", "-out"]
    assert limit == nerva.VISION_MAX_BYTES and deadline == 10.0


@pytest.mark.parametrize("stdout,returncode,said", [
    (b"", 1, "holds no image"),
    (PNG_BYTES, 1, "holds no image"),                   # a reader that failed says nothing true
    (b"plain text", 0, "not a PNG"),
    (PNG_BYTES[:8] + b"\x00" * nerva.VISION_MAX_BYTES, 0, "larger than 4 MiB"),
], ids=["empty", "failed", "text", "big"])
def test_a_clipboard_without_an_image_is_refused(monkeypatch, stdout, returncode, said):
    _clipboard(monkeypatch, stdout, returncode)
    hub = Fake()
    code, _out, err = _run(["-z", "--clipboard-image", "what?"], hub, environ={"DISPLAY": ":0"})
    assert code == nerva.EXIT_USAGE and said in err and hub.calls == []


def test_no_clipboard_reader_says_what_to_do(monkeypatch):
    import shutil

    monkeypatch.setattr(nerva.sys, "platform", "linux")
    monkeypatch.setattr(nerva, "_is_wsl", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda name, path=None: None)
    code, _out, err = _run(["-z", "--clipboard-image", "what?"], Fake(), environ={})
    assert code == nerva.EXIT_USAGE and "--image PATH" in err


def test_a_turn_without_images_is_unchanged():
    class Chat(Fake):
        def post(self, path, body=None, *, timeout=None):
            self.calls.append(("POST", path, body))
            return {"reply": "hello"}

    hub = Chat()
    code, out, _err = _run(["-z", "hi"], hub)
    assert code == nerva.EXIT_OK and out == "hello\n" and [p for _m, p, _b in hub.calls] == ["/chat"]
