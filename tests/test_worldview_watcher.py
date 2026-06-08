"""Tests for the WorldView autonomy probe (agents/core/autonomy/watchers.py, H19.3.4).

Verifies recon-pass + dark-vessel signals (with provenance), graceful degradation
when the WorldView backend is down, and EventWatcher debouncing (one alert per pass).
"""

from __future__ import annotations

import time

from agents.core.autonomy import AutonomyPolicy, AutonomyWorker, TaskQueue
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


def _worker() -> AutonomyWorker:
    queue = TaskQueue(db_path=":memory:").initialize()
    return AutonomyWorker(queue, policy=AutonomyPolicy())


async def test_per_tick_cap_bounds_emissions_and_prioritises_critical():
    """A noisy backend reporting many due events in one tick must not flood the
    queue: the probe caps alert signals per tick (dark-vessel CRITICALs win over
    recon WARNs) and aggregates the overflow into one digest signal.

    This is the real guard — READ_ONLY alerts auto-approve before the autonomy
    InterruptBudget is consulted, so the budget never caps them.
    """
    base = time.time()
    # 10 recon WARNs (varying ETA) + 3 dark-vessel CRITICALs = 13 due alerts.
    alerts = [
        {"norad_id": 40000 + i, "aoi_id": f"aoi{i}", "sensor_type": "optical",
         "t_ingress": base + 60 * (i + 1)}
        for i in range(10)
    ]
    features = [
        {"properties": {"kind": "dark_vessel", "mmsi": 600000000 + i}}
        for i in range(3)
    ]
    probe = WorldViewProbe(
        worldview_plugin=FakeWorldView(alerts=alerts, features=features),
        max_per_tick=4,
    )
    signals = await probe()

    emitted_alerts = [s for s in signals if not s.healthy]
    # 4 kept alerts + 1 overflow digest — bounded regardless of the 13 due events.
    assert len(emitted_alerts) == 5
    kept = [s for s in emitted_alerts if s.key != "worldview.digest.overflow"]
    assert len(kept) == 4
    # All 3 dark-vessel CRITICALs are kept (they outrank recon WARNs).
    assert sum(1 for s in kept if s.severity == Severity.CRITICAL) == 3
    # The overflow is summarised into exactly one digest signal, not lost.
    digest = [s for s in emitted_alerts if s.key == "worldview.digest.overflow"]
    assert len(digest) == 1
    assert "9 more due event" in digest[0].detail  # 13 - 4 kept = 9 suppressed


async def test_per_tick_cap_noop_below_threshold():
    """Below the cap, signals pass through untouched (no spurious digest)."""
    alerts = [
        {"norad_id": 40115, "aoi_id": "hormuz", "sensor_type": "optical",
         "t_ingress": time.time() + 600},
    ]
    probe = WorldViewProbe(worldview_plugin=FakeWorldView(alerts=alerts), max_per_tick=4)
    signals = await probe()
    assert all(s.key != "worldview.digest.overflow" for s in signals)


async def test_restart_does_not_reflood_due_alerts():
    """A process restart wipes EventWatcher._state; without durable dedupe every
    still-due event would re-fire as a fresh alert. The durable autonomy queue
    suppresses the re-flood.
    """
    alerts = [
        {"norad_id": 40115, "aoi_id": "hormuz", "sensor_type": "sar",
         "t_ingress": time.time() + 300},
    ]
    plugin = FakeWorldView(alerts=alerts)
    worker = _worker()

    # First boot: probe + watcher submit the alert into the durable queue.
    probe1 = WorldViewProbe(worldview_plugin=plugin)
    watcher1 = EventWatcher(worker, [probe1])
    res1 = await watcher1.observe()
    assert res1["submitted"] == 1
    submitted_keys = {
        t.payload.get("key") for t in worker.queue.list(origin="generated")
    }
    assert "worldview.recon.40115.hormuz" in submitted_keys

    # Simulate a restart: BRAND-NEW watcher (empty in-memory _state), same still-due
    # event, but the SAME durable queue. Must NOT re-submit the same alert.
    probe2 = WorldViewProbe(worldview_plugin=plugin)
    watcher2 = EventWatcher(worker, [probe2])
    res2 = await watcher2.observe()
    assert res2["submitted"] == 0, "restart re-flooded the queue with a duplicate alert"
