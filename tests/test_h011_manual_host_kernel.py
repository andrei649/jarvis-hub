"""Accepted terminal ToolRPC tasks still need the real local/SSH kernel hop."""

import asyncio
import contextvars
import json
from dataclasses import replace

import pytest

from agents.core.environments import TargetRegistry, TerminalTarget
from agents.core.environments.legacy_terminal_dispatch import (
    LegacyTerminalDispatchScope,
    bind_legacy_terminal_dispatch,
)
from agents.core.environments.local_transport import LocalHostTransport
from agents.core.environments.ssh_transport import SshHost, SshTransport
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.kernel import Decision, Verdict
from tests.test_h277_smart_terminal_integration import runtime, use_real_kernel  # noqa: F401


class Stream:
    async def read(self, _count):
        return b""


class Process:
    stdout = Stream()
    stderr = Stream()
    returncode = 0

    async def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


def prepare_host(runtime, monkeypatch, tmp_path, backend, *, spawn=None):
    queue, worker, orch, _sandbox, _seen = runtime
    root = tmp_path / "workspace"
    root.mkdir()
    spawns = []

    async def synthetic_spawn(*argv, **kwargs):
        spawns.append((argv, kwargs))
        return Process()

    spawn = spawn or synthetic_spawn
    target = "local-host" if backend == "local" else "remote"
    registry = TargetRegistry([TerminalTarget(
        name=target, backend=backend, enabled=True,
        allowed_agents=frozenset({"jarvis"}),
        capabilities=frozenset({"terminal.exec"}),
        approval_required=frozenset({"terminal.exec"}),
    )])
    monkeypatch.setattr(orch._test_coordinator, "_target_registry", lambda: registry)
    if backend == "local":
        monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
        transport = LocalHostTransport([root], spawn=spawn)
        monkeypatch.setattr(LocalHostTransport, "from_env", classmethod(
            lambda cls, **_kwargs: transport))
        cwd = str(root)
    else:
        monkeypatch.setenv("JARVIS_TERMINAL_SSH_HOST", "1")
        known = tmp_path / "known_hosts"
        known.write_text("fixture", encoding="utf-8")
        host = SshHost(target=target, user="owner", hostname="example.test", roots=("/work",))
        transport = SshTransport({target: host}, known_hosts=known, spawn=spawn)
        monkeypatch.setattr(SshTransport, "from_env", classmethod(
            lambda cls, **_kwargs: transport))
        cwd = "/work"
    return target, cwd, root, transport, registry, spawns


async def accepted_task(runtime, target, cwd, *, command="printf hello"):
    queue, worker, orch, _sandbox, _seen = runtime
    answer = await orch.tool_rpc.handle({"tool": "terminal_run", "args": {
        "target": target, "command": command, "cwd": cwd,
    }}, actor="jarvis")
    assert "task_id" in answer, answer
    task_id = answer["task_id"]
    await worker.apply_decision(task_id, "accept", "user")
    return task_id


@pytest.mark.parametrize("backend", ["local", "ssh"])
async def test_accepted_host_task_gets_real_kernel_grant_and_one_spawn(
    runtime, monkeypatch, tmp_path, backend,
):
    queue, worker, _orch, _sandbox, _seen = runtime
    target, cwd, _root, _transport, _registry, spawns = prepare_host(
        runtime, monkeypatch, tmp_path, backend)
    use_real_kernel(runtime)
    task_id = await accepted_task(runtime, target, cwd)
    assert spawns == []
    await worker.tick()
    completed = queue.get(task_id)
    assert completed.result["status"] == "ok", completed.result
    assert len(spawns) == 1
    await worker.tick()
    assert len(spawns) == 1


