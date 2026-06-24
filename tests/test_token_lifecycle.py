"""AUD-6 — managed token lifecycle: TTL, rotation, hash-at-rest, and guard wiring (F19).

The managed store is the authoritative credential system. Issued tokens are stored
only as a SHA-256 hash, carry an optional expiry, and rotating revokes the prior
ones — so an old or expired token is rejected. The static ``JARVIS_*_TOKEN`` env
vars are the *bootstrap* credential: accepted until a rotation supersedes them
(``env_revoked``), after which the static token is dead for good. The localhost
dev fallback (no credential configured) is unchanged.
"""
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.security import token_store as ts_mod
from agents.core.security.token_store import TokenStore

_DAY = 86400


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = TokenStore(db_path=str(tmp_path / "tokens.db"))
    monkeypatch.setattr(ts_mod, "_store", s)   # the guards' get_token_store() returns this
    return s


# ── TokenStore ─────────────────────────────────────────────────────
def test_issue_and_verify_scope(store):
    tok = store.issue("admin", ttl_days=7)
    assert store.verify(tok) == "admin"
    assert store.verify("nope") is None
    assert store.verify("") is None


def test_hash_at_rest(store, tmp_path):
    tok = store.issue("admin")
    raw_db = (tmp_path / "tokens.db").read_bytes()
    assert tok.encode() not in raw_db          # the usable token never hits disk
    import hashlib
    assert hashlib.sha256(tok.encode()).hexdigest().encode() in raw_db  # only its hash


def test_expired_token_rejected(store):
    tok = store.issue("admin", ttl_days=1)
    assert store.verify(tok, now=time.time() + 2 * _DAY) is None


def test_rotate_revokes_old(store):
    old = store.issue("admin")
    new = store.rotate("admin")
    assert store.verify(old) is None           # old rejected after rotation
    assert store.verify(new) == "admin"


def test_rotate_marks_env_revoked(store):
    assert store.env_revoked("admin") is False
    store.rotate("admin")                       # adopting a managed token supersedes
    assert store.env_revoked("admin") is True   # the static env token, persistently


def test_has_scope_ignores_expired(store):
    assert store.has_scope("admin") is False
    store.issue("admin", ttl_days=1)
    assert store.has_scope("admin") is True
    assert store.has_scope("admin", now=time.time() + 2 * _DAY) is False


def test_purge_and_revoke(store):
    store.issue("admin", ttl_days=1)
    assert store.purge_expired(now=time.time() + 2 * _DAY) == 1
    store.issue("user")
    assert store.revoke_all("user") == 1


def test_unknown_scope_rejected(store):
    with pytest.raises(ValueError):
        store.issue("root")


# ── CLI (offline owner recovery) ───────────────────────────────────
def test_cli_issue_then_list(store, capsys):
    assert ts_mod._main(["issue", "admin", "7"]) == 0
    tok = capsys.readouterr().out.strip()
    assert store.verify(tok) == "admin"          # the CLI-minted token is usable
    assert ts_mod._main(["list"]) == 0
    assert "admin" in capsys.readouterr().out


def test_cli_rotate_supersedes_env(store, capsys):
    assert ts_mod._main(["rotate", "admin"]) == 0
    assert store.env_revoked("admin") is True    # CLI rotate kills the env token too


# ── guard wiring ───────────────────────────────────────────────────
class _Req:
    def __init__(self, headers=None, host="127.0.0.1"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()


def test_admin_credential_ok_accepts_issued(store, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    tok = store.issue("admin")
    assert web._admin_credential_ok(tok) is True
    assert web._admin_credential_ok("garbage") is False
    assert web._admin_credential_ok("") is False


async def test_admin_guard_accepts_issued_token_from_network(store, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    tok = store.issue("admin")
    # remote client (not localhost) with a valid issued admin token → allowed
    await web._admin_guard(_Req({"x-admin-token": tok}, host="10.0.0.9"))


async def test_admin_guard_rejects_rotated_and_missing(store, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    old = store.issue("admin")
    store.rotate("admin")  # invalidates `old`
    with pytest.raises(HTTPException) as e1:
        await web._admin_guard(_Req({"x-admin-token": old}, host="10.0.0.9"))
    assert e1.value.status_code == 401
    with pytest.raises(HTTPException):  # no credential at all, remote
        await web._admin_guard(_Req({}, host="10.0.0.9"))


async def test_localhost_fallback_preserved(store, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    # no env token, no issued token → localhost is trusted, network is 403
    await web._admin_guard(_Req({}, host="127.0.0.1"))
    with pytest.raises(HTTPException) as e:
        await web._admin_guard(_Req({}, host="10.0.0.9"))
    assert e.value.status_code == 403


async def test_env_admin_token_still_required_even_on_localhost(store, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "the-env-token")
    with pytest.raises(HTTPException):  # env token set → localhost must present it
        await web._admin_guard(_Req({}, host="127.0.0.1"))
    await web._admin_guard(_Req({"x-admin-token": "the-env-token"}, host="127.0.0.1"))


def test_static_env_token_revoked_after_rotation(store, monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "the-env-token")
    assert web._admin_credential_ok("the-env-token") is True   # bootstrap accepted
    store.rotate("admin")                                       # adopt a managed token
    assert web._admin_credential_ok("the-env-token") is False  # static token now dead
    assert web._admin_configured() is True                     # the managed one stands in


# ── rotate route ───────────────────────────────────────────────────
def test_rotate_route_mints_usable_token(store, monkeypatch):
    from fastapi.testclient import TestClient
    from agents import web
    from agents.core.routers import _deps
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    web.app.dependency_overrides[_deps.admin_guard] = lambda: None
    try:
        client = TestClient(web.app)
        old = store.issue("admin")
        resp = client.post("/api/admin/rotate-tokens", json={"scope": "admin", "ttl_days": 30})
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "admin" and "once" in body["note"]
        new = body["token"]
        # the freshly minted token authorizes the guard; the pre-rotation one does not
        assert web._admin_credential_ok(new) is True
        assert web._admin_credential_ok(old) is False
    finally:
        web.app.dependency_overrides.pop(_deps.admin_guard, None)


def test_rotate_route_is_admin_guarded():
    import json
    snap = json.loads((repo_root / "tests" / "_snapshots" / "route_auth.json").read_text())
    assert snap.get("POST /api/admin/rotate-tokens") == "admin"
