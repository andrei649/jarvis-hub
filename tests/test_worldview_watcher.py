"""Tests for the WorldView autonomy probe (agents/core/autonomy/watchers.py, H19.3.4).

Verifies recon-pass + dark-vessel signals (with provenance), graceful degradation
when the WorldView backend is down, and EventWatcher debouncing (one alert per pass).
"""

from __future__ import annotations

import time

from agents.core.autonomy.observer import Severity
from agents.core.autonomy.watchers import EventWatcher, WorldViewProbe


class FakeWorldView:
    """Stands in for WorldViewPlugin: returns canned recon alerts / context features."""

    def __init__(self, alerts=None, features=None, status="ok"):
        self._alerts = alerts or []
        self._features = features or []
        self._status = status

    async def recon_alerts(self, lead=None):
        if self._status != "ok":
            return {"status": "unavailable", "error": "down"}
        return {"status": "ok", "count": len(self._alerts), "alerts": self._alerts}

    async def state_at(self, layer, t, bbox="", lod=""):
        if self._status != "ok":
            return {"status": "unavailable", "error": "down"}
        return {"status": "ok", "count": len(self._features), "features": self._features}


async def test_probe_without_plugin_is_silent():
    probe = WorldViewProbe(worldview_plugin=None)
    assert await probe() == []


async def test_probe_degrades_when_backend_down():
    probe = WorldViewProbe(worldview_plugin=FakeWorldView(status="down"))
    assert await probe() == []  # never raises, emits nothing


async def test_recon_pass_becomes_warn_signal_with_provenance():
    alerts = [
        {"norad_id": 40115, "aoi_id": "hormuz", "sensor_type": "optical",
         "t_ingress": time.time() + 600},
    ]
    probe = WorldViewProbe(worldview_plugin=FakeWorldView(alerts=alerts))
    signals = await probe()
    assert len(signals) == 1
    sig = signals[0]
    assert sig.key == "worldview.recon.40115.hormuz"
    assert sig.healthy is False
    assert sig.severity == Severity.WARN
    assert "provenance" in sig.detail.lower()
    assert "40115" in sig.detail and "hormuz" in sig.detail


async def test_dark_vessel_becomes_critical_signal_with_provenance():
    features = [
        {"properties": {"kind": "dark_vessel", "mmsi": 636092297}},
        {"properties": {"kind": "geopolitical_event"}},  # ignored
    ]
    probe = WorldViewProbe(worldview_plugin=FakeWorldView(features=features))
    signals = await probe()
    dark = [s for s in signals if s.key == "worldview.dark_vessel.636092297"]
    assert len(dark) == 1
    assert dark[0].severity == Severity.CRITICAL
    assert "provenance" in dark[0].detail.lower()


async def test_eventwatcher_debounces_repeated_recon_alert():
    alerts = [
        {"norad_id": 40115, "aoi_id": "hormuz", "sensor_type": "sar",
         "t_ingress": time.time() + 300},
    ]
    probe = WorldViewProbe(worldview_plugin=FakeWorldView(alerts=alerts))
    watcher = EventWatcher(None, [probe])

    first = watcher.evaluate(await probe())
    assert len(first) == 1 and first[0].transition == "alert"

    # Same pass still due on the next cycle → debounced (no duplicate alert).
    second = watcher.evaluate(await probe())
    assert second == []