@pytest.mark.parametrize(("backend", "change"), [
    (backend, change)
    for backend in ("local", "ssh")
    for change in ("approval", "target", "transport", "kernel", "halt", "request",
                   "source", "root_swap")
    if backend == "local" or change != "root_swap"
])
async def test_real_accepted_task_revoked_at_physical_fence(
    runtime, monkeypatch, tmp_path, backend, change,
):
    queue, worker, orch, _sandbox, _seen = runtime
    target, cwd, root, transport, registry, spawns = prepare_host(
        runtime, monkeypatch, tmp_path, backend)
    halted = use_real_kernel(runtime)
    task_id = await accepted_task(runtime, target, cwd)
    original_run = transport.run

    async def changed(*argv, **kwargs):
        source_token = None
        if change == "approval":
            queue._conn.execute("UPDATE tasks SET decided_by=? WHERE id=?", ("policy", task_id))
            queue._conn.commit()
        elif change == "target":
            registry._targets[target] = replace(registry.snapshot(target), enabled=False)
        elif change == "transport":
            if backend == "local":
                transport._roots = (tmp_path,)
            else:
                transport.connect_timeout += 1
        elif change == "kernel":
            monkeypatch.setenv("JARVIS_ACTION_KERNEL", "0")
        elif change == "halt":
            halted[0] = True
        elif change == "request":
            payload = queue.get(task_id).payload
            payload["args"]["command"] = "printf changed"
            queue._conn.execute("UPDATE tasks SET payload=? WHERE id=?",
                                (json.dumps(payload), task_id))
            queue._conn.commit()
        elif change == "source":
            from agents.core.action_origin import bind_action_origin

            source_token = bind_action_origin("external")
        elif change == "root_swap":
            moved = tmp_path / "moved"
            root.rename(moved)
            root.mkdir()
        try:
            return await original_run(*argv, **kwargs)
        finally:
            if source_token is not None:
                from agents.core.action_origin import reset_action_origin

                reset_action_origin(source_token)

    monkeypatch.setattr(transport, "run", changed)
    await worker.tick()
    result = queue.get(task_id).result
    assert result["status"] == "failed" and spawns == [], result


@pytest.mark.parametrize("backend", ["local", "ssh"])
@pytest.mark.parametrize("change", ["ask", "off", "halt"])
async def test_restrictive_kernel_wins_before_host_transport(
    runtime, monkeypatch, tmp_path, backend, change,
):
    queue, worker, _orch, _sandbox, _seen = runtime
    target, cwd, _root, _transport, _registry, spawns = prepare_host(
        runtime, monkeypatch, tmp_path, backend)
    halted = use_real_kernel(runtime)
    task_id = await accepted_task(runtime, target, cwd)
    if change == "halt":
        halted[0] = True
    else:
        worker.policy.mode = change
    await worker.tick()
    assert queue.get(task_id).result["status"] == "failed"
    assert spawns == []


async def test_checkpoint_capture_revocation_precedes_one_use_local_gate(
    runtime, monkeypatch, tmp_path,
):
    queue, worker, _orch, _sandbox, _seen = runtime
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    target, cwd, root, _transport, _registry, spawns = prepare_host(
        runtime, monkeypatch, tmp_path, "local")
    (root / "note.txt").write_text("before", encoding="utf-8")
    use_real_kernel(runtime)
    task_id = await accepted_task(runtime, target, cwd, command="rm note.txt")
    original = FileCheckpointHistory.begin_scope

    def capture_then_revoke(self, *args, **kwargs):
        captured = original(self, *args, **kwargs)
        queue.mediation_mode = "hold"
        return captured

    monkeypatch.setattr(FileCheckpointHistory, "begin_scope", capture_then_revoke)
    await worker.tick()
    assert queue.get(task_id).result["reason"] == "terminal_dispatch_revoked"
    assert spawns == [] and (root / "note.txt").read_text() == "before"


@pytest.mark.parametrize("backend", ["local", "ssh"])
async def test_raw_task_id_and_real_kernel_without_bound_revalidator_cannot_dispatch(
    runtime, monkeypatch, tmp_path, backend,
):
    _queue, worker, _orch, _sandbox, _seen = runtime
    target, cwd, _root, transport, registry, spawns = prepare_host(
        runtime, monkeypatch, tmp_path, backend)
    use_real_kernel(runtime)
    from agents.core.environments.execution import GovernedTargetRunner

    runner = GovernedTargetRunner(
        registry, object(), authorizer=worker.kernel_gate,
        approval_check=lambda _task_id: True,
        request_check=lambda _task_id, _request: True,
        local_transport=transport if backend == "local" else None,
        ssh_transport=transport if backend == "ssh" else None,
    )
    result = await runner.run(target=target, agent="jarvis", command="printf hello",
                              cwd=cwd, approved_task_id=17)
    assert result["ok"] is False and result["reason"] == "kernel_queued", result
    assert spawns == []


