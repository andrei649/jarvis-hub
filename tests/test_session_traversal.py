"""AUD-5 — session-id path-traversal is rejected at every boundary.

A ``session_id`` becomes a filename (``MEMORY_DIR / f"{session_id}.json"``), so a
hostile value like ``../../etc/passwd`` could read/write outside the memory dir.
These tests prove the validator rejects traversal, that the persistence layer
refuses such ids (defense-in-depth), and that the resume route answers 400.
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.validation import is_valid_session_id
from agents.core.memory import persistence


VALID = ["session_A", "my_session_123", "work-2024-12-01", "a", "abc", "S" * 128]
HOSTILE = [
    "../../../etc/passwd",
    "..\\windows\\system32",
    "a/b",
    "a\\b",
    "with space",
    ".",
    "..",
    "",
    "sess;rm",
    "sess.json",
    "x" * 129,         # over the length cap
    "../" * 40,
    "session_A\n",     # Python's $ anchor matches before a final newline
    "S" * 127 + "\n",  # still within the 128-character limit
    "\t", "a\r", "a\x00", True,
]


@pytest.mark.parametrize("sid", VALID)
def test_valid_session_ids_accepted(sid):
    assert is_valid_session_id(sid) is True


@pytest.mark.parametrize("sid", HOSTILE)
def test_hostile_session_ids_rejected(sid):
    assert is_valid_session_id(sid) is False


def test_non_str_session_id_rejected():
    assert is_valid_session_id(None) is False
    assert is_valid_session_id(123) is False


def test_persistence_load_refuses_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    # A would-be escape target outside the memory dir; it must never be read.
    outside = tmp_path.parent / "secret.json"
    outside.write_text('{"turns": [{"role": "user", "content": "PWNED"}]}', encoding="utf-8")
    assert persistence.load_memory("../secret") == []


def test_persistence_save_refuses_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "mem")
    persistence.save_memory("../escape", [{"role": "user", "content": "x"}])
    # Nothing written outside the memory dir.
    assert not (tmp_path / "escape.json").exists()
    assert not (tmp_path / "mem" / "..escape.json").exists()


def test_persistence_roundtrip_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    persistence.save_memory("session_ok", [{"role": "user", "content": "hi"}])
    assert persistence.load_memory("session_ok") == [{"role": "user", "content": "hi"}]


def test_persistence_refuses_to_read_newline_named_snapshot(monkeypatch):
    def memory_dir():
        raise AssertionError("invalid id must not reach the memory directory")

    monkeypatch.setattr(persistence, "_memory_dir", memory_dir)
    assert persistence.load_memory("session_A\n") == []


def test_persistence_refuses_to_save_newline_named_snapshot(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    monkeypatch.setattr(persistence, "MEMORY_DIR", memory)
    def memory_dir():
        raise AssertionError("invalid id must not reach the memory directory")

    monkeypatch.setattr(persistence, "_memory_dir", memory_dir)
    persistence.save_memory("session_A\n", [{"role": "user", "content": "should not write"}])
    assert not memory.exists(), "an invalid id must not even create the storage directory"


def test_persistence_refuses_to_delete_newline_named_snapshot(monkeypatch):
    def memory_dir():
        raise AssertionError("invalid id must not reach the memory directory")

    monkeypatch.setattr(persistence, "_memory_dir", memory_dir)
    persistence.delete_memory("session_A\n")


def test_resume_route_rejects_traversal_with_400():
    from fastapi.testclient import TestClient
    from agents import web

    client = TestClient(web.app)
    resp = client.post("/sessions/resume", json={"session_id": "../../etc/passwd"})
    assert resp.status_code == 400
    assert "invalid" in resp.json()["error"].lower()


def test_resume_route_rejects_final_newline_before_session_store(monkeypatch):
    from fastapi.testclient import TestClient
    from agents import web
    from agents.core.routers import sessions

    def downstream():
        raise AssertionError("invalid session must not reach the session store")

    monkeypatch.setattr(sessions, "get_orch", downstream)
    resp = TestClient(web.app).post("/sessions/resume", json={"session_id": "session_A\n"})
    assert resp.status_code == 400
    assert resp.json() == {"error": "invalid session_id"}


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_chat_routes_reject_final_newline_before_orchestrator(monkeypatch, route):
    from unittest.mock import AsyncMock, MagicMock
    from fastapi.testclient import TestClient
    from agents import web
    from agents.core import session_continuation

    orch = MagicMock()
    prepare = AsyncMock()
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(session_continuation, "prepare_session", prepare)
    resp = TestClient(web.app).post(route, json={"message": "hi", "session_id": "session_A\n"})
    assert resp.status_code == 422
    prepare.assert_not_awaited()
    assert orch.mock_calls == []


def test_typed_continue_rejects_final_newline_before_session_creation(monkeypatch):
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from agents import web
    from agents.core.routers import sessions

    get_orch = MagicMock()
    monkeypatch.setattr(sessions, "get_orch", get_orch)
    monkeypatch.setattr(web, "_admin_env_token", lambda: "fixture")
    monkeypatch.setattr(web, "_env_admin_active", lambda: True)
    resp = TestClient(web.app).post("/sessions/continue", json={
        "source_session_id": "session_A\n",
        "request_id": "11111111-1111-4111-8111-111111111111",
    }, headers={"x-admin-token": "fixture"})
    assert resp.status_code == 422
    get_orch.assert_not_called()
