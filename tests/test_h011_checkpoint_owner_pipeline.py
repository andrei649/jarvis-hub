"""Owner commands must reach signed approval, real kernel, files and conversation."""

import hashlib
import hmac
import json
import shlex
from contextlib import asynccontextmanager

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.checkpoint import CheckpointManager
from agents.core.commands import build_default_registry
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, FileTools, SnapshotStore
from agents.core.kernel.binding import make_action_kernel
from agents.core.memory import conversation, persistence
from agents.core.memory.manager import MemoryManager
from agents.core.orchestrator import Orchestrator
from agents.core.security.capability import KillSwitch
from agents.core.turn_approvals import open_turn_approvals, reset_turn_approvals
from tests.test_h011_owner_checkpoint_commands import GUEST, command
from tests.test_h277_video_analysis import _head_anchor


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["checkpoint.restore", "checkpoint.maintenance"])
async def test_real_coordinator_routes_checkpoint_tasks_to_controller_instead_of_llm(monkeypatch, kind):
    from tests.test_web_tools_wiring import _coordinator, _task

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "0")
    executor = _coordinator({}).build_executor()
    result = await executor.execute(_task(kind, {}))
    assert result["status"] == "refused" and result["reason"] == "approval_executor_unavailable"


@asynccontextmanager
async def make_pipeline(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(root))
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "sessions.db"))
    cp.initialize()
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    sid = await memory.new_session("approved_checkpoint")
    for role, text in [("user", "keep"), ("assistant", "kept answer"),
                       ("user", "current edit"), ("assistant", "current answer")]:
        await memory.add_turn(sid, role, text)
    signer = DetachedHMACSigner(lambda data: hmac.new(b"fixture", data, hashlib.sha256).hexdigest())
    queue_path = tmp_path / "queue.db"
    queue = TaskQueue(str(queue_path), mediation_signer=signer,
                      mediation_head_anchor=_head_anchor(queue_path),
                      mediation_scope="global", mediation_mode="enforce").initialize()
    worker = AutonomyWorker(queue)
    orch = Orchestrator.__new__(Orchestrator)
    orch._session_id_default = sid
    orch.memory, orch.checkpoints = memory, cp
    orch.commands = build_default_registry()
    orch.autonomy, orch.autonomy_queue = worker, queue
    orch.get_setting = lambda _key, default=None: default
    orch.kill_switch = KillSwitch(tmp_path / "halt.json")
    worker.bind_mediation(make_action_kernel(orch), signer)

    async def execute(task):
        from agents.core.checkpoint_controller import CheckpointController
        return await CheckpointController(orch).execute(task)

    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register("checkpoint.restore", execute)
    executor.register("checkpoint.maintenance", execute)
    worker.executor = executor.execute
    yield orch, root, SnapshotStore(), sid
    if worker._bg_tasks:
        import asyncio
        await asyncio.gather(*worker._bg_tasks, return_exceptions=True)
    queue.close()
    cp.close()


@pytest.fixture
async def pipeline(tmp_path, monkeypatch):
    async with make_pipeline(tmp_path, monkeypatch) as value:
        yield value


async def request(orch, text):
    pending, token = open_turn_approvals()
    try:
        outcome, notices = await command(orch, text)
        assert [n["code"] for n in notices] == ["checkpoint.queued"], outcome.reply
        answer = json.loads(outcome.reply)
        assert answer["ok"] and answer["status"] == "queued"
        assert pending == [answer["task_id"]]
        return answer["task_id"]
    finally:
        reset_turn_approvals(token)


