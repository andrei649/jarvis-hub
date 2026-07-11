"""creative/publishing.py — 0.50 Publishing Studio (offline publish packager).

Sits on top of `creative/pipeline.py` (which produces per-platform export **specs**). A
*publishing* package pairs a finished-asset spec with **validated** platform metadata
(title/description/caption/hashtags) and a **pre-publish checklist**, so the owner reviews a
complete, honest package before the (kernel-held) release.

Honest by construction: it validates + packages, it never publishes. Metadata that violates a
platform rule is surfaced in `violations` (never silently trimmed into a false-pass), and the
terminal publish is the irreversible action the Action Kernel QUEUEs for approval
(`creative/pipeline.py:release_action_payload`). Pure, deterministic, offline.
"""

from __future__ import annotations

from agents.core.creative.pipeline import EXPORT_TARGETS, release_action_payload

# Per-platform metadata rules. `title_max`/`desc_max` are hard caps; `hashtags_max` bounds tags;
# `needs` lists the fields a publish package must carry for that platform.
PLATFORM_RULES: dict[str, dict] = {
    "youtube": {"title_max": 100, "desc_max": 5000, "hashtags_max": 15,
                "needs": ("title", "description", "thumbnail")},
    "instagram": {"title_max": 0, "desc_max": 2200, "hashtags_max": 30,
                  "needs": ("caption",)},
    "readme": {"title_max": 120, "desc_max": 100000, "hashtags_max": 0,
               "needs": ("title", "body")},
}


def _s(v, limit: int = 100000) -> str:
    return str(v if v is not None else "").strip()[:limit]


def validate_metadata(platform: str, meta: dict) -> list[str]:
    """Return a list of human-readable rule violations (empty = clean). Never mutates *meta*."""
    rules = PLATFORM_RULES.get(platform)
    m = meta if isinstance(meta, dict) else {}
    if not rules:
        return [f"unknown platform: {platform}"]
    out: list[str] = []
    for field in rules["needs"]:
        if not _s(m.get(field)):
            out.append(f"missing required field: {field}")
    title = _s(m.get("title"))
    if rules["title_max"] and len(title) > rules["title_max"]:
        out.append(f"title exceeds {rules['title_max']} chars ({len(title)})")
    desc = _s(m.get("description")) or _s(m.get("caption")) or _s(m.get("body"))
    if rules["desc_max"] and len(desc) > rules["desc_max"]:
        out.append(f"body/description exceeds {rules['desc_max']} chars ({len(desc)})")
    tags = [t for t in (m.get("hashtags") or []) if _s(t)]
    if rules["hashtags_max"] == 0 and tags:
        out.append("this platform takes no hashtags")
    elif len(tags) > rules["hashtags_max"]:
        out.append(f"too many hashtags: {len(tags)} > {rules['hashtags_max']}")
    return out


def prepublish_checklist(platform: str, meta: dict) -> list[dict]:
    """A pass/fail checklist the owner reviews before release. Deterministic; no side effects."""
    rules = PLATFORM_RULES.get(platform) or {}
    m = meta if isinstance(meta, dict) else {}
    checks = [
        {"check": "platform known", "ok": platform in PLATFORM_RULES},
        {"check": "required fields present",
         "ok": all(_s(m.get(f)) for f in rules.get("needs", ()))},
        {"check": "within length limits", "ok": not validate_metadata(platform, meta)},
        {"check": "disclosure/consent acknowledged", "ok": bool(m.get("disclosed"))},
    ]
    return checks


def build_publish_package(platform: str, meta: dict, *, title: str = "") -> dict:
    """Assemble a review-ready publish package (export spec + validated metadata + checklist).

    ``generated: False`` — nothing is uploaded; ``ready`` is True only when there are zero
    violations AND the checklist fully passes. Use ``release_payload`` to hand the (kernel-held)
    publish to the approval queue.
    """
    spec = EXPORT_TARGETS.get(platform)
    violations = validate_metadata(platform, meta)
    checklist = prepublish_checklist(platform, meta)
    ready = not violations and all(c["ok"] for c in checklist)
    return {
        "platform": platform,
        "export_spec": dict(spec) if spec else None,
        "metadata": dict(meta) if isinstance(meta, dict) else {},
        "violations": violations,
        "checklist": checklist,
        "ready": ready,
        "generated": False,
        "disclaimer": "Package only — nothing is published here; the release is held by the "
                      "Action Kernel for owner approval.",
        "release_payload": release_action_payload({"target": platform,
                                                    "filename": _s(title, 200) or platform}),
    }
