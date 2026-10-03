"""The private worker claim cannot escape its original live task."""

import asyncio

import pytest

from agents.core.autonomy.consent_execution import (
    _worker_scope,
    consent_current,
    consent_dispatch,
    consent_scope_present,
)
from agents.core.autonomy.consent_types import ConsentClaim
from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.queue import Task
from agents.core.environments.consent_dispatch import ConsentDispatchScope, bind_consent_dispatch
from agents.core.environments.local_transport import LocalHostTransport


class Queue:
    def __init__(self):
        self.verifications = 0
        self.dispatches = 0
        self.task = None

    def get(self, task_id):
        return self.task if self.task is not None and self.task.id == task_id else None

    def verify_consent_execution(self, task_id, claim, *, live_check):
        self.verifications += 1
        return task_id == claim.task_id and live_check() is True

    def consent_dispatch_current(self, task_id, claim, *, live_check):
        self.dispatches += 1
        return task_id == claim.task_id and live_check() is True and self.dispatches == 1


@pytest.mark.asyncio
async def test_claim_is_private_to_original_worker_and_lifetime():
    queue = Queue()
    claim = ConsentClaim(17, "nonce", "execution", object())
    live = True
    copied = []
    assert not consent_scope_present()
    with _worker_scope(queue, claim, lambda: live, dispatch_check=lambda: live):
        assert consent_scope_present()
        assert consent_current(17)
        assert not consent_current(18)

        async def other():
            copied.append((consent_scope_present(), consent_current(17), consent_dispatch(17)))

        await asyncio.create_task(other())
        assert copied == [(True, False, False)]
        assert consent_dispatch(17)
        assert not consent_dispatch(17)
        live = False
        assert not consent_current(17)
    assert not consent_scope_present()
    assert not consent_current(17)
    assert queue.dispatches == 2


def _task():
    return Task(
        17, "jarvis", "toolrpc.terminal_run", "terminal", {"command": "printf hello"},
        3, "running", "ask", "manual", 1, None, "consent", "consent-session", 0,
        "2026-10-04T00:00:00Z", "2026-10-04T00:00:00Z",
    )


class _Process:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b"ok")
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = 0

    async def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.mark.asyncio
async def test_real_task_executor_wait_for_binds_only_its_guarded_handler(tmp_path):
    queue = Queue()
    queue.task = _task()
    claim = ConsentClaim(17, "nonce", "execution", object())
    spawns = []
    copied = []

    async def spawn(*argv, **kwargs):
        spawns.append(argv)
        return _Process()

    transport = LocalHostTransport([tmp_path], spawn=spawn)

    async def handler(task):
        assert consent_current(task.id)

        async def unrelated():
            copied.append((consent_current(task.id), consent_dispatch(task.id)))

        await asyncio.create_task(unrelated())
        scope = ConsentDispatchScope(
            task.id, "local", "host", ("printf", "hello"), str(tmp_path), 60,
            transport, {"target": "host", "command": "printf hello"}, lambda: True,
        )
        with bind_consent_dispatch(scope):
            return await transport.run(["printf", "hello"], cwd=tmp_path, timeout=60)

    executor = TaskExecutor(max_wall_seconds=1, execution_guard=lambda _task: True)
    executor.register("toolrpc.terminal_run", handler)
    with _worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True,
                       trusted_executor=executor.execute):
        result = await executor.execute(queue.task)
    assert result["ok"] is True
    assert copied == [(False, False)]
    assert spawns == [("printf", "hello")]
    assert queue.dispatches == 1


@pytest.mark.asyncio
async def test_timeout_revokes_handler_and_copied_descendants():
    queue = Queue()
    queue.task = _task()
    claim = ConsentClaim(17, "nonce", "execution", object())
    release = asyncio.Event()
    descendants = []
    child_tasks = []

    async def handler(task):
        assert consent_current(task.id)

        async def copied():
            await release.wait()
            descendants.append((consent_current(task.id), consent_dispatch(task.id)))

        child_tasks.append(asyncio.create_task(copied()))
        await asyncio.Event().wait()

    executor = TaskExecutor(max_wall_seconds=0.01, execution_guard=lambda _task: True)
    executor.register("toolrpc.terminal_run", handler)
    with _worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True,
                       trusted_executor=executor.execute):
        result = await executor.execute(queue.task)
        assert result["reason"] == "wall_time_budget_exceeded"
        release.set()
        await asyncio.gather(*child_tasks)
        assert descendants == [(False, False)]
    assert queue.dispatches == 0


@pytest.mark.asyncio
async def test_untrusted_executor_cannot_claim_handler_for_fabricated_consent():
    queue = Queue()
    queue.task = _task()
    claim = ConsentClaim(17, "nonce", "execution", object())
    called = []

    async def handler(_task):
        called.append(True)
        return {"status": "ok"}

    trusted = TaskExecutor(max_wall_seconds=1, execution_guard=lambda _task: True)
    foreign = TaskExecutor(max_wall_seconds=1, execution_guard=lambda _task: True)
    foreign.register("toolrpc.terminal_run", handler)
    with _worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True,
                       trusted_executor=trusted.execute):
        result = await foreign.execute(queue.task)
    assert result["reason"] == "mediation_execution_context_required"
    assert called == []


@pytest.mark.asyncio
async def test_handler_handoff_rejects_guard_mutation_and_rebind():
    queue = Queue()
    queue.task = _task()
    claim = ConsentClaim(17, "nonce", "execution", object())
    seen = []

    async def handler(task):
        seen.append(task.payload["command"])
        return {"status": "ok"}

    def mutating_guard(task):
        task.payload["command"] = "changed"
        return True

    tampered = TaskExecutor(max_wall_seconds=1, execution_guard=mutating_guard)
    tampered.register("toolrpc.terminal_run", handler)
    with _worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True,
                       trusted_executor=tampered.execute):
        refused = await tampered.execute(queue.task)
    assert refused["reason"] == "mediation_execution_context_required"
    assert seen == []

    trusted = TaskExecutor(max_wall_seconds=1, execution_guard=lambda _task: True)
    trusted.register("toolrpc.terminal_run", handler)
    with _worker_scope(queue, claim, lambda: True, dispatch_check=lambda: True,
                       trusted_executor=trusted.execute):
        first = await trusted.execute(queue.task)
        second = await trusted.execute(queue.task)
    assert first["status"] == "ok"
    assert second["reason"] == "mediation_execution_context_required"
    assert seen == ["printf hello"]
