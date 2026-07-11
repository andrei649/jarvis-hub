"""0.48 Video Production Pipelines — offline planner (assembly / effects / localization).

Pure, deterministic, honest: it plans a cut, it never renders one (`generated: False`
everywhere), unknown transitions/effects are surfaced not invented, and localization never
auto-translates (non-base tracks are flagged `needs_translation`).
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.creative import video_pipeline as vp  # noqa: E402

# ── assembly ──────────────────────────────────────────────────────

def test_assembly_orders_scenes_and_sums_duration():
    plan = vp.plan_assembly([
        {"id": "a", "seconds": 5},
        {"id": "b", "seconds": 3, "transition": "cut"},
    ])
    assert [s["id"] for s in plan["scenes"]] == ["a", "b"]
    # cut has 0 overlap → total is the sum
    assert plan["total_seconds"] == 8.0
    assert plan["scenes"][0]["transition"] == "cut"      # no transition before the first
    assert all(s["generated"] is False for s in plan["scenes"])


def test_assembly_transition_overlap_pulls_duration_in():
    # a 1.0s fade overlaps the previous clip's tail → total < naive sum
    plan = vp.plan_assembly([
        {"id": "a", "seconds": 5},
        {"id": "b", "seconds": 5, "transition": "fade"},
    ])
    assert plan["scenes"][1]["transition"] == "fade"
    assert plan["total_seconds"] == 9.0                   # 10 - 1.0 overlap


def test_assembly_unknown_transition_surfaced_and_downgraded_to_cut():
    plan = vp.plan_assembly([
        {"id": "a", "seconds": 2},
        {"id": "b", "seconds": 2, "transition": "explode"},
    ])
    assert "explode" in plan["unknown_transitions"]
    assert plan["scenes"][1]["transition"] == "cut"       # safe default, not invented


def test_assembly_is_bounded():
    plan = vp.plan_assembly([{"seconds": 1}] * (vp._MAX_SCENES + 50))
    assert len(plan["scenes"]) == vp._MAX_SCENES


# ── effects ───────────────────────────────────────────────────────

def test_effects_keep_known_drop_unknown_and_filter_params():
    out = vp.plan_effects([
        {"name": "color_grade", "look": "teal-orange", "intensity": 0.7, "bogus": 1},
        {"name": "hologram", "intensity": 1},        # unknown effect
    ])
    assert out["unknown_effects"] == ["hologram"]
    assert len(out["effects"]) == 1
    fx = out["effects"][0]
    assert fx["name"] == "color_grade"
    assert fx["params"] == {"look": "teal-orange", "intensity": 0.7}   # bogus param dropped
    assert fx["generated"] is False


def test_effects_bounded():
    out = vp.plan_effects([{"name": "denoise", "strength": 1}] * (vp._MAX_EFFECTS + 5))
    assert len(out["effects"]) == vp._MAX_EFFECTS


# ── localization ──────────────────────────────────────────────────

def test_localization_base_plus_targets_never_autotranslates():
    cues = [{"start": 0, "end": 2, "text": "hello"}, {"start": 2, "end": 4, "text": "world"}]
    loc = vp.plan_localization("en", ["ro", "de"], cues)
    langs = [t["lang"] for t in loc["tracks"]]
    assert langs == ["en", "ro", "de"]
    base = next(t for t in loc["tracks"] if t["lang"] == "en")
    ro = next(t for t in loc["tracks"] if t["lang"] == "ro")
    assert base["is_base"] is True and base["needs_translation"] is False
    assert ro["needs_translation"] is True               # honest: not auto-translated
    assert [c["text"] for c in ro["cues"]] == ["hello", "world"]   # source text carried, flagged


def test_localization_dedupes_and_defaults_base():
    loc = vp.plan_localization("", ["en", "en", "ro"], [])
    assert loc["base_lang"] == "en"
    assert [t["lang"] for t in loc["tracks"]] == ["en", "ro"]


# ── top-level plan ────────────────────────────────────────────────

def test_build_video_plan_is_a_plan_never_a_render():
    plan = vp.build_video_plan({
        "title": "Launch teaser",
        "scenes": [{"id": "hook", "seconds": 3}, {"id": "reveal", "seconds": 4, "transition": "dissolve"}],
        "effects": [{"name": "color_grade", "look": "warm"}],
        "base_lang": "en", "target_langs": ["ro"],
        "cues": [{"start": 0, "end": 3, "text": "meet jarvis"}],
    })
    assert plan["title"] == "Launch teaser"
    assert plan["generated"] is False
    assert plan["assembly"]["generated"] is False
    assert plan["effects"]["generated"] is False
    assert plan["localization"]["generated"] is False
    assert plan["runtime_seconds"] == plan["assembly"]["total_seconds"]
    assert "no media is rendered or published" in plan["disclaimer"]


def test_build_video_plan_tolerates_empty_brief():
    plan = vp.build_video_plan({})
    assert plan["runtime_seconds"] == 0.0
    assert plan["assembly"]["scenes"] == []
    assert plan["localization"]["tracks"][0]["lang"] == "en"   # default base track

def _raises_after(limit, factory):
    for index in range(limit):
        yield factory(index)
    raise AssertionError("planner consumed past its declared bound")


def test_assembly_does_not_materialize_past_scene_bound():
    scenes = _raises_after(vp._MAX_SCENES, lambda i: {"id": str(i), "seconds": 1})
    plan = vp.plan_assembly(scenes)
    assert len(plan["scenes"]) == vp._MAX_SCENES


def test_effects_do_not_materialize_past_effect_bound():
    effects = _raises_after(
        vp._MAX_EFFECTS, lambda _i: {"name": "denoise", "strength": 1}
    )
    plan = vp.plan_effects(effects)
    assert len(plan["effects"]) == vp._MAX_EFFECTS


def test_localization_bounds_cues_and_languages_before_copying():
    cues = _raises_after(
        vp._MAX_CUES,
        lambda i: {"start": i, "end": i + 1, "text": f"cue-{i}"},
    )
    languages = _raises_after(vp._MAX_LANGUAGES, lambda i: f"x-{i}")
    plan = vp.plan_localization("en", languages, cues)

    assert len(plan["tracks"]) == vp._MAX_LANGUAGES + 1
    assert all(len(track["cues"]) == vp._MAX_CUES for track in plan["tracks"])


def test_effect_parameters_are_scalar_and_bounded():
    plan = vp.plan_effects([
        {"name": "color_grade", "look": "x" * 1000, "intensity": {"huge": [1] * 1000}},
    ])
    effect = plan["effects"][0]

    assert len(effect["params"]["look"]) == vp._MAX_PARAM_TEXT
    assert "intensity" not in effect["params"]
    assert plan["invalid_params"] == ["color_grade.intensity"]

