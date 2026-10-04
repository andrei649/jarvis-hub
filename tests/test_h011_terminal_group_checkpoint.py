"""H011 local terminal capture must straddle the real physical spawn seam."""

from __future__ import annotations

import asyncio
import threading

import pytest

from agents.core.environments import TargetAuditChain, TargetRegistry, TerminalTarget
from agents.core.environments.execution import GovernedTargetRunner
from agents.core.environments.local_transport import LocalHostTransport
from agents.core.kernel import Decision, Verdict


class _Stream:
    async def read(self, count):
        return b""


class _Proc:
    def __init__(self):
        self.stdout = _Stream()
        self.stderr = _Stream()
        self.returncode = 0

    async def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class _Spawn:
    def __init__(self, mutate):
        self.mutate = mutate
        self.calls = 0

    async def __call__(self, *argv, **kwargs):
        self.calls += 1
        self.mutate()
        return _Proc()


class _HangProc(_Proc):
    def __init__(self):
        super().__init__()
        self.done = asyncio.Event()
        self.killed = False

    async def wait(self):
        await self.done.wait()
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.done.set()


def _runner(root, spawn, *, request_check=None, checkpoint_origin_lookup=None,
            authority=None):
    registry = TargetRegistry((TerminalTarget(
        name="host", backend="local", enabled=True,
        allowed_agents=frozenset({"jarvis"}), capabilities=frozenset({"terminal.exec"}),
        approval_required=frozenset({"terminal.exec"}),
    ),), audit=TargetAuditChain())
    return GovernedTargetRunner(
        registry, object(), local_transport=LocalHostTransport([root], spawn=spawn),
        authorizer=lambda *args, **kwargs: Decision(Verdict.GRANT, reason="synthetic", tier=3),
        approval_check=lambda task_id: task_id == 12,
        request_check=request_check or (lambda task_id, request: task_id == 12),
        checkpoint_origin_lookup=checkpoint_origin_lookup,
        owner_approval_check=(lambda task_id: task_id == 12) if authority == "owner" else None,
        consent_approval_check=(lambda task_id: task_id == 12) if authority == "consent" else None,
        owner_kernel_check=(
            lambda action, capability=None, *, approval_check=None:
            Decision(Verdict.GRANT, reason="owner", tier=3)
            if approval_check(action) else Decision(Verdict.DENY, reason="stale", tier=3)
        ) if authority == "owner" else None,
        consent_kernel_check=(
            lambda action, capability=None, *, approval_check=None:
            Decision(Verdict.GRANT, reason="consent", tier=3)
            if approval_check(action) else Decision(Verdict.DENY, reason="stale", tier=3)
        ) if authority == "consent" else None,
    )


