"""Guards that /admin settings are actually wired into the subsystems they name
(part of the "no dead knobs" cleanup). Each test sets a non-default value and
asserts the constructed object reflects it — so a future refactor that silently
stops reading a setting fails CI."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _gv_factory(overrides):
    """Fake settings_db.get_value backed by a {"category.key": value} dict."""
    def fake(category, key, default=None):
        return overrides.get(f"{category}.{key}", default)
    return fake


# ── memory ──────────────────────────────────────────────────────────────────
def test_memory_manager_honors_settings(monkeypatch):
    import core.memory.manager as mm
    captured = {}

    class FakeCM:
        def __init__(self, max_turns=100, persist=True):
            captured["max_turns"] = max_turns
            captured["persist"] = persist

    monkeypatch.setattr(mm, "ConversationMemory", FakeCM)
    monkeypatch.setattr("core.settings_db.get_value",
                        _gv_factory({"memory.max_turns": 42, "memory.persist": False}))
    mm.MemoryManager()
    assert captured == {"max_turns": 42, "persist": False}


# ── sandbox (security.sandbox_timeout / sandbox_memory) ───────────────────────
def test_orchestrator_sandbox_honors_settings(monkeypatch):
    monkeypatch.setattr("core.settings_db.get_value",
                        _gv_factory({"security.sandbox_timeout": 99, "security.sandbox_memory": 777}))
    from core.config import JarvisConfig
    from core.orchestrator import Orchestrator
    o = Orchestrator(JarvisConfig())
    assert o.sandbox.timeout == 99
    assert o.sandbox.max_memory_mb == 777
    assert o.sandbox.allow_subprocess is False  # HF-6: host-exec stays off


# ── autonomy (cap_per_action / daily_ceiling / interrupt_budget) ──────────────
def test_orchestrator_autonomy_caps_honor_settings(monkeypatch):
    monkeypatch.setattr("core.settings_db.get_value",
                        _gv_factory({"autonomy.cap_per_action": 12.5,
                                     "autonomy.daily_ceiling": 99.0,
                                     "autonomy.interrupt_budget": 7}))
    from core.config import JarvisConfig
    from core.orchestrator import Orchestrator
    o = Orchestrator(JarvisConfig())
    assert o.autonomy.policy.cap_per_action == 12.5
    assert o.autonomy.policy.daily_ceiling == 99.0
    assert o.autonomy.budget.per_day == 7


# ── system.log_level ──────────────────────────────────────────────────────────
def test_setup_logging_honors_log_level(monkeypatch):
    import logging
    import core.log as log
    monkeypatch.setattr("core.settings_db.get_value",
                        lambda cat, key, default=None: "WARNING" if key == "log_level" else default)
    try:
        log.setup_logging()
        assert logging.getLogger().level == logging.WARNING
    finally:
        log.setup_logging(logging.INFO)  # restore so other tests aren't affected


# ── channels.rate_limit / web_enabled (wired in the web lifespan) ─────────────
def test_lifespan_wires_rate_limit_and_web_enabled(monkeypatch):
    from fastapi.testclient import TestClient
    from agents import web
    monkeypatch.setattr("core.settings_db.get_value",
                        lambda cat, key, default=None:
                        {"channels.rate_limit": 33, "channels.web_enabled": False}.get(f"{cat}.{key}", default))
    with TestClient(web.app):
        assert web.gateway._max_rate == 33
        assert "web" not in web.gateway._channels      # disabled → not registered
        assert "voice" in web.gateway._channels        # other channels unaffected


# ── LM Studio control kill-switches (llm.control_enabled / chat_control) ──────
def test_lmstudio_control_toggles_surfaced_and_wired(monkeypatch):
    # surfaced: both toggles exist in the /admin defaults
    from core import settings_db
    keys = {(d["category"], d["key"]) for d in settings_db.DEFAULTS}
    assert ("llm", "control_enabled") in keys and ("llm", "chat_control") in keys

    # wired: the orchestrator's gating honors the live settings
    from core.config import JarvisConfig
    from core.orchestrator import Orchestrator
    o = Orchestrator(JarvisConfig())

    monkeypatch.setattr(o, "get_setting",
                        lambda k, d=None: {"llm.control_enabled": False, "llm.chat_control": True}.get(k, d))
    assert o._control_master_enabled() is False
    assert o._chat_control_enabled() is False   # chat control is gated by master control

    monkeypatch.setattr(o, "get_setting",
                        lambda k, d=None: {"llm.control_enabled": True, "llm.chat_control": False}.get(k, d))
    assert o._control_master_enabled() is True
    assert o._chat_control_enabled() is False   # its own toggle is off


# ── guardrails (security.guardrails_mode / scan_input / scan_output) ──────────
@pytest.mark.asyncio
async def test_orchestrator_guardrails_honors_settings(monkeypatch):
    from core.llm.hybrid_router import HybridRouter
    from core.security.types import RedactionMode

    # Give the router a backend so GuardrailsEngine actually constructs (the engine
    # only stores the backend at init, so a plain sentinel is enough).
    monkeypatch.setattr(HybridRouter, "backend", property(lambda self: object()))
    monkeypatch.setattr("core.settings_db.get_value",
                        _gv_factory({"security.guardrails_mode": "BLOCK",
                                     "security.scan_input": False,
                                     "security.scan_output": True}))
    from core.config import JarvisConfig
    from core.orchestrator import Orchestrator
    o = Orchestrator(JarvisConfig())
    await o.load_agents()  # GuardrailsEngine is built here, not in __init__
    assert o.security is not None
    assert o.security._mode == RedactionMode.BLOCK
    assert o.security._scan_input is False
    assert o.security._scan_output is True
