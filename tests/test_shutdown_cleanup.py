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
