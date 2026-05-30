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


def test_error_taxonomy_imports():
    from core.errors import JarvisError, ErrorCategory, ErrorSeverity, CODES
    assert JarvisError is not None
    assert len(CODES) >= 20


def test_log_helper_imports():
    from core.log import setup_logging, log_error
    assert setup_logging is not None
    assert log_error is not None


def test_oauth_imports():
    from core.plugins.oauth import save_token, load_token, init_from_env
    from core.plugins.oauth import get_google_auth_url, get_spotify_auth_url
    assert save_token is not None
    assert load_token is not None


def test_websearch_imports():
    from core.plugins.websearch import WebSearchPlugin
    assert WebSearchPlugin is not None


def test_heartbeat_imports():
    from core.heartbeat import HeartbeatScheduler
    assert HeartbeatScheduler is not None


def test_channels_import():
    from core.channels.voice import VoiceChannel
    from core.channels.telegram import TelegramChannel
    from core.channels.discord import DiscordChannel
    from core.channels.email import EmailChannel
    from core.channels.slack import SlackChannel
    from core.channels.base import ChannelAdapter
    assert VoiceChannel is not None
    assert TelegramChannel is not None
    assert DiscordChannel is not None
    assert EmailChannel is not None
    assert SlackChannel is not None
    assert ChannelAdapter is not None


def test_hybrid_router_imports():
    from core.llm.hybrid_router import HybridRouter, POLICY_LOCAL, POLICY_CLOUD, POLICY_AUTO
    from core.llm.gemini import GeminiBackend
    from core.llm.tokenizer import estimate_tokens
    assert HybridRouter is not None
    assert POLICY_LOCAL == "local"
    assert GeminiBackend is not None
    assert estimate_tokens("hello") > 0
