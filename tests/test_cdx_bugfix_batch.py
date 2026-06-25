"""CDX bug-batch regression tests (fresh-eyes review 2026-06-24).

- CDX-1: Agent.synthesize() must generate with the *routed* model (local vs
  cloud, per policy), not the configured default — process() already did this,
  synthesize() silently discarded it.
- CDX-4: the app version is single-sourced from agents.__version__ and is no
  longer the stale "0.5.0-beta" that leaked into the OpenAPI metadata.
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.agent import Agent
from agents.core.plugin_gate import PermissionGate


class _RecordingBackend:
    """Captures the model name it was asked to generate with."""
    def __init__(self):
        self.model_used = None

    async def generate(self, model="", prompt="", system="", **kwargs):
        self.model_used = model
        return "fused reply"


class _RoutingRouter:
    """select_backend returns (backend, routed_model, route_name) — the 3-tuple
    shape the real HybridRouter emits when a route picks a specific model."""
    def __init__(self, backend, routed_model, route_name="local"):
        self._backend = backend
        self._routed_model = routed_model
        self._route_name = route_name

    def select_backend(self, agent_id, prompt):
        return self._backend, self._routed_model, self._route_name


def _jarvis_agent(router):
    agent = Agent("jarvis", {"name": "Jarvis", "model": "configured-default-model"}, router,
                  permission_gate=PermissionGate())
    agent.guardrails = None
    return agent


# ── CDX-1 ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_synthesize_uses_routed_model():
    backend = _RecordingBackend()
    agent = _jarvis_agent(_RoutingRouter(backend, routed_model="routed-cloud-model"))
    # Two non-jarvis specialist responses → the real LLM synthesis path runs.
    out = await agent.synthesize({"friday": "intel report", "gecko": "finance note"}, intent=None)
    assert out == "fused reply"
    # The bug: this used "configured-default-model"; the fix honors the route.
    assert backend.model_used == "routed-cloud-model"


@pytest.mark.asyncio
async def test_synthesize_keeps_configured_model_when_route_has_none():
    # When the route returns no specific model, fall back to the configured one.
    backend = _RecordingBackend()
    agent = _jarvis_agent(_RoutingRouter(backend, routed_model="", route_name="local"))
    await agent.synthesize({"friday": "a", "gecko": "b"}, intent=None)
    assert backend.model_used == "configured-default-model"


# ── CDX-4 ─────────────────────────────────────────────────────────────────────

def test_app_version_single_sourced():
    from agents import __version__, web
    assert web.app.version == __version__
    assert web.app.version != "0.5.0-beta"
    # leaks into OpenAPI info.version — assert it tracks the package version there too
    assert web.app.openapi()["info"]["version"] == __version__
