"""Tests for H7.5 — Input validation on key endpoints."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(scope="module")
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c


# ── Chat message validation ───────────────────────────────────────

def test_chat_message_too_long_returns_422(client):
    """A chat message exceeding 4096 chars must be rejected with 422."""
    resp = client.post("/chat", json={"message": "x" * 4097, "agent": "jarvis"})
    assert resp.status_code == 422


def test_chat_message_at_limit_returns_ok(client):
    """A chat message of exactly 4096 chars must be accepted (may return reply)."""
    resp = client.post("/chat", json={"message": "x" * 4096, "agent": "jarvis"})
    # FastAPI should not 422 — accept any non-validation error code
    assert resp.status_code != 422


def test_chat_message_valid_returns_non_422(client):
    """A short valid message must not trigger input validation error."""
    resp = client.post("/chat", json={"message": "Hello", "agent": "jarvis"})
    assert resp.status_code != 422


# ── Sandbox code-size validation ──────────────────────────────────

def test_sandbox_code_too_large_returns_422(client):
    """Sandbox code exceeding 32 KB must be rejected with 422."""
    resp = client.post(
        "/sandbox/execute",
        json={"code": "x" * 32769, "language": "python"},
    )
    assert resp.status_code == 422


def test_sandbox_code_at_limit_accepted(client):
    """Sandbox code of exactly 32768 bytes must not be rejected by input validation."""
    resp = client.post(
        "/sandbox/execute",
        json={"code": "x" * 32768, "language": "python"},
    )
    # May be 403 (DEV_MODE off) or 503 (orch not init), but NOT 422
    assert resp.status_code != 422


def test_sandbox_empty_code_accepted(client):
    """Empty code must not trigger a validation error."""
    resp = client.post(
        "/sandbox/execute",
        json={"code": "", "language": "python"},
    )
    assert resp.status_code != 422


# ── Limit query param validation ──────────────────────────────────

def test_traces_limit_zero_returns_422(client):
    """limit=0 on /api/traces must return 422."""
    resp = client.get("/api/traces?limit=0")
    assert resp.status_code == 422


def test_traces_limit_too_large_returns_422(client):
    """limit=201 on /api/traces must return 422."""
    resp = client.get("/api/traces?limit=201")
    assert resp.status_code == 422


def test_traces_limit_valid_accepted(client):
    """limit=50 on /api/traces must not return 422."""
    resp = client.get("/api/traces?limit=50")
    assert resp.status_code != 422


# ── TTS text length validation ────────────────────────────────────

def test_tts_text_too_long_returns_422(client):
    """TTS text exceeding 4096 chars must be rejected with 422."""
    resp = client.post("/tts", json={"text": "x" * 4097, "lang": "ro"})
    assert resp.status_code == 422


def test_tts_text_valid_accepted(client):
    """Valid TTS text must not return 422."""
    resp = client.post("/tts", json={"text": "Hello world", "lang": "ro"})
    # May be 503 (edge-tts not installed) but not 422
    assert resp.status_code != 422