async def checkpoint(root, snapshots, *, group=False, name="note.txt"):
    note = root / name
    note.write_text("before")
    scope = FileScope([root])
    if group:
        history = FileCheckpointHistory(snapshots, scope)
        capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
        note.write_text("after")
        assert history.finish_scope(capture["id"], reaped=True)["status"] == "finished"
        return note, "group:" + capture["id"]
    tools = FileTools(scope, snapshots=snapshots)
    assert (await tools.write_file({"path": str(note), "content": "after"}, approved=True))["ok"]
    return note, "file:" + str(tools.history.list_entries()[0]["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_owner_approval_restores_real_files_and_only_current_last_user_exchange(pipeline, group):
    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots, group=group)
    audit = (persistence.MEMORY_DIR / f"{sid}.jsonl").read_bytes()
    task_id = await request(orch, "/rollback " + identifier + " --execute")
    task = orch.autonomy_queue.get(task_id)
    assert task.status == "blocked" and task.risk_tier == 1
    assert note.read_text() == "after"
    assert len(await orch.memory.get_history(sid)) == 4
    assert not orch.memory._rollback_tickets
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    await orch.autonomy.tick()
    completed = orch.autonomy_queue.get(task_id)
    assert completed.result["status"] == "ok", completed.result
    assert note.read_text() == "before"
    assert [r["content"] for r in await orch.memory.get_history(sid)] == ["keep", "kept answer"]
    assert (persistence.MEMORY_DIR / f"{sid}.jsonl").read_bytes() == audit
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(orch.checkpoints)
    assert [r["content"] for r in await restarted.get_history(sid)] == ["keep", "kept answer"]
    assert not orch.memory._rollback_tickets


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["halt", "ask", "off", "tail", "root_config", "kernel_off"])
async def test_revocation_between_approval_and_tick_never_restores_or_rewinds(pipeline, monkeypatch, revocation):
    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots)
    task_id = await request(orch, "/checkpoints restore " + identifier + " --execute")
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    if revocation == "halt":
        orch.kill_switch.engage("global", "stop")
    elif revocation in {"ask", "off"}:
        orch.autonomy.policy.mode = revocation
    elif revocation == "tail":
        await orch.memory.add_turn(sid, "user", "new unrelated request")
    elif revocation == "root_config":
        monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root.parent))
        monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(root.parent))
    else:
        monkeypatch.setenv("JARVIS_ACTION_KERNEL", "0")
    before = await orch.memory.get_history(sid)
    await orch.autonomy.tick()
    assert note.read_text() == "after"
    assert await orch.memory.get_history(sid) == before
    assert orch.autonomy_queue.get(task_id).result.get("status") != "ok"
    assert not orch.memory._rollback_tickets


@pytest.mark.asyncio
async def test_maintenance_requires_real_human_task_and_preserves_files_chat_and_shared_blobs(pipeline):
    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots, group=True)
    # Index-only maintenance continues to retain payloads until its approved GC
    # lane is implemented. A terminal group now writes in the owned namespace.
    blob_dir = snapshots.directory / "checkpoint_payloads-v1" / "blobs"
    blobs = {p.name: p.read_bytes() for p in blob_dir.iterdir()}
    before = await orch.memory.get_history(sid)
    task_id = await request(orch, "/checkpoints clear --execute")
    assert orch.autonomy_queue.get(task_id).risk_tier == 3
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    await orch.autonomy.tick()
    result = orch.autonomy_queue.get(task_id).result
    assert result["status"] == "ok", result
    assert result["filesystem"]["removed"] == [identifier]
    assert note.read_text() == "after" and await orch.memory.get_history(sid) == before
    assert {p.name: p.read_bytes() for p in blob_dir.iterdir()} == blobs


@pytest.mark.asyncio
async def test_owner_guest_cannot_queue_or_probe_effect_store(pipeline):
    orch, root, snapshots, _sid = pipeline
    note, identifier = await checkpoint(root, snapshots)
    outcome, notices = await command(orch, "/rollback " + shlex.quote(identifier) + " --execute", GUEST)
    assert outcome.status == "refused" and not notices
    assert orch.autonomy_queue.pending_decisions() == []
    assert not (snapshots.directory / "checkpoint_operations.sqlite3").exists()
    assert note.read_text() == "after"


@pytest.mark.asyncio
@pytest.mark.parametrize("late_change", [False, True])
async def test_force_requires_exact_accepted_current_bytes_and_retains_preundo(pipeline, late_change):
    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots)
    note.write_text("owner overwrite")
    task_id = await request(orch, "/rollback " + identifier + " --force --execute")
    assert orch.autonomy_queue.get(task_id).risk_tier == 3
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    if late_change:
        note.write_text("later unrelated owner bytes")
    before = await orch.memory.get_history(sid)
    await orch.autonomy.tick()
    result = orch.autonomy_queue.get(task_id).result
    if late_change:
        assert result["status"] != "ok"
        assert note.read_text() == "later unrelated owner bytes"
        assert await orch.memory.get_history(sid) == before
    else:
        assert result["status"] == "ok", result
        assert note.read_text() == "before"
        history = FileCheckpointHistory(snapshots, FileScope([root]))
        undo = history.load_snapshot(result["filesystem"]["undo_snapshot_ref"])
        assert undo is not None and history.snapshot_blob(undo) == b"owner overwrite"


