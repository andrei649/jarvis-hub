"""system_profiles.py — 0.62 System Profiles (usage-mode posture presets).

Named usage modes — like power plans for the assistant — selected with the
``JARVIS_SYSTEM_PROFILE`` env, consistent with the other env-driven posture
presets in the codebase (``JARVIS_HARDENED``, ``JARVIS_PLUGIN_LEAST_PRIVILEGE``).

Each profile declares a small set of posture knobs that other subsystems read via
:func:`active_posture`. The default is **``balanced``**, whose knobs match the
historical behavior — so with the env unset nothing changes. The first live
consumer is proactive-autonomy gating: a profile with ``background_autonomy:
False`` (gaming / multimedia) pauses agent heartbeats to free local resources;
``balanced`` keeps them on, so the default path is untouched.

Knobs (all advisory — consumers opt in by reading them):
  * ``background_autonomy`` (bool) — run proactive agent heartbeats? *(wired)*
  * ``heavy_features``      (bool) — allow heavy work (media gen / deep research)?
  * ``max_parallel_agents`` (int|None) — concurrency hint (None = no hint).
  * ``model_tier``          (str)  — preferred model weight ("local-light"/"local"/"auto").
"""

from __future__ import annotations

import os

DEFAULT = "balanced"

PROFILES: dict[str, dict] = {
    "balanced": {
        "description": "Default — full assistant behavior, balanced resource use.",
        "background_autonomy": True, "heavy_features": True,
        "max_parallel_agents": None, "model_tier": "auto",
    },
    "gaming": {
        "description": "Free the GPU/CPU for games — pause background AI, light models only.",
        "background_autonomy": False, "heavy_features": False,
        "max_parallel_agents": 1, "model_tier": "local-light",
    },
    "ai": {
        "description": "Full agent throughput for heavy AI work.",
        "background_autonomy": True, "heavy_features": True,
        "max_parallel_agents": None, "model_tier": "auto",
    },
    "multimedia": {
        "description": "Media work — minimize background AI, keep heavy features available.",
        "background_autonomy": False, "heavy_features": True,
        "max_parallel_agents": 2, "model_tier": "local",
    },
    "admin": {
        "description": "Ops / maintenance focus — modest background activity.",
        "background_autonomy": True, "heavy_features": True,
        "max_parallel_agents": 2, "model_tier": "auto",
    },
}


def active_name() -> str:
    """The active profile name from ``JARVIS_SYSTEM_PROFILE`` (unknown → default)."""
    name = os.environ.get("JARVIS_SYSTEM_PROFILE", "").strip().lower()
    return name if name in PROFILES else DEFAULT


def active_posture() -> dict:
    """The active profile's knobs (a copy). Consumers read this to adapt behavior."""
    return dict(PROFILES[active_name()])


def heavy_features_enabled() -> bool:
    """Whether the active profile permits heavy/expensive local work — media
    generation, deep research, and similar GPU/CPU-hungry operations.

    ``balanced``/``ai``/``admin`` → True (unchanged default); ``gaming`` → False
    ("free the GPU for games"). Consumers gate their heavy entry points on this so a
    constrained profile genuinely stops contending for local resources, rather than
    the knob being advisory-only."""
    return bool(active_posture().get("heavy_features", True))


def preferred_model_tier() -> str:
    """The active profile's preferred model weight: ``"local-light"`` / ``"local"`` /
    ``"auto"`` (the default). Advisory — a router/selector reads it to bias toward a
    lighter local model under a constrained profile; ``"auto"`` imposes no preference."""
    tier = active_posture().get("model_tier", "auto")
    return tier if tier in ("local-light", "local", "auto") else "auto"


def list_profiles() -> dict:
    """Everything the HUD/owner needs: the active name, the default, and all profiles."""
    return {"active": active_name(), "default": DEFAULT, "profiles": PROFILES}
