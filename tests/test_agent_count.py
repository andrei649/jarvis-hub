"""AGENT_COUNT must equal the real active roster — it silently read 16 while
the registry already had 17 (found 2026-06-10 by hitting /api/status live).
Now computed from agents.yaml; this guards it against re-drift."""

import sys
from pathlib import Path

import yaml

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents


def _active_from_registry() -> int:
    data = yaml.safe_load(
        (repo_root / "agents" / "_system" / "agents.yaml").read_text(encoding="utf-8")
    ) or {}
    return sum(
        1 for c in (data.get("agents") or {}).values()
        if (c or {}).get("status", "active") == "active"
    )


def test_agent_count_matches_registry():
    assert agents.AGENT_COUNT == _active_from_registry()


def test_agent_count_is_eighteen_today():
    # Concrete tripwire: if the roster changes, update the registry AND the docs
    # (README/STATUS/JARVIS quote this) in the same PR.
    # 18 is also `cardinality_cap` in agents.yaml — the next active agent needs
    # the architecture review that rule asks for, not just a registry entry.
    assert agents.AGENT_COUNT == 18
