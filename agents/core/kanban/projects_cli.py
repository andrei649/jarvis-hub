"""Authenticated Nerva adapter for the pinned Hermes project command tree."""

from __future__ import annotations

import argparse
import sys

from agents.core.commands import CommandContext
from agents.core.paths import data_path

from .cli_upstream.board_selection import selected_board
from .cli_upstream.projects_commands import build_parser, projects_command
from .cli_upstream.sink import capture, emit
from .context import KanbanContext, current_context, kanban_scope, scope_is_bound
from .runtime import _DELEGATED


class _Usage(Exception):
    pass


class _Exit(Exception):
    def __init__(self, code):
        self.code = code


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)

    def exit(self, status=0, message=None):
        if message:
            emit(message, end="")
        raise _Exit(status)

    def _print_message(self, message, file=None):
        if message:
            emit(message, end="", file=file)


def _result(code: int, out: str, err: str = "", reason: str | None = None):
    output = "\n".join(part for part in (out.rstrip(), err.rstrip()) if part)
    answer = {"ok": code == 0, "exit_code": code, "output": output}
    if reason:
        answer["reason"] = reason
    return answer


def _refused(reason: str, detail: str | None = None, code: int = 1):
    return _result(code, "", detail or f"project: {reason}", reason)


def _owner(principal) -> bool:
    channel = str(getattr(principal, "channel", "") or "").strip().lower()
    return bool(getattr(principal, "admin", False)) and channel not in {"", "internal", "system"}


async def execute_command(orch, argv, principal, session_id=None, profile="owner", *, owner_command=None):
    """Execute one owner metadata command against the scoped projects DB."""
    if not isinstance(argv, (list, tuple)) or any(not isinstance(item, str) for item in argv):
        return _refused("invalid_argv", code=2)
    try:
        lengths = [len(item.encode("utf-8")) for item in argv]
    except UnicodeError:
        return _refused("invalid_argv", code=2)
    if len(argv) > 128 or any(size > 8192 for size in lengths) or sum(lengths) > 65536:
        return _refused("argv_too_large", code=2)
    if not isinstance(profile, str) or profile != "owner" or (session_id is not None and not isinstance(session_id, str)):
        return _refused("invalid_identity", code=2)
    if not _owner(principal):
        return _refused("owner_required")
    if owner_command is not None and (not isinstance(owner_command, CommandContext)
                                     or owner_command.name != "project"
                                     or owner_command.orch is not orch or owner_command.principal is not principal):
        return _refused("owner_required")
    if _DELEGATED.get():
        return _refused("delegated_scope")
    try:
        enabled = orch.get_setting("llm.kanban", False) is True
    except Exception:
        enabled = False
    if not enabled:
        return _refused("board_disabled")
    inherited = current_context()
    if scope_is_bound() and inherited is None:
        return _refused("expired_scope")
    if inherited and (inherited.delegated or inherited.task_id is not None or inherited.run_id is not None
                      or not inherited.can_mutate or inherited.profile != "owner"):
        return _refused("worker_scope")
    with capture() as (out, err):
        root = _Parser(prog="nerva", add_help=False)
        build_parser(root.add_subparsers(dest="_root", parser_class=_Parser))
        try:
            args = root.parse_args(["project", *argv])
        except _Exit as exc:
            return _result(exc.code, out.getvalue(), err.getvalue(), "usage" if exc.code else None)
        except _Usage as exc:
            emit(f"project: {exc}", file=sys.stderr)
            return _result(2, out.getvalue(), err.getvalue(), "usage")
        home = inherited.home if inherited else data_path("kanban")
        base = inherited or KanbanContext(home, "owner", board=selected_board(home),
                                         can_mutate=True, session_id=session_id)
        context = KanbanContext(base.home, "owner", board=base.board, session_id=base.session_id or session_id,
                                can_mutate=True)
        with kanban_scope(context):
            try:
                code = projects_command(args)
                return _result(code, out.getvalue(), err.getvalue(), "command_failed" if code else None)
            except (ValueError, PermissionError, RuntimeError, NotImplementedError, OSError) as exc:
                return _refused("command_failed", f"project: {exc}")
