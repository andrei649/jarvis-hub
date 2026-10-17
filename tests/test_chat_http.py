"""HTTP integration tests for POST /chat and POST /chat/stream.

Covers the SSE event format, agent override, error handling, and the 503
response when the orchestrator has not been initialised.
"""
import asyncio
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web
from agents.core.checkpoint import CheckpointManager

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


def _mock_orch() -> MagicMock:
    """A chat fake still has the real durable session-status authority."""
    mock = MagicMock()
    mock.session_id = "test_session"
    mock.checkpoints = CheckpointManager(":memory:")
    mock.checkpoints.initialize()
    return mock


def _mock_orch_with_stream(tokens: list[str], full: str | None = None) -> MagicMock:
    """Build a minimal mock Orchestrator whose handle_input_stream emits *tokens*."""
    m = _mock_orch()
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
    mock = _mock_orch()
    mock.handle_input = AsyncMock(return_value="Salut!")
    monkeypatch.setattr(web, "orch", mock)

    client = TestClient(web.app)
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "Salut!"


def test_chat_direct_reply_reports_observed_zero_generation(monkeypatch):
    mock = _mock_orch()
    mock.handle_input = AsyncMock(return_value="Done.")
    monkeypatch.setattr(web, "orch", mock)
    usage = TestClient(web.app).post("/chat", json={"message": "/status"}).json()["usage"]
    assert usage["schema"] == "nerva.turn.usage.v1"
    assert (usage["api_calls"], usage["input_tokens"], usage["output_tokens"]) == (0, 0, 0)
    assert usage["estimated_cost_usd"] == 0
    assert (usage["usage_basis"], usage["cost_basis"]) == ("measured_zero", "measured_zero")


def test_chat_reports_source_assigned_runtime_stop_after_rephrased_reply(monkeypatch):
    from agents.core.turn_stops import record_runtime_stop

    mock = _mock_orch()

    async def stopped(*args, **kwargs):
        record_runtime_stop("guardian_denied")
        return "That sounds fine now."

    mock.handle_input = stopped
    monkeypatch.setattr(web, "orch", mock)
    body = TestClient(web.app).post("/chat", json={"message": "hello"}).json()
    assert body["reply"] == "That sounds fine now."
    assert body["runtime_stops"] == ["guardian_denied"]


def test_chat_returns_selected_session_id_after_new_command(monkeypatch):
    mock = _mock_orch()
    mock.session_id = "old_topic"

    async def change_session(*args, **kwargs):
        mock.session_id = "session_new_topic"
        return "Started a new conversation."

    mock.handle_input = change_session
    monkeypatch.setattr(web, "orch", mock)
    response = TestClient(web.app).post("/chat", json={"message": "/new"})
    assert response.status_code == 200
    assert response.json()["session_id"] == "session_new_topic"


def test_resume_old_topic_returns_its_exact_saved_history(monkeypatch):
    class Memory:
        async def resume_session(self, sid):
            return sid == "old_topic"

        async def get_history(self, sid):
            assert sid == "old_topic"
            return [{"role": "user", "content": "old question"},
                    {"role": "assistant", "content": "old answer"}]

    checkpoints = CheckpointManager(":memory:")
    checkpoints.initialize()
    selected = SimpleNamespace(memory=Memory(), session_id="session_new_topic", checkpoints=checkpoints)
    monkeypatch.setattr(web, "orch", selected)
    response = TestClient(web.app).post("/sessions/resume", json={"session_id": "old_topic"})
    assert response.status_code == 200
    assert response.json()["session"] == "old_topic"
    assert response.json()["turns"][1]["content"] == "old answer"
    assert selected.session_id == "old_topic"


def test_chat_agent_override_not_jarvis(monkeypatch):
    mock = _mock_orch()
    mock.handle_input = AsyncMock(return_value="Friday here.")
    monkeypatch.setattr(web, "orch", mock)

    client = TestClient(web.app)
    client.post("/chat", json={"message": "hi", "agent": "friday"})
    _, kwargs = mock.handle_input.call_args
    assert kwargs.get("agent_override") == "friday"


def test_chat_agent_jarvis_passes_no_override(monkeypatch):
    mock = _mock_orch()
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


def test_stream_end_reports_its_own_observed_zero_generation(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream(["Done."]))
    response = TestClient(web.app).post("/chat/stream", json={"message": "/status"})
    end = _parse_sse(response.text)[-1]
    assert {key: end["usage"][key] for key in (
        "schema", "api_calls", "input_tokens", "output_tokens", "estimated_cost_usd",
        "model", "provider", "usage_basis", "cost_basis", "breakdown",
    )} == {
        "schema": "nerva.turn.usage.v1", "api_calls": 0,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0,
        "model": None, "provider": None, "usage_basis": "measured_zero",
        "cost_basis": "measured_zero", "breakdown": [],
    }
    assert end["runtime_stops"] == []


def test_chat_stream_end_returns_selected_session_id(monkeypatch):
    mock = _mock_orch_with_stream([], full="Started a new conversation.")
    mock.session_id = "session_new_topic"
    monkeypatch.setattr(web, "orch", mock)
    response = TestClient(web.app).post("/chat/stream", json={"message": "/new"})
    assert _parse_sse(response.text)[-1]["session_id"] == "session_new_topic"


def test_chat_stream_end_event_carries_agent(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream(["x"]))
    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hi", "agent": "friday"})
    events = _parse_sse(resp.text)
    end_event = next(e for e in events if e.get("type") == "end")
    assert end_event["agent"] == "friday"


def test_chat_stream_error_produces_end_event(monkeypatch):
    mock = _mock_orch()
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
    assert events[-1]["usage"]["api_calls"] == 0
    assert events[-1]["usage"]["usage_basis"] == "measured_zero"


@pytest.mark.asyncio
async def test_stream_disconnect_cancels_runner_and_closes_its_usage_scope(monkeypatch):
    from agents.core import turn_usage

    mock = _mock_orch()
    started = asyncio.Event()
    cancelled = asyncio.Event()
    collectors = []
    actual_scope = turn_usage.turn_usage_scope

    @contextmanager
    def observed_scope():
        with actual_scope() as collector:
            collectors.append(collector)
            yield collector

    async def blocked_stream(message, channel, on_token, agent_override=None):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    mock.handle_input_stream = blocked_stream
    monkeypatch.setattr(turn_usage, "turn_usage_scope", observed_scope)
    stream = web._chat_event_stream(mock, "hello", "jarvis", None)
    assert '"start"' in await anext(stream)
    await asyncio.wait_for(started.wait(), 2)
    await stream.aclose()
    assert cancelled.is_set()
    assert len(collectors) == 1 and collectors[0]._closed is True


def test_chat_stream_no_tokens_still_ends(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch_with_stream([], full="direct"))
    client = TestClient(web.app)
    resp = client.post("/chat/stream", json={"message": "hi"})
    events = _parse_sse(resp.text)
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "end"
    assert events[-1]["text"] == "direct"