@pytest.mark.asyncio
async def test_actual_local_spawn_has_pre_and_post_group(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    original = root / "original.txt"
    original.write_text("before", encoding="utf-8")
    created = root / "created.txt"
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")

    def mutate():
        original.write_text("after", encoding="utf-8")
        created.write_text("created", encoding="utf-8")

    spawn = _Spawn(mutate)
    result = await _runner(root, spawn).run(
        target="host", agent="jarvis", command="git checkout -- original.txt",
        cwd=str(root), approved_task_id=12,
    )
    assert result["ok"] is True and spawn.calls == 1, result
    checkpoint = result["checkpoint"]
    assert checkpoint["status"] == "finished"
    assert checkpoint["root"] == str(root)
    assert checkpoint["modified"] == 1 and checkpoint["created"] == 1


@pytest.mark.asyncio
async def test_slow_capture_rechecks_request_before_actual_spawn(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    live = {"request": True}
    original = FileCheckpointHistory.begin_scope

    def capture_then_revoke(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        live["request"] = False
        return result

    monkeypatch.setattr(FileCheckpointHistory, "begin_scope", capture_then_revoke)
    spawn = _Spawn(lambda: None)
    result = await _runner(
        root, spawn, request_check=lambda task_id, request: live["request"]
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    assert result["ok"] is False and result["reason"] == "terminal_dispatch_revoked"
    assert spawn.calls == 0
    assert (root / "note.txt").read_text() == "before"


@pytest.mark.asyncio
async def test_checkpoint_flag_default_off_keeps_local_execution(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.delenv("JARVIS_TERMINAL_CHECKPOINTS", raising=False)
    spawn = _Spawn(lambda: None)
    result = await _runner(root, spawn).run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    )
    assert result["ok"] is True and spawn.calls == 1
    assert "checkpoint" not in result


@pytest.mark.asyncio
async def test_trusted_origin_lookup_rechecked_after_capture(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    origin = {"value": ("00000000-0000-4000-8000-000000000001",
                        "00000000-0000-4000-8000-000000000002")}
    original = FileCheckpointHistory.begin_scope

    def capture_then_change(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        origin["value"] = None
        return result

    monkeypatch.setattr(FileCheckpointHistory, "begin_scope", capture_then_change)
    spawn = _Spawn(lambda: None)
    result = await _runner(
        root, spawn, checkpoint_origin_lookup=lambda task_id: origin["value"]
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    assert result["reason"] == "terminal_dispatch_revoked" and spawn.calls == 0


@pytest.mark.asyncio
async def test_timeout_reaps_before_postimage_capture(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    proc = _HangProc()

    async def spawn(*args, **kwargs):
        note.write_text("after", encoding="utf-8")
        return proc

    result = await _runner(root, spawn).run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        timeout=1, approved_task_id=12,
    )
    assert result["reason"] == "timeout" and proc.killed is True
    assert result["checkpoint"]["status"] == "finished"
    assert result["checkpoint"]["modified"] == 1


@pytest.mark.asyncio
async def test_cancellation_reaps_before_checkpoint_finalization(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    proc = _HangProc()
    spawned = asyncio.Event()

    async def spawn(*args, **kwargs):
        note.write_text("after", encoding="utf-8")
        spawned.set()
        return proc

    task = asyncio.create_task(_runner(root, spawn).run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    ))
    await asyncio.wait_for(spawned.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed is True
    groups = FileCheckpointHistory(SnapshotStore(), FileScope([root])).list_groups()
    assert len(groups) == 1 and groups[0]["status"] == "finished"


@pytest.mark.asyncio
async def test_sequential_verified_turn_reuses_first_root_preimage(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("original", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    def origin(task_id):
        return ("00000000-0000-4000-8000-000000000001",
                "00000000-0000-4000-8000-000000000002")
    first = await _runner(
        root, _Spawn(lambda: note.write_text("first", encoding="utf-8")),
        checkpoint_origin_lookup=origin,
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    second = await _runner(
        root, _Spawn(lambda: note.write_text("second", encoding="utf-8")),
        checkpoint_origin_lookup=origin,
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    assert first["ok"] and second["ok"]
    assert first["checkpoint"]["id"] == second["checkpoint"]["id"]
    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    assert len(history.list_groups()) == 1
    runs = history.list_group_runs(second["checkpoint"]["id"])
    assert len(runs) == 2
    assert all(run["target"] == "host" and len(run["argv_sha256"]) == 64
               and run["status"] == "finished" for run in runs)
    assert history.restore_group(second["checkpoint"]["id"])["status"] == "restored"
    assert note.read_text() == "original"


@pytest.mark.asyncio
async def test_trusted_birth_without_origin_is_labelled_task_scope(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    birth = "00000000-0000-4000-8000-000000000001"
    result = await _runner(
        root, _Spawn(lambda: None), checkpoint_origin_lookup=lambda task_id: (birth, None),
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    assert result["ok"] is True
    group = FileCheckpointHistory(SnapshotStore(), FileScope([root])).list_groups()[0]
    assert group["source_kind"] == "terminal_task"
    assert group["source_key"] == f"12:{birth}"


@pytest.mark.asyncio
async def test_owner_once_physical_cas_occurs_once_after_capture(tmp_path, monkeypatch):
    from agents.core.environments import owner_once_dispatch as gate
    from agents.core.file_checkpoint_history import FileCheckpointHistory

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    order = []
    original = FileCheckpointHistory.begin_scope

    def capture(self, *args, **kwargs):
        order.append("capture")
        return original(self, *args, **kwargs)

    async def spawn(*args, **kwargs):
        order.append("spawn")
        return _Proc()

    monkeypatch.setattr(FileCheckpointHistory, "begin_scope", capture)
    monkeypatch.setattr(gate, "_owner_current", lambda task_id: task_id == 12)

    def dispatch(task_id):
        order.append("dispatch")
        return task_id == 12

    monkeypatch.setattr(gate, "_owner_dispatch", dispatch)
    result = await _runner(root, spawn, authority="owner").run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    )
    assert result["ok"] is True
    assert order == ["capture", "dispatch", "spawn"]


@pytest.mark.asyncio
async def test_consent_physical_cas_occurs_once_after_capture(tmp_path, monkeypatch):
    from agents.core.autonomy import consent_execution
    from agents.core.file_checkpoint_history import FileCheckpointHistory

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    order = []
    original = FileCheckpointHistory.begin_scope

    def capture(self, *args, **kwargs):
        order.append("capture")
        return original(self, *args, **kwargs)

    async def spawn(*args, **kwargs):
        order.append("spawn")
        return _Proc()

    monkeypatch.setattr(FileCheckpointHistory, "begin_scope", capture)
    monkeypatch.setattr(consent_execution, "consent_current", lambda task_id: task_id == 12)

    def dispatch(task_id):
        order.append("dispatch")
        return task_id == 12

    monkeypatch.setattr(consent_execution, "consent_dispatch", dispatch)
    result = await _runner(root, spawn, authority="consent").run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    )
    assert result["ok"] is True
    assert order == ["capture", "dispatch", "spawn"]


@pytest.mark.asyncio
async def test_spawn_failure_leaves_no_process_group(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")

    async def missing(*args, **kwargs):
        raise FileNotFoundError

    result = await _runner(root, missing).run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    )
    assert result["reason"] == "executable_not_found"
    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    group = history.list_groups()[0]
    assert group["status"] == "no_process"
    assert history.plan_group_restore(group["id"])["ok"] is False


@pytest.mark.asyncio
async def test_postscan_failure_is_incomplete_and_never_restorable(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import CheckpointRefusal, FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    original = FileCheckpointHistory._scan_group
    count = {"value": 0}

    def fail_second_scan(self, *args, **kwargs):
        count["value"] += 1
        if count["value"] == 2:
            raise CheckpointRefusal("scope_scan_failed")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileCheckpointHistory, "_scan_group", fail_second_scan)
    result = await _runner(
        root, _Spawn(lambda: note.write_text("after", encoding="utf-8")),
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    assert result["ok"] is True and result["checkpoint"]["status"] == "incomplete"
    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    group = history.list_groups()[0]
    assert group["status"] == "incomplete"
    assert history.plan_group_restore(group["id"])["ok"] is False


@pytest.mark.asyncio
async def test_root_swap_inside_post_capture_recheck_never_spawns(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("same", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    captured = {"done": False, "swapped": False}
    original = FileCheckpointHistory.begin_scope

    def capture(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        captured["done"] = True
        return result

    def check(task_id, request):
        if captured["done"] and not captured["swapped"]:
            root.rename(tmp_path / "old-root")
            root.mkdir()
            (root / "note.txt").write_text("same", encoding="utf-8")
            captured["swapped"] = True
        return task_id == 12

    monkeypatch.setattr(FileCheckpointHistory, "begin_scope", capture)
    spawn = _Spawn(lambda: None)
    result = await _runner(root, spawn, request_check=check).run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    )
    assert result["ok"] is False and result["reason"] == "terminal_dispatch_revoked"
    assert spawn.calls == 0 and (root / "note.txt").read_text() == "same"


@pytest.mark.asyncio
async def test_cancel_during_blocked_precapture_returns_before_worker_release(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    entered, release = threading.Event(), threading.Event()
    original = FileCheckpointHistory.begin_scope

    def blocked_capture(self, *args, **kwargs):
        entered.set()
        assert release.wait(5), "test capture worker was not released"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileCheckpointHistory, "begin_scope", blocked_capture)
    spawn = _Spawn(lambda: None)
    loop = asyncio.get_running_loop()
    errors = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    task = asyncio.create_task(_runner(root, spawn).run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=0.75)
        returned_before_release = task in done
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    try:
        assert returned_before_release and spawn.calls == 0
        history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
        for _ in range(100):
            groups = history.list_groups()
            if groups and groups[0]["status"] == "no_process":
                break
            await asyncio.sleep(0.01)
        assert groups and groups[0]["status"] == "no_process"
        await asyncio.sleep(0)
        assert errors == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
@pytest.mark.parametrize("raise_finalizer", [False, True])
async def test_cancel_during_blocked_postscan_returns_original_cancellation(
    tmp_path, monkeypatch, raise_finalizer,
):
    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    entered, release = threading.Event(), threading.Event()
    original = FileCheckpointHistory.finish_scope

    def blocked_finish(self, *args, **kwargs):
        entered.set()
        assert release.wait(5), "test postscan worker was not released"
        if raise_finalizer:
            raise RuntimeError("synthetic postscan failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileCheckpointHistory, "finish_scope", blocked_finish)
    proc = _Proc()
    waits = {"count": 0}
    original_wait = proc.wait

    async def wait():
        waits["count"] += 1
        return await original_wait()

    proc.wait = wait

    async def spawn(*args, **kwargs):
        note.write_text("after", encoding="utf-8")
        return proc

    loop = asyncio.get_running_loop()
    errors = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    task = asyncio.create_task(_runner(root, spawn).run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert waits["count"] >= 1 and proc.returncode == 0
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=0.75)
        returned_before_release = task in done
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    try:
        assert returned_before_release
        history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
        expected = "incomplete" if raise_finalizer else "finished"
        for _ in range(100):
            groups = history.list_groups()
            if groups and groups[0]["status"] == expected:
                break
            await asyncio.sleep(0.01)
        assert groups and groups[0]["status"] == expected
        await asyncio.sleep(0)
        assert errors == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_iso_queue_birth_and_verified_turn_reuse_first_preimage(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("original", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    birth = "2026-10-04T06:00:00.123456+00:00"
    turn = "00000000-0000-4000-8000-000000000002"

    def trusted(_task_id):
        return birth, turn

    first = await _runner(
        root, _Spawn(lambda: note.write_text("first", encoding="utf-8")),
        checkpoint_origin_lookup=trusted,
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    second = await _runner(
        root, _Spawn(lambda: note.write_text("second", encoding="utf-8")),
        checkpoint_origin_lookup=trusted,
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    assert first["checkpoint"]["id"] == second["checkpoint"]["id"]
    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    group = history.list_groups()[0]
    assert group["source_kind"] == "terminal_turn" and group["source_key"] == turn
    assert history.restore_group(group["id"])["status"] == "restored"
    assert note.read_text() == "original"


@pytest.mark.asyncio
async def test_process_cancellation_does_not_wait_for_blocked_postscan(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    for name in ("JARVIS_TERMINAL_LOCAL_HOST", "JARVIS_ACTION_KERNEL",
                 "JARVIS_TERMINAL_CHECKPOINTS"):
        monkeypatch.setenv(name, "1")
    entered, release = threading.Event(), threading.Event()
    spawned = asyncio.Event()
    original = FileCheckpointHistory.finish_scope

    def blocked_finish(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileCheckpointHistory, "finish_scope", blocked_finish)
    proc = _HangProc()

    async def spawn(*args, **kwargs):
        (root / "note.txt").write_text("after", encoding="utf-8")
        spawned.set()
        return proc

    task = asyncio.create_task(_runner(root, spawn).run(
        target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
        approved_task_id=12,
    ))
    try:
        await asyncio.wait_for(spawned.wait(), 2)
        task.cancel()
        assert await asyncio.to_thread(entered.wait, 2)
        done, _ = await asyncio.wait({task}, timeout=0.75)
        returned_before_release = task in done
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    assert returned_before_release and proc.killed
    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    for _ in range(100):
        groups = history.list_groups()
        if groups and groups[0]["status"] == "finished":
            break
        await asyncio.sleep(0.01)
    assert groups and groups[0]["status"] == "finished"


@pytest.mark.asyncio
async def test_iso_queue_birth_drift_after_capture_prevents_spawn(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import FileCheckpointHistory

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    observation = {"value": ("2026-10-04T06:00:00.123456+00:00",
                             "00000000-0000-4000-8000-000000000002")}
    original = FileCheckpointHistory.begin_scope

    def capture_then_drift(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        observation["value"] = ("2026-10-04T06:00:01.123456+00:00",
                                "00000000-0000-4000-8000-000000000002")
        return result

    monkeypatch.setattr(FileCheckpointHistory, "begin_scope", capture_then_drift)
    spawn = _Spawn(lambda: None)
    result = await _runner(
        root, spawn, checkpoint_origin_lookup=lambda _id: observation["value"],
    ).run(target="host", agent="jarvis", command="rm note.txt", cwd=str(root),
          approved_task_id=12)
    assert result["reason"] == "terminal_dispatch_revoked" and spawn.calls == 0
