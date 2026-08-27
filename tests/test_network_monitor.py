"""H23.16 — network monitor: egress ledger, choke-point recording, admin endpoint.

Covers the EgressMonitor data layer, the http_client choke-point wiring (allowed +
blocked attempts both land in the ledger, via httpx.MockTransport so no real socket),
and the admin-guarded GET /api/admin/network/calls.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.core.http_client import PluginEgressError, PluginHTTPClient
from agents.core.observability.egress_monitor import EGRESS_MONITOR, EgressMonitor


@pytest.fixture(autouse=True)
def _clean_monitor():
    EGRESS_MONITOR.reset()
    yield
    EGRESS_MONITOR.reset()


def _mock(client: PluginHTTPClient, status: int = 200):
    """Give *client* a MockTransport-backed pinned pool (no real network).

    SEC-B4 dials through per-target pinned clients, so the transport has to be
    injected via the factory the client builds them with — replacing ``_client``
    would leave the real (network-dialing) transport on the egress path. The
    resolve/validate/record wiring this file exercises still runs for real.
    """
    client._transport_factory = lambda _target: httpx.MockTransport(
        lambda req: httpx.Response(status, text="ok")
    )
    return client


# ── EgressMonitor unit ───────────────────────────────────────────────────────
def test_counters_and_external_classification():
    m = EgressMonitor()
    m.record("weather", "wttr.in", "GET", allowed=True, local=False)
    m.record("weather", "wttr.in", "GET", allowed=True, local=False)
    m.record("system-control", "8.8.8.8", "POST", allowed=False, local=False, reason="blocked")
    snap = m.snapshot()
    assert snap["plugins"]["weather"] == {
        "total": 2, "allowed": 2, "blocked": 0, "external": 2,
        "last_ts": snap["plugins"]["weather"]["last_ts"], "last_host": "wttr.in",
    }
    assert snap["plugins"]["system-control"]["blocked"] == 1
    assert snap["external_egress_total"] == 2
    assert snap["recent"][0]["plugin"] == "system-control"  # newest-first


def test_ring_buffer_is_bounded_but_counters_exact():
    m = EgressMonitor(max_events=3)
    for _ in range(10):
        m.record("p", "h", "GET", allowed=True, local=True)
    snap = m.snapshot(limit=100)
    assert len(snap["recent"]) == 3          # ring buffer evicts
    assert snap["plugins"]["p"]["total"] == 10  # counters survive eviction


def test_filter_by_plugin():
    m = EgressMonitor()
    m.record("a", "h", "GET", allowed=True, local=True)
    m.record("b", "h", "GET", allowed=True, local=True)
    snap = m.snapshot(plugin="a")
    assert set(snap["plugins"]) == {"a"}
    assert all(e["plugin"] == "a" for e in snap["recent"])


def test_local_only_violation_proof():
    # An allowed *external* call by a no-network plugin is the anomaly the panel proves
    # cannot happen — recording one must surface it (clean=False).
    m = EgressMonitor()
    m.record("system-control", "8.8.8.8", "GET", allowed=True, local=False)  # NONE manifest
    snap = m.snapshot()
    assert "system-control" in snap["local_only_violations"]
    assert snap["clean"] is False


def test_clean_when_only_local_or_blocked():
    m = EgressMonitor()
    m.record("worldview", "127.0.0.1", "GET", allowed=True, local=True)        # LAN, local → fine
    m.record("system-control", "8.8.8.8", "GET", allowed=False, local=False)   # blocked → fine
    snap = m.snapshot()
    assert snap["local_only_violations"] == []
    assert snap["clean"] is True


# ── http_client choke-point wiring ───────────────────────────────────────────
async def test_blocked_call_is_recorded_and_raises():
    c = PluginHTTPClient("system-control")  # NONE → always blocks
    with pytest.raises(PluginEgressError):
        await c.get("https://93.184.216.34/x")  # IP literal → no DNS
    snap = EGRESS_MONITOR.snapshot()
    st = snap["plugins"]["system-control"]
    assert st["blocked"] == 1 and st["allowed"] == 0


async def test_allowed_local_call_is_recorded():
    c = _mock(PluginHTTPClient("worldview"))  # LAN → localhost allowed
    resp = await c.get("http://127.0.0.1:4000/history")
    assert resp.status_code == 200
    st = EGRESS_MONITOR.snapshot()["plugins"]["worldview"]
    assert st["allowed"] == 1 and st["external"] == 0  # local → not external
    await c.close()


# ── admin endpoint ───────────────────────────────────────────────────────────
def test_endpoint_requires_admin():
    from agents import web
    # TestClient host is non-localhost and no token supplied → guarded.
    resp = TestClient(web.app).get("/api/admin/network/calls")
    assert resp.status_code in (401, 403)


def test_endpoint_returns_snapshot_when_authorized():
    from agents import web
    from agents.core.routers._deps import admin_guard

    EGRESS_MONITOR.record("weather", "wttr.in", "GET", allowed=True, local=False)
    web.app.dependency_overrides[admin_guard] = lambda: None
    try:
        resp = TestClient(web.app).get("/api/admin/network/calls?plugin=weather&limit=5")
    finally:
        web.app.dependency_overrides.pop(admin_guard, None)
    assert resp.status_code == 200
    body = resp.json()
    assert body["plugins"]["weather"]["external"] == 1
    assert body["external_egress_total"] == 1
    assert "no-store" in resp.headers.get("cache-control", "")
