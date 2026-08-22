"""House router blocking seams (sqlite/DNS/file stores) stay off the event loop."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.house.contracts import HouseSnapshot  # noqa: E402
from agents.core.routers import house as house_routes  # noqa: E402

SECURITY_KIND = "house.security_control"


def _json(response) -> dict:
    # Handlers return nocache_json(...) responses when invoked directly.
    return json.loads(response.body)


class _Heartbeat:
    """Ticks only while the event loop is free; a blocking seam stalls it."""

    def __init__(self) -> None:
        self.ticks = 0
        self._task: asyncio.Task | None = None

    def __enter__(self) -> "_Heartbeat":
        async def _beat() -> None:
            while True:
                self.ticks += 1
                await asyncio.sleep(0.01)

        self._task = asyncio.get_running_loop().create_task(_beat())
        return self

    def __exit__(self, *_exc: object) -> None:
        assert self._task is not None
        self._task.cancel()


def _security_runtime(delay: float) -> tuple[SimpleNamespace, dict[str, list[int]]]:
    threads: dict[str, list[int]] = {"queue_get": [], "mint": [], "confirm": []}
    task = SimpleNamespace(
        id=77,
        kind=SECURITY_KIND,
        status="proposed",
        payload={"control": "security", "entity_id": "lock.front"},
    )

    class _Queue:
        def get(self, task_id: int):
            threads["queue_get"].append(threading.get_ident())
            time.sleep(delay)
            return task if task_id == 77 else None

    class _Actuator:
        def mint_confirmation(self, _task, *args, **kwargs):
            threads["mint"].append(threading.get_ident())
            time.sleep(delay)
            return {"status": "challenge_minted", "task_id": 77}

        def confirm(self, _token, _task, *args, **kwargs):
            threads["confirm"].append(threading.get_ident())
            time.sleep(delay)
            return {"status": "confirmed", "confirmation_id": 1, "receipt": "receipt"}

    runtime = SimpleNamespace(
        orch_id=0,
        adapter=None,
        graph=None,
        private_store=None,
        actuator=_Actuator(),
        queue=_Queue(),
        private_status="live",
        confirmation_status="live",
    )
    return runtime, threads


async def _use_runtime(runtime: object, monkeypatch) -> None:
    async def _override():
        return runtime

    monkeypatch.setattr(house_routes, "_get_runtime", _override)


async def test_security_challenge_and_confirm_keep_sqlite_off_the_event_loop(monkeypatch):
    runtime, threads = _security_runtime(delay=0.15)
    await _use_runtime(runtime, monkeypatch)
    loop_thread = threading.get_ident()

    with _Heartbeat() as heartbeat:
        challenge = await house_routes.house_security_challenge(task_id=77)
        confirmed = await house_routes.house_security_confirm(
            task_id=77, body=house_routes.ConfirmationBody(challenge_token="x" * 16)
        )

    assert _json(challenge)["status"] == "challenge_minted"
    assert _json(confirmed)["status"] == "confirmed"
    # Every sqlite-backed seam ran on a worker thread, never the event loop.
    assert threads["queue_get"] and all(t != loop_thread for t in threads["queue_get"])
    assert threads["mint"] and all(t != loop_thread for t in threads["mint"])
    assert threads["confirm"] and all(t != loop_thread for t in threads["confirm"])
    # The loop stayed responsive while each seam held its (fake) sqlite lock.
    assert heartbeat.ticks >= 3


async def test_first_request_builds_the_house_runtime_off_the_event_loop(monkeypatch):
    orch = object()
    built_threads: list[int] = []

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

    def fake_build(_orch):
        built_threads.append(threading.get_ident())
        return runtime

    monkeypatch.setattr(house_routes, "_build_runtime", fake_build)
    monkeypatch.setattr(house_routes, "get_orch", lambda: orch)
    monkeypatch.setattr(house_routes, "_runtime", None)

    loop_thread = threading.get_ident()
    with _Heartbeat() as heartbeat:
        first = await house_routes.house_state()
        second = await house_routes.house_state()

    assert _json(first)["status"] == "disabled"
    assert _json(second)["status"] == "disabled"
    # Built once, off-loop, then cached per orchestrator identity.
    assert len(built_threads) == 1
    assert built_threads[0] != loop_thread
    assert heartbeat.ticks >= 1


async def test_control_routes_reuse_the_cached_runtime_without_rebuilding(monkeypatch):
    build_calls: list[int] = []

    class _Actuator:
        async def request_light(self, entity_id, *, state, brightness_pct=None, agent="jarvis"):
            return {"ok": True, "queued": False, "reason": ""}

    runtime = SimpleNamespace(
        orch_id=0,
        adapter=None,
        graph=None,
        private_store=None,
        actuator=_Actuator(),
        queue=None,
        private_status="live",
        confirmation_status="unavailable",
    )

    async def _override():
        build_calls.append(1)
        return runtime

    monkeypatch.setattr(house_routes, "_get_runtime", _override)

    response = await house_routes.house_control_light(
        house_routes.LightControlBody(entity_id="light.kitchen", state="on")
    )

    assert _json(response)["status"] == "unverified"
    assert len(build_calls) == 1

