"""Tests for the Argus geospatial-OSINT agent (H19.3.6).

Verifies Argus is registered (agents.yaml), permission-gated to the WorldView
plugin, that geospatial queries route to him, and that his SOUL loads.
"""

from __future__ import annotations

from pathlib import Path

from agents.core.config import JarvisConfig
from agents.core.plugin_gate import PermissionGate
from agents.core.router import IntentRouter


def test_argus_registered_active_with_worldview_plugin():
    cfg = JarvisConfig()
    assert "argus" in cfg.agents, "argus missing from agents.yaml"
    argus = cfg.agents["argus"]
    assert argus.status == "active"
    assert "worldview" in argus.plugins  # Argus's primary tool is WorldView


def test_worldview_plugin_serves_argus():
    gate = PermissionGate()
    # Argus may call the gated WorldView plugin; an unrelated agent may not.
    assert gate.check_call("worldview", "argus") is True
    assert gate.check_call("worldview", "frigga") is False


async def test_geospatial_queries_route_to_argus():
    router = IntentRouter(JarvisConfig())
    for query in (
        "when is the next satellite recon pass over Hormuz",
        "any dark vessel in the strait right now",
        "show me the AOI overflight schedule",
        "is there gps jamming near the worldview AOI",
    ):
        intent = await router.classify(query, {})
        assert "argus" in (intent.target_agents or []), f"{query!r} -> {intent.target_agents}"


async def test_general_research_still_routes_to_vision_not_argus():
    """Argus must not steal plain web-research intent from Vision (distinct keywords)."""
    router = IntentRouter(JarvisConfig())
    intent = await router.classify("research and investigate this company online", {})
    assert "vision" in (intent.target_agents or [])
    assert "argus" not in (intent.target_agents or [])


def test_argus_soul_loads():
    soul = Path("agents/argus/SOUL.md")
    assert soul.exists(), "agents/argus/SOUL.md missing"
    text = soul.read_text(encoding="utf-8")
    assert "id: argus" in text
    assert "Geospatial OSINT" in text
