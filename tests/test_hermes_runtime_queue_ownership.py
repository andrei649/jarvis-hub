"""The generic agent executor cannot consume a private Hermes continuation."""

from agents.core.autonomy.queue import TaskQueue, TaskStatus


def test_hermes_approval_is_reserved_for_its_runtime_dispatcher(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    try:
        runtime = queue.enqueue("hermes", "hermes.runtime", "Exact pending RPC", {})
        ordinary = queue.enqueue("agent", "ordinary", "Ordinary work", {})
        for task in (runtime, ordinary):
            queue.transition(task, TaskStatus.APPROVED, decided_by="owner", decision="accept")
        assert [task.id for task in queue.runnable()] == [ordinary]
        assert queue.runnable(task_id=runtime) == []
        assert [task.id for task in queue.runnable(task_id=ordinary)] == [ordinary]
        assert queue.get(runtime).status == "approved"
    finally:
        queue.close()


def test_kind_filter_is_applied_before_the_list_limit(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    try:
        waiting = queue.enqueue("hermes", "hermes.runtime", "Pending Hermes operation", {})
        for index in range(101):
            queue.enqueue("agent", "ordinary", f"Other operation {index}", {})
        assert [task.id for task in queue.list(kind="hermes.runtime", limit=1)] == [waiting]
    finally:
        queue.close()
