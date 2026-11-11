"""H484 — third review round.

Two defects in the store-as-truth sync, each on the real settings store:

* the coordinator took the blocking write lock on the event-loop thread, so the hub
  (HTTP, channels, the e-stop route) froze while a writer waited on the store;
* a store that could no longer be read was answered from the process's last good
  value, so the hub kept running ``auto`` against a stored ``off`` it had never seen
  and the "unknown reads as the stricter side" path was unreachable.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import autonomy_coordinator, estop, settings_db
from agents.core.autonomy import mode as mode_module
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget
from tests.test_h484_review2 import boot, store  # noqa: F401  (fixtures)


def _corrupt(db) -> None:
    """A disk fault or a truncated copy: the file and its journal are no database."""
    for path in (db.DB_PATH, Path(f"{db.DB_PATH}-wal"), Path(f"{db.DB_PATH}-shm")):
        if path.exists():
            path.write_bytes(b"not a database" * 100)


async def test_an_unreadable_store_is_unknown_not_the_last_value_the_hub_saw(boot, store):  # noqa: F811
    orch = boot(mode="auto")
    coordinator = autonomy_coordinator.AutonomyCoordinator(orch)
    assert coordinator._sync_approval_mode() == "auto"

    # Another process tightened the dial; the hub has not ticked since. Then the store
    # becomes unreadable.
    store.put_category("autonomy", {"mode": "off"})
    _corrupt(store)

    with pytest.raises(Exception):  # noqa: B017 — whatever the store raises, it must raise
        mode_module.sync_policy(orch)
    assert coordinator._sync_approval_mode() == "unknown"      # the tick runs nothing proactive
    assert orch.autonomy.policy.mode == "auto"                 # and the policy is left as it was


async def test_the_coordinator_never_waits_for_the_write_lock_on_the_event_loop(tmp_path, monkeypatch):
    queue = TaskQueue(db_path=str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(mode="auto"), budget=InterruptBudget(per_day=4))
    orch = SimpleNamespace(
        autonomy=worker, autonomy_queue=queue, observer=None, event_watcher=None,
        reflector=None, curator=None, cognition=None, ingestion_watcher=None,
        get_setting=lambda key, default=None: {"system.error_backlog_sync_enabled": False}.get(key, default))
    synced = []
    monkeypatch.setattr(mode_module, "stored_values", lambda read=None: synced.append(1) or ("auto", {}))
    monkeypatch.setattr(mode_module, "_assert_readable", lambda: None, raising=False)
    monkeypatch.setattr(autonomy_coordinator, "autonomy_tick_seconds", lambda orch: 0.01)
    monkeypatch.setattr(estop, "check_paused", lambda *a, **k: True)   # the tick stops after the sync

    held, gate = threading.Event(), threading.Lock()
    gate.acquire()

    def writer():                       # a writer stuck on the store while it holds the lock
        with mode_module._write_lock:
            held.set()
            gate.acquire(timeout=10)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    assert held.wait(2)

    loop = asyncio.create_task(autonomy_coordinator.AutonomyCoordinator(orch).loop())
    worst, last = 0.0, time.monotonic()
    try:
        for _ in range(60):             # 0.6 s of heartbeats while the lock is held
            await asyncio.sleep(0.01)
            now = time.monotonic()
            worst, last = max(worst, now - last), now
        assert worst < 0.25, f"the event loop stalled {worst:.2f}s behind the write lock"
        assert synced == []             # the sync is waiting for the lock, off the loop ...
        gate.release()
        for _ in range(200):
            if synced:
                break
            await asyncio.sleep(0.01)
        assert synced                   # ... and goes through once the writer is done
    finally:
        if gate.locked() and not synced:
            gate.release()
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
        thread.join(2)
        queue.close()


def test_the_cli_names_the_autonomy_tick_for_the_dial():
    from agents.cli import nerva

    # The dial is picked up on the coordinator's tick, not the 30 s settings reload.
    for key in ("mode", "agent_modes"):
        assert "autonomy tick" in nerva._when_applied("autonomy", key, {"kind": "select"})
    assert "30 s" in nerva._when_applied("autonomy", "interrupt_budget", {"kind": "int"})
