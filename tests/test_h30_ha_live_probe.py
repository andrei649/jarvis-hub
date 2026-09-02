"""H30 owner-live probes against a real HTTP Home Assistant stand-in.

The hermetic pack (`house_reality.py`) injects a simulator in place of the REST
and WebSocket transports, so it never exercises `_HttpxREST`, the pinned-origin
rewrite, the `Host` header, the bearer header, or JSON parsing of a real socket
response. Those are precisely the seams that break first against a real Home
Assistant, and they are what the owner-live cases exist to cover.

This module runs the real probes against a real uvicorn server speaking Home
Assistant's REST shapes on loopback. It is not a substitute for the owner's HA
(schema drift in HA itself is still only visible against the real thing) — it is
the tier below: proof that the probe wiring and transport work at all.

Regression pinned here: the owner-live read probe used to build
`HomeAssistantAdapter()` with no secret broker, so `_token()` raised
`credential_unavailable` before any request and the case could never pass, even
against a healthy host.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability.house_reality import (  # noqa: E402
    _probe_owner_live_actuation,
    _probe_owner_live_read,
)

_TOKEN = "-".join(("live", "probe", "fixture", "token"))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_app() -> FastAPI:
    """The narrow slice of the HA REST API the adapter and driver actually use."""
    app = FastAPI()
    states: dict[str, dict] = {
        "light.kitchen": {
            "entity_id": "light.kitchen",
            "state": "off",
            # Real HA emits both stamps; the adapter reads `last_updated`.
            "attributes": {"friendly_name": "Kitchen", "brightness": 0},
            "last_changed": "2026-09-01T10:00:00+00:00",
            "last_updated": "2026-09-01T10:00:00+00:00",
        },
        "lock.front_door": {
            "entity_id": "lock.front_door",
            "state": "locked",
            "attributes": {"friendly_name": "Front Door"},
            "last_changed": "2026-09-01T10:00:00+00:00",
            "last_updated": "2026-09-01T10:00:00+00:00",
        },
    }

    def _auth(authorization: str | None) -> None:
        if authorization != f"Bearer {_TOKEN}":
            raise HTTPException(status_code=401, detail="bad token")

    @app.get("/api/states")
    async def get_states(authorization: str | None = Header(default=None)):
        _auth(authorization)
        return list(states.values())

    @app.post("/api/services/{domain}/{service}")
    async def call_service(
        domain: str,
        service: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        _auth(authorization)
        body = await request.json()
        entity_id = body.get("entity_id")
        if entity_id not in states or not entity_id.startswith(f"{domain}."):
            raise HTTPException(status_code=400, detail="unknown entity")
        if service == "turn_on":
            states[entity_id]["state"] = "on"
        elif service == "turn_off":
            states[entity_id]["state"] = "off"
        else:
            raise HTTPException(status_code=400, detail="unsupported service")
        return [states[entity_id]]

    return app


@pytest.fixture()
def ha_server():
    port = _free_port()
    config = uvicorn.Config(_build_app(), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            threading.Event().wait(0.05)
        else:  # pragma: no cover - only on a pathologically slow runner
            pytest.fail("test Home Assistant stand-in did not start")
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _configure(monkeypatch, port: int, *, token: str | None = _TOKEN) -> None:
    monkeypatch.setenv("JARVIS_HOUSE_BRAIN", "1")
    monkeypatch.setenv("JARVIS_HOME_ASSISTANT", "1")
    monkeypatch.setenv("JARVIS_HA_URL", f"http://localhost:{port}")
    monkeypatch.setenv("JARVIS_HA_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("JARVIS_HA_TOKEN_REF", "{{secret:" + "home_assistant_token}}")
    monkeypatch.setenv("JARVIS_H30_HA_LIVE", "1")
    if token is None:
        monkeypatch.delenv("JARVIS_H30_HA_TOKEN", raising=False)
    else:
        monkeypatch.setenv("JARVIS_H30_HA_TOKEN", token)


def test_live_read_reaches_a_real_socket(monkeypatch, ha_server):
    _configure(monkeypatch, ha_server)

    result = asyncio.run(_probe_owner_live_read())

    assert result["passed"] is True, result
    assert result["metadata"]["status"] == "live"
    assert result["metadata"]["entities"] == 2


def test_live_read_without_a_broker_is_the_regression_this_module_pins(monkeypatch, ha_server):
    """No token configured → honest credential degradation, not a transport error."""
    _configure(monkeypatch, ha_server, token=None)

    result = asyncio.run(_probe_owner_live_read())

    assert result["passed"] is False
    assert result["metadata"]["reason"] == "owner_live_credential_missing"


def test_adapter_without_a_broker_cannot_authenticate_against_a_healthy_host(
    monkeypatch, ha_server
):
    """The exact defect: the old probe body, against a server that is up and correct.

    `HomeAssistantAdapter()` with no `secret_broker` is what `_probe_owner_live_read`
    used to construct. It degrades with `credential_unavailable` before issuing a
    request, so the owner-live case reported the same result whether Home Assistant
    was healthy, misconfigured, or absent — it could never go green.
    """
    from agents.core.house.home_assistant import HomeAssistantAdapter

    _configure(monkeypatch, ha_server)

    snapshot = asyncio.run(HomeAssistantAdapter().snapshot())

    assert snapshot.status == "degraded"
    assert snapshot.reason == "credential_unavailable"

    # Same host, same config, one difference: the broker the fix supplies.
    from agents.core.observability.house_reality import _live_secret_broker

    fixed = asyncio.run(HomeAssistantAdapter(secret_broker=_live_secret_broker()).snapshot())

    assert fixed.status == "live"
    assert len(fixed.entities) == 2


def test_live_read_rejects_a_wrong_token(monkeypatch, ha_server):
    _configure(monkeypatch, ha_server, token="not-the-right-token")

    result = asyncio.run(_probe_owner_live_read())

    assert result["passed"] is False
    assert result["metadata"]["status"] == "degraded"


def test_live_actuation_flips_and_rolls_back(monkeypatch, ha_server):
    _configure(monkeypatch, ha_server)

    result = asyncio.run(_probe_owner_live_actuation())

    assert result["passed"] is True, result
    meta = result["metadata"]
    assert meta["entity"] == "light.kitchen"
    assert meta["observed_after_apply"] == "on"
    assert meta["observed_after_rollback"] == "off"
    assert meta["lock_refused_by_allowlist"] is True
    assert meta["mutation_probe"] is True


def test_live_probes_stay_off_without_the_opt_in(monkeypatch, ha_server):
    _configure(monkeypatch, ha_server)
    monkeypatch.delenv("JARVIS_H30_HA_LIVE", raising=False)

    for probe in (_probe_owner_live_read, _probe_owner_live_actuation):
        result = asyncio.run(probe())
        assert result["passed"] is False
        assert result["metadata"]["reason"] == "owner_live_opt_in_missing"


def test_actuation_leaves_no_device_on_when_verification_fails(monkeypatch, ha_server):
    """A refused service call must still leave the light off, not mid-flight."""
    _configure(monkeypatch, ha_server)
    import agents.core.house.actuation as actuation

    original = actuation.HomeAssistantServiceDriver._adapter_service_call

    async def _refuse(self, domain, service, data):
        if service == "turn_on":
            return {"ok": False, "transport_status": 400, "reason": "ha_service_failed"}
        return await original(self, domain, service, data)

    monkeypatch.setattr(actuation.HomeAssistantServiceDriver, "_adapter_service_call", _refuse)

    result = asyncio.run(_probe_owner_live_actuation())

    assert result["passed"] is False
    assert result["metadata"]["observed_after_rollback"] == "off"


@contextlib.contextmanager
def _noop():  # pragma: no cover - placeholder to keep import surface honest
    yield
