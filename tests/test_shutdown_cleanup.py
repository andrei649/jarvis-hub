"""Tests for shutdown cleanup (FIX 3 / BUG-7 / NEW-1): Orchestrator.aclose(),
HybridRouter.aclose() and ClaudeBackend.aclose() release every pooled resource
(LLM httpx clients, MCP sessions, autonomy sqlite queue) — defensively, never
raising during shutdown.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig
from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.hybrid_router import HybridRouter
from agents.core.orchestrator import Orchestrator


class _FakeBackend:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_claude_backend_has_aclose():
    be = ClaudeBackend(api_key="x")
    assert hasattr(be, "aclose")
    await be.aclose()  # closes the real httpx client; must not raise
    assert be.client.is_closed


@pytest.mark.asyncio
async def test_hybrid_router_aclose_closes_all_backends():
    router = HybridRouter()
    local = _FakeBackend()
    gem = _FakeBackend()
    claude = _FakeBackend()
    ollama = _FakeBackend()
    router._backend = local
    router._gemini_backend = gem
    router._claude_backend = claude
    router._ollama_backend = ollama

    await router.aclose()

    assert local.closed and gem.closed and claude.closed and ollama.closed
    # References cleared so a closed router can't hand out a dead backend.
    assert router._gemini_backend is None
    assert router._claude_backend is None
    assert router._ollama_backend is None


@pytest.mark.asyncio
async def test_hybrid_router_aclose_no_backends_is_noop():
    # Nothing attached → must not raise.
    await HybridRouter().aclose()


@pytest.mark.asyncio
async def test_orchestrator_aclose_closes_mcp_and_queue():
    orch = Orchestrator(JarvisConfig())

    closed = {"mcp": False, "queue": False, "router": False}

    class _MCP:
        async def close_all(self):
            closed["mcp"] = True

    class _Queue:
        def close(self):
            closed["queue"] = True

    class _Router:
        async def aclose(self):
            closed["router"] = True

    orch.mcp = _MCP()
    orch.autonomy_queue = _Queue()
    orch.llm_router = _Router()

    await orch.aclose()

    assert closed == {"mcp": True, "queue": True, "router": True}


@pytest.mark.asyncio
async def test_orchestrator_aclose_is_defensive():
    # A raising collaborator must not abort the rest of shutdown.
    orch = Orchestrator(JarvisConfig())
    queue_closed = {"v": False}

    class _BadRouter:
        async def aclose(self):
            raise RuntimeError("router boom")

    class _BadMCP:
        async def close_all(self):
            raise RuntimeError("mcp boom")

    class _Queue:
        def close(self):
            queue_closed["v"] = True

    orch.llm_router = _BadRouter()
    orch.mcp = _BadMCP()
    orch.autonomy_queue = _Queue()

    # Should not raise despite both router and mcp failing, and still reach the
    # queue close.
    await orch.aclose()
    assert queue_closed["v"] is True


# ── AUD-18: context cache + plugin HTTP clients + channel transports ────────────

@pytest.mark.asyncio
async def test_orchestrator_aclose_closes_context_cache_and_channels():
    orch = Orchestrator(JarvisConfig())
    closed = {"cache": False, "chan": False}

    class _Cache:
        async def close(self):
            closed["cache"] = True

    class _Channel:        # mirrors TelegramChannel.aclose()
        async def aclose(self):
            closed["chan"] = True

    class _NoCloseChannel:  # a channel without aclose must be skipped, not crash
        pass

    orch.context_cache = _Cache()
    orch.channels = {"telegram": _Channel(), "web": _NoCloseChannel()}

    await orch.aclose()

    assert closed == {"cache": True, "chan": True}


@pytest.mark.asyncio
async def test_orchestrator_aclose_drains_plugin_http_clients():
    from agents.core import http_client

    # Register a couple of pooled per-plugin clients, then prove shutdown drains them.
    a = http_client.PluginHTTPClient.for_plugin("plug_a")
    b = http_client.PluginHTTPClient.for_plugin("plug_b")
    a._get_client(); b._get_client()          # force the lazy httpx clients to exist
    assert "plug_a" in http_client._clients and "plug_b" in http_client._clients

    orch = Orchestrator(JarvisConfig())
    await orch.aclose()

    # close_all() closed each client and emptied the registry.
    assert a._client.is_closed and b._client.is_closed
    assert "plug_a" not in http_client._clients and "plug_b" not in http_client._clients


@pytest.mark.asyncio
async def test_close_all_is_defensive_and_snapshot_safe():
    from agents.core import http_client

    c = http_client.PluginHTTPClient.for_plugin("plug_boom")
    c._get_client()

    # A client whose close() raises must not abort draining the rest.
    async def _boom():
        http_client._clients.pop("plug_boom", None)   # still mutates the registry
        raise RuntimeError("close boom")
    c.close = _boom

    await http_client.close_all()                     # must not raise
    assert "plug_boom" not in http_client._clients
