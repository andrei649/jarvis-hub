"""Tests for live model resolution + admin-configurable Claude model.

Covers:
  * Base LLMRouter auto-detects the loaded model from the live backend
    (_fetch_loaded_model parsing for LM Studio + Ollama shapes).
  * HybridRouter.detect resolves _local_model from the detected (real loaded)
    model first, falling back to the /admin `llm.default_model` setting.
  * Claude model is taken from /admin config (llm.claude_model) in
    get_model / select_backend.
  * settings_db.get_value degrades to default safely.
  * agents.yaml no longer duplicates `howard` in the bench section.

All offline (super().detect and _check monkeypatched; no network).
"""
import sys
from pathlib import Path

import pytest
import yaml

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.router import LLMRouter
from agents.core.llm.hybrid_router import (
    HybridRouter, DEFAULT_CLAUDE_MODEL, DEFAULT_LOCAL_MODEL,
)
from agents.core import settings_db


# ── _fetch_loaded_model parsing ───────────────────────────────────────────────

class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Minimal async context manager standing in for httpx.AsyncClient."""
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        return self._resp


@pytest.mark.asyncio
async def test_fetch_loaded_model_lmstudio(monkeypatch):
    resp = _Resp({"data": [{"id": "google/gemma-4-31b-a4b"}, {"id": "other"}]})
    monkeypatch.setattr("agents.core.llm.router.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(resp))
    r = LLMRouter()
    model = await r._fetch_loaded_model("http://localhost:1234/v1/models", "lmstudio")
    assert model == "google/gemma-4-31b-a4b"


@pytest.mark.asyncio
async def test_fetch_loaded_model_ollama(monkeypatch):
    resp = _Resp({"models": [{"name": "qwen3:7b"}]})
    monkeypatch.setattr("agents.core.llm.router.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(resp))
    r = LLMRouter()
    model = await r._fetch_loaded_model("http://localhost:11434/api/tags", "ollama")
    assert model == "qwen3:7b"


@pytest.mark.asyncio
async def test_fetch_loaded_model_empty(monkeypatch):
    resp = _Resp({"data": []})
    monkeypatch.setattr("agents.core.llm.router.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(resp))
    r = LLMRouter()
    assert await r._fetch_loaded_model("http://x/v1/models", "lmstudio") is None


# ── HybridRouter local-model resolution ───────────────────────────────────────

async def _no_network_check(url):
    return False


@pytest.mark.asyncio
async def test_detect_uses_real_loaded_model(monkeypatch):
    async def fake_super_detect(self):
        self._backend = object()
        self._detected_model = "loaded-model-xyz"
    monkeypatch.setattr(LLMRouter, "detect", fake_super_detect)

    r = HybridRouter()
    monkeypatch.setattr(r, "_check", _no_network_check)
    await r.detect()
    assert r._local_model == "loaded-model-xyz"  # real loaded model wins


@pytest.mark.asyncio
async def test_detect_falls_back_to_admin_default(monkeypatch):
    async def fake_super_detect(self):
        self._backend = object()
        self._detected_model = None  # nothing loaded / couldn't read
    monkeypatch.setattr(LLMRouter, "detect", fake_super_detect)
    monkeypatch.setattr(settings_db, "get_value",
                        lambda cat, key, default=None: "admin-model" if key == "default_model" else default)

    r = HybridRouter()
    monkeypatch.setattr(r, "_check", _no_network_check)
    await r.detect()
    assert r._local_model == "admin-model"


@pytest.mark.asyncio
async def test_detect_falls_back_to_hardcoded_default(monkeypatch):
    async def fake_super_detect(self):
        self._backend = object()
        self._detected_model = None
    monkeypatch.setattr(LLMRouter, "detect", fake_super_detect)
    monkeypatch.setattr(settings_db, "get_value", lambda cat, key, default=None: default)

    r = HybridRouter()
    monkeypatch.setattr(r, "_check", _no_network_check)
    await r.detect()
    assert r._local_model == DEFAULT_LOCAL_MODEL


# ── Admin-configurable Claude model ───────────────────────────────────────────

def test_get_model_uses_admin_claude_model():
    r = HybridRouter(anthropic_api_key="sk-test")
    r._claude_available = True
    r._claude_model = "claude-from-admin"  # as detect() would resolve it
    assert r.get_model("vision") == "claude-from-admin"


def test_select_backend_claude_uses_admin_model():
    r = HybridRouter(anthropic_api_key="sk-test")
    r._claude_available = True
    r._claude_backend = object()
    r._claude_model = "claude-from-admin"
    backend, model, route = r.select_backend("vision", "hello")
    assert route == "claude"
    assert model == "claude-from-admin"


def test_claude_model_defaults_to_constant_before_detect():
    r = HybridRouter()
    assert r._claude_model == DEFAULT_CLAUDE_MODEL  # backward-compatible default


# ── settings_db.get_value safety ──────────────────────────────────────────────

def test_get_value_returns_default_for_missing():
    assert settings_db.get_value("nonexistent_cat", "nope", "fallback") == "fallback"


# ── Config integrity ──────────────────────────────────────────────────────────

def test_agents_yaml_no_howard_bench_duplicate():
    data = yaml.safe_load((repo_root / "agents/_system/agents.yaml").read_text())
    assert "howard" in data.get("agents", {})          # active
    assert "howard" not in (data.get("bench") or {})   # no bench duplicate
