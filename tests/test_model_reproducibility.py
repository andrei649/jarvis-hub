"""H23.2 — per-agent approved-model allowlist (model pinning), enforced in the router.

Opt-in: an agent with no allowlist is unrestricted (today's behavior). When pinned, the
router refuses an off-list model — strict by default, `JARVIS_STRICT_MODELS=0` downgrades
to a warning (mirrors the egress-strictness pattern).
"""

import pytest

from agents.core.config import AgentConfig
from agents.core.llm import hybrid_router as hr
from agents.core.llm.hybrid_router import HybridRouter, ModelNotApprovedError


def _router(monkeypatch, approved_map):
    monkeypatch.setattr(hr, "_registry_approved_models", lambda: approved_map)
    return HybridRouter()


# ── config parsing ────────────────────────────────────────────────────────────
def test_agent_config_parses_approved_models():
    assert AgentConfig({"id": "x", "approved_models": ["m1", "m2"]}).approved_models == ["m1", "m2"]
    assert AgentConfig({"id": "y"}).approved_models == []            # default empty
    assert AgentConfig({"id": "z", "approved_models": None}).approved_models == []


# ── query helpers ───────────────────────────────────────────────────────────────
def test_query_helpers(monkeypatch):
    r = _router(monkeypatch, {"stark": ["a", "b"]})
    assert r.approved_models("stark") == ["a", "b"]
    assert r.is_model_approved("stark", "a") is True
    assert r.is_model_approved("stark", "z") is False
    assert r.is_model_approved("unlisted_agent", "anything") is True   # no list → unrestricted


# ── enforcement at the routing front door ──────────────────────────────────────
def test_no_allowlist_is_unrestricted(monkeypatch):
    r = _router(monkeypatch, {})
    monkeypatch.setattr(r, "_select_backend_inner", lambda a, p: ("BK", "any-model", "local"))
    assert r.select_backend("stark", "hi") == ("BK", "any-model", "local")


def test_approved_model_passes(monkeypatch):
    r = _router(monkeypatch, {"stark": ["gemma", "claude-opus"]})
    monkeypatch.setattr(r, "_select_backend_inner", lambda a, p: ("BK", "gemma", "local"))
    assert r.select_backend("stark", "hi")[1] == "gemma"


def test_unapproved_model_blocked_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_STRICT_MODELS", raising=False)  # strict is the default
    r = _router(monkeypatch, {"stark": ["gemma"]})
    monkeypatch.setattr(r, "_select_backend_inner", lambda a, p: ("BK", "rogue-model", "cloud"))
    with pytest.raises(ModelNotApprovedError):
        r.select_backend("stark", "hi")


def test_unapproved_warns_when_opted_out(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_MODELS", "0")  # escape hatch → warn, no raise
    r = _router(monkeypatch, {"stark": ["gemma"]})
    monkeypatch.setattr(r, "_select_backend_inner", lambda a, p: ("BK", "rogue", "cloud"))
    assert r.select_backend("stark", "hi")[1] == "rogue"
