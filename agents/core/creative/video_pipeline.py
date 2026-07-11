"""creative/video_pipeline.py — 0.48 Video Production Pipelines (offline planner).

Extends ``video_prompt.py`` (a single-prompt helper) into a coordinated *production plan*:

* **assembly** — order scenes into a timeline with validated transitions + total duration,
* **effects** — per-clip effect specs from a whitelist (unknown effects surfaced, never invented),
* **localization** — subtitle/caption track specs per target language (never machine-translates
  behind your back — untranslated cues are flagged ``needs_translation``).

Like the P4 creative pipeline this is a **planner**, honest by construction:

* **Nothing is faked as rendered.** Every clip / effect / track records the (null) generator it
  *would* drive and ``generated: False``. The actual encode/render/burn-in is owner-gated wiring
  (a real NLE / ffmpeg / cloud video model), never invented here.
* **Publish is held.** Planning + drafting is reversible (kernel GRANT); the terminal publish of a
  finished cut is the irreversible step the Action Kernel QUEUEs for approval — reuse
  ``creative/pipeline.py:release_action_payload`` for that release-class action.

Pure, deterministic, offline-testable — no clocks, no randomness, no network.
"""

from __future__ import annotations

import math
from itertools import islice

# Transition allowlist: name → default duration (seconds) between two scenes. A transition not
# on this list is surfaced in ``unknown_transitions`` and downgraded to a hard ``cut`` (safe
# default), never silently accepted or invented.
TRANSITIONS: dict[str, float] = {
    "cut": 0.0, "dissolve": 0.5, "fade": 1.0, "fadeblack": 1.0, "wipe": 0.5, "slide": 0.5,
}

# Effect allowlist: name → the parameter keys it accepts. A requested effect not on this list
# is surfaced in ``unknown_effects`` and dropped; unknown params on a known effect are dropped.
EFFECTS: dict[str, tuple[str, ...]] = {
    "color_grade": ("look", "intensity"),
    "stabilize": ("strength",),
    "speed_ramp": ("factor",),
    "zoom": ("scale", "direction"),
    "denoise": ("strength",),
    "subtitle_burn": ("lang", "position"),
}

_MAX_SCENES = 200
_MAX_EFFECTS = 12
_MAX_CUES = 2000
_MAX_LANGUAGES = 20
_MAX_PARAM_TEXT = 200


def _num(v, default: float = 0.0) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


def _s(v, limit: int = 200) -> str:
    return str(v if v is not None else "").strip()[:limit]


def _take(values, limit: int) -> list:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    try:
        return list(islice(iter(values), limit))
    except TypeError:
        return []


def _safe_param(value):
    if isinstance(value, str):
        return True, _s(value, _MAX_PARAM_TEXT)
    if isinstance(value, bool):
        return True, value
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(float(value))
        except (OverflowError, TypeError, ValueError):
            finite = False
        if finite:
            return True, value
    return False, None


def plan_assembly(scenes, *, default_transition: str = "cut") -> dict:
    """Order *scenes* into a timeline with validated transitions and a total duration.

    ``scenes`` is a list of dicts ``{id?, source?, seconds, transition?}``. Returns a plan with
    per-scene ``start``/``end`` offsets, the applied transition (unknown → ``cut``, surfaced),
    the total runtime, and ``generated: False`` — this describes a cut, it does not render one.
    """
    dt = default_transition if default_transition in TRANSITIONS else "cut"
    items = _take(scenes, _MAX_SCENES)
    timeline: list[dict] = []
    unknown: list[str] = []
    t = 0.0
    for i, sc in enumerate(items):
        sc = sc if isinstance(sc, dict) else {}
        seconds = _num(sc.get("seconds"), 0.0)
        req = _s(sc.get("transition"), 40) or (dt if i > 0 else "cut")
        if req not in TRANSITIONS:
            unknown.append(req)
            req = "cut"
        trans = req if i > 0 else "cut"           # no transition before the first scene
        overlap = TRANSITIONS[trans]
        # a transition overlaps the tail of the previous clip, so it pulls the start back
        start = max(0.0, t - overlap)
        end = start + seconds
        timeline.append({
            "index": i,
            "id": _s(sc.get("id"), 80) or f"scene{i}",
            "source": _s(sc.get("source"), 300),
            "seconds": seconds,
            "transition": trans,
            "start": round(start, 3),
            "end": round(end, 3),
            "generated": False,
        })
        t = end
    return {
        "kind": "assembly",
        "scenes": timeline,
        "total_seconds": round(t, 3),
        "unknown_transitions": unknown,
        "generated": False,
    }


