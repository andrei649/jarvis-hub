"""O26-P2.4 — settings-backed Product Posture wakes wave-1 intelligence."""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import orchestrator as orch_mod  # noqa: E402
from agents.core import (
    product_posture,  # noqa: E402
    settings_db,  # noqa: E402
)


def test_product_posture_setting_is_seeded_default_off():
    by_key = {(d["category"], d["key"]): d for d in settings_db.DEFAULTS}

    spec = by_key[("product", "posture")]
    assert spec["value"] == "off"
    assert spec["kind"] == "select"
    assert "companion_wave1" in spec["opts"]
    assert "design_partner" in spec["opts"]


def test_companion_wave1_overlays_memory_and_cognition_flags():
    flat = {
        "product.posture": "companion_wave1",
        "memory.recall_enabled": False,
        "cognition.enabled": False,
        "cognition.honesty_enabled": False,
    }

    effective = product_posture.apply_to_runtime_settings(flat)

    assert effective["memory.recall_enabled"] is True
    assert effective["memory.embed_turns"] is True
    assert effective["cognition.enabled"] is True
    assert effective["cognition.honesty_enabled"] is True
    assert effective["cognition.affect_enabled"] is True
    assert effective["cognition.memory_enabled"] is True
    assert effective["cognition.learning_enabled"] is True
    assert effective["cognition.personality_enabled"] is True


def test_default_off_posture_preserves_existing_runtime_values():
    flat = {"product.posture": "off", "memory.recall_enabled": False}

    effective = product_posture.apply_to_runtime_settings(flat)

    assert effective["memory.recall_enabled"] is False
    assert "memory.embed_turns" not in effective


def test_product_posture_snapshot_reports_provenance(monkeypatch):
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    flat = product_posture.apply_to_runtime_settings({
        "product.posture": "companion_wave1",
        "memory.recall_enabled": False,
        "cognition.enabled": False,
    })

    snap = product_posture.snapshot(flat)

    assert snap["name"] == "companion_wave1"
    assert snap["wave"] == 1
    assert snap["hardened"]["enabled"] is False
    assert snap["flags"]["memory.recall_enabled"]["source"] == "product.posture:companion_wave1"
    assert snap["flags"]["kg.ingest"]["value"] == "wired"


def test_orchestrator_load_runtime_settings_applies_posture(monkeypatch):
    class _Memory:
        embed_turns = False

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.lmstudio = None
    orch.llm_router = None
    orch.memory = _Memory()

    monkeypatch.setattr(orch_mod, "_get_settings", lambda: {
        "product": [{"key": "posture", "value": "companion_wave1"}],
        "memory": [{"key": "recall_enabled", "value": False}],
        "cognition": [{"key": "enabled", "value": False}],
    })

    orch.load_runtime_settings()

    assert orch.get_setting("memory.recall_enabled") is True
    assert orch.get_setting("cognition.enabled") is True
    assert orch.memory.embed_turns is True
