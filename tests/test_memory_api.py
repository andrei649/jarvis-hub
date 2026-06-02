"""HTTP integration tests for memory endpoints.

Covers:
  GET  /memory              — session history read
  POST /memory/clear        — session clear with confirm guard
  GET  /api/memory/search   — hybrid recall (graceful no-orch path)
  POST /api/memory/remember — store a fact (validation + success)
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web

_NO_ORCH_CLIENT = TestClient(web.app)  # no lifespan → orch stays None


def _mock_orch() -> MagicMock:
    m = MagicMock()
    m.session_id = "sess-test-001"
    m.memory.get_history = AsyncMock(return_value=[
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ])
    m.memory.clear = AsyncMock(return_value=None)
    m.memory.new_session = AsyncMock(return_value="sess-test-002")
    m.checkpoints.create_session_record = MagicMock()
    return m


# ---------------------------------------------------------------------------
# GET /memory
# ---------------------------------------------------------------------------

def test_memory_no_orch_returns_503():
    resp = _NO_ORCH_CLIENT.get("/memory")
    assert resp.status_code == 503


def test_memory_returns_session_and_turns(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.get("/memory")
    assert resp.status_code == 200
    data = resp.json()
    assert "session" in data
    assert "turns" in data
    assert isinstance(data["turns"], list)


def test_memory_returns_correct_session_id(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    data = client.get("/memory").json()
    assert data["session"] == "sess-test-001"


def test_memory_turns_have_role_content(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    turns = client.get("/memory").json()["turns"]
    assert len(turns) == 2
    for turn in turns:
        assert "role" in turn and "content" in turn


# ---------------------------------------------------------------------------
# POST /memory/clear
# ---------------------------------------------------------------------------

def test_memory_clear_no_orch_returns_503():
    resp = _NO_ORCH_CLIENT.post("/memory/clear")
    assert resp.status_code == 503


def test_memory_clear_requires_confirm_header_in_prod_mode(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", False)
    client = TestClient(web.app)
    resp = client.post("/memory/clear")
    assert resp.status_code == 400
    assert "confirmation" in resp.json()["error"].lower() or "confirm" in resp.json()["error"].lower()


def test_memory_clear_succeeds_with_confirm_header(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", False)
    client = TestClient(web.app)
    resp = client.post("/memory/clear", headers={"X-Confirm": "true"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_memory_clear_new_session_id_returned(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", False)
    client = TestClient(web.app)
    data = client.post("/memory/clear", headers={"X-Confirm": "true"}).json()
    assert data["new_session"] == "sess-test-002"


def test_memory_clear_succeeds_in_dev_mode(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", True)
    client = TestClient(web.app)
    resp = client.post("/memory/clear")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# GET /api/memory/search
# ---------------------------------------------------------------------------

def test_memory_search_no_orch_returns_graceful_empty():
    resp = _NO_ORCH_CLIENT.get("/api/memory/search", params={"q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert data["total"] == 0


def test_memory_search_returns_structure_with_mock(monkeypatch):
    hit = MagicMock()
    hit.id = "vec-001"
    hit.score = 0.95
    hit.sources = ["turn:3"]
    hit.payload = {"text": "jarvis can do calendar"}

    mock = _mock_orch()
    mock.memory.embed = AsyncMock(return_value=[0.1, 0.2])
    mock.memory.hybrid_search = AsyncMock(return_value=[hit])
    monkeypatch.setattr(web, "orch", mock)

    client = TestClient(web.app)
    resp = client.get("/api/memory/search", params={"q": "calendar", "top_k": "5"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["results"][0]["id"] == "vec-001"
    assert data["results"][0]["score"] == 0.95


def test_memory_search_empty_query_returns_structure(monkeypatch):
    mock = _mock_orch()
    mock.memory.hybrid_search = AsyncMock(return_value=[])
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    data = client.get("/api/memory/search").json()
    assert "results" in data and "query" in data and "total" in data


def test_memory_search_top_k_clamped_to_50(monkeypatch):
    mock = _mock_orch()
    mock.memory.embed = AsyncMock(return_value=None)
    mock.memory.hybrid_search = AsyncMock(return_value=[])
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    client.get("/api/memory/search", params={"q": "x", "top_k": "999"})
    _, kwargs = mock.memory.hybrid_search.call_args
    assert kwargs.get("top_k", 50) <= 50


# ---------------------------------------------------------------------------
# POST /api/memory/remember
# ---------------------------------------------------------------------------

def test_memory_remember_no_orch_returns_503():
    resp = _NO_ORCH_CLIENT.post("/api/memory/remember", json={"text": "hello"})
    assert resp.status_code == 503


def test_memory_remember_empty_text_returns_400(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.post("/api/memory/remember", json={"text": ""})
    assert resp.status_code == 400
    assert "text" in resp.json()["error"].lower()


def test_memory_remember_missing_text_returns_400(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.post("/api/memory/remember", json={})
    assert resp.status_code == 400


def test_memory_remember_stores_and_returns_ok(monkeypatch):
    mock = _mock_orch()
    mock.memory.remember = AsyncMock(return_value="mem-uuid-42")
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    resp = client.post("/api/memory/remember", json={"text": "I prefer dark mode"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["id"] == "mem-uuid-42"


def test_memory_remember_passes_metadata(monkeypatch):
    mock = _mock_orch()
    mock.memory.remember = AsyncMock(return_value="mem-uuid-99")
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    client.post("/api/memory/remember", json={"text": "fact", "metadata": {"source": "user"}})
    _, kwargs = mock.memory.remember.call_args
    assert kwargs.get("metadata") == {"source": "user"}
