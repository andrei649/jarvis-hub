"""Home Assistant DNS resolution must not block request-path event loops."""

from __future__ import annotations

import threading
import time

import pytest

from agents.core.house.actuation import HomeAssistantServiceDriver
from agents.core.house.home_assistant import HAConfig, HomeAssistantAdapter


class _Response:
    status_code = 200
    url = "http://127.0.0.1/api/states"

    @staticmethod
    def json():
        return [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Kitchen"},
                "last_updated": 100.0,
            }
        ]


class _REST:
    def __init__(self) -> None:
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _Response()


class _BlockingAdapter(HomeAssistantAdapter):
    def __init__(self) -> None:
        self.config = HAConfig(
            enabled=True,
            ha_enabled=True,
            base_url="http://ha.local",
            token_ref="{{secret:ha}}",
            allowed_hosts=("ha.local",),
        )
        self._config_error = ""
        self._rest = _REST()
        self._clock = lambda: 100.0
        self._health = {}
        self.endpoint_threads = []

    def _runtime_endpoint(self):
        self.endpoint_threads.append(threading.get_ident())
        time.sleep(0.01)
        return "http://ha.local", "127.0.0.1", "ha.local", 80

    @staticmethod
    def _token():
        return "token"


@pytest.mark.asyncio
async def test_service_dns_resolution_runs_off_event_loop_and_preserves_success():
    loop_thread = threading.get_ident()
    adapter = _BlockingAdapter()

    result = await HomeAssistantServiceDriver(adapter=adapter).apply(
        {"control": "light", "entity_id": "light.kitchen", "action": "on"}
    )

    assert result == {"ok": True, "transport_status": 200}
    assert adapter.endpoint_threads and adapter.endpoint_threads == [
        thread_id for thread_id in adapter.endpoint_threads if thread_id != loop_thread
    ]
    assert adapter._rest.calls[0][0:2] == (
        "POST",
        "http://127.0.0.1/api/services/light/turn_on",
    )


@pytest.mark.asyncio
async def test_snapshot_dns_resolution_runs_off_event_loop_and_preserves_live_state():
    loop_thread = threading.get_ident()
    adapter = _BlockingAdapter()

    snapshot = await adapter.snapshot()

    assert snapshot.status == "live"
    assert [(entity.entity_id, entity.state) for entity in snapshot.entities] == [
        ("light.kitchen", "on")
    ]
    assert adapter.endpoint_threads and adapter.endpoint_threads == [
        thread_id for thread_id in adapter.endpoint_threads if thread_id != loop_thread
    ]
    assert adapter._rest.calls[0][0:2] == ("GET", "http://127.0.0.1/api/states")
