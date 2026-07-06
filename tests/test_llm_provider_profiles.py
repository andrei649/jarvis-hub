"""Tests for the Hermes-style declarative LLM provider profile registry."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def test_builtin_provider_profiles_cover_existing_backends():
    from core.llm.providers import BUILTIN_PROVIDER_IDS, get_profile, list_profiles

    ids = {p.id for p in list_profiles()}
    assert {"lm-studio", "ollama", "gemini", "anthropic", "openrouter"} <= ids
    assert set(BUILTIN_PROVIDER_IDS) <= ids
    assert get_profile("openrouter").backend_kind == "openai-compatible"
    assert "chat" in get_profile("gemini").capabilities


def test_provider_status_reports_configuration_without_secret_values(monkeypatch):
    from core.llm.providers import get_profile

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret")
    status = get_profile("openrouter").status()

    assert status["configured"] is True
    assert status["auth"] == {"type": "bearer", "env": "OPENROUTER_API_KEY", "configured": True}
    assert "sk-or-secret" not in repr(status)


def test_provider_status_keeps_optional_local_profiles_enabled_by_default(monkeypatch):
    from core.llm.providers import get_profile

    monkeypatch.delenv("JARVIS_LM_STUDIO_URL", raising=False)
    status = get_profile("lm-studio").status()

    assert status["configured"] is True
    assert status["base_url"] == "http://localhost:1234"
    assert status["auth"] == {"type": "none", "env": None, "configured": True}


def test_register_profile_rejects_duplicate_ids():
    from core.llm.providers import ProviderProfile, ProviderRegistry

    registry = ProviderRegistry()
    registry.register(ProviderProfile(id="custom", display_name="Custom", backend_kind="test"))

    with pytest.raises(ValueError, match="duplicate provider profile"):
        registry.register(ProviderProfile(id="custom", display_name="Other", backend_kind="test"))


def test_hybrid_router_exposes_provider_catalog_without_network_calls(monkeypatch):
    from core.llm.hybrid_router import HybridRouter

    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    router = HybridRouter()

    catalog = router.provider_catalog()
    anthropic = next(p for p in catalog if p["id"] == "anthropic")

    assert anthropic["configured"] is True
    assert anthropic["auth"]["env"] == "ANTHROPIC_API_KEY"
    assert "anthropic-secret" not in repr(catalog)
