"""Authenticated Nerva entry point for the pinned Hermes Kanban command tree."""

from __future__ import annotations

import argparse
from pathlib import Path

from agents.core.paths import data_path

from .cli_parser import build_parser
from .cli_upstream import boards, handlers, ops
from .cli_upstream.board_selection import selected_board
from .cli_upstream.sink import capture, emit
from .context import KanbanContext, current_context, kanban_scope, scope_is_bound
from .runtime import _DELEGATED
from .upstream import kanban_db as kb
from .upstream.compat import require_scoped_path


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
    return _result(code, "", detail or f"kanban: {reason}", reason)


def _owner(principal) -> bool:
    channel = str(getattr(principal, "channel", "") or "").strip().lower()
    return bool(getattr(principal, "admin", False)) and channel not in {"", "internal", "system"}


_UNBOUND = frozenset({
    "swarm", "claim", "reclaim",
    "tail", "daemon", "watch", "gc", "specify", "decompose",
    "notify-subscribe", "notify-unsubscribe", "heartbeat",
})
_UNBOUND_BOARD = frozenset({"set-default-workdir", "export", "import", "delete"})


def _parse(argv):
    root = _Parser(prog="nerva", add_help=False)
    build_parser(root.add_subparsers(dest="_root", parser_class=_Parser))
    try:
        return root.parse_args(["kanban", *argv]), None
    except _Exit as exc:
        return None, exc.code
    except _Usage as exc:
        return str(exc), 2


def _preflight(args, context):
    action = args.kanban_action
    if action in _UNBOUND:
        return f"kanban {action}: Nerva effect adapter is not bound"
    if action == "dispatch" and (args.dry_run or args.failure_limit != kb.DEFAULT_FAILURE_LIMIT):
        return "kanban dispatch: dry-run/failure-limit adapter is not bound"
    if action == "boards":
        sub = args.boards_action or "list"
        if sub in _UNBOUND_BOARD:
            return f"kanban boards {sub}: Nerva board/file adapter is not bound"
        if sub in {"rm", "remove"} and args.delete:
            return "kanban boards rm --delete: permanent deletion adapter is not bound"
        if sub in {"create", "new"} and args.default_workdir:
            return "kanban boards create: default-workdir adapter is not bound"
    if action == "create":
        if args.body_file is not None:
            if args.body_file == "-":
                return "kanban create: stdin body adapter is not bound"
            require_scoped_path(Path(args.body_file))
        if (args.workspace not in (None, "scratch") or args.branch or args.project
                or args.goal_mode or args.goal_max_turns is not None):
            return "kanban create: workspace/project/goal adapter is not bound"
        if args.skills:
            return "kanban create: worker skill injection adapter is not bound"
        if args.completion_contract not in (None, "local-only"):
            return "kanban create: GitHub/PR completion contract adapter is not bound"
        meta = kb.read_board_metadata(context.board)
        if meta.get("project_id") or meta.get("default_workdir"):
            return "kanban create: board project/workspace adapter is not bound"
    if action == "attach":
        require_scoped_path(Path(args.path))
    if action == "attach-rm":
        with kb.connect_closing() as conn:
            attachment = kb.get_attachment(conn, args.attachment_id)
        if attachment is not None:
            stored = Path(attachment.stored_path).resolve()
            if not stored.is_relative_to(kb.attachments_root().resolve()):
                return "kanban attach-rm: stored attachment path escapes this board"
    if action == "archive" and getattr(args, "purge_ids", None):
        return "kanban archive --rm: attachment deletion adapter is not bound"
    targets = []
    if action in {"complete", "archive", "unblock", "reopen-review"}:
        targets = list(getattr(args, "task_ids", ()) or ())
    elif action in {"block", "schedule", "promote"}:
        targets = [args.task_id, *(getattr(args, "ids", None) or ())]
    elif action == "link":
        targets = [args.child_id]
    elif action in {"edit", "assign", "set-model", "reassign", "request-review", "request-changes"}:
        targets = [args.task_id]
    if action == "reassign" and args.reclaim:
        return "kanban reassign --reclaim: active-worker reclaim adapter is not bound"
    if targets:
        with kb.connect_closing() as conn:
            for tid in targets:
                task = kb.get_task(conn, tid)
                if task is not None and (task.claim_lock or task.worker_pid):
                    return f"kanban {action}: active-worker transition adapter is not bound"
    if action in {"complete", "request-review"}:
        if getattr(args, "force", False):
            return f"kanban {action}: active-worker force adapter is not bound"
        raw_metadata = getattr(args, "metadata", None)
        if raw_metadata:
            try:
                metadata = __import__("json").loads(raw_metadata)
            except (TypeError, ValueError):
                metadata = None  # The donor command reports the usage error.
            if isinstance(metadata, dict) and metadata.get("artifacts"):
                return f"kanban {action}: workspace artifact adapter is not bound"
        with kb.connect_closing() as conn:
            tids = args.task_ids if action == "complete" else [args.task_id]
            for tid in tids:
                task = kb.get_task(conn, tid)
                if task is None:
                    continue
                if task.goal_mode:
                    return f"kanban {action}: goal judge adapter is not bound"
                if task.workspace_path:
                    return f"kanban {action}: workspace cleanup adapter is not bound"
                if task.completion_contract not in (None, "local-only"):
                    return f"kanban {action}: GitHub/PR acceptance adapter is not bound"
    return None


