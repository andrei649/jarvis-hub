"""Resident Docker worker over bounded, run-to-completion CLI operations.

No generic remote argv: this adapter owns its image, commands and mailbox path.
The mailbox lives in the container's size-limited tmpfs, never on the host. Tool
RPC retains its separate governed mount. SSH/Modal need isolated provisioning and
are deliberately not represented by this Docker implementation.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import secrets
from dataclasses import dataclass

from .session_kernels import (
    CHILD_RPC_ROOT,
    CRASHED,
    KERNEL_UNAVAILABLE,
    TIMED_OUT,
    WORKER_SOURCE,
    KernelKey,
    KernelRefused,
    KernelTeardownUnconfirmed,
    PipeKernelBackend,
    docker_kernel_argv,
)

# nosec B108 — private size-limited container tmpfs; never a host path.
MAILBOX_ROOT = '/tmp/nerva-kernel'  # noqa: S108
MAX_PACKET = 262144

# Shared by the worker and the fixed exec helpers. Refuse links, non-regular files
# and oversized packets before reading. Creation never follows or replaces a link.
MAILBOX_IO = r'''
import os, stat, time
ROOT = "/tmp/nerva-kernel"
LIMIT = 262144

def open_root():
    return os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

def read_packet(name):
    root = open_root()
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
                raise ValueError("invalid packet")
            data = f.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise ValueError("oversized packet")
        os.unlink(name, dir_fd=root)
        return data
    finally:
        os.close(root)

def write_packet(name, data):
    if len(data) > LIMIT:
        raise ValueError("oversized packet")
    root = open_root()
    try:
        fd = os.open(name + ".part", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # A pre-existing name is a protocol failure, never an overwrite.
        os.link(name + ".part", name, src_dir_fd=root, dst_dir_fd=root, follow_symlinks=False)
        os.unlink(name + ".part", dir_fd=root)
    finally:
        os.close(root)

'''

DETACHED_WORKER_SOURCE = MAILBOX_IO + r'''
import sys
os.mkdir(ROOT, 0o700)
class MailInput:
    def readline(self):
        while True:
            packet = read_packet("request")
            if packet is not None:
                return packet.decode("utf-8")
            time.sleep(0.01)
    def __iter__(self):
        return self
    def __next__(self):
        return self.readline()
class MailOutput:
    def write(self, text):
        write_packet("response", text.encode("utf-8"))
        while os.path.lexists(ROOT + "/response"):
            time.sleep(0.01)
        return len(text)
    def flush(self):
        pass
sys.stdin, sys.stdout = MailInput(), MailOutput()
''' + WORKER_SOURCE

WRITE_REQUEST = MAILBOX_IO + '\nimport sys\nfor _ in range(200):\n    if os.path.lexists(ROOT): break\n    time.sleep(.01)\nwrite_packet("request", sys.stdin.buffer.read(LIMIT + 1))\n'
READ_RESPONSE = MAILBOX_IO + '\nimport sys\nsys.stdout.buffer.write(read_packet("response") or b"")\n'


@dataclass(slots=True)
class _DetachedHandle:
    name: str
    token: str
    child_rpc_dir: str = ''
    running: bool = True
    monitor: asyncio.Task | None = None


class _MailboxReader:
    def __init__(self, backend, handle):
        self.backend, self.handle = backend, handle
        self.buffer = b''

    async def readline(self):
        while not self.buffer:
            self.buffer = await self.backend._exec(self.handle, READ_RESPONSE)
            if not self.buffer:
                if not await self.backend.probe(self.handle):
                    raise KernelRefused(CRASHED)
                await asyncio.sleep(.02)
        header, sep, self.buffer = self.buffer.partition(b'\n')
        if not sep:
            raise KernelRefused(CRASHED)
        return header + sep

    async def readexactly(self, size):
        if len(self.buffer) != size:
            raise KernelRefused(CRASHED)
        body, self.buffer = self.buffer, b''
        return body


class DetachedDockerBackend(PipeKernelBackend):
    """Cached synchronous status, explicit async probes, bounded CLI I/O."""
    def __init__(self, image: str, *, available=lambda: True):
        if not re.fullmatch(r'[^\s]+@sha256:[a-fA-F0-9]{64}', image):
            raise ValueError('session image must be pinned by digest')
        super().__init__(docker_kernel_argv(image), name='docker-detached',
                         child_root=CHILD_RPC_ROOT, available=available)

    async def _command(self, argv, *, data=None):
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=self._child_env())
        async def exchange():
            if data:
                proc.stdin.write(data)
                await proc.stdin.drain()
            proc.stdin.close()
            out = await proc.stdout.read(MAX_PACKET + 1)
            if len(out) > MAX_PACKET:
                raise KernelRefused(CRASHED)
            # read() may return before EOF; keep a strict total bound.
            while more := await proc.stdout.read(MAX_PACKET + 1 - len(out)):
                out += more
                if len(out) > MAX_PACKET:
                    raise KernelRefused(CRASHED)
            if await proc.wait():
                raise KernelRefused(CRASHED)
            return out
        try:
            return await asyncio.wait_for(exchange(), 10)
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()

    async def _exec(self, handle, source, *, data=None):
        return await self._command(['docker', 'exec', '-i', handle.name,
                                    'python', '-c', source], data=data)

    def launch_argv(self, key, token, rpc_dir=""):
        argv = list(self._argv(key, token, rpc_dir))
        argv[argv.index('-i')] = '-d'
        argv[3:3] = ['--log-driver', 'none']
        argv[-1] = DETACHED_WORKER_SOURCE
        return argv

    async def start(self, key: KernelKey, *, rpc_dir='', child_rpc_dir=''):
        if not self.available():
            raise KernelRefused(KERNEL_UNAVAILABLE)
        token = secrets.token_hex(16)
        argv = self.launch_argv(key, token, rpc_dir)
        handle = _DetachedHandle(argv[argv.index('--name') + 1], token, child_rpc_dir)
        try:
            await self._command(argv)
            await self._exec(handle, WRITE_REQUEST, data=(json.dumps({
                'token': token, 'max_output': self._max_output_bytes,
                'rpc_timeout': self._rpc_timeout}) + '\n').encode())
            ready = await asyncio.wait_for(self._reply(handle), 10)
            if not ready.get('ready'):
                raise KernelRefused(KERNEL_UNAVAILABLE)
            handle.monitor = asyncio.create_task(self._watch(handle))
            return handle
        except BaseException as failure:
            try:
                await self.stop(handle)
            except Exception:
                raise KernelTeardownUnconfirmed(handle,
                    cancelled=isinstance(failure, asyncio.CancelledError)) from None
            if isinstance(failure, asyncio.CancelledError):
                raise
            raise KernelRefused(KERNEL_UNAVAILABLE) from None

    async def _watch(self, handle):
        # Status endpoints remain synchronous and cheap; only this asynchronous
        # monitor and dispatch-time probes talk to Docker. No thread blocks the UI.
        while handle.running:
            await asyncio.sleep(1)
            if not await self.probe(handle):
                return

    def alive(self, handle):
        return handle is not None and handle.running

    async def probe(self, handle):
        if not self.alive(handle):
            return False
        try:
            out = await self._command(['docker', 'inspect', '--format',
                                      '{{.State.Running}}', handle.name])
            handle.running = out.strip() == b'true'
        except Exception:
            handle.running = False
        return handle.running

    async def _reply(self, handle, sinks=None, cell_id=""):
        from types import SimpleNamespace
        return await self._read_reply(SimpleNamespace(stdout=_MailboxReader(self, handle)),
                                      handle.token, sinks=sinks, cell_id=cell_id)

    async def run_cell(self, handle, cell, *, timeout, rpc_dir='', max_tool_calls=0, sinks=None):
        cell_id = secrets.token_hex(16)
        async def exchange():
            await self._exec(handle, WRITE_REQUEST, data=(json.dumps({
                'cell': cell, 'cell_id': cell_id, 'rpc_dir': rpc_dir, 'max_calls': max_tool_calls},
                ensure_ascii=False) + '\n').encode())
            return await self._reply(handle, sinks, cell_id)
        try:
            return await asyncio.wait_for(exchange(), timeout)
        except TimeoutError:
            raise KernelRefused(TIMED_OUT) from None
        except (OSError, ValueError):
            raise KernelRefused(CRASHED) from None

    async def stop(self, handle):
        if handle.monitor is not None:
            handle.monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await handle.monitor
        try:
            await self._command(['docker', 'rm', '-f', handle.name])
        except Exception:
            # An inspect failure cannot distinguish absence from an unreachable
            # daemon. A successful exact-name listing can establish absence.
            try:
                remaining = await self._command(['docker', 'ps', '-a', '--filter',
                    f'name=^/{handle.name}$', '--format', '{{.Names}}'])
                if remaining.strip():
                    raise KernelTeardownUnconfirmed(handle)
            except Exception:
                raise KernelTeardownUnconfirmed(handle) from None
        handle.running = False
