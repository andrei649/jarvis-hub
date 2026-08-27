"""House router runtime construction stays off request-path event loops."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from agents.core.house.contracts import HouseSnapshot
from agents.core.routers import house as house_routes


@pytest.mark.asyncio
async def test_first_house_request_builds_runtime_off_the_event_loop(monkeypatch):
    orch = object()
    build_threads = []

    class _Adapter:
        async def snapshot(self):
            return HouseSnapshot(
                enabled=False,
                status="disabled",
                observed_at=0.0,
                reason="house_brain_disabled",
            )

    runtime = SimpleNamespace(
        orch_id=id(orch),
        adapter=_Adapter(),
        graph=None,
        private_store=None,
        actuator=None,
        queue=None,
        private_status="disabled",
        confirmation_status="unavailable",
    )

    def blocking_build(_orch):
        build_threads.append(threading.get_ident())
        time.sleep(0.01)
        return runtime

    monkeypatch.setattr(house_routes, "_build_runtime", blocking_build)
    monkeypatch.setattr(house_routes, "get_orch", lambda: orch)
    monkeypatch.setattr(house_routes, "_runtime", None)
    loop_thread = threading.get_ident()

    first = await house_routes.house_state()
    second = await house_routes.house_state()

    assert json.loads(first.body)["status"] == "disabled"
    assert json.loads(second.body)["status"] == "disabled"
    assert len(build_threads) == 1
    assert build_threads[0] != loop_thread
