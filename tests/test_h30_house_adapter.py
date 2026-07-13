"""H30.1 — strict-local, read-first Home Assistant adapter."""

from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError

import pytest

from agents.core.house.contracts import HouseEntity, HouseEvent, HouseSnapshot
from agents.core.house.home_assistant import (
    HAConfigError,
    HomeAssistantAdapter,
    _HttpxREST,
    load_ha_config,
)
from agents.core.security.secret_broker import SecretBroker


class _Response:
    def __init__(self, payload, *, status=200, headers=None, url=""):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.url = url

    def json(self):
        return self._payload


class _REST:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected REST call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _WSConnection:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    async def recv(self):
        if not self.frames:
            raise ConnectionError("closed")
        frame = self.frames.pop(0)
        if isinstance(frame, BaseException):
            raise frame
        return json.dumps(frame) if isinstance(frame, dict) else frame

    async def send(self, frame):
        self.sent.append(json.loads(frame))

    async def close(self):
        self.closed = True


class _WS:
    def __init__(self, connections=()):
        self.connections = list(connections)
        self.calls = []

    async def connect(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.connections:
            raise ConnectionError("offline")
        connection = self.connections.pop(0)
        if isinstance(connection, BaseException):
            raise connection
        return connection


def _resolver(host, _port):
    assert host == "ha.home.local"
    return ["192.168.1.44"]


def _enabled_env(**overrides):
    env = {
        "JARVIS_HOUSE_BRAIN": "1",
        "JARVIS_HOME_ASSISTANT": "1",
        "JARVIS_HA_URL": "http://ha.home.local:8123",
        "JARVIS_HA_TOKEN_REF": "{{secret:home_assistant_token}}",
        "JARVIS_HA_ALLOWED_HOSTS": "ha.home.local",
    }
    env.update(overrides)
    return env


def _broker(token="TOP-SECRET-TOKEN"):
    broker = SecretBroker()
    broker.put("home_assistant_token", token)
    return broker


@pytest.mark.asyncio
async def test_default_rest_transport_ignores_ambient_proxy_configuration(monkeypatch):
    captured = {}

    class _Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, method, url, **kwargs):
            captured["request"] = (method, url, kwargs)
            return _Response([])

    monkeypatch.setattr("httpx.AsyncClient", _Client)

    await _HttpxREST().request("GET", "http://192.168.1.44:8123/api/states")

    assert captured["client"] == {"follow_redirects": False, "trust_env": False}


def _state(entity_id="light.kitchen", state="on", **attrs):
    return {
        "entity_id": entity_id,
        "state": state,
        "last_updated": "2026-07-13T06:00:00+00:00",
        "attributes": {
            "friendly_name": "Kitchen",
            "area_id": "kitchen",
            "area_name": "Kitchen",
            "device_class": "light",
            **attrs,
        },
    }


def _event(entity_id="light.kitchen", state="on", fired="2026-07-13T06:00:01+00:00"):
    return {
        "id": 7,
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "time_fired": fired,
            "data": {
                "entity_id": entity_id,
                "old_state": _state(entity_id, "off"),
                "new_state": _state(entity_id, state),
            },
        },
    }


def test_snapshot_contract_refuses_unbounded_entity_collections():
    entity = HouseEntity(
        entity_id="sensor.kitchen",
        domain="sensor",
        name="Kitchen",
        state="idle",
        updated_at=1.0,
    )

    with pytest.raises(ValueError, match="entity count"):
        HouseSnapshot(
            enabled=True,
            status="live",
            observed_at=1.0,
            entities=(entity,) * 2_001,
        )


@pytest.mark.asyncio
async def test_default_off_never_touches_rest_or_websocket():
    rest = _REST()
    ws = _WS()
    adapter = HomeAssistantAdapter(env={}, rest=rest, websocket=ws)

    snapshot = await adapter.snapshot()
    events = await adapter.collect_events(limit=5, reconnect_attempts=1)

    assert snapshot.enabled is False and snapshot.status == "disabled"
    assert snapshot.entities == () and snapshot.areas == ()
    assert events == []
    assert rest.calls == [] and ws.calls == []


