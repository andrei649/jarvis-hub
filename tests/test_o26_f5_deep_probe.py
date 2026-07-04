"""
test_o26_f5_deep_probe.py — ORIZONT 26 P0.5 (finding F5).

Before the fix, JARVIS_AUTO_DEEP (default ON) rerouted ANY auto-agent prompt
containing a heavy keyword ("analyze", "strategy", ...) to the hardcoded
deep-slot model — which a default one-model box doesn't have loaded, turning
ordinary words into invisible latency/failures. The deep slot now requires
EVIDENCE: the model appears in the live backend's served listing, or the
owner explicitly pinned JARVIS_DEEP_MODEL.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm import hybrid_router as hr  # noqa: E402

HEAVY_PROMPT = "Please analyze the tradeoffs and propose a strategy for my move."


def _router(served: set, monkeypatch) -> hr.HybridRouter:
    monkeypatch.delenv("JARVIS_DEEP_MODEL", raising=False)
    monkeypatch.setattr(hr, "AUTO_DEEP_ENABLED", True)
    r = hr.HybridRouter.__new__(hr.HybridRouter)
    r._backend = object()
    r._backend_name = "lm-studio"
    r._local_available = True
    r._local_model = "gemma-3-12b"
    r._local_max = 8000
    r._flash_max = 128000
    r._cloud_available = False
    r._claude_available = False
    r._cloud_fallback_mode = "on-demand"
    r._served_models = set(served)
    r._ollama_available = False
    return r


def test_one_model_box_never_routes_to_a_missing_deep_model(monkeypatch):
    r = _router({"gemma-3-12b"}, monkeypatch)
    backend, model, route = r.select_backend("stark", HEAVY_PROMPT)
    assert route == "local", f"F5 regression: heavy keyword escalated to {route}"
    assert model == "gemma-3-12b"


def test_deep_slot_fires_when_the_model_is_actually_served(monkeypatch):
    r = _router({"gemma-3-12b", hr.DEFAULT_DEEP_MODEL}, monkeypatch)
    _, model, route = r.select_backend("stark", HEAVY_PROMPT)
    assert route == "local-deep"
    assert model == hr.DEFAULT_DEEP_MODEL


def test_owner_pinned_deep_model_is_honored_without_a_listing(monkeypatch):
    r = _router(set(), monkeypatch)
    monkeypatch.setenv("JARVIS_DEEP_MODEL", "my-deep-model")
    assert r._deep_model_available() is True


def test_partial_id_match_counts_as_evidence(monkeypatch):
    """LM Studio ids often carry org/quant prefixes around the family name."""
    r = _router({f"lmstudio-community/{hr.DEFAULT_DEEP_MODEL}-GGUF"}, monkeypatch)
    assert r._deep_model_available() is True


def test_deep_think_agents_fall_through_without_evidence(monkeypatch):
    """A deep-think agent on a one-model box uses normal routing, not a ghost."""
    r = _router({"gemma-3-12b"}, monkeypatch)
    agent = next(iter(hr.DEEP_THINK_AGENTS))
    _, model, route = r.select_backend(agent, "hello there")
    assert route != "local-deep"
    assert model != hr.DEFAULT_DEEP_MODEL


def test_deep_think_agents_escalate_with_evidence(monkeypatch):
    r = _router({hr.DEFAULT_DEEP_MODEL}, monkeypatch)
    agent = next(iter(hr.DEEP_THINK_AGENTS))
    _, model, route = r.select_backend(agent, "hello there")
    assert route == "local-deep" and model == hr.DEFAULT_DEEP_MODEL
