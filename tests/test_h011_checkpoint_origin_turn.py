"""Checkpoint grouping observes durable server provenance without granting anything."""

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
    tool_approval_scope,
)
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.commands import Principal


@pytest.fixture
def queue(tmp_path):
    value = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    yield value
    value.close()


def enqueue(queue, *, tool="terminal_run", governed=True):
    turn = open_approval_turn(session_id="session", session_instance="instance",
                              principal=Principal(channel="web", admin=True),
                              session_is_live=lambda *_: True)
    token = bind_approval_turn(turn)
    try:
        with tool_approval_scope(tool):
            if governed:
                task_id = AutonomyWorker(queue).govern_enqueue(
                    "jarvis", "toolrpc." + tool, "Synthetic task",
                    payload={"args": {"argv": ["rm", "synthetic.txt"]}},
                    attention_mode="none",
                )
            else:
                task_id = queue.enqueue("jarvis", "toolrpc." + tool, "Unfinished task")
    finally:
        close_approval_turn(turn, token)
    return task_id, turn.turn_id


def test_closed_chat_origin_is_read_only_and_survives_queue_restart(queue):
    task_id, origin = enqueue(queue)
    task = queue.get(task_id)
    before = queue._conn.total_changes
    assert queue.checkpoint_origin_turn(task_id, task.created_at) == origin
    assert queue._conn.total_changes == before
    assert queue.get(task_id) == task and task.status == "blocked"
    queue.transition(task_id, TaskStatus.APPROVED, decided_by="web", decision="accept")
    restarted = TaskQueue(queue.db_path).initialize()
    try:
        assert restarted.checkpoint_origin_turn(task_id, task.created_at) == origin
        assert restarted.get(task_id).status == "approved"
    finally:
        restarted.close()


def test_stale_birth_and_same_byte_task_edit_have_no_turn(queue):
    task_id, _ = enqueue(queue)
    task = queue.get(task_id)
    assert queue.checkpoint_origin_turn(task_id, task.created_at + "replacement") is None
    queue.update_payload(task_id, task.payload)
    assert queue.checkpoint_origin_turn(task_id, task.created_at) is None


@pytest.mark.parametrize("tool,governed", [("terminal_run", False), ("file_write", True)])
def test_raw_unready_and_nonterminal_associations_have_no_turn(queue, tool, governed):
    task_id, _ = enqueue(queue, tool=tool, governed=governed)
    assert queue.checkpoint_origin_turn(task_id, queue.get(task_id).created_at) is None


def test_malformed_server_origin_is_not_a_grouping_key(queue):
    task_id, _ = enqueue(queue)
    task = queue.get(task_id)
    queue._conn.execute("UPDATE chat_approval_origins SET origin_id='malformed'")
    queue._conn.execute("UPDATE chat_approval_tasks SET origin_id='malformed'")
    queue._conn.commit()
    assert queue.checkpoint_origin_turn(task_id, task.created_at) is None


@pytest.mark.parametrize("task_id,birth", [(True, "x"), ("1", "x"), (0, "x"), (1, None)])
def test_invalid_or_missing_observation_arguments_refuse(queue, task_id, birth):
    assert queue.checkpoint_origin_turn(task_id, birth) is None
    assert queue.checkpoint_origin_turn(999999, "absent") is None
