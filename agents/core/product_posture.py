"""Product posture composition for ORIZONT 26 P2.4.

The code defaults stay conservative. A named product posture, selected through
settings DB, can deliberately wake the owner-approved wave-1 intelligence
surface while the existing ``JARVIS_HARDENED`` env posture remains the security
hardening source of truth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

OFF = "off"
COMPANION_WAVE1 = "companion_wave1"
DESIGN_PARTNER = "design_partner"

WAVE1_FLAGS: dict[str, bool] = {
    "memory.recall_enabled": True,
    "memory.embed_turns": True,
    "cognition.enabled": True,
    "cognition.honesty_enabled": True,
    "cognition.affect_enabled": True,
    "cognition.memory_enabled": True,
    "cognition.learning_enabled": True,
    "cognition.personality_enabled": True,
}

POSTURES: dict[str, dict[str, Any]] = {
    OFF: {
        "name": OFF,
        "label": "Off",
        "wave": 0,
        "description": "Default conservative posture; no product-level intelligence flags are forced.",
        "applies": {},
    },
    COMPANION_WAVE1: {
        "name": COMPANION_WAVE1,
        "label": "Companion Wave 1",
        "wave": 1,
        "description": "Owner-consented memory/persona posture: recall, turn embeddings, living memory, honesty, affect, learning, and personality.",
        "applies": WAVE1_FLAGS,
    },
    DESIGN_PARTNER: {
        "name": DESIGN_PARTNER,
        "label": "Design Partner",
        "wave": 1,
        "description": "Wave-1 companion posture composed with the existing JARVIS_HARDENED env posture when enabled.",
        "applies": WAVE1_FLAGS,
    },
}

_SNAPSHOT_FLAGS = tuple(WAVE1_FLAGS) + ("kg.ingest",)


def known_names() -> list[str]:
    return list(POSTURES)


def normalize(name: object) -> str:
    value = str(name or OFF).strip()
    return value if value in POSTURES else OFF


def selected_name(flat: dict[str, Any] | None) -> str:
    return normalize((flat or {}).get("product.posture", OFF))


def apply_to_runtime_settings(flat: dict[str, Any]) -> dict[str, Any]:
    """Return a runtime-settings copy with the selected posture overlaid."""
    effective = dict(flat)
    name = selected_name(effective)
    effective["product.posture"] = name
    for key, value in POSTURES[name].get("applies", {}).items():
        effective[key] = value
    return effective


def _flag_snapshot(flat: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    applied = POSTURES[name].get("applies", {})
    flags: dict[str, dict[str, Any]] = {}
    for key in _SNAPSHOT_FLAGS:
        if key == "kg.ingest":
            flags[key] = {
                "value": "wired",
                "source": "shared record seam",
            }
            continue
        source = f"product.posture:{name}" if key in applied else ("settings" if key in flat else "default")
        flags[key] = {"value": flat.get(key, False), "source": source}
    return flags


def snapshot(flat: dict[str, Any] | None = None) -> dict[str, Any]:
    """Machine-readable product posture snapshot for trust/onboarding surfaces."""
    flat = dict(flat or {})
    raw_name = str(flat.get("product.posture", OFF) or OFF)
    effective = apply_to_runtime_settings(flat)
    name = effective["product.posture"]
    from agents.core.security import hardened

    return {
        "name": name,
        "raw_name": raw_name,
        "valid": raw_name == name,
        "label": POSTURES[name]["label"],
        "wave": POSTURES[name]["wave"],
        "description": POSTURES[name]["description"],
        "available": [deepcopy(POSTURES[n]) for n in known_names()],
        "flags": _flag_snapshot(effective, name),
        "hardened": hardened.posture(),
    }