def plan_effects(effects) -> dict:
    """Validate a list of requested effects against the allowlist.

    ``effects`` is a list of dicts ``{name, ...params}``. Returns validated effect specs (only
    known params kept), plus ``unknown_effects`` for anything off the allowlist (surfaced, never
    silently dropped). Bounded to ``_MAX_EFFECTS``.
    """
    out: list[dict] = []
    unknown: list[str] = []
    invalid: list[str] = []
    for e in _take(effects, _MAX_EFFECTS):
        e = e if isinstance(e, dict) else {}
        name = _s(e.get("name"), 40)
        if name not in EFFECTS:
            if name:
                unknown.append(name)
            continue
        params: dict = {}
        for key in EFFECTS[name]:
            if key not in e:
                continue
            ok, value = _safe_param(e[key])
            if ok:
                params[key] = value
            else:
                invalid.append(f"{name}.{key}")
        out.append({"name": name, "params": params, "generator": "null", "generated": False})
    return {
        "kind": "effects",
        "effects": out,
        "unknown_effects": unknown,
        "invalid_params": invalid,
        "generated": False,
    }


def plan_localization(base_lang: str, target_langs, cues) -> dict:
    """Plan subtitle/caption tracks for *target_langs* from timed *cues*.

    ``cues`` is a list of ``{start, end, text}``. The base-language track carries the source text;
    every other target gets a track with the SAME cues flagged ``needs_translation: True`` — the
    planner never machine-translates behind your back. Returns one track per language.
    """
    base = _s(base_lang, 12) or "en"
    src_cues = []
    for c in _take(cues, _MAX_CUES):
        c = c if isinstance(c, dict) else {}
        src_cues.append({
            "start": round(_num(c.get("start")), 3),
            "end": round(_num(c.get("end")), 3),
            "text": _s(c.get("text"), 500),
        })
    tracks: list[dict] = []
    seen: set[str] = set()
    targets = _take(target_langs, _MAX_LANGUAGES)
    for lang in [base, *targets]:
        lang = _s(lang, 12)
        if not lang or lang in seen:
            continue
        seen.add(lang)
        is_base = lang == base
        tracks.append({
            "lang": lang,
            "is_base": is_base,
            "needs_translation": not is_base,     # honest: not auto-translated
            "cues": [dict(c) for c in src_cues],
            "generated": False,
        })
    return {"kind": "localization", "base_lang": base, "tracks": tracks, "generated": False}


def build_video_plan(brief: dict) -> dict:
    """Combine assembly + effects + localization into one production plan from a *brief*.

    ``brief`` = ``{title?, scenes?, effects?, base_lang?, target_langs?, cues?, default_transition?}``.
    The result is a pure plan (``generated: False`` throughout); rendering/publishing is the
    owner-gated step, held by the Action Kernel via ``creative/pipeline.py``.
    """
    b = brief if isinstance(brief, dict) else {}
    assembly = plan_assembly(b.get("scenes"), default_transition=_s(b.get("default_transition"), 40) or "cut")
    effects = plan_effects(b.get("effects"))
    loc = plan_localization(_s(b.get("base_lang"), 12) or "en", b.get("target_langs"), b.get("cues"))
    return {
        "title": _s(b.get("title"), 200),
        "assembly": assembly,
        "effects": effects,
        "localization": loc,
        "runtime_seconds": assembly["total_seconds"],
        "generated": False,        # a plan, never a rendered file
        "disclaimer": "Plan only — no media is rendered or published here; render/encode/publish "
                      "is owner-gated and the terminal publish is held by the Action Kernel.",
    }
