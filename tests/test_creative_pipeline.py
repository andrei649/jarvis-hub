"""P4 — Creative / Publishing pack: a planner with provenance + a publish-is-held rail.

The pipeline plans stages (script→…→export) and per-platform export-pack *specs* with
provenance — never faking generated media (everything carries ``generated: False``). The
governance test proves the publishing-safety property with real primitives: the pipeline
drafts/plans freely (GRANT), but the terminal **release** (publishing to the world) is
QUEUED by the real kernel — nothing is auto-published on the user's behalf.
"""

import os
import shutil
import tempfile

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.creative import (
    EXPORT_TARGETS,
    build_export_packs,
    plan_pipeline,
    release_action_payload,
)
from agents.core.kernel import Action, Verdict, authorize
from agents.core.observability import capability_registry as cr
from agents.core.observability.reality_harness import CASES, run_reality
from agents.core.security.capability import KillSwitch


# ── pipeline plan ──────────────────────────────────────────────────────────────
def test_plan_has_ordered_stages_chained_by_provenance():
    plan = plan_pipeline({"goal": "Launch teaser", "inputs": ["brand_book.md", "demo.mp4"]})
    assert [s["id"] for s in plan["stages"]] == ["script", "image_prompts", "render", "assemble", "export"]
    assert plan["stages"][0]["inputs"] == ["brand_book.md", "demo.mp4"]   # first stage takes the brief
    assert plan["stages"][1]["inputs"] == ["<script>"]                    # each stage feeds the next
    assert plan["slug"] == "launch-teaser"


def test_nothing_is_faked_as_generated():
    plan = plan_pipeline({"goal": "x", "platforms": ["youtube"]})
    assert all(s["generated"] is False for s in plan["stages"])
    assert all(p["generated"] is False for p in plan["exports"])
    assert plan["provenance"]["generated"] is False


def test_export_packs_specs_for_known_targets_only():
    packs = build_export_packs("My Demo", ["youtube", "instagram", "readme", "tiktok"])
    targets = [p["target"] for p in packs]
    assert targets == ["youtube", "instagram", "readme"]   # tiktok unmodeled → dropped, not invented
    yt = next(p for p in packs if p["target"] == "youtube")
    assert yt["aspect"] == "16:9" and yt["filename"] == "my-demo-youtube.mp4"
    ig = next(p for p in packs if p["target"] == "instagram")
    assert ig["aspect"] == "9:16" and ig["format"] == "mp4"
    readme = next(p for p in packs if p["target"] == "readme")
    assert readme["format"] == "png" and readme["caption_kind"] == "markdown-embed"


def test_empty_or_garbage_brief_is_honest():
    assert plan_pipeline(None)["slug"] == "short-video"        # falls back to the format
    assert plan_pipeline({})["exports"][0]["target"] == "youtube"   # default platforms
    # an all-unknown platform list still yields a readme pack (never an empty/invented plan)
    assert plan_pipeline({"goal": "g", "platforms": ["tiktok"]})["exports"][0]["target"] == "readme"


def test_known_export_targets_are_the_three_ac_platforms():
    assert set(EXPORT_TARGETS) == {"youtube", "instagram", "readme"}


# ── governance rail: publish is held, drafting is free (real policy + kernel) ───
def _authorize(action):
    d = tempfile.mkdtemp(prefix="creative-gov-")
    try:
        ks = KillSwitch(path=os.path.join(d, "kill.json"))  # isolated, not halted
        return authorize(action, kill_switch=ks, policy=AutonomyPolicy())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_release_is_queued_drafting_is_granted():
    plan = plan_pipeline({"goal": "teaser", "platforms": ["youtube"]})
    draft = _authorize(Action(kind="creative.draft", title="draft script", scope="global"))
    release = _authorize(Action(kind="release.publish", title="release campaign to youtube",
                                scope="global", payload=release_action_payload(plan["exports"][0])))
    assert draft.verdict is Verdict.GRANT                # planning/drafting runs freely
    assert release.verdict is Verdict.QUEUE              # publishing to the world is held
    assert "IRREVERSIBLE_OR_MONEY" in (release.reason or "")


# ── the reality case promotes the creative capability to VERIFIED ──────────────
def teardown_function():
    cr.clear_verifications()
    cr._OVERRIDES.clear()


async def test_creative_reality_case_present_and_passes():
    case = next((c for c in CASES if c.name == "creative-release-queued"), None)
    assert case is not None, "the P4 publish-is-held reality case must be registered"
    assert case.capability_id == "plugin:social_x" and case.live is False
    out = await run_reality([case], now="2026-06-28T00:00:00+00:00")
    assert out["passed"] == 1 and out["total"] == 1 and "plugin:social_x" in out["promoted"]
