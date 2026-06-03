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

def test_webhook_endpoints_flow():
    from agents import web
    with TestClient(web.app) as c:
        # create
        resp = c.post("/api/webhooks", json={"target": "jarvis", "target_type": "agent"})
        assert resp.status_code == 200
        rec = resp.json()
        hook_id, token = rec["id"], rec["token"]

        # list masks the token
        listed = c.get("/api/webhooks").json()["webhooks"]
        assert any(w["id"] == hook_id and "token" not in w for w in listed)

        # trigger without token → 401
        assert c.post(f"/api/webhooks/{hook_id}", json={"text": "hi"}).status_code == 401

        # trigger with token (header) → 200, runs the agent
        ok = c.post(
            f"/api/webhooks/{hook_id}",
            json={"text": "hello"},
            headers={"X-Webhook-Token": token},
        )
        assert ok.status_code == 200
        assert ok.json()["ok"] is True
        assert ok.json()["target"] == "jarvis"

        # unknown webhook → 404
        assert c.post("/api/webhooks/nope", json={}, headers={"X-Webhook-Token": "x"}).status_code == 404

        # delete
        assert c.delete(f"/api/webhooks/{hook_id}").status_code == 200
