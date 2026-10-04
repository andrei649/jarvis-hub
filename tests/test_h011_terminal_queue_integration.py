"""Actual producer, owner decision, worker, coordinator and synthetic local spawn."""

import uuid

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.commands import Principal
from agents.core.environments.local_transport import LocalHostTransport
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore
from tests.test_h277_smart_terminal_integration import runtime, use_real_kernel  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [None, "birth", "association"])
async def test_actual_queue_origin_reaches_checkpoint_without_grant(
    runtime, tmp_path, monkeypatch, mutation,
):
    queue, worker, orch, _sandbox, _seen = runtime
    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    calls = []

    class Stream:
        async def read(self, count):
            return b""

    class Process:
        stdout = Stream()
        stderr = Stream()
        returncode = 0

        async def wait(self):
            return 0

    async def spawn(*argv, **kwargs):
        calls.append(argv)
        note.write_text("after", encoding="utf-8")
        return Process()

    monkeypatch.setattr(LocalHostTransport, "from_env", classmethod(
        lambda cls, **kwargs: cls([root], spawn=spawn)))
    # A real physical host hop needs the worker's current kernel revalidator;
    # a GRANT-only fixture proves provenance but cannot authorize dispatch.
    use_real_kernel(runtime)
    turn = open_approval_turn(session_id="chat", session_instance="instance",
                             principal=Principal(channel="web", admin=True),
                             session_is_live=lambda *_: True)
    token = bind_approval_turn(turn)
    try:
        answer = await orch.tool_rpc.handle({"tool": "terminal_run", "args": {
            "target": "local-host", "command": "rm note.txt", "cwd": str(root),
        }}, actor="jarvis")
    finally:
        close_approval_turn(turn, token)
    task_id = answer["task_id"]
    task = queue.get(task_id)
    assert task.status == "blocked" and calls == []
    assert "T" in task.created_at
    assert queue.checkpoint_origin_turn(task_id, task.created_at) == turn.turn_id
    if mutation:
        original = FileCheckpointHistory.begin_scope

        def capture_then_revoke(self, *args, **kwargs):
            captured = original(self, *args, **kwargs)
            if mutation == "birth":
                queue._conn.execute("UPDATE tasks SET created_at=? WHERE id=?",
                                    (task.created_at + "replacement", task_id))
            else:
                queue._conn.execute("UPDATE chat_approval_tasks SET ready=0 WHERE task_id=?",
                                    (task_id,))
            queue._conn.commit()
            return captured

        monkeypatch.setattr(FileCheckpointHistory, "begin_scope", capture_then_revoke)
    await worker.apply_decision(task_id, "accept", "user")
    await worker.tick()
    completed = queue.get(task_id)
    assert completed.status == "done", completed.result
    if mutation:
        assert calls == [] and note.read_text() == "before"
        assert completed.result["reason"] == "terminal_dispatch_revoked"
        group = FileCheckpointHistory(SnapshotStore(), FileScope([root])).list_groups()[0]
        assert group["status"] == "no_process"
        return
    assert calls == [("rm", "note.txt")], completed.result
    group = FileCheckpointHistory(SnapshotStore(), FileScope([root])).list_groups()[0]
    assert group["source_kind"] == "terminal_turn"
    assert group["source_key"] == str(uuid.UUID(hex=turn.turn_id))
    assert group["status"] == "finished"
    assert completed.result["result"]["checkpoint"]["modified"] == 1
