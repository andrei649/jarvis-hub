"""Shutdown must actually stop the workers and release the handles.

Four things outlived `stop_channels()` / `aclose()`:

* the autonomy worker task — created in `start_channels()` and never cancelled,
* the learning loop — created as a bare local and dropped, so nothing *could*
  cancel it,
* the settings watcher — cancelled, but never awaited, so `stop_channels()`
  returned while it was still mid-iteration,
* the AuditLogger and CheckpointManager sqlite connections — both classes have
  had a `close()` all along; shutdown simply never called either.

None of this is tidiness. A worker still running after shutdown writes to a
database the forget/purge path is about to wipe, and an open sqlite handle makes
the enclosing directory undeletable on Windows — which is precisely what that
path needs to do, on precisely the platform this product ships to.
"""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.orchestrator import Orchestrator

# ── _cancel_task: the primitive the fix is built on ───────────────────────────

@pytest.mark.asyncio
async def test_cancel_task_waits_for_the_loop_to_actually_stop():
    """`task.cancel()` only REQUESTS cancellation. Without the await, shutdown
    returns while the worker is still running — and then the caller wipes the
    data directory underneath it."""
    orch = Orchestrator.__new__(Orchestrator)
    stopped = asyncio.Event()

    async def worker():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(0)      # a real loop does teardown work here
            stopped.set()
            raise

    orch._worker = asyncio.create_task(worker())
    await asyncio.sleep(0)              # let it start

    await orch._cancel_task("_worker")

    assert stopped.is_set(), "returned before the worker finished stopping"
    assert orch._worker is None, "the handle must be cleared so it cannot be reused"


@pytest.mark.asyncio
async def test_cancel_task_is_a_noop_for_a_task_that_was_never_started():
    orch = Orchestrator.__new__(Orchestrator)
    orch._worker = None
    await orch._cancel_task("_worker")          # must not raise
    await orch._cancel_task("_never_set_at_all")  # nor for a missing attribute


@pytest.mark.asyncio
async def test_cancel_task_does_not_let_a_failing_worker_abort_shutdown():
    """One broken worker must not stop the rest of shutdown from running."""
    orch = Orchestrator.__new__(Orchestrator)

    async def broken():
        raise RuntimeError("worker died badly")

    orch._worker = asyncio.create_task(broken())
    await asyncio.sleep(0)
    await orch._cancel_task("_worker")   # swallowed, logged
    assert orch._worker is None


# ── stop_channels stops every long-lived loop ─────────────────────────────────

def _stub_orchestrator():
    """An orchestrator with only what stop_channels() touches."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.channel_manager = SimpleNamespace(stop_all=_noop_async)
    orch.heartbeat_scheduler = SimpleNamespace(stop=lambda: None)
    orch.plugin_manager = SimpleNamespace(close_all=_noop_async)
    orch._settings_watcher_task = None
    orch._autonomy_task = None
    orch._learning_task = None
    orch.oracle_bridge = None
    return orch


async def _noop_async(*a, **k):
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("attr", ["_settings_watcher_task", "_autonomy_task", "_learning_task"])
async def test_stop_channels_stops_every_background_loop(attr):
    """The autonomy worker and learning loop were never cancelled at all — they
    kept ticking against a hub that had closed its backends."""
    orch = _stub_orchestrator()
    ticks = 0

    async def loop():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    setattr(orch, attr, asyncio.create_task(loop()))
    await asyncio.sleep(0.03)
    assert ticks > 0, "the loop never ran, so stopping it proves nothing"

    await orch.stop_channels()

    assert getattr(orch, attr) is None
    settled = ticks
    await asyncio.sleep(0.05)
    assert ticks == settled, f"{attr} was still ticking after stop_channels()"


@pytest.mark.asyncio
async def test_stop_channels_stops_the_oracle_github_watcher():
    """It polls GitHub every 30s when enabled, and nothing stopped it."""
    orch = _stub_orchestrator()
    called = []
    orch.oracle_bridge = SimpleNamespace(
        stop_watcher=lambda: (called.append(1), _noop_async())[1])

    await orch.stop_channels()
    assert called == [1]


@pytest.mark.asyncio
async def test_stop_channels_survives_a_bridge_that_raises():
    orch = _stub_orchestrator()

    async def boom():
        raise RuntimeError("watcher stop failed")

    orch.oracle_bridge = SimpleNamespace(stop_watcher=boom)
    await orch.stop_channels()   # must not raise


# ── aclose releases the sqlite handles ────────────────────────────────────────

class _FakeStore:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _closable_orchestrator():
    """An orchestrator carrying only what the tail of aclose() touches."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._flush_checkpoint = _noop_async
    orch._cache_tasks = None
    orch.llm_router = None
    orch.mcp = None
    orch.autonomy_queue = None
    orch.context_cache = None
    # `channels` is a property that writes through to channel_manager.
    orch.channel_manager = SimpleNamespace(channels={})
    orch.audit = _FakeStore()
    orch.checkpoints = _FakeStore()
    return orch


@pytest.mark.asyncio
async def test_aclose_closes_the_audit_and_checkpoint_connections():
    """Both were opened at boot and held until process exit. On Windows an open
    sqlite handle makes the data directory undeletable — and deleting it is
    exactly what the forget/purge path has to do."""
    orch = _closable_orchestrator()
    await orch.aclose()
    assert orch.audit.closed, "audit log connection leaked past shutdown"
    assert orch.checkpoints.closed, "checkpoint store connection leaked past shutdown"


@pytest.mark.asyncio
async def test_aclose_still_closes_the_second_store_when_the_first_one_raises():
    """Shutdown is defensive throughout — one failure must not skip the rest."""
    orch = _closable_orchestrator()

    def boom():
        raise OSError("cannot close")
    orch.audit.close = boom

    await orch.aclose()
    assert orch.checkpoints.closed


@pytest.mark.asyncio
async def test_aclose_tolerates_stores_that_are_absent():
    orch = _closable_orchestrator()
    orch.audit = None
    orch.checkpoints = None
    await orch.aclose()   # must not raise


# ── the real classes do expose close(), which is what aclose now calls ────────

def test_the_real_stores_have_the_close_methods_shutdown_relies_on():
    """Guards against the fix silently becoming a no-op if either class is
    refactored — aclose() reaches `close` via getattr and would skip it."""
    from agents.core.checkpoint import CheckpointManager
    from agents.core.security.audit import AuditLogger

    assert callable(getattr(AuditLogger, "close", None))
    assert callable(getattr(CheckpointManager, "close", None))
