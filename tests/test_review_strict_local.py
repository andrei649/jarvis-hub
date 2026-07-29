"""H20 learning loop — strict-local review + purge invalidates the core snapshot.

Regression tests for the two adversarial-review findings:
  1. the review LLM path must fail CLOSED to local (never HybridRouter.backend,
     which prefers cloud Claude/Gemini when keys are configured);
  2. the explicit user-forget path must drop the frozen core-block prompt cache.
All offline.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.data_purge import clear_live_memory
from agents.core.llm.hybrid_router import HybridRouter
from agents.core.llm.router import LLMRouter


def test_local_backend_raises_when_no_local():
    r = LLMRouter()
    with pytest.raises(RuntimeError):
        _ = r.local_backend


def test_local_backend_never_falls_back_to_cloud():
    """The exact leak shape: Anthropic key configured, local backend down —
    HybridRouter.backend happily returns the cloud backend, local_backend
    must fail closed instead."""
    r = HybridRouter(gemini_api_key="", anthropic_api_key="")
    cloud = object()
    r._claude_backend = cloud
    r._cloud_available = True
    r._backend = None
    r._local_available = False
    assert r.backend is cloud                  # documented cloud preference
    with pytest.raises(RuntimeError):
        _ = r.local_backend                    # strict-local path fails closed


def test_local_backend_returns_local_when_up():
    r = HybridRouter(gemini_api_key="", anthropic_api_key="")
    local = object()
    r._backend = local
    r._local_available = True
    r._claude_backend = object()               # cloud also configured
    assert r.local_backend is local            # local wins on the strict path


async def test_purge_drops_frozen_core_block_cache():
    class _Orch:
        _core_block_cache = (("session-1", "2026-07-06"), "[core memory]\n- fact")

    orch = _Orch()
    cleared, _failed = await clear_live_memory(orch)
    assert "core_block_cache" in cleared
    assert orch._core_block_cache is None


async def test_purge_without_cache_is_noop_for_cache_entry():
    class _Orch:
        pass

    cleared, _failed = await clear_live_memory(_Orch())
    assert "core_block_cache" not in cleared
