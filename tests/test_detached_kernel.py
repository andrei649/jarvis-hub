"""Real mailbox worker tests; local interpreter is explicitly NOT isolation proof."""
import asyncio
import sys
from types import SimpleNamespace

import pytest

from agents.core import session_kernels as sk


def local_backend(tmp_path):
    from agents.core.detached_kernel import MAILBOX_ROOT, DetachedDockerBackend

    class LocalCLI(DetachedDockerBackend):
        async def _command(self, argv, *, data=None):
            if argv[1] == 'run':
                source = argv[-1].replace(MAILBOX_ROOT, str(tmp_path / 'box'))
                self.worker = await asyncio.create_subprocess_exec(sys.executable, '-c', source)
                return b'container\n'
            if argv[1] == 'rm':
                if self.worker.returncode is None:
                    self.worker.kill()
                await self.worker.wait()
                import shutil
                shutil.rmtree(tmp_path / 'box', ignore_errors=True)
                return b''
            if argv[1] == 'inspect':
                return b'true\n' if self.worker.returncode is None else b'false\n'
            assert argv[:3] == ['docker', 'exec', '-i']
            proc = await asyncio.create_subprocess_exec(sys.executable, '-c',
                argv[-1].replace(MAILBOX_ROOT, str(tmp_path / 'box')),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
            try:
                out, _ = await proc.communicate(data)
                if proc.returncode:
                    raise sk.KernelRefused(sk.CRASHED)
                return out
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()

    return LocalCLI('python@sha256:' + 'a' * 64)


@pytest.mark.asyncio
async def test_detached_transport_preserves_state_over_completed_cli_calls(tmp_path):
    backend = local_backend(tmp_path)
    manager = sk.SessionKernelManager(backend)
    inv = SimpleNamespace(agent='a', principal='p', session_id='s', data_scope=None, expired=lambda: False)
    try:
        first = await manager.run(inv, 'import math\nrows = [math.pi] * 3')
        second = await manager.run(inv, 'print(round(sum(rows), 3))')
        assert first.ok and second.ok
        assert '9.425' in second.stdout
        assert second.continuity == sk.CONTINUED
        await manager.reset(inv)
        third = await manager.run(inv, "print('rows' in globals())")
        assert third.state_lost and 'False' in third.stdout
    finally:
        await manager.shutdown()

@pytest.mark.parametrize('kind', ['symlink', 'oversized', 'root_symlink'])
def test_mailbox_rejects_unsafe_packets(tmp_path, kind):
    from agents.core.detached_kernel import MAILBOX_IO, MAILBOX_ROOT
    box = tmp_path / 'box'
    box.mkdir()
    outside = tmp_path / 'secret'
    outside.write_text('private')
    if kind == 'symlink':
        (box / 'response').symlink_to(outside)
    elif kind == 'oversized':
        (box / 'response').write_bytes(b'x' * 262145)
    else:
        target = tmp_path / 'target'
        target.mkdir()
        (target / 'response').write_text('forged')
        box.rmdir()
        box.symlink_to(target, target_is_directory=True)
    namespace = {}
    exec(MAILBOX_IO.replace(MAILBOX_ROOT, str(box)), namespace)
    with pytest.raises((OSError, ValueError)):
        namespace['read_packet']('response')
    assert outside.read_text() == 'private'

@pytest.mark.asyncio
async def test_stale_cell_frame_is_rejected():
    import json
    backend = sk.PipeKernelBackend(lambda *a: [])
    reader = asyncio.StreamReader()
    body = json.dumps({'ok': True, 'cell_id': 'old'}).encode()
    reader.feed_data(b'token ' + str(len(body)).encode() + b'\n' + body)
    reader.feed_eof()
    with pytest.raises(sk.KernelRefused):
        await backend._read_reply(SimpleNamespace(stdout=reader), 'token', cell_id='current')

@pytest.mark.asyncio
@pytest.mark.parametrize('end', ['cancel', 'timeout', 'kill'])
async def test_detached_worker_loss_is_reported_before_reuse(tmp_path, end):
    backend = local_backend(tmp_path)
    manager = sk.SessionKernelManager(backend, cell_timeout_seconds=.3 if end == 'timeout' else 10)
    inv = SimpleNamespace(agent='a', principal='p', session_id='s', data_scope=None, expired=lambda: False)
    try:
        assert (await manager.run(inv, 'marker = 1')).ok
        if end == 'kill':
            backend.worker.kill()
            await backend.worker.wait()
        else:
            task = asyncio.create_task(manager.run(inv, 'import time\ntime.sleep(20)'))
            if end == 'cancel':
                await asyncio.sleep(.1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                assert (await task).reason == sk.TIMED_OUT
        result = await manager.run(inv, "print('marker' in globals())")
        assert result.state_lost and 'False' in result.stdout
    finally:
        await manager.shutdown()

@pytest.mark.asyncio
async def test_detached_stream_and_current_broker(tmp_path):
    from agents.core.environments.output_limits import StreamSinks
    from agents.core.tool_rpc_runtime import ToolCallBroker
    from tests.test_session_kernels import _bind, _server
    backend = local_backend(tmp_path)
    # The local worker sees the host mount path, unlike production Docker.
    backend._child_root = None
    manager = sk.SessionKernelManager(backend, rpc_root=str(tmp_path / 'rpc'))
    server = _server()
    invocation = _bind(server)
    chunks = []
    try:
        first = await manager.run(invocation, 'saved = jarvis_tool_call',
            broker=ToolCallBroker(server, invocation))
        result = await manager.run(invocation, "print('a' * 60000 + 'MIDDLE' + 'z' * 60000)\nprint(saved('echo', {'value':'new'}))",
            broker=ToolCallBroker(server, invocation), sinks=StreamSinks(stdout=chunks.append))
        assert first.ok and result.ok
        assert b'MIDDLE' in b''.join(chunks)
        assert "'echo': 'new'" in result.stdout
    finally:
        await manager.shutdown()

@pytest.mark.asyncio
@pytest.mark.parametrize('frame', [b'token 999999999\n', b'token 4\nnope', b'token 4\n{}'])
async def test_invalid_frames_fail_closed(frame):
    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()
    backend = sk.PipeKernelBackend(lambda *args: [])
    with pytest.raises((sk.KernelRefused, asyncio.IncompleteReadError)):
        await backend._read_reply(SimpleNamespace(stdout=reader), 'token')

def test_detached_container_disables_unbounded_daemon_logs():
    from agents.core.detached_kernel import DetachedDockerBackend
    backend = DetachedDockerBackend('python@sha256:' + 'a' * 64)
    argv = backend.launch_argv(sk.KernelKey('a', 'p', 's', '*'), 'token')
    assert argv[argv.index('--log-driver') + 1] == 'none'
    assert argv[argv.index('--network') + 1] == 'none'
    assert '--read-only' in argv and '-d' in argv and '-i' not in argv
    assert argv[argv.index('--memory') + 1] == '256m'

@pytest.mark.asyncio
async def test_idle_status_liveness_updates_without_a_new_cell(tmp_path):
    backend = local_backend(tmp_path)
    manager = sk.SessionKernelManager(backend)
    invocation = SimpleNamespace(agent='a', principal='p', session_id='s', data_scope=None, expired=lambda: False)
    try:
        assert (await manager.run(invocation, 'marker = 1')).ok
        backend.worker.kill()
        await backend.worker.wait()
        await asyncio.sleep(2.2)
        assert manager.status()[0]['alive'] is False
    finally:
        await manager.shutdown()

@pytest.mark.asyncio
async def test_malformed_terminal_payload_is_refused():
    import json
    reader = asyncio.StreamReader()
    body = json.dumps({'ok': True, 'cell_id': 'cell', 'tool_calls': {}}).encode()
    reader.feed_data(b'token ' + str(len(body)).encode() + b'\n' + body)
    reader.feed_eof()
    backend = sk.PipeKernelBackend(lambda *args: [])
    with pytest.raises(sk.KernelRefused):
        await backend._read_reply(SimpleNamespace(stdout=reader), 'token', cell_id='cell')
