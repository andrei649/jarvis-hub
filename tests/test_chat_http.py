"""HTTP integration tests for POST /chat and POST /chat/stream.

Covers the SSE event format, agent override, error handling, and the 503
response when the orchestrator has not been initialised.
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NO_ORCH_CLIENT = TestClient(web.app)  # no lifespan → orch stays None


def _parse_sse(text: str) -> list[dict]:
    """Return a list of parsed JSON objects from SSE response body."""
    events = []
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data: "):
            payload = chunk[len("data: "):]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


def _mock_orch_with_stream(tokens: list[str], full: str | None = None) -> MagicMock:
    """Build a minimal mock Orchestrator whose handle_input_stream emits *tokens*."""
    m = MagicMock()
    m.agents = {}
    m.observer = None

    expected_full = full if full is not None else "".join(tokens)

    async def _stream(message, channel, on_token, agent_override=None):
        for tok in tokens:
            await on_token(tok)
        return expected_full

    m.handle_input_stream = _stream
    return m


# ---------------------------------------------------------------------------
# POST /chat — no orchestrator
# ---------------------------------------------------------------------------

def test_chat_no_orch_returns_not_initialized():
    resp = _NO_ORCH_CLIENT.post("/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "Jarvis not initialized."


# ---------------------------------------------------------------------------
# POST /chat — with mocked orchestrator
# ---------------------------------------------------------------------------

def test_chat_with_mock_orch_returns_reply(monkeypatch):
    mock = MagicMock()
    mock.handle_input = AsyncMock(return_value="Salut!")
    monkeypatch.setattr(web, "orch", mock)

    client = TestClient(web.app)
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "Salut!"


def test_chat_agent_override_not_jarvis(monkeypatch):
    mock = MagicMock()
    mock.handle_input = AsyncMock(return_value="Friday here.")
    monkeypatch.setattr(web, "orch", mock)

    client = TestClient(web.app)
    client.post("/chat", json={"message": "hi", "agent": "friday"})
    _, kwargs = mock.handle_input.call_args
    assert kwargs.get("agent_override") == "friday"


def test_chat_agent_jarvis_passes_no_override(monkeypatch):
    mock = MagicMock()
    mock.handle_input = AsyncMock(return_value="Jarvis here.")
    monkeypatch.setattr(web, "orch", mock)

    client = TestClient(web.app)
    client.post("/chat", json={"message": "hi", "agent": "jarvis"})
    _, kwargs = mock.handle_input.call_args
    assert kwargs.get("agent_override") is None


# ---------------------------------------------------------------------------
# POST /chat/stream — no orchestrator
# ---------------------------------------------------------------------------

def test_chat_stream_no_orch_returns_503():
    resp = _NO_ORCH_CLIENT.post("/chat/stream", json={"message": "hello"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /chat/stream — SSE event format
# ---------------------------------------------------------------------------

def test_chat_stream_content_type_is_event_stream(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream(["Hi"]))
    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hello"})
    assert "text/event-stream" in resp.headers.get("content-type", "")


def test_chat_stream_first_event_is_start(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream(["Hi"]))
    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hello"})
    events = _parse_sse(resp.text)
    assert events[0]["type"] == "start"


def test_chat_stream_emits_token_events(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream(["Hello", " world"]))
    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hello"})
    events = _parse_sse(resp.text)
    token_events = [e for e in events if e.get("type") == "token"]
    assert len(token_events) == 2
    assert token_events[0]["text"] == "Hello"
    assert token_events[1]["text"] == " world"


def test_chat_stream_last_event_is_end(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream(["Hi"], full="Hi"))
    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hello"})
    events = _parse_sse(resp.text)
    last = events[-1]
    assert last["type"] == "end"
    assert last["text"] == "Hi"


def test_chat_stream_end_event_carries_agent(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream(["x"]))
    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hi", "agent": "friday"})
    events = _parse_sse(resp.text)
    end_event = next(e for e in events if e.get("type") == "end")
    assert end_event["agent"] == "friday"


def test_chat_stream_error_produces_end_event(monkeypatch):
    mock = MagicMock()
    mock.agents = {}
    mock.observer = None

    async def _raising_stream(message, channel, on_token, agent_override=None):
        raise RuntimeError("boom")

    mock.handle_input_stream = _raising_stream
    monkeypatch.setattr(web, "orch", mock)

    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hello"})
    events = _parse_sse(resp.text)
    assert any(e.get("type") == "end" for e in events)


def test_chat_stream_no_tokens_still_ends(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream([], full="direct"))
    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hi"})
    events = _parse_sse(resp.text)
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "end"
    assert events[-1]["text"] == "direct"
