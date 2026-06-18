"""Tests for H17.4 — Externally-anchored audit + intent attribution."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.security.anchor import IntentLog, TransparencyAnchor


# ── intent log: signing + chain + attribution ────────────────────────────────

def test_intent_record_has_attribution_and_signature(tmp_path):
    log = IntentLog(path=tmp_path / "i.json", secret_key="k")
    e = log.record("jarvis", "send_email", why="user asked to reply to Bob",
                   cause="user_request:42")
    assert e["why"] and e["cause"] == "user_request:42"
    assert e["signature"] and e["entry_hash"]


def test_intent_chain_verifies(tmp_path):
    log = IntentLog(path=tmp_path / "i.json", secret_key="k")
    log.record("a", "act1", "why1")
    log.record("a", "act2", "why2")
    assert log.verify()["ok"] is True


def test_intent_tamper_detected(tmp_path):
    p = tmp_path / "i.json"
    log = IntentLog(path=p, secret_key="k")
    log.record("a", "act1", "why1")
    log.record("a", "act2", "why2")
    # tamper with a record's content on disk
    import json
    data = json.loads(p.read_text())
    data[0]["action"] = "TAMPERED"
    p.write_text(json.dumps(data))
    log2 = IntentLog(path=p, secret_key="k")
    v = log2.verify()
    assert v["ok"] is False and v["bad_seq"] == 1


def test_intent_signature_forgery_detected(tmp_path):
    p = tmp_path / "i.json"
    IntentLog(path=p, secret_key="real").record("a", "act", "why")
    # an attacker with the wrong key can't validate the signature
    assert IntentLog(path=p, secret_key="wrong").verify()["ok"] is False


# ── transparency anchor ──────────────────────────────────────────────────────

def test_anchor_chain_and_latest(tmp_path):
    a = TransparencyAnchor(path=tmp_path / "t.json")
    r1 = a.anchor("roothash1")
    r2 = a.anchor("roothash2")
    assert r2["prev_anchor_hash"] == r1["anchor_hash"]   # hash-linked
    assert a.latest()["root"] == "roothash2"
    assert a.verify()["ok"] is True


def test_anchor_tamper_detected(tmp_path):
    p = tmp_path / "t.json"
    a = TransparencyAnchor(path=p)
    a.anchor("root1"); a.anchor("root2")
    import json
    data = json.loads(p.read_text())
    data[0]["root"] = "FORGED"
    p.write_text(json.dumps(data))
    assert TransparencyAnchor(path=p).verify()["ok"] is False


# ── endpoints ────────────────────────────────────────────────────────────────

def test_endpoints():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    hdr = {"X-Admin-Token": "test-secret"}
    try:
        with TestClient(web.app) as c:
            if getattr(web.orch, "intent_log", None) is None:
                return
            web.orch.intent_log.clear()
            web.orch.transparency.clear()
            assert c.post("/api/security/audit/action", json={"actor": "x"}, headers=hdr).status_code == 400
            rec = c.post("/api/security/audit/action",
                         json={"actor": "jarvis", "action": "reply", "why": "user asked"}, headers=hdr)
            assert rec.status_code == 200 and rec.json()["entry"]["signature"]

            intent = c.get("/api/security/audit/intent")
            assert intent.status_code == 200 and intent.json()["verify"]["ok"] is True

            # anchoring requires admin
            assert c.post("/api/security/audit/anchor").status_code == 401
            anc = c.post("/api/security/audit/anchor", headers=hdr)
            assert anc.status_code == 200 and anc.json()["receipt"]["anchor_hash"]
            anchors = c.get("/api/security/audit/anchors")
            assert anchors.json()["verify"]["ok"] is True
    finally:
        web.ADMIN_TOKEN = old