@pytest.mark.asyncio
async def test_enabled_but_incomplete_configuration_is_honestly_degraded_without_io():
    rest = _REST()
    adapter = HomeAssistantAdapter(
        env={"JARVIS_HOUSE_BRAIN": "1", "JARVIS_HOME_ASSISTANT": "1"},
        rest=rest,
    )

    snapshot = await adapter.snapshot()

    assert snapshot.enabled is True
    assert snapshot.status == "degraded" and snapshot.reason == "configuration_invalid"
    assert rest.calls == []


def test_product_posture_never_enables_house_or_home_assistant():
    config = load_ha_config(
        env={"JARVIS_PRODUCT_POSTURE": "design_partner"},
        settings={"product.posture": "design_partner"},
    )
    assert config.enabled is False
    assert config.ha_enabled is False


def test_environment_precedence_is_explicit_and_credentials_are_handles_only():
    config = load_ha_config(
        env=_enabled_env(JARVIS_HA_URL="http://ha.home.local:8123"),
        settings={
            "house.enabled": False,
            "house.ha_enabled": False,
            "house.ha_url": "http://192.168.1.2:8123",
            "house.ha_token_ref": "{{secret:wrong}}",
        },
        resolver=_resolver,
    )
    assert config.enabled is True and config.ha_enabled is True
    assert config.base_url == "http://ha.home.local:8123"
    assert config.token_ref == "{{secret:home_assistant_token}}"

    with pytest.raises(HAConfigError, match="secret handle"):
        load_ha_config(
            env=_enabled_env(JARVIS_HA_TOKEN_REF="raw-token-is-forbidden"),
            resolver=_resolver,
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@ha.home.local:8123",
        "http://ha.home.local:8123?token=leak",
        "http://ha.home.local:8123/path",
        "ftp://ha.home.local:8123",
        "http://example.com:8123",
    ],
)
def test_origin_validation_rejects_credentials_queries_paths_schemes_and_public_hosts(url):
    with pytest.raises(HAConfigError):
        load_ha_config(env=_enabled_env(JARVIS_HA_URL=url), resolver=_resolver)


def test_dns_rebinding_or_public_resolution_fails_closed():
    def mixed(_host, _port):
        return ["192.168.1.44", "203.0.113.7"]

    with pytest.raises(HAConfigError, match="LAN"):
        load_ha_config(env=_enabled_env(), resolver=mixed)


@pytest.mark.asyncio
async def test_runtime_dns_rebinding_is_refused_before_the_bearer_transport_call():
    resolutions = iter([["192.168.1.44"], ["203.0.113.7"]])

    def rebound(_host, _port):
        return next(resolutions)

    rest = _REST()
    adapter = HomeAssistantAdapter(
        env=_enabled_env(), resolver=rebound, rest=rest, secret_broker=_broker()
    )

    snapshot = await adapter.snapshot()

    assert snapshot.status == "degraded"
    assert snapshot.reason == "origin_validation_failed"
    assert rest.calls == []


@pytest.mark.asyncio
async def test_snapshot_normalizes_bounded_immutable_entities_and_areas_without_raw_payload():
    rest = _REST([_Response([_state(extra_secret="must-not-pass")])])
    adapter = HomeAssistantAdapter(
        env=_enabled_env(),
        resolver=_resolver,
        rest=rest,
        secret_broker=_broker(),
        clock=lambda: 1_720_000_000.0,
    )

    snapshot = await adapter.snapshot()

    assert snapshot.enabled is True and snapshot.status == "live"
    assert snapshot.observed_at == 1_720_000_000.0
    assert snapshot.areas[0].area_id == "kitchen"
    assert snapshot.entities[0].entity_id == "light.kitchen"
    assert dict(snapshot.entities[0].attributes) == {"device_class": "light"}
    assert "must-not-pass" not in repr(snapshot)
    with pytest.raises(FrozenInstanceError):
        snapshot.status = "forged"


