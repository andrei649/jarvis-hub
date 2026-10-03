"""Owner-once authority is consumed at the real terminal spawn boundary."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.core.environments import owner_once_dispatch as gate
from agents.core.environments.execution import GovernedTargetRunner
from agents.core.environments.local_transport import LocalHostTransport
from agents.core.environments.owner_once_dispatch import (
    OwnerOnceDispatchScope,
    bind_owner_once_dispatch,
    physical_gate,
)
from agents.core.environments.ssh_transport import SshHost, SshTransport
from agents.core.environments.targets import TargetRegistry, TerminalTarget
from agents.core.kernel import Decision, Verdict
from agents.core.sandbox import Sandbox


class _Process:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b"ok")
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = 0
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


async def test_copied_child_context_cannot_consume_live_physical_scope(monkeypatch):
    transport = object()
    dispatched = []
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: dispatched.append(task_id) or True)
    scope = OwnerOnceDispatchScope(
        7, "local", "host", ("printf", "hello"), "/tmp", 30, transport,
        {"target": "host", "command": "printf hello"}, lambda: True,
    )
    with bind_owner_once_dispatch(scope):
        async def child_gate():
            return physical_gate(transport, backend="local", argv=("printf", "hello"),
                                 cwd="/tmp", timeout=30)

        assert await asyncio.create_task(child_gate()) is False
        assert physical_gate(transport, backend="local", argv=("printf", "hello"),
                             cwd="/tmp", timeout=30) is True
    assert dispatched == [7]


def _registry(backend):
    return TargetRegistry([TerminalTarget(
        name="host", backend=backend, enabled=True,
        allowed_agents=frozenset({"jarvis"}),
        capabilities=frozenset({"terminal.exec"}),
        approval_required=frozenset({"terminal.exec"}),
    )])


def _grant_kernel(action, capability=None, *, approval_check=None):
    assert action.kind == "terminal.exec"
    assert capability.name == "terminal.exec"
    assert approval_check is not None and approval_check(action) is True
    return Decision(Verdict.GRANT, reason="live", tier=3)


def _runner(monkeypatch, backend, transport, sandbox=None, *, request_check=None,
            owner_kernel_check=_grant_kernel):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_SSH_HOST", "1")
    return GovernedTargetRunner(
        _registry(backend), sandbox or SimpleNamespace(),
        local_transport=transport if backend == "local" else None,
        ssh_transport=transport if backend == "ssh" else None,
        authorizer=lambda *_args, **_kwargs: Decision(Verdict.GRANT, reason="test", tier=3),
        approval_check=lambda task_id: task_id == 7,
        owner_approval_check=lambda task_id: task_id == 7,
        owner_kernel_check=owner_kernel_check,
        request_check=request_check or (lambda task_id, request: task_id == 7
                                        and request == {"target": "host", "command": "printf hello"}),
    )


@pytest.mark.parametrize("backend", ["local", "ssh", "docker"])
@pytest.mark.parametrize("mode", ["ask", "kill_switch", "budget", "loop"])
async def test_kernel_revalidation_change_while_transport_paused_blocks_spawn(
    monkeypatch, tmp_path, backend, mode,
):
    entered, release = asyncio.Event(), asyncio.Event()
    spawned, dispatched = [], []

    async def spawn(*argv, **_kwargs):
        spawned.append(argv)
        return _Process()

    if backend == "local":
        transport = LocalHostTransport([tmp_path], spawn=spawn)
        sandbox = None
    elif backend == "ssh":
        pinned = tmp_path / "known_hosts"
        pinned.write_text("fixture", encoding="utf-8")
        host = SshHost("host", "alice", "example.test", roots=(str(tmp_path),))
        transport = SshTransport({"host": host}, known_hosts=pinned, spawn=spawn)
        sandbox = None
    else:
        transport = None
        sandbox = Sandbox.__new__(Sandbox)
        sandbox._has_docker = True
        sandbox.allow_subprocess = False
        sandbox.timeout = 30
        sandbox.max_memory_mb = 256
        sandbox.max_output_bytes = 50_000
        sandbox.docker_image = "fixture:local"
        sandbox.work_dir = tmp_path
        sandbox.work_dir_managed = False
        sandbox._read_output_capped = lambda _proc, _sinks: asyncio.sleep(0, result=("", ""))
        monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", spawn)
    owner = transport if transport is not None else sandbox
    original = owner.run if transport is not None else owner.execute_shell

    async def paused(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    if transport is not None:
        transport.run = paused
    else:
        sandbox.execute_shell = paused
    live = [True]

    def revalidate(action, capability=None, *, approval_check=None):
        assert action.kind == "terminal.exec"
        assert action.payload["argv"] == ["printf", "hello"]
        assert capability.name == "terminal.exec"
        assert approval_check is not None and approval_check(action) is True
        return Decision(Verdict.GRANT if live[0] else
                        Verdict.QUEUE if mode == "ask" else Verdict.DENY,
                        reason="live" if live[0] else mode, tier=3)

    runner = _runner(monkeypatch, backend, transport, sandbox=sandbox,
                     owner_kernel_check=revalidate)
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: dispatched.append(task_id) or True)
    task = asyncio.create_task(runner.run(
        target="host", agent="jarvis", command="printf hello", approved_task_id=7,
    ))
    await asyncio.wait_for(entered.wait(), 1)
    live[0] = False
    release.set()
    result = await task
    assert result["ok"] is False, result
    assert dispatched == [] and spawned == []


@pytest.mark.parametrize("kind", ["missing", "dict", "awaitable", "mutated_action"])
async def test_owner_kernel_revalidator_must_return_exact_synchronous_grant(
    monkeypatch, tmp_path, kind,
):
    spawned, dispatched = [], []

    async def spawn(*argv, **_kwargs):
        spawned.append(argv)
        return _Process()

    async def delayed_grant(*_args, **_kwargs):
        return Decision(Verdict.GRANT, reason="late")

    def mutated_grant(action, **_kwargs):
        action.payload["target"] = "other"
        return Decision(Verdict.GRANT, reason="mutated")

    revalidator = {
        "missing": None,
        "dict": lambda *_args, **_kwargs: {"verdict": "grant"},
        "awaitable": delayed_grant,
        "mutated_action": mutated_grant,
    }[kind]
    transport = LocalHostTransport([tmp_path], spawn=spawn)
    runner = _runner(monkeypatch, "local", transport, owner_kernel_check=revalidator)
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: dispatched.append(task_id) or True)
    result = await runner.run(target="host", agent="jarvis", command="printf hello",
                              approved_task_id=7)
    assert result["ok"] is False, result
    assert spawned == [] and dispatched == []


@pytest.mark.parametrize("backend", ["local", "ssh"])
async def test_builtin_transport_consumes_once_immediately_before_physical_spawn(
    monkeypatch, tmp_path, backend,
):
    order = []

    async def spawn(*argv, **kwargs):
        order.append(("spawn", argv, kwargs))
        return _Process()

    if backend == "local":
        transport = LocalHostTransport([tmp_path], spawn=spawn)
    else:
        pinned = tmp_path / "known_hosts"
        pinned.write_text("fixture", encoding="utf-8")
        host = SshHost("host", "alice", "example.test", roots=(str(tmp_path),))
        transport = SshTransport({"host": host}, known_hosts=pinned, spawn=spawn)
    def revalidate(action, capability=None, *, approval_check=None):
        order.append(("kernel", action.kind))
        return _grant_kernel(action, capability, approval_check=approval_check)

    runner = _runner(monkeypatch, backend, transport, owner_kernel_check=revalidate)
    monkeypatch.setattr(gate, "_owner_current", lambda task_id: task_id == 7)

    def dispatch(task_id):
        order.append(("dispatch", task_id))
        return True

    monkeypatch.setattr(gate, "_owner_dispatch", dispatch)
    result = await runner.run(target="host", agent="jarvis", command="printf hello",
                              approved_task_id=7)
    assert result["ok"] is True, result
    assert [event[0] for event in order] == ["kernel", "dispatch", "spawn"]
    if backend == "local":
        assert order[2][1] == ("printf", "hello")
        assert order[2][2]["cwd"] == str(tmp_path.resolve())
    else:
        assert order[2][1][0] == "ssh"
        assert "printf hello" in order[2][1][-1]


@pytest.mark.parametrize("backend", ["local", "ssh"])
async def test_revocation_during_transport_pause_blocks_dispatch_and_spawn(
    monkeypatch, tmp_path, backend,
):
    entered, release = asyncio.Event(), asyncio.Event()
    spawned, dispatched = [], []

    async def spawn(*_args, **_kwargs):
        spawned.append(True)
        return _Process()

    if backend == "local":
        transport = LocalHostTransport([tmp_path], spawn=spawn)
    else:
        pinned = tmp_path / "known_hosts"
        pinned.write_text("fixture", encoding="utf-8")
        host = SshHost("host", "alice", "example.test", roots=(str(tmp_path),))
        transport = SshTransport({"host": host}, known_hosts=pinned, spawn=spawn)
    original = transport.run

    async def paused(*args, **kwargs):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            # A resistant transport can keep running; the physical gate must still refuse.
            await release.wait()
        return await original(*args, **kwargs)

    transport.run = paused
    live = [True]
    runner = _runner(monkeypatch, backend, transport,
                     request_check=lambda _task_id, _request: live[0])
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: live[0])
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: dispatched.append(task_id) or True)
    task = asyncio.create_task(runner.run(target="host", agent="jarvis", command="printf hello",
                                          approved_task_id=7))
    await asyncio.wait_for(entered.wait(), 1)
    live[0] = False
    task.cancel()
    release.set()
    result = await task
    assert result["ok"] is False
    assert spawned == [] and dispatched == []


async def test_custom_local_transport_cannot_skip_owner_physical_gate(monkeypatch, tmp_path):
    called = []
    custom = SimpleNamespace(
        roots=(str(tmp_path),), max_timeout=60,
        bound_timeout=lambda _timeout: 30,
        resolve_cwd=lambda _cwd: tmp_path,
        run=lambda *_args, **_kwargs: called.append(True),
    )
    runner = _runner(monkeypatch, "local", custom)
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda _task_id: called.append("dispatch") or True)
    result = await runner.run(target="host", agent="jarvis", command="printf hello",
                              approved_task_id=7)
    assert result["ok"] is False
    assert called == []


@pytest.mark.parametrize("backend", ["local", "ssh", "docker"])
@pytest.mark.parametrize("change", ["disabled", "backend", "agent", "capability", "approval"])
async def test_policy_change_while_builtin_transport_paused_refuses_physical_dispatch(
    monkeypatch, tmp_path, backend, change,
):
    entered, release = asyncio.Event(), asyncio.Event()
    spawned, dispatched = [], []

    async def spawn(*argv, **_kwargs):
        spawned.append(argv)
        return _Process()

    if backend == "local":
        transport = LocalHostTransport([tmp_path], spawn=spawn)
        sandbox = None
    elif backend == "ssh":
        pinned = tmp_path / "known_hosts"
        pinned.write_text("fixture", encoding="utf-8")
        host = SshHost("host", "alice", "example.test", roots=(str(tmp_path),))
        transport = SshTransport({"host": host}, known_hosts=pinned, spawn=spawn)
        sandbox = None
    else:
        transport = None
        sandbox = Sandbox.__new__(Sandbox)
        sandbox._has_docker = True
        sandbox.allow_subprocess = False
        sandbox.timeout = 30
        sandbox.max_memory_mb = 256
        sandbox.max_output_bytes = 50_000
        sandbox.docker_image = "fixture:local"
        sandbox.work_dir = tmp_path
        sandbox.work_dir_managed = False
        sandbox._read_output_capped = lambda _proc, _sinks: asyncio.sleep(0, result=("", ""))
        monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", spawn)

    runner = _runner(monkeypatch, backend, transport, sandbox=sandbox)
    owner = transport if transport is not None else sandbox
    original = owner.run if transport is not None else owner.execute_shell

    async def paused(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    if transport is not None:
        transport.run = paused
    else:
        sandbox.execute_shell = paused
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: dispatched.append(task_id) or True)
    task = asyncio.create_task(runner.run(
        target="host", agent="jarvis", command="printf hello", approved_task_id=7,
    ))
    await asyncio.wait_for(entered.wait(), 1)
    policy = runner._registry
    old = policy._targets.pop("host")
    changed = {
        "disabled": {"enabled": False},
        "backend": {"backend": "docker" if backend != "docker" else "local"},
        "agent": {"allowed_agents": frozenset({"other"})},
        "capability": {"capabilities": frozenset({"other.capability"}),
                       "approval_required": frozenset()},
        "approval": {"approval_required": frozenset()},
    }[change]
    policy.register(replace(old, **changed))
    release.set()
    result = await task
    assert result["ok"] is False, result
    assert dispatched == [] and spawned == []
    assert policy.audit.verify_chain()
    assert len(policy.audit.entries) == 2
    expected_outcome = {"backend": "approval_required", "approval": "allow"}.get(change, "deny")
    assert policy.audit.entries[-1]["outcome"] == expected_outcome


async def test_owner_docker_gate_is_after_setup_and_never_falls_back_to_host(monkeypatch, tmp_path):
    sandbox = Sandbox.__new__(Sandbox)
    sandbox._has_docker = True
    sandbox.allow_subprocess = True
    sandbox.timeout = 30
    sandbox.max_memory_mb = 256
    sandbox.max_output_bytes = 50_000
    sandbox.docker_image = "fixture:local"
    sandbox.work_dir = tmp_path
    sandbox.work_dir_managed = False
    order = []

    async def spawn(*argv, **_kwargs):
        order.append(("spawn", argv))
        return _Process()

    async def output(_proc, _sinks):
        return "ok", ""

    async def forbidden_host(*_args, **_kwargs):
        order.append(("host",))
        raise AssertionError("owner grant fell back to host")

    sandbox._read_output_capped = output
    sandbox._execute_subprocess_shell = forbidden_host
    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", spawn)
    runner = _runner(monkeypatch, "docker", None, sandbox=sandbox)
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: order.append(("dispatch", task_id)) or True)
    result = await runner.run(target="host", agent="jarvis", command="printf hello",
                              approved_task_id=7)
    assert result["ok"] is True, result
    assert [item[0] for item in order] == ["dispatch", "spawn"]
    assert order[1][1][:2] == ("docker", "run")


@pytest.mark.parametrize("backend", ["local", "ssh"])
async def test_cancel_swallowed_by_spawn_after_dispatch_still_kills_child(
    monkeypatch, tmp_path, backend,
):
    entered, release = asyncio.Event(), asyncio.Event()
    process = _Process()
    dispatches = []

    async def spawn(*_args, **_kwargs):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return process

    if backend == "local":
        transport = LocalHostTransport([tmp_path], spawn=spawn)
    else:
        pinned = tmp_path / "known_hosts"
        pinned.write_text("fixture", encoding="utf-8")
        host = SshHost("host", "alice", "example.test", roots=(str(tmp_path),))
        transport = SshTransport({"host": host}, known_hosts=pinned, spawn=spawn)
    runner = _runner(monkeypatch, backend, transport)
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: dispatches.append(task_id) or True)
    task = asyncio.create_task(runner.run(target="host", agent="jarvis", command="printf hello",
                                          approved_task_id=7))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert dispatches == [7]
    assert process.killed


async def test_docker_missing_after_dispatch_never_falls_back_to_host(monkeypatch, tmp_path):
    sandbox = Sandbox.__new__(Sandbox)
    sandbox._has_docker = True
    sandbox.allow_subprocess = True
    sandbox.timeout = 30
    sandbox.max_memory_mb = 256
    sandbox.max_output_bytes = 50_000
    sandbox.docker_image = "fixture:local"
    sandbox.work_dir = tmp_path
    sandbox.work_dir_managed = False
    called = []

    async def missing(*_args, **_kwargs):
        raise FileNotFoundError("docker")

    async def forbidden_host(*_args, **_kwargs):
        called.append("host")
        return SimpleNamespace(exit_code=0, stdout="", stderr="", duration=0)

    sandbox._execute_subprocess_shell = forbidden_host
    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", missing)
    runner = _runner(monkeypatch, "docker", None, sandbox=sandbox)
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: called.append(task_id) or True)
    result = await runner.run(target="host", agent="jarvis", command="printf hello",
                              approved_task_id=7)
    assert result["ok"] is False
    assert called == [7]


async def test_docker_cancel_swallowed_during_spawn_kills_client_and_container(monkeypatch, tmp_path):
    sandbox = Sandbox.__new__(Sandbox)
    sandbox._has_docker = True
    sandbox.allow_subprocess = False
    sandbox.timeout = 30
    sandbox.max_memory_mb = 256
    sandbox.max_output_bytes = 50_000
    sandbox.docker_image = "fixture:local"
    sandbox.work_dir = tmp_path
    sandbox.work_dir_managed = False
    entered, release = asyncio.Event(), asyncio.Event()
    process = _Process()
    calls, dispatches = [], []

    async def spawn(*argv, **_kwargs):
        calls.append(argv)
        if argv[:2] != ("docker", "run"):
            return _Process()
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return process

    async def output(_proc, _sinks):
        return "ok", ""

    sandbox._read_output_capped = output
    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", spawn)
    runner = _runner(monkeypatch, "docker", None, sandbox=sandbox)
    monkeypatch.setattr(gate, "_owner_current", lambda _task_id: True)
    monkeypatch.setattr(gate, "_owner_dispatch", lambda task_id: dispatches.append(task_id) or True)
    task = asyncio.create_task(runner.run(target="host", agent="jarvis", command="printf hello",
                                          approved_task_id=7))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert dispatches == [7]
    assert process.killed
    assert len(calls) == 2 and calls[1][:2] == ("docker", "kill")
