"""Register the ported board tools without ambient Hermes storage or authority.

Owner metadata edits run locally. A worker can edit only its live owned run;
launching workers, workspaces, goal judges and network fetches require their
separate Nerva bindings and are not silently enabled by this state/tool port.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from agents.core.capability_manifests import RollbackContract
from agents.core.tool_profiles import classify_turn
from agents.core.tool_rpc import current_tool_actor

from .context import KanbanContext, current_context, kanban_scope, scope_is_bound

READ_TOOLS = frozenset({"kanban_show", "kanban_attachments"})
ORCHESTRATOR_TOOLS = frozenset({"kanban_list", "kanban_unblock"})
_DELEGATED: ContextVar[bool] = ContextVar("nerva_kanban_delegated", default=False)


@contextmanager
def delegate_scope():
    """A child cannot recreate board authority from an inherited owner principal."""
    token = _DELEGATED.set(True)
    try:
        with kanban_scope(None):
            yield
    finally:
        _DELEGATED.reset(token)


def offer_allowed(name: str, posture: str, enabled: bool, *, network_enabled: bool = False) -> bool:
    if _DELEGATED.get():
        return False
    if name == "kanban_attach_url" and network_enabled is not True:
        return False
    context = current_context()
    if context is not None:
        return (context.can_mutate and not context.delegated
                and (context.task_id is None or name not in ORCHESTRATOR_TOOLS))
    return not scope_is_bound() and enabled is True and posture == "operator/owner"


def _validate_scope(context, name, args):
    if not context.can_mutate or context.delegated:
        raise PermissionError("Kanban scope cannot mutate")
    if context.profile != current_tool_actor():
        raise PermissionError("Kanban scope belongs to another agent")
    if context.task_id is not None:
        if args.get("board") not in (None, context.board):
            raise PermissionError("worker cannot switch boards")
        if name in ORCHESTRATOR_TOOLS:
            raise PermissionError("orchestrator tool is not available to a worker")
        if name != "kanban_create" and args.get("task_id") not in (None, context.task_id):
            raise PermissionError("worker cannot access another task")
        if name == "kanban_link" and args.get("child_id") != context.task_id:
            raise PermissionError("worker cannot change another task's dependencies")
        from .upstream import kanban_db as kb
        with kb.connect_closing() as conn:
            task = kb.get_task(conn, context.task_id)
            if (context.run_id is None or task is None
                    or task.current_run_id != context.run_id
                    or task.status not in {"running", "review"}):
                raise PermissionError("worker no longer owns the current run")
    if name == "kanban_create" and any(args.get(key) is not None for key in
            ("workspace_kind", "workspace_path", "project", "project_id")):
        raise ValueError("workspace/project adapter is not bound")
    if args.get("session_id") is not None:
        raise ValueError("session provenance is assigned by Nerva")


#: H399 — the board tools that may share a model step. Every other kanban tool changes the
#: board (create, comment, block, link, attach, heartbeat, …) and runs alone in a step.
#: ``kanban_list`` is here although it writes (``LIST_ROLLBACK``): its dependency catch-up
#: is one IMMEDIATE transaction and idempotent, so two listings, or a listing beside a
#: show, leave the board as either alone would. Parallel safety is not the effect label.
KANBAN_READ_TOOLS = frozenset({"kanban_list", "kanban_show", "kanban_attachments"})
#: H325 — what the capability registry says a board write leaves behind. The tools are
#: ungated, so without this the registry called every one of them read-only.
WRITE_ROLLBACK = RollbackContract(
    mode="compensate",
    description=("A later board call moves the task again (unblock, request changes, a new "
                 "comment or a completion); nothing is erased."),
    limitations=("The board keeps every comment, link, attachment and run event, so a write "
                 "is answered by another write, never undone."),
)
#: H325 review r2 — ``kanban_list`` is not a pure read: before listing it runs
#: ``kanban_db.recompute_ready`` (``tools._handle_list``), the catch-up the dispatcher tick
#: and the CLI list run, which writes task statuses and ``promoted`` events.
LIST_ROLLBACK = RollbackContract(
    mode="compensate",
    description=("Every listing first runs the board's dependency catch-up, the one the "
                 "dispatcher tick and the CLI list run: each todo task, and each blocked one "
                 "that is neither held for an operator nor at its failure limit, whose parents "
                 "are all done or archived (or that has none) moves to ready, or back to review "
                 "where it left off, and gets a 'promoted' event; the answer counts them in "
                 "`promoted`. A later board write answers it: linking a ready task under a "
                 "parent that is still open (kanban_link) gates it back to todo."),
    limitations=("The catch-up covers the whole board, not only the rows the filters return; "
                 "the 'promoted' events stay in the log; and a promoted task is dispatchable "
                 "from the next dispatcher tick, whose own catch-up would have promoted it."),
)
#: H325 — each board tool's ``(risk, rollback)``. A tool not named here writes the board
#: like the rest (``sensitive``/``WRITE_ROLLBACK``); the two pure reads leave every row of
#: the board database as it was (``tests/test_tool_surface.py`` runs them and checks).
KANBAN_EFFECTS = {
    "kanban_show": ("read_only", None),
    "kanban_attachments": ("read_only", None),
    "kanban_list": ("reversible", LIST_ROLLBACK),
}


def register_kanban_tools(server, *, home, enabled, principal, session_id=lambda: None,
                          profiles=lambda: ("jarvis",), network=lambda: None):
    from . import tools  # noqa: F401 -- registers the pinned schemas/handlers locally
    from .tool_compat import profiles_scope, registry

    for name, spec in registry.entries.items():
        def invoke(args, *, _name=name, _spec=spec):
            try:
                if _DELEGATED.get():
                    raise PermissionError("delegates have no board authority")
                context = current_context()
                if context is not None:
                    _validate_scope(context, _name, args)
                    if _name == "kanban_attach_url":
                        adapter = network()
                        if adapter is None:
                            raise ValueError("network attachment adapter is not bound")
                        return adapter.submit(args)
                    return json.loads(_spec["handler"](args))
                if (scope_is_bound() or enabled() is not True
                        or classify_turn(principal()).key != "operator/owner"):
                    raise PermissionError("Kanban is available to the owner or an assigned worker only")
                context = KanbanContext(home=Path(home()), profile=current_tool_actor(),
                                        can_mutate=True, session_id=session_id())
                with kanban_scope(context):
                    _validate_scope(context, _name, args)
                    if _name == "kanban_attach_url":
                        adapter = network()
                        if adapter is None:
                            raise ValueError("network attachment adapter is not bound")
                        return adapter.submit(args)
                    return json.loads(_spec["handler"](args))
            except (PermissionError, ValueError) as exc:
                return {"ok": False, "reason": "kanban_refused", "error": str(exc)}

        async def handler(args, *, _invoke=invoke):
            with profiles_scope(profiles()):
                return await asyncio.to_thread(_invoke, args)

        schema = spec["schema"]
        risk, rollback = KANBAN_EFFECTS.get(name, ("sensitive", WRITE_ROLLBACK))
        server.register_tool(name, handler, description=schema.get("description", ""),
                             input_schema=schema["parameters"], untrusted_output=True,
                             # H325 — an identity, so the capability board lists the
                             # board tools at all, under what they really do.
                             capability_id=f"tool:{name}",
                             parallel_safe=None if name in KANBAN_READ_TOOLS else False,
                             risk=risk, rollback=rollback)
