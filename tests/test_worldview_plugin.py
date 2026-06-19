"""Tests for the WorldView 4D OSINT plugin + its permission-gate manifest (H19.3.3)."""

import asyncio

from agents.core.plugin_gate import DataScope, NetworkAccess, PermissionGate
from agents.core.plugins.worldview import LAYERS, WorldViewPlugin


def test_worldview_manifest_registered_and_scoped():
    gate = PermissionGate()
    assert "worldview" in gate.plugins
    m = gate.plugins["worldview"]
    # Local-first: LAN reach, data never leaves the machine.
    assert m.network_access == NetworkAccess.LAN
    assert m.data_scope == DataScope.LOCAL_ONLY
    # Served to the geospatial/OSINT agents named in the ticket (Athena/Stark) + Vision/Jarvis.
    for agent in ("jarvis", "athena", "stark", "vision"):
        assert agent in m.agents_served
    # The gate lets a served agent call it and blocks an unrelated one.
    assert gate.check_call("worldview", "athena") is True
    assert gate.check_call("worldview", "stark") is True
    assert gate.check_call("worldview", "frigga") is False


async def test_state_at_rejects_unknown_layer():
    wv = WorldViewPlugin(api_url="http://localhost:4000")
    try:
        res = await wv.state_at("not-a-layer", 1700000000.0)
        assert res["status"] == "error"
        assert set(res["layers"]) == set(LAYERS)
    finally:
        await wv.close()


async def test_unavailable_backend_degrades_gracefully(monkeypatch):
    """A down backend yields a structured 'unavailable' result, never an exception."""
    wv = WorldViewPlugin(api_url="http://localhost:4000")

    async def boom(path, params=None):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(wv, "_get", boom)
    try:
        state = await wv.state_at("adsb", 1700000000.0)
        assert state["status"] == "unavailable"

        windows = await wv.recon_windows()
        assert windows["status"] == "unavailable"

        overview = await wv.recon_overview()
        assert overview["status"] == "unavailable"
    finally:
        await wv.close()


async def test_recon_overview_merges_windows_and_alerts(monkeypatch):
    wv = WorldViewPlugin()

    async def fake_get(path, params=None):
        if path == "/recon/windows":
            return {"windows": [{"norad_id": 40115, "aoi_id": "hormuz"}]}
        if path == "/recon/alerts":
            return {"alerts": [{"norad_id": 40115, "aoi_id": "hormuz"}]}
        return {}

    monkeypatch.setattr(wv, "_get", fake_get)
    try:
        overview = await wv.recon_overview()
        assert overview["status"] == "ok"
        assert len(overview["upcoming_windows"]) == 1
        assert len(overview["due_alerts"]) == 1
        assert overview["api_url"].endswith(":4000")
    finally:
        await wv.close()


async def test_recon_overview_runs_subcalls_concurrently(monkeypatch):
    """H19.3 latency fix: the two recon_overview sub-calls fire concurrently on the
    chat turn (asyncio.gather), so worst-case latency is ~one call, not two serial.
    """
    wv = WorldViewPlugin()
    started = 0
    max_concurrent = 0

    async def slow_get(path, params=None):
        nonlocal started, max_concurrent
        started += 1
        max_concurrent = max(max_concurrent, started)
        await asyncio.sleep(0.05)  # hold both calls open to observe overlap
        started -= 1
        if path == "/recon/windows":
            return {"windows": []}
        return {"alerts": []}

    monkeypatch.setattr(wv, "_get", slow_get)
    try:
        overview = await wv.recon_overview()
        assert overview["status"] == "ok"
        # Both sub-calls were in flight at the same time → concurrent, not serial.
        assert max_concurrent == 2
    finally:
        await wv.close()


def test_interactive_timeout_is_small():
    """The chat-path GET uses a small per-attempt timeout (not the old 15s) so an
    unreachable backend degrades fast instead of stalling the synchronous turn."""
    closure = WorldViewPlugin._get.__closure__
    timeouts = [c.cell_contents for c in closure
                if isinstance(c.cell_contents, float)]
    assert 5.0 in timeouts and 15.0 not in timeouts


async def test_state_at_happy_path_counts_features(monkeypatch):
    wv = WorldViewPlugin()

    async def fake_get(path, params=None):
        assert path == "/history/adsb"
        return {"type": "FeatureCollection", "features": [{"id": "a"}, {"id": "b"}]}

    monkeypatch.setattr(wv, "_get", fake_get)
    try:
        res = await wv.state_at("adsb", 1700000000.0)
        assert res["status"] == "ok"
        assert res["count"] == 2
    finally:
        await wv.close()


# ── F-06: bridge auth (Authorization: Bearer when WORLDVIEW_API_TOKEN is set) ──

class _FakeResp:
    def raise_for_status(self):
        pass
    def json(self):
        return {"ok": True}


async def test_bridge_sends_bearer_when_token_set(monkeypatch):
    monkeypatch.setenv("WORLDVIEW_API_TOKEN", "wv-secret")
    wv = WorldViewPlugin(api_url="http://localhost:4000")
    captured = {}

    async def fake_get(url, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return _FakeResp()

    monkeypatch.setattr(wv.client, "get", fake_get)
    await wv._get("history/state")
    assert captured["headers"].get("Authorization") == "Bearer wv-secret"


async def test_bridge_sends_no_auth_header_by_default(monkeypatch):
    monkeypatch.delenv("WORLDVIEW_API_TOKEN", raising=False)
    wv = WorldViewPlugin(api_url="http://localhost:4000")  # no token → local, auth-disabled
    captured = {}

    async def fake_get(url, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return _FakeResp()

    monkeypatch.setattr(wv.client, "get", fake_get)
    await wv._get("history/state")
    assert "Authorization" not in (captured["headers"] or {})
