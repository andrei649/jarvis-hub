"""O26-P2.3 — dormant-module disposition.

Pins the advertised cognition modules so none of them are both shipped and
asleep: ensemble/persona get the live active-agent roster, governed learning is
proved at the autonomy hook, and the legacy profile extractor is explicitly
parked instead of silently presented as a live turn seam.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))
sys.path.insert(0, str(repo_root / "tests"))

from golden_harness import make_golden_orchestrator  # noqa: E402

from agents.core.autonomy.policy import RiskTier  # noqa: E402
from agents.core.memory import profile_extractor  # noqa: E402


@pytest.mark.asyncio
async def test_active_agents_populate_persona_and_ensemble_rosters(monkeypatch, tmp_path):
    orch, _fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    active_ids = sorted(orch.agents.keys())

    persona = orch.cognition.module("persona")
    ensemble = orch.cognition.module("ensemble")

    assert persona.status()["agents"] == active_ids
    assert ensemble.status()["agents"] == active_ids
    assert ensemble.status()["diversity"]["min_distance"] is not None


@pytest.mark.asyncio
async def test_governed_learning_is_wired_to_autonomy_caution(monkeypatch, tmp_path):
    orch, _fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    orch._runtime_settings.update({
        "cognition.enabled": True,
        "cognition.learning_enabled": True,
    })

    learning = orch.cognition.module("learning")
    learning.record_outcome("note", correct=False, confidence=0.9)

    assert orch.autonomy.policy.classify({"kind": "note"}) == RiskTier.EXTERNAL


def test_profile_extractor_is_explicitly_parked_legacy_code():
    status = profile_extractor.legacy_status()

    assert status["active"] is False
    assert status["disposition"] == "parked"
    assert status["production_callers"] == []


def test_profile_extractor_has_no_production_callers():
    allowed = {
        Path("agents/core/memory/profile_extractor.py"),
        Path("agents/core/memory/__init__.py"),
    }
    callers = []
    for path in (repo_root / "agents").rglob("*.py"):
        rel = path.relative_to(repo_root)
        if rel in allowed:
            continue
        if "profile_extractor" in path.read_text(encoding="utf-8"):
            callers.append(rel.as_posix())

    assert callers == []
