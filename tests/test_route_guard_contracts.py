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


# ── distributed-mesh / dispatch (Tier-4: untested; smoke before extraction) ────
# These routes had NO test coverage. The plan extracts them late and says "write
# smoke tests first" — this is that. User-guarded routes reach their handlers
# because conftest's autouse `_disable_user_guard` is active; admin-guarded
# mutations correctly require a token.

def test_nodes_list_open_register_admin(client):
    assert client.get("/api/nodes").status_code == 200          # roster read
    # registration mutates the mesh → admin-guarded (no token → 401)
    assert client.post("/api/nodes/register", json={}).status_code == 401
    assert client.delete("/api/nodes/n1").status_code == 401


def test_node_dispatch_validates_body(client):
    # user-guarded (guard disabled in tests) → reaches body validation
    r = client.post("/api/nodes/n1/dispatch", json={})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][-1] == "capability"


def test_satellites_list_open_register_validates(client):
    assert client.get("/api/satellites").status_code == 200
    r = client.post("/api/satellites/register", json={})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][-1] == "satellite_id"


def test_subagents_spawn_and_toolrpc_validate_body(client):
    assert client.post("/api/subagents/spawn", json={}).json()["detail"][0]["loc"][-1] == "task"
    assert client.post("/api/toolrpc/call", json={}).json()["detail"][0]["loc"][-1] == "tool"


def test_sync_and_compress_are_safe_noops_when_disabled(client):
    # sync is off by default → read-only no-ops (no network), not errors
    assert client.post("/api/sync/push", json={}).status_code == 200
    assert client.post("/api/sync/pull", json={}).status_code == 200
    assert client.post("/api/context/compress", json={}).status_code == 200


# ── oauth service-routing + admin read surface ─────────────────────────────────

def test_oauth_unknown_service_is_404(client):
    # missing/blank `service` → "Unknown service" (locks the dispatch contract)
    assert client.get("/api/oauth/auth-url").status_code == 404
    assert client.post("/api/oauth/refresh", json={}, headers=ADMIN).status_code == 404  # SEC-3: now admin-guarded


def test_admin_read_surface_requires_admin(client):
    for path in ("/api/admin/audit", "/api/admin/widgets", "/api/admin/agents/stats"):
        assert client.get(path).status_code == 401, f"{path} should require admin"
        assert client.get(path, headers=ADMIN).status_code == 200, f"{path} authed"

