"""H21.4 — Governed learning signals (KC mastery + calibration + corrections)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.cognition.learning import (
    KCStore, CorrectionLedger, calibration_autonomy_adjustment, LearningModule,
)
from agents.core.autonomy.policy import AutonomyPolicy, RiskTier


# ── KC mastery + calibration ──────────────────────────────────────────────────

def test_mastery_tracks_success_rate():
    kc = KCStore()
    kc.record("algebra", True)
    kc.record("algebra", True)
    kc.record("algebra", False)
    assert kc.mastery("algebra") == round(2 / 3, 3)
    assert kc.mastery("unknown") == 0.0


def test_calibration_brier():
    kc = KCStore()
    kc.record("a", correct=True, confidence=0.9)     # confident + right → low brier
    assert kc.calibration_error("a") == round((0.9 - 1.0) ** 2, 3)
    kc.record("b", correct=False, confidence=0.9)    # confident + wrong → high brier
    assert kc.calibration_error("b") == round((0.9 - 0.0) ** 2, 3)


def test_kc_scoping_user_vs_agent():
    kc = KCStore()
    kc.record("x", True, scope="agent", who="jarvis")
    kc.record("x", False, scope="user", who="andrei")
    assert kc.mastery("x", "agent", "jarvis") == 1.0
    assert kc.mastery("x", "user", "andrei") == 0.0
    assert len(kc.list()) == 2


# ── correction ledger ─────────────────────────────────────────────────────────

def test_correction_ledger():
    cl = CorrectionLedger()
    cl.record("it's 5", "it's 4", component="math")
    cl.record("same", "same")
    assert cl.count() == 2
    assert cl.entries()[0]["changed"] is False    # most-recent first; "same"==
    assert cl.entries()[1]["changed"] is True


# ── calibration → autonomy adjustment ─────────────────────────────────────────

def test_calibration_adjustment():
    assert calibration_autonomy_adjustment(0.9, None) == 0       # no data → neutral
    assert calibration_autonomy_adjustment(0.9, 0.05) == 0       # mastered + calibrated
    assert calibration_autonomy_adjustment(0.3, 0.05) == 1       # low mastery → caution
    assert calibration_autonomy_adjustment(0.9, 0.4) == 1        # miscalibrated → caution


# ── module ────────────────────────────────────────────────────────────────────

def test_module_practice_proposals():
    lm = LearningModule()
    for _ in range(3):
        lm.record_outcome("weak", correct=False, confidence=0.8)   # mastery 0, miscalibrated
    lm.record_outcome("strong", correct=True, confidence=0.9)
    props = lm.practice_proposals()
    names = {p["component"] for p in props}
    assert "weak" in names and "strong" not in names


def test_module_autonomy_adjustment_and_status():
    lm = LearningModule()
    lm.record_outcome("send_email", correct=False, confidence=0.9)   # miscalibrated
    assert lm.autonomy_adjustment("send_email") == 1
    lm.record_correction("a", "b")
    st = lm.status()
    assert st["kc_count"] == 1 and st["corrections"] == 1


# ── policy integration (gated, safe) ──────────────────────────────────────────

def test_policy_hook_bumps_tier():
    p = AutonomyPolicy()
    base = p.classify({"risk_tier": 1})              # REVERSIBLE
    p.calibration_hook = lambda a: 1
    assert int(p.classify({"risk_tier": 1})) == int(base) + 1


def test_policy_hook_default_is_noop():
    p = AutonomyPolicy()
    assert p.classify({"risk_tier": 1}) == RiskTier.REVERSIBLE   # unchanged without hook


def test_policy_hook_never_exceeds_irreversible():
    p = AutonomyPolicy()
    p.calibration_hook = lambda a: 9
    assert int(p.classify({"risk_tier": 1})) == int(RiskTier.IRREVERSIBLE_OR_MONEY)
    # already top tier → hook is skipped, stays put (never overflows)
    assert int(p.classify({"risk_tier": 3})) == int(RiskTier.IRREVERSIBLE_OR_MONEY)
