"""Tests for H15.4 — Secret broker (JIT credential injection)."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.security.secret_broker import SecretBroker


# ── handles + management ─────────────────────────────────────────────────────

def test_reference_is_handle_not_value():
    assert SecretBroker.reference("gh_token") == "{{secret:gh_token}}"


def test_put_has_names_delete():
    b = SecretBroker()
    b.put("gh_token", "ghp_SECRET")
    assert b.has("gh_token") and b.names() == ["gh_token"]
    assert b.delete("gh_token") is True
    assert b.has("gh_token") is False


# ── injection is gated by approval ───────────────────────────────────────────

def test_inject_blocked_without_approval():
    b = SecretBroker()
    b.put("gh_token", "ghp_SECRET")
    r = b.inject("auth: {{secret:gh_token}}", approved=False)
    assert "ghp_SECRET" not in r["text"]            # value never revealed
    assert "approval required" in r["text"]
    assert r["blocked"] == ["gh_token"] and r["injected"] == []


def test_inject_resolves_when_approved():
    b = SecretBroker()
    b.put("gh_token", "ghp_SECRET")
    r = b.inject("auth: {{secret:gh_token}}", approved=True)
    assert r["text"] == "auth: ghp_SECRET"
    assert r["injected"] == ["gh_token"]


def test_inject_missing_secret():
    b = SecretBroker()
    r = b.inject("{{secret:nope}}", approved=True)
    assert "not found" in r["text"] and r["blocked"] == ["nope"]


# ── redaction (defense-in-depth) ─────────────────────────────────────────────

def test_redact_masks_known_values():
    b = SecretBroker()
    b.put("gh_token", "ghp_SECRET")
    assert b.redact("leaked ghp_SECRET here") == "leaked [REDACTED:gh_token] here"


# ── endpoints (never return plaintext) ───────────────────────────────────────

def test_secret_broker_endpoints():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    hdr = {"X-Admin-Token": "test-secret"}
    try:
        with TestClient(web.app) as c:
            if getattr(web.orch, "secret_broker", None) is None:
                return
            assert c.post("/api/secrets/broker", json={"name": "k", "value": "v"}).status_code == 401
            put = c.post("/api/secrets/broker", json={"name": "apikey", "value": "TOPSECRET"}, headers=hdr)
            assert put.status_code == 200 and put.json()["reference"] == "{{secret:apikey}}"
            # list returns names only, never values
            names = c.get("/api/secrets/broker", headers=hdr).json()["names"]
            assert "apikey" in names
            # redact endpoint masks the value
            red = c.post("/api/secrets/broker/redact", json={"text": "x TOPSECRET y"}, headers=hdr)
            assert "TOPSECRET" not in red.json()["redacted"]
            assert c.delete("/api/secrets/broker/apikey", headers=hdr).status_code == 200
    finally:
        web.ADMIN_TOKEN = old
