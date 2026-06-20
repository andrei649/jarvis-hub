"""Tests for the Jarvis Signal Layer plugin bridge."""

from agents.core.plugin_gate import DataScope, NetworkAccess, PermissionGate
from agents.core.plugins.signal_layer import SignalLayerPlugin


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def test_signal_layer_manifest_registered_and_scoped():
    gate = PermissionGate()
    assert "signal-layer" in gate.plugins
    manifest = gate.plugins["signal-layer"]
    assert manifest.network_access == NetworkAccess.LAN
    assert manifest.data_scope == DataScope.LOCAL_ONLY
    for agent in ("jarvis", "friday", "athena", "stark", "vision", "argus"):
        assert agent in manifest.agents_served
    assert gate.check_call("signal-layer", "argus") is True
    assert gate.check_call("signal-layer", "frigga") is False


async def test_signal_layer_unavailable_backend_degrades_gracefully(monkeypatch):
    plugin = SignalLayerPlugin(api_url="http://localhost:8787")

    async def boom(path, params=None):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(plugin, "_get", boom)
    try:
        assert (await plugin.health())["status"] == "unavailable"
        assert (await plugin.world_brief())["status"] == "unavailable"
        assert (await plugin.country_assessment("RO"))["status"] == "unavailable"
    finally:
        await plugin.close()


async def test_signal_layer_signals_passes_relevance_params(monkeypatch):
    plugin = SignalLayerPlugin(api_url="http://localhost:8787")
    captured = {}

    async def fake_get(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return {
            "count": 1,
            "signals": [{"id": "sig-1", "title": "Signal"}],
            "evidence": [{"id": "ev-1"}],
            "freshness": {"stale": False},
            "provider": "worldmonitor",
        }

    monkeypatch.setattr(plugin, "_get", fake_get)
    try:
        result = await plugin.signals(limit=5, relevant_only=True, country="RO", min_severity="elevated")
        assert result["status"] == "ok"
        assert result["count"] == 1
        assert captured["path"] == "/signals"
        assert captured["params"]["relevantOnly"] == "true"
        assert captured["params"]["country"] == "RO"
        assert captured["params"]["minSeverity"] == "elevated"
    finally:
        await plugin.close()


async def test_signal_layer_ask_world_posts_question(monkeypatch):
    plugin = SignalLayerPlugin(api_url="http://localhost:8787")
    captured = {}

    async def fake_post(path, payload=None):
        captured["path"] = path
        captured["payload"] = payload
        return {"answer": "World brief", "mode": "overnight_brief"}

    monkeypatch.setattr(plugin, "_post", fake_post)
    try:
        result = await plugin.ask_world("What changed overnight?", mode="overnight_brief", limit=3)
        assert result["status"] == "ok"
        assert result["answer"] == "World brief"
        assert captured["path"] == "/ask/world"
        assert captured["payload"]["question"] == "What changed overnight?"
        assert captured["payload"]["mode"] == "overnight_brief"
        assert captured["payload"]["limit"] == 3
    finally:
        await plugin.close()


async def test_signal_layer_sends_bearer_when_token_set(monkeypatch):
    plugin = SignalLayerPlugin(api_url="http://localhost:8787", api_token="sl-secret")
    captured = {}

    async def fake_get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _FakeResp({"ok": True})

    monkeypatch.setattr(plugin.client, "get", fake_get)
    try:
        await plugin._get("/healthz")
        assert captured["url"] == "http://localhost:8787/healthz"
        assert captured["headers"].get("Authorization") == "Bearer sl-secret"
    finally:
        await plugin.close()
