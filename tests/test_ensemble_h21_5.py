"""H21.5 — Ensemble diversity & identity-anchored maturation. All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.cognition.ensemble import (
    trait_distance, diversity_check, bounded_drift, drift_magnitude,
    EnsembleModule, LIFETIME_CAP,
)


def test_trait_distance():
    assert trait_distance({"a": 0.0}, {"a": 0.0}) == 0.0
    assert trait_distance({"a": 0.0, "b": 0.0}, {"a": 0.3, "b": 0.4}) == 0.5


def test_diversity_flags_close_pairs():
    diverse = {"x": {"warmth": 0.2}, "y": {"warmth": 0.9}}
    assert diversity_check(diverse, eps=0.1)["ok"] is True
    close = {"x": {"warmth": 0.50}, "y": {"warmth": 0.52}}
    res = diversity_check(close, eps=0.1)
    assert res["ok"] is False and res["violations"][0]["distance"] < 0.1


def test_bounded_drift_clamps_to_lifetime_cap():
    base = {"warmth": 0.5}
    out = bounded_drift(base, {"warmth": 0.95})       # wants +0.45, capped to +0.10
    assert out["warmth"] == round(0.5 + LIFETIME_CAP, 4)
    out2 = bounded_drift(base, {"warmth": 0.0})        # wants -0.5, capped to -0.10
    assert out2["warmth"] == round(0.5 - LIFETIME_CAP, 4)


def test_drift_proposal_is_bounded_and_gated():
    e = EnsembleModule()
    e.register_persona("jarvis", {"warmth": 0.5, "humor": 0.4})
    prop = e.drift_proposal("jarvis", {"warmth": 1.0, "humor": 1.0})
    assert prop["requires_approval"] is True and prop["reversible"] is True
    assert prop["proposed"]["warmth"] == round(0.5 + LIFETIME_CAP, 4)   # clamped


def test_apply_drift_then_diff():
    e = EnsembleModule()
    e.register_persona("jarvis", {"warmth": 0.5})
    e.apply_drift("jarvis", {"warmth": 0.58})
    d = e.diff("jarvis")
    assert d["current"]["warmth"] == 0.58 and d["delta"]["warmth"] == round(0.08, 4)


def test_psychometric_selftest_tripwire():
    e = EnsembleModule(selftest_threshold=0.05)
    e.register_persona("jarvis", {"warmth": 0.5})
    assert e.psychometric_selftest("jarvis")["tripwire"] is False   # no drift yet
    e.apply_drift("jarvis", {"warmth": 0.6})                        # +0.10 > 0.05
    st = e.psychometric_selftest("jarvis")
    assert st["tripwire"] is True and st["drift"] > 0.05


def test_relational_delta_accumulates():
    e = EnsembleModule()
    e.relational_delta("jarvis", "andrei", 0.1)
    assert e.relational_delta("jarvis", "andrei", 0.2) == round(0.3, 4)


def test_status_reports_diversity():
    e = EnsembleModule()
    e.register_persona("a", {"warmth": 0.2})
    e.register_persona("b", {"warmth": 0.9})
    st = e.status()
    assert st["agents"] == ["a", "b"] and st["diversity"]["ok"] is True