@pytest.mark.parametrize("backend", ["local", "ssh"])
async def test_cancellation_after_manual_kernel_grant_never_spawns(
    runtime, monkeypatch, tmp_path, backend,
):
    from agents.core.environments.execution import GovernedTargetRunner

    target, cwd, _root, transport, registry, spawns = prepare_host(
        runtime, monkeypatch, tmp_path, backend)

    def grant_after_cancelling(_action, **_kwargs):
        asyncio.current_task().cancel()
        return Decision(Verdict.GRANT)

    runner = GovernedTargetRunner(
        registry, object(), authorizer=grant_after_cancelling,
        approval_check=lambda task_id: task_id == 17,
        request_check=lambda task_id, _request: task_id == 17,
        legacy_kernel_check=lambda *_args, **_kwargs: Decision(Verdict.GRANT),
        local_transport=transport if backend == "local" else None,
        ssh_transport=transport if backend == "ssh" else None,
    )
    pending = asyncio.create_task(runner.run(
        target=target, agent="jarvis", command="printf hello", cwd=cwd,
        approved_task_id=17,
    ))
    try:
        result = await pending
    except asyncio.CancelledError:
        pass
    else:
        assert result["ok"] is False
    assert spawns == []


@pytest.mark.parametrize("backend", ["local", "ssh"])
async def test_provided_but_failing_current_kernel_receipt_refuses_grant_fixture(
    runtime, monkeypatch, tmp_path, backend,
):
    from agents.core.environments.execution import GovernedTargetRunner

    target, cwd, _root, transport, registry, spawns = prepare_host(
        runtime, monkeypatch, tmp_path, backend)
    runner = GovernedTargetRunner(
        registry, object(), authorizer=lambda *_args, **_kwargs: Decision(Verdict.GRANT),
        approval_check=lambda task_id: task_id == 17,
        request_check=lambda task_id, _request: task_id == 17,
        legacy_kernel_check=lambda *_args, **_kwargs: Decision(Verdict.DENY),
        local_transport=transport if backend == "local" else None,
        ssh_transport=transport if backend == "ssh" else None,
    )
    result = await runner.run(target=target, agent="jarvis", command="printf hello",
                              cwd=cwd, approved_task_id=17)
    assert result["reason"] == "legacy_terminal_dispatch_unavailable", result
    assert spawns == []


@pytest.mark.parametrize("backend", ["local", "ssh"])
async def test_private_scope_is_one_use_and_wrong_task_cannot_spawn(
    monkeypatch, tmp_path, backend,
):
    spawns = []

    async def spawn(*argv, **kwargs):
        spawns.append((argv, kwargs))
        return Process()

    if backend == "local":
        monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
        root = tmp_path / "workspace"
        root.mkdir()
        cwd = str(root)
        transport = LocalHostTransport([root], default_timeout=30, spawn=spawn)

        async def run(argv=("printf", "hello")):
            return await transport.run(argv, cwd=cwd, timeout=30)
        target = "local-host"
    else:
        known = tmp_path / "known_hosts"
        known.write_text("fixture", encoding="utf-8")
        target, cwd = "remote", "/work"
        host = SshHost(target=target, user="owner", hostname="example.test", roots=(cwd,))
        transport = SshTransport({target: host}, known_hosts=known, default_timeout=30,
                                 spawn=spawn)

        async def run(argv=("printf", "hello")):
            return await transport.run(argv, target=target, cwd=cwd,
                                       timeout=30)
    scope = LegacyTerminalDispatchScope(
        17, backend, target, ("printf", "hello"), cwd, 30, transport,
        {"target": target, "command": "printf hello"}, lambda: True,
    )
    with bind_legacy_terminal_dispatch(scope):
        closed_context = contextvars.copy_context()
        copied = await asyncio.create_task(run())
        assert copied["reason"] == "legacy_terminal_dispatch_unavailable"
        assert scope.used is False
        first = await run()
        second = await run()
        assert first["ok"] is True and second["reason"] == "legacy_terminal_dispatch_unavailable"
    assert scope.active is False and scope.used is True
    closed = await closed_context.run(asyncio.create_task, run())
    assert closed["reason"] == "legacy_terminal_dispatch_unavailable"
    mismatch_scope = LegacyTerminalDispatchScope(
        17, backend, target, ("printf", "hello"), cwd, 30, transport,
        {"target": target, "command": "printf hello"}, lambda: True,
    )
    with bind_legacy_terminal_dispatch(mismatch_scope):
        mismatch = await run(("printf", "changed"))
        assert mismatch["reason"] == "legacy_terminal_dispatch_unavailable"
        assert mismatch_scope.used is True
        after_mismatch = await run()
        assert after_mismatch["reason"] == "legacy_terminal_dispatch_unavailable"
    assert len(spawns) == 1
