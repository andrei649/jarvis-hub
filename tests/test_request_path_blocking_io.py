"""Request-path blocking network I/O — regression gate.

A prior parallel bug hunt confirmed four places where async route handlers ran
blocking network calls (sync DNS / sync httpx) directly on the event loop,
freezing every other route for the duration of the lookup. The codebase
convention (test_new4_bounded_request_path.py:334) is: pay blocking backends in
a worker thread (asyncio.to_thread). Each test here proves one flagged path now
runs its network work OFF the loop thread while the loop keeps ticking.
"""
import asyncio
import contextlib
import json
import socket
import threading
import time

import pytest

from agents.core.routers._deps import user_guard  # noqa: F401  (import cost)


def _body(resp):
    return json.loads(resp.body)


def _slow_getaddrinfo(record_thread, delay=0.25):
    """Stand-in for a slow/resolving DNS resolver: records its thread, sleeps."""

    def fake(host, port, *args, **kwargs):
        record_thread["thread"] = threading.current_thread().name
        time.sleep(delay)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", 0))]

    return fake


async def _assert_loop_alive(coro_factory):
    """Run the handler while a ticker task measures loop responsiveness."""
    import agents.core.security.ssrf as ssrf_mod

    seen = {}
    original = ssrf_mod.socket.getaddrinfo
    ssrf_mod.socket.getaddrinfo = _slow_getaddrinfo(seen)
    try:
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        tick_task = asyncio.create_task(ticker())
        try:
            result = await coro_factory()
        finally:
            tick_task.cancel()
        return result, ticks, seen.get("thread")
    finally:
        ssrf_mod.socket.getaddrinfo = original


# ── house: per-snapshot Home Assistant origin re-resolution ───────────────────


def _ha_adapter():
    from agents.core.house.home_assistant import HomeAssistantAdapter

    env = {
        "JARVIS_HOUSE_BRAIN": "1",
        "JARVIS_HOME_ASSISTANT": "1",
        "JARVIS_HA_URL": "http://homeassistant.local:8123",
        "JARVIS_HA_TOKEN_REF": "{{secret:ha_token}}",
    }
    return HomeAssistantAdapter(env=env, settings={})


@pytest.mark.asyncio
async def test_house_snapshot_resolves_dns_off_the_event_loop(monkeypatch):
    """`snapshot()` re-validated the HA origin inline: a fresh blocking
    getaddrinfo ran on the loop for every /api/house/state poll (and each
    actuation). The HTTP transport itself is already async httpx."""
    import agents.core.house.home_assistant as ha_mod

    seen = {}

    def fake(host, port, *args, **kwargs):
        seen["thread"] = threading.current_thread().name
        time.sleep(0.25)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", port or 0))]

    monkeypatch.setattr(ha_mod.socket, "getaddrinfo", fake)
    adapter = _ha_adapter()
    assert adapter.config.ha_enabled, "adapter fixture must enable HA"

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    tick_task = asyncio.create_task(ticker())
    try:
        snapshot = await adapter.snapshot()
    finally:
        tick_task.cancel()

    assert snapshot.status in {"live", "degraded"}  # auth may degrade; DNS still ran
    assert seen.get("thread") != threading.main_thread().name, (
        "the HA origin DNS resolution ran on the event loop"
    )
    assert ticks > 3, f"the event loop was starved during the snapshot (ticks={ticks})"


@pytest.mark.asyncio
async def test_house_actuation_resolves_dns_off_the_event_loop(monkeypatch):
    """`_adapter_service_call` resolved the pinned endpoint inline before its
    async POST — same blocking-DNS-on-loop pattern on the control path."""
    from agents.core.house.actuation import HomeAssistantServiceDriver

    seen = {}
    adapter = _ha_adapter()
    assert adapter.config.ha_enabled

    original = type(adapter)._runtime_endpoint

    def slow_endpoint(self):
        seen["thread"] = threading.current_thread().name
        time.sleep(0.25)
        return original(self)

    monkeypatch.setattr(type(adapter), "_runtime_endpoint", slow_endpoint)

    async def noop_request(*a, **kw):
        raise TimeoutError("stop before HTTP")

    monkeypatch.setattr(adapter._rest, "request", noop_request)

    driver = HomeAssistantServiceDriver(adapter=adapter)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    tick_task = asyncio.create_task(ticker())
    try:
        # credential/transport errors after DNS are fine — DNS still ran
        with contextlib.suppress(Exception):
            await driver.apply(
                {"control": "light", "entity_id": "light.desk", "action": "on"}
            )
    finally:
        tick_task.cancel()

    assert seen.get("thread") is not None, "the actuation endpoint was never resolved"
    assert seen.get("thread") != threading.main_thread().name, (
        "the actuation endpoint resolution ran on the event loop"
    )
    assert ticks > 3, f"the event loop was starved during actuation (ticks={ticks})"


# ── onvif/cameras: WS-discovery address normalization ─────────────────────────


