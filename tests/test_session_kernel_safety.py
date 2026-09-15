"""Regressions from independent H660 review; local workers are not isolation proof."""
import asyncio
from types import SimpleNamespace

import pytest

from agents.core import session_kernels as sk
from tests.test_code_tools import _session_tool
from tests.test_detached_kernel import local_backend
from tests.test_session_kernels import _bind, _server


@pytest.mark.asyncio
async def test_stop_during_startup_blocks_fallback_execution(tmp_path):
    _, tool = _session_tool(tmp_path)
    stopped = False
    tool._kernels._estop = lambda: stopped
    async def unavailable(*args, **kwargs):
        nonlocal stopped
        stopped = True
        raise sk.KernelRefused(sk.KERNEL_UNAVAILABLE)
    tool._kernels._backend.start = unavailable
    result = await tool.execute({'code': "print('EXECUTED_AFTER_ESTOP')"})
    assert not result['ok'] and result['reason'] == sk.ESTOP_ENGAGED
    assert 'EXECUTED_AFTER_ESTOP' not in result.get('stdout', '')
    assert 'fallback_reason' not in result


@pytest.mark.asyncio
async def test_expiry_during_startup_cannot_advertise_safe_fallback(tmp_path):
    backend = local_backend(tmp_path)
    expired = False
    invocation = SimpleNamespace(agent='a', principal='p', session_id='s', data_scope=None,
                                 expired=lambda: expired)
    manager = sk.SessionKernelManager(backend)
    async def unavailable(*args, **kwargs):
        nonlocal expired
        expired = True
        raise sk.KernelRefused(sk.KERNEL_UNAVAILABLE)
    backend.start = unavailable
    result = await manager.run(invocation, 'print(1)')
    assert not result.fallback_safe
    assert result.reason == sk.AUTHORITY_EXPIRED