@pytest.mark.asyncio
async def test_instruction_restore_keeps_tier_three_and_real_human_receipt(pipeline):
    orch, root, snapshots, _sid = pipeline
    note, identifier = await checkpoint(root, snapshots, group=True, name="SOUL.md")
    task_id = await request(orch, "/rollback " + identifier + " --execute")
    task = orch.autonomy_queue.get(task_id)
    assert task.risk_tier == 3 and task.payload["preview"]["instruction_sensitive_paths"] == ["SOUL.md"]
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    await orch.autonomy.tick()
    assert orch.autonomy_queue.get(task_id).result["status"] == "ok"
    assert note.read_text() == "before"


@pytest.mark.asyncio
async def test_raw_running_task_copy_and_neighbor_kind_cannot_authorize_restore(pipeline):
    from agents.core.checkpoint_controller import CheckpointController

    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots)
    task_id = await request(orch, "/rollback " + identifier + " --execute")
    forged = orch.autonomy_queue.get(task_id)
    forged.status, forged.decision, forged.decided_by = "running", "accept", "user"
    controller = CheckpointController(orch)
    assert (await controller.execute(forged))["status"] == "refused"
    forged.kind = "checkpoint.restore.evil"
    assert (await controller.execute(forged))["status"] == "refused"
    assert note.read_text() == "after" and len(await orch.memory.get_history(sid)) == 4


@pytest.mark.asyncio
async def test_running_operation_from_interrupted_attempt_never_automatically_replays(pipeline):
    from agents.core.checkpoint_operations import CheckpointOperationStore

    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots)
    task_id = await request(orch, "/rollback " + identifier + " --execute")
    task = orch.autonomy_queue.get(task_id)
    journal = CheckpointOperationStore(snapshots)
    assert journal.claim(task.payload["request_id"], task_id=task.id,
                         intent_sha=task.payload["intent_sha"])["ok"]
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    await orch.autonomy.tick()
    result = orch.autonomy_queue.get(task_id).result
    assert result["status"] == "refused" and result["reason"] == "operation_in_flight"
    assert note.read_text() == "after" and len(await orch.memory.get_history(sid)) == 4


@pytest.mark.asyncio
async def test_partial_group_late_halt_preserves_conversation_and_durable_undo(pipeline, monkeypatch):
    import agents.core.file_checkpoint_history as module

    orch, root, snapshots, sid = pipeline
    first, second = root / "a.txt", root / "b.txt"
    first.write_text("before a")
    second.write_text("before b")
    history = FileCheckpointHistory(snapshots, FileScope([root]))
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    first.write_text("after a")
    second.write_text("after b")
    history.finish_scope(capture["id"], reaped=True)
    task_id = await request(orch, "/rollback group:" + capture["id"] + " --execute")
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    original = module._replace

    def halt_after_first(parent, name, data, mode):
        original(parent, name, data, mode)
        orch.kill_switch.engage("global", "late stop")

    monkeypatch.setattr(module, "_replace", halt_after_first)
    before = await orch.memory.get_history(sid)
    await orch.autonomy.tick()
    result = orch.autonomy_queue.get(task_id).result
    assert result["status"] == "partial", result
    assert first.read_text() == "before a" and second.read_text() == "after b"
    assert result["filesystem"]["restored"] == 1
    assert result["filesystem"]["undo_snapshot_refs"]
    assert await orch.memory.get_history(sid) == before and not orch.memory._rollback_tickets


