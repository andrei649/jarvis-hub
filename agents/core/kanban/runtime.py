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
        server.register_tool(name, handler, description=schema.get("description", ""),
                             input_schema=schema["parameters"], untrusted_output=True)
