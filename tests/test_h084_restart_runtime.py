"""Ephemeral restart admission counts only owned live work."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from agents.core.restart_runtime import runtime_for


def test_exact_owner_token_and_control_admission():
    first, second = SimpleNamespace(), SimpleNamespace()
    runtime = runtime_for(first)
    assert runtime_for(first) is runtime
    other = runtime_for(second)
    running = runtime.acquire("job")
    assert running is not None
    token = runtime.close_admission()
    assert token is not None and runtime.close_admission() is None
    assert runtime.acquire("job") is None
    assert runtime.snapshot()["by_kind"]["job"] == 1
    control = runtime.acquire_control()
    assert runtime.snapshot()["by_kind"]["control"] == 1
    control.release()
    control.release()
    assert not other.reopen(token)
    assert runtime.snapshot()["accepting"] is False
    running.release()
    assert runtime.reopen(token)
    assert runtime.snapshot()["accepting"] is True
    assert not runtime.reopen(token)


@pytest.mark.asyncio
async def test_only_explicit_same_task_live_binding_can_reenter():
    runtime = runtime_for(SimpleNamespace())
    parent = runtime.acquire("turn")
    assert parent is not None
    with parent.bind():
        token = runtime.close_admission()
        nested = runtime.acquire("job", allow_reentrant=True)
        assert nested is not None

        async def inherited_context():
            return runtime.acquire("job", allow_reentrant=True)

        assert await asyncio.create_task(inherited_context()) is None
        nested.release()
    parent.release()
    assert runtime.acquire("job", allow_reentrant=True) is None
    assert runtime.reopen(token)


@pytest.mark.asyncio
async def test_trusted_child_wrapper_rebinds_only_a_live_parent():
    runtime = runtime_for(SimpleNamespace())
    parent = runtime.acquire("turn")
    assert parent is not None

    async def child():
        nested = runtime.acquire("job", allow_reentrant=True)
        if nested is not None:
            nested.release()
        return nested is not None

    with parent.bind():
        token = runtime.close_admission()
        wrapped = runtime.bind_child_operation(child())
        assert await asyncio.create_task(wrapped) is True
        assert await asyncio.create_task(child()) is False
        late = runtime.bind_child_operation(child())
    parent.release()
    with pytest.raises(RuntimeError):
        await asyncio.create_task(late)
    assert runtime.reopen(token)


def test_other_thread_cannot_inherit_live_binding():
    runtime = runtime_for(SimpleNamespace())
    lease = runtime.acquire("turn")
    assert lease is not None
    with lease.bind():
        token = runtime.close_admission()
        answer = []

        def other_thread():
            answer.append(runtime.acquire("job", allow_reentrant=True))

        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()
        assert answer == [None]
    lease.release()
    assert runtime.reopen(token)


@pytest.mark.asyncio
async def test_wait_idle_keeps_owned_gate_closed_on_success():
    runtime = runtime_for(SimpleNamespace())
    lease = runtime.acquire("job")
    assert lease is not None
    token = runtime.close_admission()
    waiter = asyncio.create_task(runtime.wait_idle(token, 1, extra_probe=lambda: False))
    await asyncio.sleep(0)
    assert not waiter.done()
    lease.release()
    assert await waiter is True
    assert runtime.snapshot()["accepting"] is False
    assert runtime.reopen(token)


@pytest.mark.asyncio
async def test_timeout_unknown_and_cancel_reopen_only_owned_token():
    runtime = runtime_for(SimpleNamespace())
    lease = runtime.acquire("job")
    token = runtime.close_admission()
    assert await runtime.wait_idle(token, 0.01) is False
    assert runtime.snapshot()["accepting"] is True
    lease.release()
    token = runtime.close_admission()
    assert await runtime.wait_idle(token, 0.1, extra_probe=lambda: None) is False
    assert runtime.snapshot()["accepting"] is True
    token = runtime.close_admission()

    async def pending_probe():
        await asyncio.Event().wait()

    waiter = asyncio.create_task(runtime.wait_idle(token, 10, extra_probe=pending_probe))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert runtime.snapshot()["accepting"] is True
