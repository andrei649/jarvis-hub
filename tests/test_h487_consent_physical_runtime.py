"""Consent denial reaches the actual local/SSH/Docker spawn seams."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.autonomy.consent_execution import _worker_scope
from agents.core.autonomy.consent_types import ConsentClaim
from agents.core.environments.consent_dispatch import (
    ConsentDispatchScope,
    bind_consent_dispatch,
    physical_gate,
)
from agents.core.environments.execution import GovernedTargetRunner
from agents.core.environments.local_transport import LocalHostTransport
from agents.core.environments.ssh_transport import SshHost, SshTransport
from agents.core.environments.targets import TargetRegistry, TerminalTarget
from agents.core.kernel import Decision, Verdict
from agents.core.sandbox import Sandbox


class Queue:
    def __init__(self):
        self.dispatches = 0

    def verify_consent_execution(self, task_id, claim, *, live_check):
        return live_check()

    def consent_dispatch_current(self, task_id, claim, *, live_check):
        self.dispatches += 1
        return live_check() and self.dispatches == 1


@pytest.mark.asyncio
async def test_local_scope_wrong_request_and_copy_never_spawn(tmp_path):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("spawn must remain closed")

    transport = LocalHostTransport(roots=[tmp_path], spawn=spawn)
    queue = Queue()
    claim = ConsentClaim(7, "n", "e", object())
    request = {"target": "l", "command": "echo safe"}
    scope = ConsentDispatchScope(
        7, "local", "l", ("echo", "safe"), str(tmp_path), 60,
        transport, request, lambda: True,
    )
    with _worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True):
        with bind_consent_dispatch(scope):
            result = await transport.run(["echo", "changed"], cwd=tmp_path, timeout=60)
            assert result["reason"] == "consent_dispatch_unavailable"
        assert not calls
        copied = []
        with bind_consent_dispatch(ConsentDispatchScope(
            7, "local", "l", ("echo", "safe"), str(tmp_path), 60,
            transport, request, lambda: True,
        )):
            async def other():
                copied.append(await transport.run(["echo", "safe"], cwd=tmp_path, timeout=60))
            await asyncio.create_task(other())
        assert copied[0]["reason"] == "consent_dispatch_unavailable"
    assert not calls
    assert queue.dispatches == 0


@pytest.mark.asyncio
async def test_closed_copied_scope_and_mutated_request_block_local_spawn(tmp_path):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        raise AssertionError("spawn must remain closed")

    transport = LocalHostTransport([tmp_path], spawn=spawn)
    queue = Queue()
    claim = ConsentClaim(7, "n", "e", object())
    request = {"target": "l", "command": "echo safe"}
    scope = ConsentDispatchScope(7, "local", "l", ("echo", "safe"), str(tmp_path),
                                 60, transport, request, lambda: True)
    release = asyncio.Event()
    with _worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True):
        with bind_consent_dispatch(scope):
            scope.request["command"] = "echo changed"
            refused = await transport.run(["echo", "safe"], cwd=tmp_path, timeout=60)
            assert refused["reason"] == "consent_dispatch_unavailable"

        closed = ConsentDispatchScope(7, "local", "l", ("echo", "safe"),
                                      str(tmp_path), 60, transport,
                                      {"target": "l", "command": "echo safe"}, lambda: True)
        with bind_consent_dispatch(closed):
            async def later():
                await release.wait()
                return await transport.run(["echo", "safe"], cwd=tmp_path, timeout=60)

            copied = asyncio.create_task(later())
        release.set()
        result = await copied
        assert result["reason"] == "consent_dispatch_unavailable"
    assert not calls and queue.dispatches == 0


@pytest.mark.asyncio
async def test_physical_gate_consumes_exact_scope_once(tmp_path):
    transport = object()
    queue = Queue()
    claim = ConsentClaim(7, "n", "e", object())
    scope = ConsentDispatchScope(7, "local", "l", ("echo",), str(tmp_path), 60,
                                 transport, {"target": "l"}, lambda: True)
    with (_worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True),
          bind_consent_dispatch(scope)):
        args = {"backend": "local", "argv": ("echo",), "cwd": str(tmp_path), "timeout": 60}
        assert physical_gate(transport, **args) is True
        assert physical_gate(transport, **args) is False
    assert queue.dispatches == 1


@pytest.mark.asyncio
async def test_ssh_scope_wrong_transport_never_spawns(tmp_path):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        raise AssertionError("spawn must remain closed")

    known = tmp_path / "known_hosts"
    known.write_text("host key")
    host = SshHost(target="remote", user="u", hostname="host", roots=("/srv",))
    transport = SshTransport({"remote": host}, known_hosts=known, spawn=spawn)
    scope = ConsentDispatchScope(7, "ssh", "remote", ("echo",), "/srv", 60,
                                 object(), {"target": "remote"}, lambda: True)
    queue = Queue()
    claim = ConsentClaim(7, "n", "e", object())
    with (_worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True),
          bind_consent_dispatch(scope)):
        result = await transport.run(["echo"], target="remote", cwd="/srv", timeout=60)
    assert result["reason"] == "consent_dispatch_unavailable"
    assert not calls
    assert queue.dispatches == 0


@pytest.mark.asyncio
async def test_docker_scope_blocks_spawn_and_host_fallback(monkeypatch, tmp_path):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        raise AssertionError("docker spawn must remain closed")

    sandbox = Sandbox.__new__(Sandbox)
    sandbox._has_docker = True
    sandbox.allow_subprocess = True
    sandbox.timeout = 30
    sandbox.max_memory_mb = 256
    sandbox.docker_image = "fixture:local"
    sandbox.work_dir = tmp_path
    sandbox.work_dir_managed = False
    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", spawn)
    queue = Queue()
    claim = ConsentClaim(7, "n", "e", object())
    scope = ConsentDispatchScope(7, "docker", "box", ("sh", "-c", "echo safe"),
                                 "/workspace", 30, sandbox,
                                 {"target": "box", "command": "echo safe"}, lambda: True)
    with (_worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True),
          bind_consent_dispatch(scope)):
        refused = await sandbox._run_docker(["sh", "-c", "echo changed"])
        assert refused.exit_code == -1
        sandbox._has_docker = False
        fallback = await sandbox.execute_shell("echo safe")
        assert fallback.exit_code == -1
    assert not calls and queue.dispatches == 0


@pytest.mark.asyncio
async def test_runner_rechecks_kernel_at_local_spawn(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    live = [True]

    async def spawn(*args, **kwargs):
        calls.append(args)
        raise AssertionError("spawn must remain closed")

    transport = LocalHostTransport([tmp_path], spawn=spawn)
    original_run = transport.run

    async def paused(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_run(*args, **kwargs)

    transport.run = paused
    registry = TargetRegistry([TerminalTarget(
        "host", "local", True, frozenset({"jarvis"}), frozenset({"terminal.exec"}),
        frozenset({"terminal.exec"}),
    )])
    request = {"target": "host", "command": "printf hello"}

    def kernel_check(action, *, capability, approval_check):
        assert approval_check(action) is True
        return Decision(Verdict.GRANT if live[0] else Verdict.DENY, reason="live", tier=3)

    runner = GovernedTargetRunner(
        registry, SimpleNamespace(), local_transport=transport,
        authorizer=lambda *_args, **_kwargs: Decision(Verdict.GRANT, reason="first", tier=3),
        approval_check=lambda task_id: task_id == 7,
        consent_approval_check=lambda task_id: task_id == 7,
        consent_kernel_check=kernel_check,
        request_check=lambda task_id, candidate: task_id == 7 and candidate == request,
    )
    queue = Queue()
    claim = ConsentClaim(7, "n", "e", object())

    async def run():
        with _worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True):
            return await runner.run(target="host", agent="jarvis", command="printf hello",
                                    approved_task_id=7)

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 1)
    live[0] = False
    release.set()
    result = await task
    assert result["reason"] == "consent_dispatch_unavailable"
    assert not calls and queue.dispatches == 0


@pytest.mark.asyncio
async def test_runner_refuses_mixed_owner_and_consent(monkeypatch):
    registry = TargetRegistry([TerminalTarget(
        "host", "docker", True, frozenset({"jarvis"}), frozenset({"terminal.exec"}),
    )])
    runner = GovernedTargetRunner(
        registry, SimpleNamespace(), owner_approval_check=lambda _id: True,
        consent_approval_check=lambda _id: True,
    )
    result = await runner.run(target="host", agent="jarvis", command="echo safe",
                              approved_task_id=7)
    assert result["reason"] == "mixed_approval_authority"


@pytest.mark.asyncio
async def test_durable_marker_without_private_worker_scope_never_spawns(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    spawned = []

    async def spawn(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("spawn must remain closed")

    transport = LocalHostTransport([tmp_path], spawn=spawn)
    registry = TargetRegistry([TerminalTarget(
        "host", "local", True, frozenset({"jarvis"}), frozenset({"terminal.exec"}),
        frozenset({"terminal.exec"}),
    )])
    runner = GovernedTargetRunner(
        registry, SimpleNamespace(), local_transport=transport,
        authorizer=lambda *_args, **_kwargs: Decision(Verdict.GRANT, reason="first", tier=3),
        approval_check=lambda _id: True,
        consent_approval_check=lambda _id: True,
        consent_kernel_check=lambda *_args, **_kwargs: Decision(Verdict.GRANT, reason="live", tier=3),
        request_check=lambda _id, _request: True,
    )
    result = await runner.run(target="host", agent="jarvis", command="printf hello",
                              approved_task_id=7)
    assert result["reason"] == "consent_dispatch_unavailable"
    assert not spawned