@pytest.mark.asyncio
async def test_failed_remove_quarantines_worker_until_confirmed_reset(tmp_path):
    backend = local_backend(tmp_path)
    manager = sk.SessionKernelManager(backend)
    invocation = _bind(_server())
    original = backend._command
    try:
        assert (await manager.run(invocation, 'marker = 1')).ok
        worker = backend.worker
        async def unavailable(argv, *, data=None):
            if argv[1] in {'rm', 'ps'}:
                raise sk.KernelRefused(sk.CRASHED)
            return await original(argv, data=data)
        backend._command = unavailable
        assert await manager.reset(invocation) is False
        row = manager.status()[0]
        assert row['quarantined'] and row['reason'] == 'teardown_unconfirmed'
        assert worker.returncode is None
        result = await manager.run(invocation, "print('SHOULD_NOT_EXECUTE')")
        assert not result.ok and result.reason == 'teardown_unconfirmed'
        assert backend.worker is worker
        assert await manager.close_session(invocation.session_id) == 0
        assert await manager.shutdown() == 0
        backend._command = original
        assert await manager.reset(invocation)
        assert manager.status() == [] and worker.returncode is not None
        result = await manager.run(invocation, "print('marker' in globals())")
        assert result.ok and result.state_lost and 'False' in result.stdout
    finally:
        backend._command = original
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize('label', ['[]', '{}'])
async def test_unhashable_stream_label_destroys_worker(tmp_path, label):
    backend = local_backend(tmp_path)
    manager = sk.SessionKernelManager(backend)
    try:
        result = await manager.run(_bind(_server()),
            "jarvis_tool_call.__globals__['reply']({'stream': " + label + ", 'text': ''})")
        assert not result.ok and result.reason == sk.CRASHED
        assert manager.status() == [] and backend.worker.returncode is not None
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize('trigger', ['stop', 'timeout'])
async def test_blocked_broker_does_not_block_cell_stop_or_deadline(tmp_path, trigger):
    backend = local_backend(tmp_path)
    backend._child_root = None
    stopped = False
    manager = sk.SessionKernelManager(backend, rpc_root=str(tmp_path / 'rpc'),
        estop=lambda: stopped, cell_timeout_seconds=.6)
    started, cancelled = asyncio.Event(), asyncio.Event()
    class Broker:
        async def call(self, tool, args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    task = asyncio.create_task(manager.run(_bind(_server()),
        "jarvis_tool_call('echo', {})", broker=Broker()))
    try:
        await asyncio.wait_for(started.wait(), 3)
        stopped = trigger == 'stop'
        result = await asyncio.wait_for(task, 2)
        assert result.reason == (sk.STOPPED if stopped else sk.TIMED_OUT)
        assert cancelled.is_set()
        assert manager.status() == [] and backend.worker.returncode is not None
    finally:
        if not task.done():
            task.cancel()
        await manager.shutdown()

@pytest.mark.asyncio
async def test_fallback_rechecks_stop_at_sandbox_dispatch(tmp_path):
    _, tool = _session_tool(tmp_path)
    stopped = False
    tool._kernels._estop = lambda: stopped
    async def unavailable(*args, **kwargs):
        raise sk.KernelRefused(sk.KERNEL_UNAVAILABLE)
    tool._kernels._backend.start = unavailable
    original = tool._oneshot
    async def queued(*args, **kwargs):
        nonlocal stopped
        stopped = True
        return await original(*args, **kwargs)
    tool._oneshot = queued
    result = await tool.execute({'code': "print('DISPATCHED_AFTER_STOP')"})
    assert not result['ok'] and result['reason'] == sk.ESTOP_ENGAGED
    assert 'DISPATCHED_AFTER_STOP' not in result.get('stdout', '')


@pytest.mark.asyncio
async def test_startup_with_unconfirmed_cleanup_remains_quarantined(tmp_path):
    backend = local_backend(tmp_path)
    manager = sk.SessionKernelManager(backend)
    invocation = _bind(_server())
    original = backend._command
    async def unavailable(argv, *, data=None):
        if argv[1] in {'exec', 'rm', 'ps'}:
            raise sk.KernelRefused(sk.CRASHED)
        return await original(argv, data=data)
    backend._command = unavailable
    try:
        result = await manager.run(invocation, 'marker = 1')
        assert not result.fallback_safe and result.reason == 'teardown_unconfirmed'
        assert manager.status()[0]['quarantined']
        worker = backend.worker
        assert not (await manager.run(invocation, 'print(1)')).ok
        assert backend.worker is worker
    finally:
        backend._command = original
        await manager.shutdown()


@pytest.mark.asyncio
async def test_cancel_resistant_broker_cannot_delay_teardown_or_write_late_reply(tmp_path):
    backend = local_backend(tmp_path)
    backend._child_root = None
    manager = sk.SessionKernelManager(backend, rpc_root=str(tmp_path / 'rpc'), cell_timeout_seconds=.6)
    started, cancelled, release, finished = [asyncio.Event() for _ in range(4)]
    class Broker:
        async def call(self, tool, args):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            finally:
                finished.set()
            return {'ok': True, 'late': True}
    task = asyncio.create_task(manager.run(_bind(_server()),
        "jarvis_tool_call('echo', {})", broker=Broker()))
    try:
        await asyncio.wait_for(started.wait(), 3)
        result = await asyncio.wait_for(task, 2)
        assert result.reason == sk.TIMED_OUT
        assert cancelled.is_set() and not finished.is_set()
        assert manager.status() == [] and backend.worker.returncode is not None
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
        await asyncio.sleep(.05)
        assert not list((tmp_path / 'rpc').rglob('res_*.json'))
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await manager.shutdown()

@pytest.mark.asyncio
async def test_old_cell_failure_after_reset_cannot_destroy_replacement(tmp_path):
    from tests.test_session_kernels import _manager
    manager = _manager(tmp_path)
    invocation = _bind(_server())
    assert (await manager.run(invocation, 'old = 1')).ok
    original = manager._backend.run_cell
    waiting, release = asyncio.Event(), asyncio.Event()
    async def delayed_failure(*args, **kwargs):
        try:
            return await original(*args, **kwargs)
        except sk.KernelRefused:
            waiting.set()
            await release.wait()
            raise
    manager._backend.run_cell = delayed_failure
    old = asyncio.create_task(manager.run(invocation, 'import time\ntime.sleep(30)'))
    try:
        await asyncio.sleep(.1)
        assert await manager.reset(invocation)
        waiter = asyncio.create_task(waiting.wait())
        await asyncio.wait([waiter, old], timeout=3, return_when=asyncio.FIRST_COMPLETED)
        waiter.cancel()
        assert (await manager.run(invocation, 'replacement = 42')).ok
        release.set()
        await old
        result = await manager.run(invocation, 'print(replacement)')
        assert result.ok and '42' in result.stdout
    finally:
        release.set()
        if not old.done():
            old.cancel()
        await manager.shutdown()

@pytest.mark.asyncio
async def test_confirmed_daemon_absence_releases_quarantine(tmp_path):
    backend = local_backend(tmp_path)
    manager = sk.SessionKernelManager(backend)
    invocation = _bind(_server())
    original = backend._command
    try:
        assert (await manager.run(invocation, 'marker = 1')).ok
        backend.worker.kill()
        await backend.worker.wait()
        async def absent(argv, *, data=None):
            if argv[1] == 'rm':
                raise sk.KernelRefused(sk.CRASHED)
            if argv[1] == 'ps':
                assert argv[2:4] == ['-a', '--filter']
                assert argv[4].startswith('name=^/nerva-kernel-') and argv[4].endswith('$')
                return b''
            return await original(argv, data=data)
        backend._command = absent
        assert await manager.reset(invocation)
        assert manager.status() == []
    finally:
        backend._command = original
        await manager.shutdown()
