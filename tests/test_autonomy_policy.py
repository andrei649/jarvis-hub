"""Tests for the autonomy risk gate / policy (H6.3)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from agents.core.autonomy.policy import AutonomyPolicy, RiskTier, ACT, NOTIFY, ASK


@pytest.fixture
def policy():
    return AutonomyPolicy(cap_per_action=50.0, daily_ceiling=200.0)


class TestClassification:
    def test_read_only_kinds(self, policy):
        for kind in ("research_market", "summarize_inbox", "fetch_weather", "check_status"):
            assert policy.classify({"kind": kind}) == RiskTier.READ_ONLY

    def test_reversible_kinds(self, policy):
        for kind in ("draft_email", "organize_files", "label_thread", "save_note"):
            assert policy.classify({"kind": kind}) == RiskTier.REVERSIBLE

    def test_external_kinds(self, policy):
        for kind in ("send_email", "post_linkedin", "reply_message"):
            assert policy.classify({"kind": kind}) == RiskTier.EXTERNAL

    def test_money_and_irreversible_kinds(self, policy):
        for kind in ("pay_invoice", "delete_file", "deploy_release", "book_flight"):
            assert policy.classify({"kind": kind}) == RiskTier.IRREVERSIBLE_OR_MONEY

    def test_amount_forces_money_tier(self, policy):
        assert policy.classify({"kind": "draft_email", "amount": 10}) == RiskTier.IRREVERSIBLE_OR_MONEY

    def test_unknown_kind_is_conservative(self, policy):
        assert policy.classify({"kind": "frobnicate_widget"}) == RiskTier.IRREVERSIBLE_OR_MONEY

    def test_explicit_risk_tier_respected(self, policy):
        assert policy.classify({"kind": "send_email", "risk_tier": 1}) == RiskTier.REVERSIBLE
        assert policy.classify({"kind": "research", "risk_tier": "money"}) == RiskTier.IRREVERSIBLE_OR_MONEY


class TestScoring:
    def test_irreversible_flag_bumps_to_external(self, policy):
        assert policy.classify({"kind": "save_note", "reversible": False}) == RiskTier.EXTERNAL

    def test_high_blast_radius_bumps_up(self, policy):
        assert policy.classify({"kind": "draft_email", "blast_radius": 0.9}) == RiskTier.EXTERNAL

    def test_low_signal_quality_bumps_up(self, policy):
        assert policy.classify({"kind": "summarize", "signal_quality": 0.1}) == RiskTier.REVERSIBLE


class TestBalancedDecisions:
    def test_reversible_acts_autonomously(self, policy):
        assert policy.decide({"kind": "draft_email"}).outcome == ACT
        assert policy.decide({"kind": "research_market"}).outcome == ACT

    def test_external_notifies(self, policy):
        assert policy.decide({"kind": "send_email"}).outcome == NOTIFY

    def test_irreversible_asks(self, policy):
        assert policy.decide({"kind": "delete_file"}).outcome == ASK


class TestMoneyCaps:
    def test_small_payment_within_cap_acts(self, policy):
        d = policy.decide({"kind": "pay_invoice", "amount": 20})
        assert d.outcome == ACT

    def test_payment_over_cap_asks(self, policy):
        d = policy.decide({"kind": "pay_invoice", "amount": 80})
        assert d.outcome == ASK
        assert d.urgent is True

    def test_daily_ceiling_enforced(self, policy):
        # spend up to near the ceiling with sub-cap payments
        policy.record_spend(190)
        d = policy.decide({"kind": "pay_invoice", "amount": 40})  # under cap, over ceiling
        assert d.outcome == ASK

    def test_reset_daily(self, policy):
        policy.record_spend(190)
        policy.reset_daily()
        assert policy.decide({"kind": "pay_invoice", "amount": 40}).outcome == ACT


class TestUrgency:
    def test_time_sensitive_ask_is_urgent(self, policy):
        d = policy.decide({"kind": "delete_file", "time_sensitivity": 0.9})
        assert d.outcome == ASK and d.urgent is True
