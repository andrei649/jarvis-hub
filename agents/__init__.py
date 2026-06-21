"""Jarvis Hub — agents package."""

__version__ = "0.10.0"


def _count_active_agents() -> int:
    """Active-agent count from the canonical registry (agents/_system/agents.yaml).

    Computed, not hardcoded — a static constant silently drifts every time an
    agent is added (it read 16 while the roster was already 17). Falls back to
    the last known value if the registry can't be read at import time."""
    try:
        from pathlib import Path

        import yaml

        data = yaml.safe_load(
            (Path(__file__).parent / "_system" / "agents.yaml").read_text(encoding="utf-8")
        ) or {}
        agents = data.get("agents") or {}
        n = sum(1 for c in agents.values() if (c or {}).get("status", "active") == "active")
        return n or 17
    except Exception:
        return 17


AGENT_COUNT = _count_active_agents()
