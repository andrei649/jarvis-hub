"""Tests for H16.4 — Signed ambient triggers (HMAC-signed webhook sources)."""
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.webhooks import WebhookStore, compute_signature


# ── store-level signing ──────────────────────────────────────────────────────

def test_unsigned_hook_has_no_secret(tmp_path):
    s = WebhookStore(path=tmp_path / "w.json")
    rec = s.create("jarvis")
    assert rec["signed"] is False and rec["signing_secret"] is None


def test_signed_hook_provisions_secret_and_verifies(tmp_path):
    s = WebhookStore(path=tmp_path / "w.json")
    rec = s.create("jarvis", signed=True)
    assert rec["signed"] is True and rec["signing_secret"]
    body = b'{"text": "ping"}'
    sig = compute_signature(rec["signing_secret"], body)
    assert s.verify_signature(rec["id"], body, sig) is True
    # bare hexdigest (no sha256= prefix) also accepted
    assert s.verify_signature(rec["id"], body, sig.split("=")[1]) is True


def test_bad_signature_and_tampered_body_rejected(tmp_path):
    s = WebhookStore(path=tmp_path / "w.json")
    rec = s.create("jarvis", signed=True)
    body = b'{"text": "ping"}'
    sig = compute_signature(rec["signing_secret"], body)
    assert s.verify_signature(rec["id"], body, "sha256=deadbeef") is False
    assert s.verify_signature(rec["id"], b'{"text": "tampered"}', sig) is False
    assert s.verify_signature(rec["id"], body, "") is False


def test_unsigned_hook_rejects_signature_check(tmp_path):
    s = WebhookStore(path=tmp_path / "w.json")
    rec = s.create("jarvis")          # no signing secret
    assert s.verify_signature(rec["id"], b"x", "sha256=whatever") is False


def test_list_masks_signing_secret(tmp_path):
    s = WebhookStore(path=tmp_path / "w.json")
    s.create("jarvis", signed=True)
    listed = s.list()[0]
    assert "signing_secret" not in listed and "token" not in listed
    assert listed["signed"] is True


# ── endpoint round-trip ──────────────────────────────────────────────────────

def test_signed_webhook_endpoint(monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "test-admin-secret")  # SEC-1: management is admin-only
    _admin = {"X-Admin-Token": "test-admin-secret"}
    with TestClient(web.app) as c:
        if web.orch is None:
            return
        created = c.post("/api/webhooks", json={"target": "jarvis", "signed": True}, headers=_admin)
        assert created.status_code == 200
        rec = created.json()
        hook_id, secret = rec["id"], rec["signing_secret"]
        assert secret

        captured = {}
        async def fake_handle(text, channel="webhook", agent_override=None):
            captured["text"] = text
            return "ok"
        orig = web.orch.handle_input
        web.orch.handle_input = fake_handle
        try:
            body = json.dumps({"text": "ambient ping"})
            good_sig = compute_signature(secret, body)
            # valid signature → 200
            r = c.post(f"/api/webhooks/{hook_id}", data=body,
                       headers={"X-Signature-256": good_sig, "Content-Type": "application/json"})
            assert r.status_code == 200 and r.json()["ok"] is True
            assert captured["text"] == "ambient ping"
            # missing/invalid signature → 401
            assert c.post(f"/api/webhooks/{hook_id}", data=body,
                          headers={"Content-Type": "application/json"}).status_code == 401
            assert c.post(f"/api/webhooks/{hook_id}", data=body,
                          headers={"X-Signature-256": "sha256=bad"}).status_code == 401
            # a token (the unsigned auth path) must NOT bypass a signed hook
            assert c.post(f"/api/webhooks/{hook_id}", json={"text": "x"},
                          headers={"X-Webhook-Token": rec["token"]}).status_code == 401
        finally:
            web.orch.handle_input = orig
        c.delete(f"/api/webhooks/{hook_id}", headers=_admin)
