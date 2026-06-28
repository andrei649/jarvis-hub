"""creative/pipeline.py — P4 Creative / Publishing pack: governed asset pipeline planner.

ORIZONT 24 Track P (P4 — Creative / Publishing). Plans a coordinated creative pipeline
(script → image prompts → render → assemble → export) from a brief, and builds per-platform
**export packs** (YouTube / Instagram / README) — deterministic *specs*, with provenance.
Two properties keep it honest:

* **Nothing is faked as generated.** This is a *planner*: every stage and export pack
  records its inputs + the (null) generator it *would* call and ``generated: False``. The
  actual media generation (image/video models) is owner-gated wiring — the planner never
  invents a rendered asset and passes it off as real.
* **Publish is held.** The pipeline plans and drafts freely (the Action Kernel GRANTs
  reversible draft/plan work), but the terminal **release** — publishing a finished
  campaign to the world — is an irreversible side-effect the kernel QUEUEs for approval.
  :func:`release_action_payload` builds that release-class action; the P4 reality case
  proves it is held against the real policy + kernel.

Offline by design: it plans over the brief you provide. Live render/publish (a media-gen
API, the platform upload APIs) is owner-gated (`docs/OWNER_TASKS.md`).
"""

from __future__ import annotations

# Export targets → a deterministic render spec (NOT a rendered file). Aspect/size/format
# mirror each platform's canonical delivery; `caption_kind` tells the (owner-gated) render
# step what copy to attach. README is the docs/marketing embed (markdown, no media-gen).
EXPORT_TARGETS: dict[str, dict] = {
    "youtube": {"aspect": "16:9", "width": 1920, "height": 1080, "format": "mp4",
                "caption_kind": "title+description", "max_seconds": 600},
    "instagram": {"aspect": "9:16", "width": 1080, "height": 1920, "format": "mp4",
                  "caption_kind": "caption+hashtags", "max_seconds": 90},
    "readme": {"aspect": "16:9", "width": 1200, "height": 630, "format": "png",
               "caption_kind": "markdown-embed", "max_seconds": 0},
}

# The ordered pipeline. Each stage names the (null) generator it would drive and whether it
# is a write/side-effecting step. `kind` maps to the kernel verb tier (plan/draft → GRANT).
_STAGES = [
    {"id": "script", "title": "Script & beats", "generator": "llm", "kind": "creative.draft"},
    {"id": "image_prompts", "title": "Image prompts", "generator": "llm", "kind": "creative.draft"},
    {"id": "render", "title": "Render frames/clips", "generator": "media_gen", "kind": "creative.plan"},
    {"id": "assemble", "title": "Assemble cut", "generator": "editor", "kind": "creative.draft"},
    {"id": "export", "title": "Export packs", "generator": "exporter", "kind": "creative.draft"},
]


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in str(text or "").strip()]
    s = "".join(keep)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-") or "asset"


def plan_pipeline(brief) -> dict:
    """Plan a creative pipeline from *brief* ``{goal, format?, platforms?, inputs?}``.

    Returns the ordered stages (each carrying provenance: its inputs + the null generator
    it would call + ``generated: False``) and the export-pack specs for the requested
    platforms. Pure + deterministic; an empty/garbage brief yields a minimal honest plan.
    """
    b = brief if isinstance(brief, dict) else {}
    goal = str(b.get("goal") or "").strip()
    fmt = str(b.get("format") or "short-video").strip()
    inputs = [str(x) for x in (b.get("inputs") or []) if str(x).strip()]
    platforms = [p for p in (b.get("platforms") or ["youtube", "readme"]) if p in EXPORT_TARGETS]
    if not platforms:
        platforms = ["readme"]

    stages = []
    for i, s in enumerate(_STAGES):
        stage_inputs = inputs if i == 0 else [f"<{_STAGES[i - 1]['id']}>"]  # each stage feeds the next
        stages.append({
            "id": s["id"], "title": s["title"], "kind": s["kind"],
            "generator": s["generator"], "inputs": stage_inputs,
            "generated": False,        # planner only — nothing is actually produced here
        })

    return {
        "goal": goal,
        "format": fmt,
        "slug": _slug(goal or fmt),
        "stages": stages,
        "exports": build_export_packs(goal or fmt, platforms),
        "provenance": {"source_inputs": inputs, "generated": False,
                       "note": "plan only — render/publish are owner-gated"},
    }


def build_export_packs(title, targets) -> list[dict]:
    """Per-platform export-pack *specs* (dimensions/format/caption-kind) — never rendered media.

    Each pack is a deterministic delivery spec for the (owner-gated) render step, with
    ``generated: False`` so a spec is never mistaken for a finished asset. Unknown targets
    are dropped (honest — no spec is invented for a platform we don't model).
    """
    packs: list[dict] = []
    for t in targets or []:
        spec = EXPORT_TARGETS.get(t)
        if not spec:
            continue
        packs.append({
            "target": t,
            "filename": f"{_slug(title)}-{t}.{spec['format']}",
            **spec,
            "generated": False,
        })
    return packs


def release_action_payload(pack: dict, *, base: dict | None = None) -> dict:
    """Build the terminal **release** (publish-to-world) action payload.

    Publishing a finished campaign is an irreversible external side-effect, so the payload
    declares the irreversible risk tier — the Action Kernel QUEUEs it for approval. The
    pipeline plans/drafts freely, but it can never auto-publish on your behalf.
    """
    from agents.core.autonomy.policy import RiskTier
    payload = dict(base or {})
    p = pack if isinstance(pack, dict) else {}
    payload.update({
        "target": p.get("target"),
        "filename": p.get("filename"),
        "risk_tier": int(RiskTier.IRREVERSIBLE_OR_MONEY),  # publication is irreversible → held
    })
    return payload
