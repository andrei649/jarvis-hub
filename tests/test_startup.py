"""Smoke tests for Jarvis startup: config loading, orchestrator init, dotenv."""

import os
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig


def test_config_loads():
    cfg = JarvisConfig()
    assert cfg.agents, "No agents loaded from YAML"
    assert "jarvis" in cfg.agents, "jarvis agent missing"
    assert cfg.general, "general section missing"


def test_all_agents_have_channel():
    cfg = JarvisConfig()
    for aid, agent in cfg.agents.items():
        assert agent.channel, f"Agent {aid} has no channel"


def test_all_agents_have_model():
    cfg = JarvisConfig()
    for aid, agent in cfg.agents.items():
        assert agent.model, f"Agent {aid} has no model"


def test_active_agents_filter():
    cfg = JarvisConfig()
    active = cfg.get_active_agents()
    assert len(active) > 0
    for a in active:
        assert a.status == "active"


def test_dotenv_importable():
    try:
        from dotenv import load_dotenv
        assert load_dotenv is not None
    except ImportError:
        pytest.fail("python-dotenv not installed")


def test_orchestrator_imports():
    from agents.core.orchestrator import Orchestrator
    assert Orchestrator is not None


def test_guardrails_imports():
    from agents.core.security.guardrails import GuardrailsEngine
    assert GuardrailsEngine is not None


def test_permission_gate_imports():
    from agents.core.plugin_gate import PermissionGate, BUILTIN_PLUGINS
    gate = PermissionGate()
    assert "weather" in gate.plugins
    assert "news" in gate.plugins
    assert "cloud-llm" in gate.plugins
    assert "telegram" in gate.plugins
