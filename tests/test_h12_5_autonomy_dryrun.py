"""Tests for H12.5 — Autonomy dry-run / preview."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.autonomy.dry_run import preview_task


# ── preview semantics ────────────────────────────────────────────────────────

def test_preview_irreversible_send():
    p = preview_task({"kind": "send_email", "title": "Reply to Bob",
                      "payload": {"to": "bob@x.com", "body": "hi"}, "risk_tier": 2})
    assert p["irreversible"] is True
    assert p["requires_approval"] is True
    assert p["target"] == "bob@x.com"
    assert any(e["field"] == "to" for e in p["effects"])
    assert p["would_execute"] is False
    assert "IRREVERSIBLE" in p["summary"]


def test_preview_reversible_low_risk():
    p = preview_task({"kind": "summarize", "title": "Summarize inbox",
                      "payload": {"query": "unread"}, "risk_tier": 3})
    assert p["irreversible"] is False
    assert p["requires_approval"] is False         # reversible + low risk (tier 3)
    assert "reversible" in p["summary"]


def test_preview_high_risk_requires_approval_even_if_reversible():
    p = preview_task({"kind": "analyze", "title": "Deep scan",
                      "payload": {}, "risk_tier": 1})
    assert p["irreversible"] is False
    assert p["requires_approval"] is True          # tier 1 (high) → approval


def test_preview_accepts_task_object():
    class _T:
        def to_dict(self):
            return {"kind": "delete_file", "title": "rm logs",
                    "payload": {"path": "/tmp/x"}, "risk_tier": 2}
    p = preview_task(_T())
    assert p["irreversible"] is True and p["target"] == ""
    assert any(e["field"] == "path" for e in p["effects"])


# ── decision card integration ────────────────────────────────────────────────

def test_decision_card_includes_preview():
    from agents.core.autonomy.inbox import build_decision_card
    card = build_decision_card({"id": 1, "agent": "jarvis", "kind": "send_email",
                                "title": "Email the team", "risk_tier": 2,
                                "payload": {"to": "team@x.com"}})
    assert "Preview" in card["text"]


# ── endpoints ────────────────────────────────────────────────────────────────

def test_preview_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        assert c.post("/api/autonomy/preview", json={}).status_code == 400
        r = c.post("/api/autonomy/preview",
                   json={"kind": "transfer", "title": "Move funds",
                         "payload": {"amount": 500, "to": "acct"}, "risk_tier": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["irreversible"] is True and body["requires_approval"] is True
        assert body["would_execute"] is False
