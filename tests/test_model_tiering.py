"""Tests for H7.5 — Complexity-based fast/heavy model tiering.

All tests are offline (no network, no LM Studio, no Ollama).
The router is constructed directly and its private attributes are patched
to simulate a detected local backend.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.core.llm.hybrid_router as hybrid_router
from agents.core.llm.hybrid_router import (
    HybridRouter,
    DEFAULT_DEEP_MODEL,
    HEAVY_TOKEN_THRESHOLD,
    is_heavy_request,
)
from core.llm.base import LLMBackend


# ---------------------------------------------------------------------------
# Minimal fake backend so we don't need LM Studio running
# ---------------------------------------------------------------------------

class _FakeBackend(LLMBackend):
    async def generate(self, *a, **kw):
        return "fake"


_SENTINEL = _FakeBackend()


def _make_router() -> HybridRouter:
    """Return a HybridRouter pre-configured as if local backend was detected."""
    r = HybridRouter()
    r._local_available = True
    r._backend = _SENTINEL
    r._local_model = "fast-model"
    return r


# ---------------------------------------------------------------------------
# 1. is_heavy_request
# ---------------------------------------------------------------------------

def test_is_heavy_request_short_simple_is_false():
    """A short, simple prompt should NOT be classified as heavy."""
    assert is_heavy_request("What is the weather today?") is False


def test_is_heavy_request_heavy_keyword_ro_en():
    """A prompt containing a known heavy keyword must return True."""
    assert is_heavy_request("fă o analiză strategică a pieței") is True


def test_is_heavy_request_heavy_keyword_en():
    """English heavy keyword should also trigger True."""
    assert is_heavy_request("Perform a deep analysis of the system") is True


def test_is_heavy_request_keyword_case_insensitive():
    """Keyword matching must be case-insensitive."""
    assert is_heavy_request("REASONING about the problem") is True
    assert is_heavy_request("Planning the architecture") is True


def test_is_heavy_request_very_long_prompt():
    """A prompt that exceeds HEAVY_TOKEN_THRESHOLD tokens must return True."""
    # Each 'word ' is ~1 token; generate well above the threshold.
    long_prompt = "word " * (HEAVY_TOKEN_THRESHOLD + 500)
    assert is_heavy_request(long_prompt) is True


def test_is_heavy_request_just_under_threshold_no_keywords():
    """A prompt just under the token threshold with no keywords stays False."""
    # 10 tokens is well below HEAVY_TOKEN_THRESHOLD (2000)
    assert is_heavy_request("hello world this is ten words here ok yes") is False


def test_is_heavy_request_custom_threshold():
    """Custom token_threshold parameter should be respected."""
    # A 5-token prompt will exceed a threshold of 3
    short = "one two three four five"
    assert is_heavy_request(short, token_threshold=3) is True
    # Same prompt stays False with a high threshold and no keywords
    assert is_heavy_request(short, token_threshold=10_000) is False


# ---------------------------------------------------------------------------
# 2. select_backend — normal auto agent with a LIGHT prompt
# ---------------------------------------------------------------------------

def test_select_backend_light_prompt_stays_on_fast():
    """A short, simple prompt for an auto agent routes to the fast local slot."""
    r = _make_router()
    _backend, model, route = r.select_backend("jarvis", "What is the weather today?")
    assert route == "local"
    assert model == "fast-model"
    assert _backend is _SENTINEL


# ---------------------------------------------------------------------------
# 3. select_backend — normal auto agent with a HEAVY prompt
# ---------------------------------------------------------------------------

def test_select_backend_heavy_keyword_escalates_to_deep():
    """A heavy-keyword prompt for an auto agent escalates to local-deep."""
    r = _make_router()
    _backend, model, route = r.select_backend("jarvis", "fă o analiză strategică")
    assert route == "local-deep"
    assert model == DEFAULT_DEEP_MODEL
    assert _backend is _SENTINEL


def test_select_backend_heavy_long_prompt_escalates_to_deep():
    """A very long prompt (> HEAVY_TOKEN_THRESHOLD) escalates to local-deep."""
    r = _make_router()
    long_prompt = "word " * (HEAVY_TOKEN_THRESHOLD + 500)
    _backend, model, route = r.select_backend("friday", long_prompt)
    assert route == "local-deep"
    assert model == DEFAULT_DEEP_MODEL


# ---------------------------------------------------------------------------
# 4. JARVIS_AUTO_DEEP=0 disables escalation
# ---------------------------------------------------------------------------

def test_select_backend_auto_deep_disabled_stays_fast(monkeypatch):
    """When AUTO_DEEP_ENABLED is False, heavy prompts for auto agents stay on fast."""
    # The flag is read at import time, so we patch the module attribute directly.
    monkeypatch.setattr(hybrid_router, "AUTO_DEEP_ENABLED", False)
    r = _make_router()
    _backend, model, route = r.select_backend("jarvis", "fă o analiză strategică")
    assert route == "local"
    assert model == "fast-model"


def test_select_backend_auto_deep_disabled_long_prompt_stays_fast(monkeypatch):
    """With AUTO_DEEP_ENABLED=False, even an over-threshold prompt stays on fast (within LOCAL_MAX_TOKENS)."""
    monkeypatch.setattr(hybrid_router, "AUTO_DEEP_ENABLED", False)
    r = _make_router()
    # Heavy by token count but still within LOCAL_MAX_TOKENS (8000)
    medium_heavy = "word " * (HEAVY_TOKEN_THRESHOLD + 100)
    _backend, model, route = r.select_backend("jarvis", medium_heavy)
    assert route == "local"
    assert model == "fast-model"


# ---------------------------------------------------------------------------
# 5. Local-only agents are unaffected by the new complexity escalation
# ---------------------------------------------------------------------------

def test_local_only_agent_heavy_prompt_not_escalated():
    """A local-only agent (ultron) with a heavy prompt is NOT routed to local-deep
    by the new escalation; it stays on the normal local slot (POLICY_LOCAL branch)."""
    r = _make_router()
    _backend, model, route = r.select_backend("ultron", "fă o analiză strategică")
    # ultron has POLICY_LOCAL which returns "local" directly — escalation never fires
    assert route == "local"
    assert model == "fast-model"


def test_deep_think_agent_unaffected_uses_deep_slot_as_before():
    """A deep-think agent (hephaestus) uses local-deep regardless of prompt complexity
    — driven by DEEP_THINK_AGENTS membership, not by the new escalation."""
    r = _make_router()
    # Simple, non-heavy prompt: still goes to local-deep (existing behavior)
    _backend, model, route = r.select_backend("hephaestus", "hello world")
    assert route == "local-deep"
    assert model == DEFAULT_DEEP_MODEL


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

def test_select_backend_different_auto_agents_same_routing():
    """Complexity escalation applies to any auto-policy agent, not just 'jarvis'."""
    r = _make_router()
    for agent in ("friday", "thor", "loki", "unknown-agent"):
        _, model, route = r.select_backend(agent, "perform a synthesis of findings")
        assert route == "local-deep", f"Expected local-deep for agent={agent!r}"
        assert model == DEFAULT_DEEP_MODEL


def test_is_heavy_request_strategy_keyword():
    """'strategy' keyword (EN) triggers heavy classification."""
    assert is_heavy_request("What is our marketing strategy for Q3?") is True


def test_is_heavy_request_planning_keyword():
    """'planning' keyword (EN) triggers heavy classification."""
    assert is_heavy_request("I need help planning the system architecture") is True


def test_is_heavy_request_synthes_keyword():
    """'synthes' substring matches 'synthesis' and 'synthesize'."""
    assert is_heavy_request("Please synthesize the research results") is True


def test_is_heavy_request_demonstr_ro_keyword():
    """Romanian 'demonstr' substring triggers heavy classification."""
    assert is_heavy_request("demonstrează că soluția funcționează") is True