@pytest.mark.asyncio
async def test_snapshot_uses_bearer_secret_only_at_transport_boundary_and_never_returns_it():
    token = "TOP-SECRET-TOKEN"
    rest = _REST([_Response([_state()])])
    adapter = HomeAssistantAdapter(
        env=_enabled_env(), resolver=_resolver, rest=rest, secret_broker=_broker(token)
    )

    snapshot = await adapter.snapshot()

    headers = rest.calls[0][2]["headers"]
    assert headers["Authorization"] == f"Bearer {token}"
    assert headers["Host"] == "ha.home.local:8123"
    assert rest.calls[0][1] == "http://192.168.1.44:8123/api/states"
    assert rest.calls[0][2]["extensions"] == {"sni_hostname": "ha.home.local"}
    assert token not in repr(snapshot)
    assert "token" not in rest.calls[0][1].lower()
    assert rest.calls[0][2]["follow_redirects"] is False


@pytest.mark.asyncio
async def test_snapshot_malformed_oversized_timeout_and_redirect_are_honest_degraded_states():
    cases = [
        _Response({"not": "a list"}),
        _Response([_state(f"sensor.s{i}") for i in range(2_001)]),
        TimeoutError("TOP-SECRET-TOKEN timed out"),
        _Response([], status=302, headers={"location": "http://evil.example/steal"}),
    ]
    for response in cases:
        rest = _REST([response])
        adapter = HomeAssistantAdapter(
            env=_enabled_env(), resolver=_resolver, rest=rest, secret_broker=_broker()
        )
        snapshot = await adapter.snapshot()
        assert snapshot.status == "degraded"
        assert snapshot.entities == ()
        assert "TOP-SECRET-TOKEN" not in snapshot.reason
        assert len(rest.calls) == 1


@pytest.mark.asyncio
async def test_websocket_auth_subscription_and_event_normalization_are_local_and_bounded():
    connection = _WSConnection(
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
            _event(),
        ]
    )
    ws = _WS([connection])
    adapter = HomeAssistantAdapter(
        env=_enabled_env(), resolver=_resolver, websocket=ws, secret_broker=_broker()
    )

    events = await adapter.collect_events(limit=1, reconnect_attempts=1)

    assert len(events) == 1 and isinstance(events[0], HouseEvent)
    assert events[0].entity_id == "light.kitchen"
    assert events[0].previous_state == "off" and events[0].current_state == "on"
    assert events[0].privacy_class == "household"
    assert connection.sent[0] == {"type": "auth", "access_token": "TOP-SECRET-TOKEN"}
    assert connection.sent[1] == {
        "id": 1,
        "type": "subscribe_events",
        "event_type": "state_changed",
    }
    assert "TOP-SECRET-TOKEN" not in ws.calls[0][0]
    assert ws.calls[0][1]["max_size"] == 65_536
    assert ws.calls[0][1]["max_queue"] == 16
    assert ws.calls[0][1]["host"] == "192.168.1.44"
    assert ws.calls[0][1]["port"] == 8123
    assert ws.calls[0][1]["proxy"] is None
    assert connection.closed is True


@pytest.mark.asyncio
async def test_websocket_auth_failure_refuses_without_subscribing():
    connection = _WSConnection([{"type": "auth_required"}, {"type": "auth_invalid"}])
    adapter = HomeAssistantAdapter(
        env=_enabled_env(),
        resolver=_resolver,
        websocket=_WS([connection]),
        secret_broker=_broker(),
    )

    events = await adapter.collect_events(limit=1, reconnect_attempts=1)

    assert events == []
    assert len(connection.sent) == 1
    assert connection.closed is True


