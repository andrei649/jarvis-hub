"""Tests for H10.8 — Inbound Webhook Triggers.

Store + auth are tested directly; the trigger endpoint is exercised against the
real app with a real webhook (agent run goes through the offline orchestrator,
which returns a graceful response with no LLM backend).
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.webhooks import WebhookStore, extract_input


# ── input extraction ────────────────────────────────────────────────────────

def test_extract_input_prefers_known_keys():
    assert extract_input({"text": "hi"}) == "hi"
    assert extract_input({"message": "yo"}) == "yo"
    assert extract_input("raw string") == "raw string"


def test_extract_input_falls_back_to_json():
    out = extract_input({"foo": "bar", "n": 1})
    assert "foo" in out and "bar" in out


# ── store + auth ────────────────────────────────────────────────────────────

def test_create_and_verify(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("friday", "agent", name="daily")
    assert rec["target"] == "friday"
    assert store.verify(rec["id"], rec["token"]) is True
    assert store.verify(rec["id"], "wrong") is False
    assert store.verify("nope", rec["token"]) is False


def test_invalid_target_type(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    try:
        store.create("x", "banana")
        assert False, "should raise"
    except ValueError:
        pass


def test_list_masks_token(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis")
    listed = store.list()
    assert listed[0]["id"] == rec["id"]
    assert "token" not in listed[0]
    assert listed[0]["token_hint"].endswith("…")


def test_delete_and_persistence(tmp_path):
    p = tmp_path / "wh.json"
    store = WebhookStore(path=p)
    rec = store.create("jarvis")
    # reload from disk → still there
    assert WebhookStore(path=p).get(rec["id"]) is not None
    assert store.delete(rec["id"]) is True
    assert store.delete(rec["id"]) is False
    assert WebhookStore(path=p).get(rec["id"]) is None


def test_mark_called_increments(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis")
    store.mark_called(rec["id"])
    store.mark_called(rec["id"])
    assert store.get(rec["id"])["calls"] == 2


# ── endpoints (admin CRUD + token-gated trigger) ────────────────────────────

_ADMIN = {"X-Admin-Token": "test-admin-secret"}


def test_webhook_management_requires_admin():
    """SEC-1: management routes are admin-only; the unauthenticated network client
    (TestClient host is not localhost) must be rejected, so it cannot mint a token."""
    from agents import web
    with TestClient(web.app) as c:
        assert c.post("/api/webhooks", json={"target": "jarvis"}).status_code in (401, 403)
        assert c.get("/api/webhooks").status_code in (401, 403)
        assert c.delete("/api/webhooks/anything").status_code in (401, 403)


def test_webhook_endpoints_flow(monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "test-admin-secret")  # SEC-1: management needs admin
    with TestClient(web.app) as c:
        # create (admin)
        resp = c.post("/api/webhooks", json={"target": "jarvis", "target_type": "agent"}, headers=_ADMIN)
        assert resp.status_code == 200
        rec = resp.json()
        hook_id, token = rec["id"], rec["token"]

        # list masks the token (admin)
        listed = c.get("/api/webhooks", headers=_ADMIN).json()["webhooks"]
        assert any(w["id"] == hook_id and "token" not in w for w in listed)

        # trigger without token → 401 (trigger stays open but per-webhook authenticated)
        no_token = c.post(f"/api/webhooks/{hook_id}", json={"text": "hi"})
        assert no_token.status_code == 401

        # trigger with token (header) → 200, runs the agent — no admin token needed
        ok = c.post(
            f"/api/webhooks/{hook_id}",
            json={"text": "hello"},
            headers={"X-Webhook-Token": token},
        )
        assert ok.status_code == 200
        assert ok.json()["ok"] is True
        assert ok.json()["target"] == "jarvis"

        # unknown webhook → 404
        unknown = c.post("/api/webhooks/nope", json={}, headers={"X-Webhook-Token": "x"})
        assert unknown.status_code == 404

        # delete (admin)
        deleted = c.delete(f"/api/webhooks/{hook_id}", headers=_ADMIN)
        assert deleted.status_code == 200
