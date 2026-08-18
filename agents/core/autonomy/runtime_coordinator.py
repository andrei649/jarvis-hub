"""runtime_coordinator.py — Always-On headless engine entrypoint (no HTTP server).

Boots the same ``Orchestrator`` used by ``agents/web.py`` (``JarvisConfig`` ->
``Orchestrator`` -> ``load_agents()``), starts the existing autonomy coordinator loop
(``AutonomyCoordinator.loop`` — already contains the H6.6 night-shift gate) and the
existing heartbeat scheduler exactly as ``Orchestrator.start_channels()`` does, then runs
one more loop of its own: a **cycle recorder** that, on the same cadence as the autonomy
tick (``system.autonomy_tick``), takes a read-only snapshot of the task queue and the
heartbeat scheduler and appends one JSON line to the run-log (``runtime_log.py``) plus a
small persisted state document (``runtime_state.py``) so a crash/``kill -9`` restart
resumes the cycle counter instead of losing history.

Deliberately non-invasive: this module never mutates ``TaskQueue``, ``AutonomyWorker`` or
``AutonomyCoordinator`` — the security-hardened B7 mediation path is untouched. The
recorder only calls existing read-only APIs (``TaskQueue.stats()``,
``HeartbeatScheduler.get_status()``) and computes deltas locally.

Deliberately headless: no web/voice/telegram/discord channel adapters, no uvicorn. Those
remain the concern of ``agents/web.py`` + ``serve.py``. **Run this OR the full app against
the same ``JARVIS_HOME`` — never both**: each independently starts
``AutonomyCoordinator.loop()`` against the same durable ``autonomy.db``, and running two
copies would tick (and could double-execute approved tasks against) the same queue.
``scripts/runtime_supervisor.py`` wraps THIS module for OS-level crash recovery; the
``Makefile``'s ``runtime-up`` target is the documented way to run it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time

from .runtime_log import append_record, default_log_path, utc_now_iso
from .runtime_state import RuntimeStateStore
from .worker import is_night_window

logger = logging.getLogger("jarvis.autonomy.runtime")

_STATUS_COUNTED = ("done", "failed", "approved", "blocked", "proposed", "running")


def _night_shift_snapshot(orch) -> dict:
    """Mirror AutonomyCoordinator.loop()'s own night-window read (read-only)."""
    enabled = bool(orch.get_setting("autonomy.night_shift", False))
    start = int(orch.get_setting("autonomy.night_start", 23) or 23)
    end = int(orch.get_setting("autonomy.night_end", 6) or 6)
    active = enabled and is_night_window(time.localtime().tm_hour, start, end)
    return {"enabled": enabled, "start": start, "end": end, "active": active}


def _heartbeat_snapshot(orch) -> dict:
    try:
        status = orch.heartbeat_scheduler.get_status()
    except Exception:
        logger.debug("heartbeat snapshot failed", exc_info=True)
        return {"scheduler_running": False, "count": 0}
    heartbeats = status.get("heartbeats") or []
    return {"scheduler_running": bool(status.get("scheduler_running")), "count": len(heartbeats)}