@pytest.mark.asyncio
async def test_duplicate_and_out_of_order_events_are_dropped():
    frames = [
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"id": 1, "type": "result", "success": True},
        _event(fired="2026-07-13T06:00:02+00:00"),
        _event(fired="2026-07-13T06:00:02+00:00"),
        _event(state="off", fired="2026-07-13T06:00:01+00:00"),
        _event(state="off", fired="2026-07-13T06:00:03+00:00"),
    ]
    adapter = HomeAssistantAdapter(
        env=_enabled_env(),
        resolver=_resolver,
        websocket=_WS([_WSConnection(frames)]),
        secret_broker=_broker(),
    )

    events = await adapter.collect_events(limit=2, reconnect_attempts=1)

    assert [event.current_state for event in events] == ["on", "off"]
    assert len({event.dedupe_key for event in events}) == 2


@pytest.mark.asyncio
async def test_websocket_reconnect_backoff_is_bounded_and_recovers():
    recovered = _WSConnection(
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
            _event(),
        ]
    )
    ws = _WS([ConnectionError("first"), ConnectionError("second"), recovered])
    delays = []

    async def sleep(delay):
        delays.append(delay)

    adapter = HomeAssistantAdapter(
        env=_enabled_env(),
        resolver=_resolver,
        websocket=ws,
        secret_broker=_broker(),
        sleep=sleep,
    )

    events = await adapter.collect_events(limit=1, reconnect_attempts=3)

    assert len(events) == 1
    assert delays == [0.25, 0.5]
    assert max(delays) <= 4.0


@pytest.mark.asyncio
async def test_websocket_frame_and_collection_limits_stop_floods():
    huge = "x" * 65_537
    oversized = _WSConnection(
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
            huge,
        ]
    )
    adapter = HomeAssistantAdapter(
        env=_enabled_env(),
        resolver=_resolver,
        websocket=_WS([oversized]),
        secret_broker=_broker(),
    )
    assert await adapter.collect_events(limit=2, reconnect_attempts=1) == []
    assert oversized.closed is True

    flood_frames = [
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"id": 1, "type": "result", "success": True},
        *[_event(f"sensor.s{i}", str(i), f"2026-07-13T06:00:{i:02d}+00:00") for i in range(10)],
    ]
    flood = HomeAssistantAdapter(
        env=_enabled_env(),
        resolver=_resolver,
        websocket=_WS([_WSConnection(flood_frames)]),
        secret_broker=_broker(),
    )
    events = await flood.collect_events(limit=3, reconnect_attempts=1)
    assert len(events) == 3


@pytest.mark.asyncio
async def test_pre_cancelled_subscription_closes_without_connecting():
    stop = asyncio.Event()
    stop.set()
    ws = _WS()
    adapter = HomeAssistantAdapter(
        env=_enabled_env(), resolver=_resolver, websocket=ws, secret_broker=_broker()
    )

    assert await adapter.collect_events(limit=2, reconnect_attempts=2, stop_event=stop) == []
    assert ws.calls == []


@pytest.mark.asyncio
async def test_active_subscription_cancellation_closes_the_connection():
    release = asyncio.Event()

    class _BlockingConnection(_WSConnection):
        async def recv(self):
            if self.frames:
                return await super().recv()
            await release.wait()
            raise ConnectionError("released")

    connection = _BlockingConnection(
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
        ]
    )
    stop = asyncio.Event()
    adapter = HomeAssistantAdapter(
        env=_enabled_env(),
        resolver=_resolver,
        websocket=_WS([connection]),
        secret_broker=_broker(),
    )

    task = asyncio.create_task(
        adapter.collect_events(limit=2, reconnect_attempts=1, stop_event=stop)
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    stop.set()
    assert await asyncio.wait_for(task, timeout=1.0) == []
    assert connection.closed is True
