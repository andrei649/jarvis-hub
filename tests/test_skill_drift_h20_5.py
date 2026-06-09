"""H20.5 — Skill drift manifest + refinement proposal. All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.skill_drift import manifest_hash, SkillDriftManifest, refine_proposal


def test_manifest_hash_stable_and_whitespace_normalized():
    assert manifest_hash("hello world") == manifest_hash("hello world")
    assert manifest_hash("a\nb  ") == manifest_hash("a\nb")          # trailing ws normalized
    assert manifest_hash("a") != manifest_hash("b")


def test_record_and_detect_drift():
    m = SkillDriftManifest()
    m.record("s1", "version one")
    assert m.has_drifted("s1", "version one") is False
    assert m.has_drifted("s1", "version TWO") is True
    assert m.has_drifted("unknown", "x") is False        # unknown → not drift


def test_drift_report_classifies():
    m = SkillDriftManifest()
    m.record("a", "aaa")
    m.record("b", "bbb")
    report = m.drift_report({"a": "aaa", "b": "CHANGED", "c": "new one"})
    assert report["unchanged"] == ["a"]
    assert report["drifted"] == ["b"]
    assert report["new"] == ["c"]


@pytest.mark.asyncio
async def test_refine_proposal_with_refiner():
    async def refiner(content):
        return content + "\n# improved"

    out = await refine_proposal("s1", "body", refiner=refiner)
    assert out["changed"] is True and out["requires_approval"] is True
    assert out["proposed"].endswith("# improved")


@pytest.mark.asyncio
async def test_refine_proposal_deferred_without_refiner():
    out = await refine_proposal("s1", "body")
    assert out["proposed"] == "" and out["changed"] is False


@pytest.mark.asyncio
async def test_refine_proposal_refiner_failure_is_safe():
    async def boom(content):
        raise RuntimeError("llm down")

    out = await refine_proposal("s1", "body", refiner=boom)
    assert out["changed"] is False and out["proposed"] == ""
