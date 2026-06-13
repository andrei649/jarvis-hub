"""Characterization tests for high-risk, previously-untested routes (Phase 0).

These lock the *contract* (auth guard + request validation + headline behavior)
of routes that the CLN-3 extraction will move, so an extraction that silently
drops a `Depends(_admin_guard)` or a Pydantic body model is caught. They capture
CURRENT behavior on `main` — they are not aspirational.

Auth model (verified 2026-06-13): with `web.ADMIN_TOKEN` set, an admin route
without the `X-Admin-Token` header returns 401 — which cleanly proves the route
is admin-guarded without depending on the localhost/proxy fallback. The
autouse `_disable_user_guard` fixture (conftest) disables only the *user* guard,
so the admin guard is genuinely exercised here.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

ADMIN = {"X-Admin-Token": "test-secret"}


@pytest.fixture(scope="module")
def client():
    """Full-lifespan client with an admin token configured (restored on teardown)."""
    import agents.web as web

    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


# ── admin-guard contract (no token → 401; with token → real behavior) ──────────

def test_llm_auth_profiles_requires_admin(client):
    assert client.get("/api/llm/auth-profiles").status_code == 401
    r = client.get("/api/llm/auth-profiles", headers=ADMIN)
    assert r.status_code == 200
    assert "pools" in r.json()


def test_llm_load_requires_admin_and_validates_body(client):
    # guard: missing token → 401 (never reaches the handler)
    assert client.post("/api/llm/load", json={"model": "x"}).status_code == 401
    # validation: authed but missing the required `model` field → 422
    r = client.post("/api/llm/load", json={}, headers=ADMIN)
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][-1] == "model"


def test_autonomy_mode_get_and_validation(client):
    assert client.get("/autonomy/mode").status_code == 401
    r = client.get("/autonomy/mode", headers=ADMIN)
    assert r.status_code == 200 and "mode" in r.json()
    # POST without the required `mode` field → 422
    assert client.post("/autonomy/mode", json={}, headers=ADMIN).status_code == 422


def test_payments_reject_requires_admin_then_404s_unknown(client):
    assert client.post("/api/payments/nope/reject", json={}).status_code == 401
    # authed: unknown payment id → 400 "not found or cannot be rejected"
    r = client.post("/api/payments/nope/reject", json={}, headers=ADMIN)
    assert r.status_code == 400


# ── open (intentionally unguarded) read routes → 200 ───────────────────────────

def test_status_is_open(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert set(r.json()) >= {"version", "agents", "status"}


def test_heartbeat_status_is_open(client):
    r = client.get("/heartbeat/status")
    assert r.status_code == 200
    assert "scheduler_running" in r.json()


def test_security_kill_switch_read_is_open(client):
    r = client.get("/api/security/kill-switch")
    assert r.status_code == 200
    assert "global" in r.json()