async def execute_command(orch, argv, principal, session_id=None, profile="owner", *, owner_command=None):
    """Run one parsed command against a trusted, scoped Nerva board.

    Profile and session identity are supplied by the authenticated Nerva caller;
    parser flags cannot alter either. Worker/delegated contexts cannot become owner.
    """
    if not isinstance(argv, (list, tuple)) or any(not isinstance(v, str) for v in argv):
        return _refused("invalid_argv", code=2)
    try:
        lengths = [len(v.encode("utf-8")) for v in argv]
    except UnicodeError:
        return _refused("invalid_argv", code=2)
    if len(argv) > 128 or any(size > 8192 for size in lengths) or sum(lengths) > 65536:
        return _refused("argv_too_large", code=2)
    if not isinstance(profile, str) or not profile.strip() or (session_id is not None and not isinstance(session_id, str)):
        return _refused("invalid_identity", code=2)
    if not _owner(principal):
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
    if inherited and (inherited.delegated or inherited.task_id is not None or inherited.run_id is not None or not inherited.can_mutate
                      or inherited.profile != profile):
        return _refused("worker_scope")
    with capture() as (out, err):
        parsed, early = _parse(argv)
        if early is not None:
            if isinstance(parsed, str):
                emit(f"kanban: {parsed}", file=__import__("sys").stderr)
            return _result(early, out.getvalue(), err.getvalue(), "usage" if early else None)
        args = parsed
        action = args.kanban_action
        if not action:
            emit(args._kanban_parser.format_help(), end="")
            return _result(0, out.getvalue(), err.getvalue())
        base = inherited or KanbanContext(data_path("kanban"), profile, can_mutate=True, session_id=session_id)
        if inherited:
            board = inherited.board
        else:
            with kanban_scope(base):
                board = selected_board(base.home)
        if action != "boards" and args.board:
            try:
                board = kb._require_slug(args.board)
            except ValueError as exc:
                return _refused("invalid_board", f"kanban: {exc}", 2)
        context = KanbanContext(base.home, base.profile, board=board, session_id=base.session_id or session_id,
                                can_mutate=True)
        with kanban_scope(context):
            try:
                if action != "boards" and board != "default" and not kb.board_exists(board):
                    return _refused("unknown_board", f"kanban: board {board!r} does not exist")
                rejection = _preflight(args, context)
                if rejection:
                    return _refused("adapter_unbound", rejection)
                args._nerva_profiles = tuple(
                    name for name in (getattr(orch, "agents", {}) or {})
                    if isinstance(name, str) and name
                )
                if action == "dispatch":
                    autonomy = getattr(orch, "_autonomy", None)
                    controller = autonomy.kanban_dispatcher() if autonomy else None
                    if controller is None:
                        return _refused("governed_worker_unavailable")
                    limit = 4 if args.max is None else args.max
                    if owner_command is not None:
                        if owner_command.orch is not orch or owner_command.principal is not principal:
                            return _refused("owner_required")
                        answer = await controller.request_owner_command(owner_command, board=board, limit=limit)
                    else:
                        answer = await controller.request(principal, board=board, limit=limit)
                    if args.json:
                        emit(__import__("json").dumps(answer, ensure_ascii=False, indent=2))
                    elif answer.get("ok") is True:
                        emit(f"Dispatch {answer.get('status', 'queued')}: {len(answer.get('queued') or [])} queued")
                        for item in answer.get("queued") or []:
                            emit(f"  {item.get('task_id')}: {item.get('status')} ({item.get('queue_id')})")
                    else:
                        emit(f"kanban dispatch: {answer.get('reason') or 'refused'}")
                    return _result(0 if answer.get("ok") is True else 1, out.getvalue(), err.getvalue(),
                                   None if answer.get("ok") else str(answer.get("reason") or "dispatch_refused"))
                if action == "init":
                    path = kb.init_db()
                    emit(f"Kanban DB initialized at {path}")
                    return _result(0, out.getvalue(), err.getvalue())
                if action == "repair":
                    code = ops._cmd_repair(args)
                    return _result(code, out.getvalue(), err.getvalue(), "repair_failed" if code else None)
                if action == "boards":
                    code = boards._dispatch_boards(args)
                else:
                    kb.init_db()
                    handler = handlers._HANDLERS.get(action)
                    if handler is None:
                        return _refused("unknown_action", code=2)
                    code = int(handler(args) or 0)
                return _result(code, out.getvalue(), err.getvalue(), "command_failed" if code else None)
            except (ValueError, PermissionError, RuntimeError, NotImplementedError, OSError) as exc:
                return _refused("command_failed", f"kanban: {exc}")
