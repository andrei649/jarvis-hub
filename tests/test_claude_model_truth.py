"""The operational Claude default is single-sourced, current, and priced."""

import asyncio
from pathlib import Path

from agents.core import settings_db
from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.cost_estimator import MODELS, estimate_cost
from agents.core.llm.model_config import (
    DEFAULT_CLAUDE_MODEL,
    RETIRED_CLAUDE_DEFAULT,
)
from agents.core.llm.providers import get_profile
from agents.core.plugins.cloud_llm import CloudLLMPlugin

PUBLIC_SOULS = (
    Path("agents/_templates/SOUL.template.md"),
    Path("agents/athena/SOUL.md"),
    Path("agents/argus/SOUL.md"),
    Path("agents/veronica/SOUL.md"),
    Path("agents/vision/SOUL.md"),
)


def test_claude_backend_default_is_canonical():
    backend = ClaudeBackend(api_key="test")
    try:
        assert backend.model == DEFAULT_CLAUDE_MODEL
    finally:
        asyncio.run(backend.aclose())


def test_cloud_plugin_default_is_canonical(monkeypatch):
    plugin = CloudLLMPlugin(anthropic_key="test")
    captured = {}

    async def fake_call(prompt, system, model, max_tokens):
        captured["model"] = model
        return "ok"

    monkeypatch.setattr(plugin, "_call_anthropic", fake_call)
    try:
        assert asyncio.run(plugin.generate("hello")) == "ok"
        assert captured["model"] == DEFAULT_CLAUDE_MODEL
    finally:
        asyncio.run(plugin.close())


def test_anthropic_profile_default_is_canonical():
    assert get_profile("anthropic").fallback_models == (DEFAULT_CLAUDE_MODEL,)


def test_settings_default_is_canonical():
    row = next(
        item
        for item in settings_db.DEFAULTS
        if item["category"] == "llm" and item["key"] == "claude_model"
    )
    assert row["value"] == DEFAULT_CLAUDE_MODEL


def test_public_soul_hints_are_claude_4_6():
    for path in PUBLIC_SOULS:
        text = path.read_text(encoding="utf-8")
        assert f"fallback: {DEFAULT_CLAUDE_MODEL}" in text, path


def test_retired_default_is_not_an_operational_default():
    assert RETIRED_CLAUDE_DEFAULT != DEFAULT_CLAUDE_MODEL
    assert get_profile("anthropic").fallback_models != (RETIRED_CLAUDE_DEFAULT,)
    assert all(
        RETIRED_CLAUDE_DEFAULT not in path.read_text(encoding="utf-8")
        for path in PUBLIC_SOULS
    )


def test_configured_cloud_defaults_have_prices():
    assert DEFAULT_CLAUDE_MODEL in MODELS
    assert estimate_cost(
        DEFAULT_CLAUDE_MODEL,
        1_000_000,
        1_000_000,
    )["total"] == 18.0
    assert estimate_cost("unknown-model", 1_000_000, 1_000_000)["total"] == 0.0