@pytest.mark.asyncio
async def test_failed_conversation_commit_reports_file_chat_split_and_keeps_undo(pipeline, monkeypatch):
    from agents.core.memory.manager import RewindRefused

    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots)
    task_id = await request(orch, "/rollback " + identifier + " --execute")
    await orch.autonomy.apply_decision(task_id, "accept", "user")

    async def failed_commit(_ticket):
        raise RewindRefused("synthetic persistence failure")

    monkeypatch.setattr(orch.memory, "commit_rollback_rewind", failed_commit)
    before = await orch.memory.get_history(sid)
    await orch.autonomy.tick()
    result = orch.autonomy_queue.get(task_id).result
    assert result["status"] == "partial" and result["reason"] == "conversation_rewind_not_committed"
    assert note.read_text() == "before" and result["filesystem"]["undo_snapshot_ref"]
    assert await orch.memory.get_history(sid) == before and not orch.memory._rollback_tickets


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["history_instance", "forbid_clock_seeding"])
async def test_physical_fence_reads_exact_persisted_identity_without_clock_writes(pipeline, monkeypatch, change):
    from agents.core.checkpoint_operations import CheckpointOperationStore

    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots)
    task_id = await request(orch, "/rollback " + identifier + " --execute")
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    original = CheckpointOperationStore.claim

    def change_after_claim(store, *args, **kwargs):
        result = original(store, *args, **kwargs)
        if change == "history_instance":
            with orch.checkpoints._lock, orch.checkpoints._conn:
                orch.checkpoints._conn.execute(
                    "UPDATE session_history_instances SET instance_id=? WHERE session_id=?",
                    ("revoked-history-identity", sid))
        else:
            def forbidden_seed(_sid):
                raise AssertionError("physical approval checks must not seed/update clocks")
            monkeypatch.setattr(orch.checkpoints, "clock_snapshot", forbidden_seed)
        return result

    monkeypatch.setattr(CheckpointOperationStore, "claim", change_after_claim)
    await orch.autonomy.tick()
    result = orch.autonomy_queue.get(task_id).result
    if change == "history_instance":
        assert note.read_text() == "after", "revoked durable identity must stop the file effect"
        assert result["status"] != "ok"
    else:
        assert result["status"] == "ok", result
        assert note.read_text() == "before"


@pytest.mark.asyncio
async def test_actual_cli_web_owner_restore_queues_then_worker_restores_without_command_append(pipeline, monkeypatch, tmp_path):
    import asyncio
    import io

    from starlette.requests import Request

    from agents import web
    from agents.cli.nerva import EXIT_FAILED, Context, main
    from agents.core.security.token_store import TokenStore

    orch, root, snapshots, sid = pipeline
    note, identifier = await checkpoint(root, snapshots)
    monkeypatch.setenv("JARVIS_KEEP_AWAKE", "0")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "fixture-owner-token")
    tokens = TokenStore(str(tmp_path / "tokens.sqlite3"))
    monkeypatch.setattr(web, "get_token_store", lambda: tokens)
    monkeypatch.setattr(web, "orch", orch)
    req = Request({"type": "http", "method": "POST", "path": "/chat",
                   "headers": [(b"x-admin-token", b"fixture-owner-token")],
                   "client": ("127.0.0.1", 43123), "scheme": "http"})
    loop = asyncio.get_running_loop()
    responses = []

    class InProcessHub:
        base_url = "http://127.0.0.1:8080"

        def post(self, path, body):
            assert path == "/chat"
            response = asyncio.run_coroutine_threadsafe(
                web.chat(web.ChatRequest(message=body["message"]), req), loop).result(timeout=10)
            responses.append(response.model_dump())
            return responses[-1]

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, client_factory=lambda _: InProcessHub())
    before = await orch.memory.get_history(sid)
    code = await asyncio.to_thread(main, ["checkpoints", "restore", identifier, "--execute"], context=ctx)
    assert code == EXIT_FAILED and not out.getvalue() and err.getvalue()
    assert [n["code"] for n in responses[0]["notices"]] == ["checkpoint.queued"]
    task_id, = responses[0]["pending_approvals"]
    assert note.read_text() == "after" and await orch.memory.get_history(sid) == before
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    await orch.autonomy.tick()
    assert orch.autonomy_queue.get(task_id).result["status"] == "ok"
    assert note.read_text() == "before"
    assert [r["content"] for r in await orch.memory.get_history(sid)] == ["keep", "kept answer"]


@pytest.mark.asyncio
async def test_memory_rewire_revokes_effect_and_discards_ticket_from_original_manager(pipeline, monkeypatch):
    from agents.core.checkpoint_operations import CheckpointOperationStore

    orch, root, snapshots, sid = pipeline
    original_memory = orch.memory
    note, identifier = await checkpoint(root, snapshots)
    task_id = await request(orch, "/rollback " + identifier + " --execute")
    await orch.autonomy.apply_decision(task_id, "accept", "user")
    original_claim = CheckpointOperationStore.claim
    replacement = MemoryManager()
    replacement.set_checkpoint_manager(orch.checkpoints)

    def rewire_after_claim(store, *args, **kwargs):
        record = original_claim(store, *args, **kwargs)
        orch.memory = replacement
        return record

    monkeypatch.setattr(CheckpointOperationStore, "claim", rewire_after_claim)
    await orch.autonomy.tick()
    assert note.read_text() == "after"
    assert not original_memory._rollback_tickets
    assert len(await original_memory.get_history(sid)) == 4
