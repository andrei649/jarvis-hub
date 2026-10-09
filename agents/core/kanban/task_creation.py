"""Owner workspace/task metadata creation, with validation in the board transaction."""

from . import dispatch_store
from .context import require_mutation
from .upstream import kanban_db as kb


def create_task(conn, **kwargs):
    """Keep the donor's full task semantics; roll back invalid workspace anchors.

    Planning is read-only. No directory, Git worktree, worker or provider is
    created until the later signed proposal is approved and consumed.
    """
    context = require_mutation()
    if context.task_id is not None or context.run_id is not None:
        raise PermissionError("owner task creation requires an unbound request scope")
    with kb.write_txn(conn, allow_nested=True):
        task_id = kb.create_task(conn, **kwargs)
        dispatch_store.workspace_snapshot(conn, task_id)
    return task_id
