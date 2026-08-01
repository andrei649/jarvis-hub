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
    # RiskTier scale: 0=READ_ONLY, 1=REVERSIBLE, 2=EXTERNAL, 3=IRREVERSIBLE_OR_MONEY.
    p = preview_task({"kind": "summarize", "title": "Summarize inbox",
                      "payload": {"query": "unread"}, "risk_tier": 1})
    assert p["irreversible"] is False
    assert p["requires_approval"] is False         # reversible + low risk (tier 1)
    assert p["would_execute"] is True              # PNB-055: the chip's green branch is real
    assert "reversible" in p["summary"]


def test_preview_high_risk_requires_approval_even_if_reversible():
    p = preview_task({"kind": "analyze", "title": "Deep scan",
                      "payload": {}, "risk_tier": 3})
    assert p["irreversible"] is False
    assert p["requires_approval"] is True          # tier 3 (money/irreversible) → approval
    assert p["would_execute"] is False


def test_preview_money_kinds_read_irreversible_not_auto_approvable():
    """GOV-038: a tier-3 money task must never preview as 'reversible;
    auto-approvable' — that text is what the human reads before approving."""
    for kind in ("book_flight", "purchase_item", "withdraw_cash"):
        p = preview_task({"kind": kind, "title": "do it", "payload": {}, "risk_tier": 3})
        assert p["irreversible"] is True, kind      # policy-set tokens now recognized
        assert p["requires_approval"] is True, kind
        assert "IRREVERSIBLE" in p["summary"], kind


def test_preview_pipeline_autonomy_level_forces_approval_never_relaxes_it():
    """A pipeline with its own approval floor (house intake: ask-until-earned)
    stamps the preview with reality; "act" never overrides the tier floor."""
    low = {"kind": "house.control", "title": "light on → light.kitchen",
           "payload": {}, "risk_tier": 1}
    assert preview_task(low, autonomy_level="ask")["requires_approval"] is True
    assert preview_task(low, autonomy_level="act")["would_execute"] is True
    money = {**low, "risk_tier": 3}
    assert preview_task(money, autonomy_level="act")["requires_approval"] is True


def test_preview_unknown_tier_fails_closed_and_words_not_substrings():
    # A task with no risk_tier defaults to tier 3 → approval required (fail closed).
    p = preview_task({"kind": "mystery", "title": "?", "payload": {}})
    assert p["requires_approval"] is True and p["would_execute"] is False
    # Token matching is word-based: "design" must not flag via the "sign" token.
    p2 = preview_task({"kind": "design_review", "title": "Review mockups",
                       "payload": {}, "risk_tier": 1})
    assert p2["irreversible"] is False and p2["would_execute"] is True


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
