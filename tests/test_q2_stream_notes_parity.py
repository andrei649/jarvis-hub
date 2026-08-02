"""Q2 — /chat/stream parity with /chat: session notes injected; constant errors.

/chat prepends the session's notes block (H10.21) before handing the message
to the orchestrator, but /chat/stream — the cockpit's only chat path — passed
``req.message`` raw, so persistent notes silently stopped applying the moment
the HUD switched to streaming. Same-file honesty ride-along: both chat error
paths returned live exception text to the client (the py/stack-trace-exposure
family that blocked #750) — now constant, specifics kept in the server log.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from starlette.testclient import TestClient  # noqa: E402


def _payload(chunk: str) -> dict:
    import json

    return json.loads(chunk.removeprefix("data: ").strip())


def test_stream_injects_session_notes_like_chat():
    from agents import web

    with TestClient(web.app) as c:
        if getattr(web.orch, "notes", None) is None:
            return
        sid = getattr(web.orch, "session_id", "web")
        web.orch.notes.clear(sid)
        assert c.put("/api/notes", json={"content": "always reply in French"}).status_code == 200

        captured = {}

        async def fake_stream(message, channel="web", on_token=None, agent_override=None):
            captured["msg"] = message
            return "ok"

        orig = web.orch.handle_input_stream
        web.orch.handle_input_stream = fake_stream
        try:
            r = c.post("/chat/stream", json={"message": "hello"})
            assert r.status_code == 200
            assert "[Session notes]" in captured["msg"], (
                "the stream path must inject the same notes block /chat does"
            )
            assert "always reply in French" in captured["msg"]
            assert captured["msg"].endswith("hello")
        finally:
            web.orch.handle_input_stream = orig
            web.orch.notes.clear(sid)


def test_chat_error_reply_is_constant_never_exception_text():
    from agents import web

    with TestClient(web.app) as c:
        async def boom(message, channel="web", agent_override=None):
            raise RuntimeError("secret-token-xyz")

        orig = web.orch.handle_input
        web.orch.handle_input = boom
        try:
            r = c.post("/chat", json={"message": "hello"})
            assert r.status_code == 200
            reply = r.json()["reply"]
            assert reply == "Internal error."
            assert "secret-token-xyz" not in reply
        finally:
            web.orch.handle_input = orig


async def test_stream_error_event_is_constant_never_exception_text():
    from agents import web

    class FakeOrch:
        async def handle_input_stream(self, message, channel, on_token, agent_override=None):
            raise RuntimeError("secret-token-xyz")

    events = [_payload(c) async for c in web._chat_event_stream(FakeOrch(), "hi", "jarvis", None)]

    assert events[-1]["type"] == "end"
    assert events[-1]["text"] == "Eroare internă."
    assert "secret-token-xyz" not in events[-1]["text"]
