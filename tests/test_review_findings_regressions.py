"""H20 learning loop — regressions from the adversarial diff review. Offline.

  1. generate_skill provenance must be recorded under the REGISTERED skill name
     (manifest title), which is what the curator iterates — not the dir slug.
  2. review fact-dedupe must not count an unchanged core ring as a write.
  3. sub-agent turns (channel="subagent") never trigger a review pass.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import json

from agents.core.cognition.memory import LivingMemory
from agents.core.learning.background_review import BackgroundReviewer
from agents.core.orchestrator import Orchestrator
from agents.core.skills import loader as loader_module
from agents.core.skills.loader import SkillLoader
from agents.core.skills.usage import SkillUsageStore


def test_generated_skill_provenance_uses_registered_name(tmp_path, monkeypatch):
    monkeypatch.setattr(loader_module, "SKILLS_DIR", tmp_path / "skills")
    loader = SkillLoader()
    usage = SkillUsageStore(path=tmp_path / "usage.json")
    loader.attach_usage(usage)

    slug = loader.generate_skill("jarvis", "triage the inbox daily", ["scan", "sort"])
    assert slug is not None

    # the registry key is the manifest title (Title Case), not the dir slug —
    # provenance recorded under the slug would be invisible to the curator
    registered = next(n for n, s in loader.skills.items()
                      if str(getattr(s, "path", "")).endswith(slug))
    assert registered != slug
    rec = usage.get(registered)
    assert rec is not None and rec["origin"] == "agent"
    assert usage.curatable(registered) is True       # the curator can see it


async def test_duplicate_fact_not_counted_as_update(tmp_path):
    living = LivingMemory(core_path=tmp_path / "c.json",
                          tiers_path=tmp_path / "t.json",
                          user_path=tmp_path / "u.json")

    async def llm(prompt):
        return json.dumps({"user_facts": ["prefers RO"], "agent_facts": [],
                           "corrections": [], "skill_updates": [], "nothing": False})

    r = BackgroundReviewer(llm, living=living)
    first = await r.run("u", "a")
    assert first["counts"]["facts"] == 1
    second = await r.run("u", "a")                    # same fact again → dedupe
    assert second["counts"]["facts"] == 0
    assert not any("User profile updated" in a for a in second["actions"])
    assert living.user_core.list() == ["prefers RO"]


def test_subagent_channel_is_review_skipped():
    assert "subagent" in Orchestrator._REVIEW_SKIP_CHANNELS
    assert "reflection" in Orchestrator._REVIEW_SKIP_CHANNELS
    assert "autonomy" in Orchestrator._REVIEW_SKIP_CHANNELS
