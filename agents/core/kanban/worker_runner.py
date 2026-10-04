"""Run one controller-approved Kanban worker turn under its claimed board scope."""

from __future__ import annotations

import sqlite3
from contextlib import ExitStack, closing

from agents.core.action_origin import bind_action_origin, reset_action_origin
from agents.core.commands import Principal
from agents.core.llm.job_selection import _selection, selection_scope
from agents.core.llm.request_context import (
    _reasoning,
    reasoning_scope,
    request_overrides_scope,
    session_scope,
)
from agents.core.steering import steering_scope
from agents.core.turn_approvals import _turn_approvals

from .context import current_context


class WorkerTurnRefused(RuntimeError):
    """A worker cannot prove the requested turn belongs to its live board run."""


def _check_ownership(context):
    """Read the current board row without creating a missing board."""
    from .upstream import kanban_db as kb

    if current_context() is not context:
        raise WorkerTurnRefused("Kanban worker scope is no longer active")
    try:
        path = kb.kanban_db_path(board=context.board)
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            task = kb.get_task(conn, context.task_id)
            run = kb.get_run(conn, context.run_id)
    except (OSError, sqlite3.Error, ValueError, PermissionError) as exc:
        raise WorkerTurnRefused("Kanban worker board cannot be verified") from exc
    if (
        task is None
        or run is None
        or task.status != "running"
        or task.current_run_id != context.run_id
        or run.id != context.run_id
        or run.task_id != context.task_id
        or run.status != "running"
        or run.profile != context.profile
    ):
        raise WorkerTurnRefused("Kanban worker no longer owns the current run")
    return task


async def run_worker_turn(orch, *, prompt: str, agent_id: str, session_id: str) -> str:
    """Execute the exact configured agent in its own session and live Kanban run.

    The trusted controller binds ``KanbanContext`` and holds the execution
    permit. This function neither creates board authority nor borrows an
    approval from the parent turn.
    """
    context = current_context()
    if (
        context is None
        or not context.can_mutate
        or context.delegated
        or not context.task_id
        or type(context.run_id) is not int
        or not session_id
        or context.session_id != session_id
        or context.profile != agent_id
        or not prompt
        or not prompt.strip()
        or agent_id not in orch.agents
        or session_id == getattr(orch, "_session_id_default", None)
    ):
        raise WorkerTurnRefused("Kanban worker identity or configured agent is invalid")

    _check_ownership(context)
    async with orch.turn_lease(session_id) as acquired:
        if not acquired:
            raise WorkerTurnRefused("Kanban worker session is busy")
        task = _check_ownership(context)

        # Deferred: the orchestrator may import this runner while composing its
        # coordinator, before these context variables are defined.
        from agents.core.autonomy_coordinator import _APPROVED_TASK
        from agents.core.orchestrator import (
            _active_session,
            _session_is_shared,
            bind_turn_principal,
            reset_turn_principal,
        )

        # Every binding is context-local. ExitStack reverses all tokens even when
        # a provider fails or the coroutine is cancelled during the model call.
        with ExitStack() as stack:

            def reset(variable, value):
                token = variable.set(value)
                stack.callback(variable.reset, token)

            reset(_active_session, session_id)
            reset(_session_is_shared, False)
            stack.enter_context(session_scope(session_id))
            stack.callback(reset_turn_principal, bind_turn_principal(Principal(channel="internal")))
            stack.callback(reset_action_origin, bind_action_origin("generated"))
            reset(_selection, None)
            reset(_reasoning, None)
            stack.enter_context(request_overrides_scope(None))
            stack.enter_context(steering_scope(None))
            reset(_APPROVED_TASK, None)
            reset(_turn_approvals, None)

            pins = {}
            if task.model_override is not None:
                pins["model"] = task.model_override
            if task.provider_override is not None:
                pins["provider"] = task.provider_override
            try:
                selection = stack.enter_context(selection_scope(pins))
                stack.enter_context(reasoning_scope(task.reasoning_effort))
                if selection is not None:
                    router = getattr(orch, "llm_router", None)
                    if not callable(getattr(router, "select_backend", None)):
                        raise WorkerTurnRefused("task model pins require the governed model router")
                    router.select_backend(agent_id, prompt)
                    if selection.lifetime.resolved is None:
                        raise WorkerTurnRefused(
                            "task model pins were not resolved by the governed router"
                        )
            except Exception as exc:
                raise WorkerTurnRefused(f"task model selection refused: {exc}") from exc

            text, error = await orch.process_detailed(prompt, agent=agent_id, channel="internal")
            if error is not None or not isinstance(text, str) or not text.strip():
                raise WorkerTurnRefused(str(error or "empty worker reply"))
            return text