@pytest.mark.asyncio
async def test_onvif_discovery_resolves_addresses_off_the_event_loop():
    """`_normalize` resolved every discovery candidate's xaddr inline
    (resolver -> socket.getaddrinfo) — up to 8 addresses x 128 results of
    blocking DNS per /cameras/onvif/discover request, on the loop."""
    from agents.core.cameras.onvif import OnvifDiscoveryConfig, OnvifDiscoveryService

    seen = {}

    def slow_resolver(host, port):
        seen["thread"] = threading.current_thread().name
        time.sleep(0.25)
        return ("192.168.1.64",)

    service = OnvifDiscoveryService(
        config=OnvifDiscoveryConfig(enabled=True, timeout_seconds=5.0),
        admin_gate=lambda: True,
        discoverer=lambda: [
            {"xaddrs": ["http://camhost.local:2020/onvif/device_service"], "name": "Cam"}
        ],
        resolver=slow_resolver,
    )

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    tick_task = asyncio.create_task(ticker())
    try:
        result = await service.discover()
    finally:
        tick_task.cancel()

    assert result.status == "online" and len(result.devices) == 1
    assert seen.get("thread") != threading.main_thread().name, (
        "the ONVIF address resolution ran on the event loop"
    )
    assert ticks > 3, f"the event loop was starved during discovery (ticks={ticks})"


# ── memory/kg: sync neo4j httpx on the graph-editor routes ────────────────────


class _SlowGraph:
    """Stands in for Neo4jGraph: every method is a slow blocking HTTP call."""

    def __init__(self, seen):
        self._seen = seen

    def _block(self):
        self._seen["thread"] = threading.current_thread().name
        time.sleep(0.25)

    def list_entities(self, limit=100):
        self._block()
        return [{"name": "Alpha", "type": "person"}]

    def search(self, q):
        self._block()
        return [{"name": "Alpha", "type": "person"}]

    def get_entity(self, name):
        self._block()
        return {"name": name, "type": "person"}

    def get_relations(self, name):
        return ()

    def add_entity(self, *a, **kw):
        self._block()
        return True

    def delete_entity(self, name):
        self._block()
        return True

    def add_relation(self, *a, **kw):
        self._block()
        return True

    def delete_relation(self, *a, **kw):
        self._block()
        return True


def _fake_orch(monkeypatch):
    import types

    import agents.core.routers.memory_kg as kg_mod

    seen = {}
    orch = types.SimpleNamespace(
        memory=types.SimpleNamespace(graph=_SlowGraph(seen)),
        entities=None,
    )
    monkeypatch.setattr(kg_mod, "get_orch", lambda: orch)
    return kg_mod, seen


async def _with_ticker(coro_factory):
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    tick_task = asyncio.create_task(ticker())
    try:
        return await coro_factory(), ticks
    finally:
        tick_task.cancel()


@pytest.mark.asyncio
async def test_kg_entities_queries_the_graph_off_the_event_loop(monkeypatch):
    """With KNOWLEDGE_GRAPH_BACKEND=neo4j the editor routes call a sync
    httpx.Client (5s probe / 10s query timeouts) inline — a slow Neo4j froze
    every route in the process for up to 10s per KG request."""
    kg_mod, seen = _fake_orch(monkeypatch)
    (resp, ticks) = await _with_ticker(lambda: kg_mod.kg_entities(q="", limit=10))

    assert json.loads(resp.body)["total"] == 1
    assert seen.get("thread") != threading.main_thread().name, (
        "the KG list ran its blocking call on the event loop"
    )
    assert ticks > 3, f"the event loop was starved during the KG read (ticks={ticks})"


@pytest.mark.asyncio
async def test_kg_writes_run_off_the_event_loop(monkeypatch):
    kg_mod, seen = _fake_orch(monkeypatch)

    class _Req:
        headers = {}

        async def json(self):
            return {"name": "Alpha", "type": "person", "properties": {}}

    (resp, ticks) = await _with_ticker(lambda: kg_mod.kg_upsert_entity(_Req()))

    assert json.loads(resp.body)["ok"] is True
    assert seen.get("thread") != threading.main_thread().name, (
        "the KG write ran its blocking call on the event loop"
    )
    assert ticks > 3, f"the event loop was starved during the KG write (ticks={ticks})"


# ── browser: SSRF DNS resolution on /api/browser/* ────────────────────────────


@pytest.mark.asyncio
async def test_browser_check_resolves_dns_off_the_event_loop():
    """`BrowserPolicy.domain_allowed` -> check_ssrf -> socket.getaddrinfo ran
    inline on the loop: every /api/browser/check froze all routes for a full DNS
    round-trip."""
    from agents.core.routers.browser import BrowserCheckBody, browser_check

    async def call():
        return await browser_check(
            BrowserCheckBody(url="https://example.com/page", allowlist=["example.com"])
        )

    result, ticks, dns_thread = await _assert_loop_alive(call)

    assert _body(result)["allowed"] is True
    assert dns_thread is not None, "the SSRF DNS resolution never ran"
    assert dns_thread != threading.main_thread().name, (
        "the SSRF DNS resolution ran on the event loop"
    )
    assert ticks > 3, f"the event loop was starved during the check (ticks={ticks})"


@pytest.mark.asyncio
async def test_browser_plan_preview_resolves_dns_off_the_event_loop():
    """`GovernedBrowser.preview` classified up to 200 navigate steps, each doing
    a blocking getaddrinfo inline — up to 200 frozen DNS round-trips per call."""
    from agents.core.routers.browser import BrowserPreviewBody, browser_plan_preview

    body = BrowserPreviewBody(
        plan=[{"action": "navigate", "url": "https://example.com/a"}],
        allowlist=["example.com"],
    )

    async def call():
        return await browser_plan_preview(body)

    result, ticks, dns_thread = await _assert_loop_alive(call)

    steps = _body(result)["steps"]
    assert steps and steps[0]["decision"] == "run"
    assert dns_thread != threading.main_thread().name, (
        "the plan preview SSRF check ran on the event loop"
    )
    assert ticks > 3, f"the event loop was starved during the preview (ticks={ticks})"