class RuntimeCoordinator:
    """Owns the headless boot + the cycle-recorder loop. One instance per process."""

    def __init__(
        self,
        *,
        log_path=None,
        state_store: RuntimeStateStore | None = None,
        cycle_floor_seconds: float = 15.0,
    ):
        self.log_path = default_log_path() if log_path is None else log_path
        self.state_store = state_store or RuntimeStateStore()
        self.cycle_floor_seconds = cycle_floor_seconds
        self.orch = None
        self._stop = asyncio.Event()
        self._prev_stats: dict[str, int] = {}
        self.boot_id = 0
        self.pid = os.getpid()

    async def boot(self):
        """Boot the same Orchestrator agents/web.py uses, minus HTTP/channels.

        Mirrors ``agents/web.py``'s ``lifespan`` (config -> Orchestrator -> load_agents)
        and ``Orchestrator.start_channels()``'s autonomy/heartbeat wiring, without the
        FastAPI app, gateway, or channel adapters — this process serves no HTTP surface.
        """
        from agents.core.config import JarvisConfig
        from agents.core.orchestrator import Orchestrator

        try:
            from core.boot_guards import enforce_boot_posture

            enforce_boot_posture()
        except Exception:
            logger.debug("boot posture guard unavailable/no-op in this entrypoint")
        from agents.core.paths import ensure_user_home

        ensure_user_home()

        config = JarvisConfig()
        orch = Orchestrator(config)
        await orch.load_agents()
        orch.checkpoints.create_session_record(
            orch.session_id,
            agent_id="orchestrator",
            metadata={"source": "runtime_coordinator", "agents": len(orch.agents)},
        )
        orch.heartbeat_scheduler.start(orch)
        orch._autonomy.wire()
        orch._autonomy_task = asyncio.create_task(orch._autonomy.loop())
        self.orch = orch

        state = self.state_store.load()
        self.boot_id = int(state.get("boot_id", 0)) + 1
        state["boot_id"] = self.boot_id
        self.state_store.save(state)
        logger.info("Always-On runtime coordinator booted (boot_id=%s, pid=%s)", self.boot_id, self.pid)
        return orch

    def _autonomy_tick_interval(self) -> float:
        try:
            return max(self.cycle_floor_seconds, float(self.orch.get_setting("system.autonomy_tick", 60) or 60))
        except (TypeError, ValueError):
            return max(self.cycle_floor_seconds, 60.0)

    def _snapshot_and_classify(self) -> tuple[dict, dict, str]:
        """One read-only cycle sample. Never raises — an error is its own status."""
        try:
            stats = dict(self.orch.autonomy_queue.stats())
        except Exception:
            logger.warning("runtime cycle: queue snapshot failed", exc_info=True)
            return {}, {}, "error"
        prev = self._prev_stats
        done_delta = max(0, int(stats.get("done", 0)) - int(prev.get("done", 0)))
        failed_delta = max(0, int(stats.get("failed", 0)) - int(prev.get("failed", 0)))
        self._prev_stats = stats
        worker = {"done_delta": done_delta, "failed_delta": failed_delta}
        status = "degraded" if failed_delta else "clean"
        return stats, worker, status

    async def _run_cycle(self, cycle: int) -> dict:
        queue_stats, worker, status = self._snapshot_and_classify()
        record = {
            "phase": "cycle",
            "ts": utc_now_iso(),
            "cycle": cycle,
            "boot_id": self.boot_id,
            "pid": self.pid,
            "status": status,
            "worker": worker,
            "queue": queue_stats,
            "night_shift": _night_shift_snapshot(self.orch),
            "heartbeats": _heartbeat_snapshot(self.orch),
        }
        append_record(self.log_path, record)
        state = self.state_store.load()
        state["cycle"] = cycle
        state["last_cycle_ts"] = record["ts"]
        state["last_status"] = status
        state["consecutive_clean"] = (
            int(state.get("consecutive_clean", 0)) + 1 if status == "clean" else 0
        )
        state["boot_id"] = self.boot_id
        self.state_store.save(state)
        return record

    async def run_forever(self) -> None:
        """The cycle-recorder loop. Runs until ``stop()`` is called or cancelled."""
        state = self.state_store.load()
        cycle = int(state.get("cycle", 0))
        while not self._stop.is_set():
            interval = self._autonomy_tick_interval()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break  # stop() was called during the sleep
            except TimeoutError:
                pass
            cycle += 1
            try:
                await self._run_cycle(cycle)
            except Exception:
                logger.warning("runtime cycle #%s failed", cycle, exc_info=True)

    def stop(self) -> None:
        self._stop.set()


async def main() -> None:
    from agents.core.log import setup_logging

    setup_logging()
    coordinator = RuntimeCoordinator()
    await coordinator.boot()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            # Suppressed: platforms without signal handlers in the event loop (e.g. Windows).
            loop.add_signal_handler(sig, coordinator.stop)

    append_record(
        coordinator.log_path,
        {"phase": "supervisor", "event": "coordinator_boot", "boot_id": coordinator.boot_id, "pid": coordinator.pid},
    )
    try:
        await coordinator.run_forever()
    finally:
        append_record(
            coordinator.log_path,
            {"phase": "shutdown", "boot_id": coordinator.boot_id, "pid": coordinator.pid},
        )


if __name__ == "__main__":
    asyncio.run(main())
