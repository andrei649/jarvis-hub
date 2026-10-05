"""Pinned Hermes ``project`` command tree and local, scoped handlers.

Adapted from ``hermes_cli/projects_cmd.py`` at MIT commit
59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e. See ``LICENSE`` here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from ..upstream.compat import require_scoped_path
from .sink import emit


def build_parser(parent_subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the donor's complete ``project`` subcommand tree."""
    parser = parent_subparsers.add_parser(
        "project", help="Manage projects (named, multi-folder workspaces)",
        description=("Projects are human-named workspaces that can span multiple "
                     "folders / repos. They anchor desktop session grouping and, when "
                     "bound to a kanban board, give tasks a deterministic worktree + "
                     "branch convention. State is per-profile."),
    )
    sub = parser.add_subparsers(dest="project_action")
    create = sub.add_parser("create", help="Create a new project")
    create.add_argument("name", help="Human name, e.g. 'Hermes Agent'")
    create.add_argument("folders", nargs="*", help="Folder paths to include (first = primary)")
    create.add_argument("--slug", default=None, help="Explicit slug override")
    create.add_argument("--primary", default=None, metavar="PATH", help="Primary repo path")
    for option in ("--description", "--icon", "--color"):
        create.add_argument(option, default=None)
    create.add_argument("--board", default=None, metavar="SLUG", help="Bind a kanban board")
    create.add_argument("--use", action="store_true", help="Set as the active project")
    listing = sub.add_parser("list", aliases=["ls"], help="List projects")
    listing.add_argument("--all", action="store_true", dest="include_archived", help="Include archived projects")

    def project_sub(name: str, help_text: str) -> argparse.ArgumentParser:
        item = sub.add_parser(name, help=help_text)
        item.add_argument("project", help="Project id or slug")
        return item

    project_sub("show", "Show a project's details")
    add = project_sub("add-folder", "Add a folder to a project")
    add.add_argument("path", help="Folder path")
    add.add_argument("--label", default=None)
    add.add_argument("--primary", action="store_true", help="Mark as primary repo")
    project_sub("remove-folder", "Remove a folder from a project").add_argument("path", help="Folder path")
    project_sub("rename", "Rename a project").add_argument("name", help="New name")
    project_sub("set-primary", "Set the primary folder").add_argument(
        "path", help="Folder path (must already be in project)")
    use = sub.add_parser("use", help="Set the active project")
    use.add_argument("project", nargs="?", default=None, help="Project id or slug (omit to clear)")
    project_sub("archive", "Archive a project")
    project_sub("restore", "Restore an archived project")
    project_sub("bind-board", "Bind a kanban board to a project").add_argument(
        "board", nargs="?", default="", help="Board slug (omit to unbind)")
    parser.set_defaults(_project_parser=parser)
    return parser


def _error(message: str) -> int:
    emit(f"project: {message}", file=sys.stderr)
    return 1


def _project(conn, ident: str, *, allow_archived: bool = False):
    project = pdb.get_project(conn, ident)
    if project is None or (project.archived and not allow_archived):
        raise ValueError(f"no such active project: {ident}")
    return project


def _show(project) -> None:
    emit(f"{project.slug}  [{project.id}]{' (archived)' if project.archived else ''}")
    emit(f"  name:    {project.name}")
    for label, value in (("about", project.description), ("board", project.board_slug),
                         ("primary", project.primary_path)):
        if value:
            emit(f"  {label}:{' ' * (8 - len(label))}{value}")
    if project.folders:
        emit("  folders:")
        for folder in project.folders:
            emit(f"   {' *' if folder.is_primary else '  '} {folder.path}"
                 f"{f' ({folder.label})' if folder.label else ''}")


def _safe_board_paths(board: str) -> None:
    for path in (kb.board_metadata_path(board), kb.kanban_db_path(board)):
        if path.resolve() != path or require_scoped_path(path) != path:
            raise PermissionError("board path changed or escaped its scoped home")


def _validated_board(raw: str | None, primary: str | None = None) -> str | None:
    if raw is None or not raw.strip():
        return None
    board = kb._require_slug(raw)
    _safe_board_paths(board)
    if not kb.board_exists(board):
        raise ValueError(f"board {board!r} does not exist")
    meta = kb.read_board_metadata(board)
    if meta.get("archived"):
        raise ValueError(f"board {board!r} is archived")
    if primary:
        from agents.core.file_tools import FileScope

        scoped = FileScope.from_env().resolve(primary)
        if str(scoped) != primary:
            raise PermissionError("project primary path changed since it was stored")
    return board


def _metadata_bytes(board: str) -> bytes | None:
    _safe_board_paths(board)
    path = kb.board_metadata_path(board)
    return path.read_bytes() if path.exists() else None


def _restore_metadata(board: str, before: bytes | None, written: bytes | None) -> bool:
    """Compensate our write only while its exact bytes are still current."""
    if _metadata_bytes(board) != written:
        return False
    path = kb.board_metadata_path(board)
    if before is None:
        path.unlink(missing_ok=True)
    else:
        fd, tmp = tempfile.mkstemp(prefix=".board-rollback-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(before)
                stream.flush()
                os.fsync(stream.fileno())
            _safe_board_paths(board)
            os.replace(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)
    return True


def _change_board_link(conn, project, board: str | None, *, after: Callable[[], None] | None = None) -> str:
    """Change the SQLite and JSON links with guarded compensation on failure.

    The two stores cannot commit atomically. A failed command restores only its
    own writes; newer board metadata is left for an explicit repair.
    """
    desired = _validated_board(board, project.primary_path)
    old = project.board_slug
    old_meta = None
    if desired:
        meta = kb.read_board_metadata(desired)
        attached = meta.get("project_id")
        if attached and attached != project.id:
            raise ValueError(f"board {desired!r} is bound to another project")
    if old and old != desired and kb.board_exists(old):
        _safe_board_paths(old)
        old_meta = kb.read_board_metadata(old)
    changed: list[tuple[str, bytes | None, bytes | None]] = []
    foreign_change = False

    def write(board_slug: str, **fields) -> None:
        nonlocal foreign_change
        before = _metadata_bytes(board_slug)
        expected = kb.read_board_metadata(board_slug)
        expected.pop("db_path", None)
        expected.update({key: value or None for key, value in fields.items()})
        try:
            kb.write_board_metadata(board_slug, **fields)
        finally:
            written = _metadata_bytes(board_slug)
            if written != before:
                try:
                    actual = json.loads(written) if written is not None else None
                    # The writer sets created_at on a first write. Other
                    # differences mean another writer has moved the board.
                    if isinstance(actual, dict) and not expected.get("created_at"):
                        expected["created_at"] = actual.get("created_at")
                    if actual != expected:
                        foreign_change = True
                    else:
                        changed.append((board_slug, before, written))
                except (TypeError, ValueError):
                    foreign_change = True

    try:
        if desired != old:
            pdb.update_project(conn, project.id, board_slug=desired or "")
        if desired:
            write(desired, project_id=project.id,
                  default_workdir=project.primary_path or "")
        if old_meta and old_meta.get("project_id") == project.id:
            clear_workdir = old_meta.get("default_workdir") == project.primary_path
            write(old, project_id="", **({"default_workdir": ""} if clear_workdir else {}))
        if after:
            after()
    except Exception as exc:
        repair_needed = foreign_change
        for board_slug, before, written in reversed(changed):
            try:
                if not _restore_metadata(board_slug, before, written):
                    repair_needed = True
            except Exception:
                repair_needed = True
        try:
            current = pdb.get_project(conn, project.id)
            if current and current.archived != project.archived:
                (pdb.archive_project if project.archived else pdb.restore_project)(conn, project.id)
            if current and current.board_slug == desired and desired != old:
                pdb.update_project(conn, project.id, board_slug=old or "")
            elif current and current.board_slug not in {old, desired}:
                repair_needed = True
        except Exception:
            repair_needed = True
        if repair_needed:
            raise RuntimeError(
                "project/board linkage changed during recovery; inspect and repair with bind-board"
            ) from exc
        raise
    return (f"Bound {project.slug} -> board {desired}" if desired
            else f"Unbound board from {project.slug}")


def _bind_board(conn, project, board: str | None) -> str:
    return _change_board_link(conn, project, board)


def projects_command(args: argparse.Namespace) -> int:
    """Dispatch a parsed donor command using the live Nerva scope and sink."""
    action = getattr(args, "project_action", None)
    if not action:
        parser = getattr(args, "_project_parser", None)
        emit(parser.format_help() if parser else "usage: nerva project <action> [options]", end="")
        return 0
    if action not in _ACTIONS:
        return _error(f"unknown project action: {action}")
    # Keep parser construction stdlib-only; storage and file tooling are needed
    # only after an actual project action has been selected.
    global kb, pdb
    from ..upstream import kanban_db as kb
    from ..upstream import projects_db as pdb

    try:
        with pdb.connect_closing() as conn:
            return _ACTIONS[action](args, conn)
    except ValueError as exc:
        emit(f"project: {exc}", file=sys.stderr)
        return 2


def _create(args, conn) -> int:
    board = _validated_board(args.board)
    if board and kb.read_board_metadata(board).get("project_id"):
        raise ValueError(f"board {board!r} is bound to another project")
    pid = pdb.create_project(
        conn, name=args.name, slug=args.slug, folders=args.folders,
        primary_path=args.primary, description=args.description,
        icon=args.icon, color=args.color,
    )
    project = pdb.get_project(conn, pid)
    if project is None:
        return _error("vanished after create")
    try:
        if board:
            _bind_board(conn, project, board)
        if args.use:
            pdb.set_active(conn, pid)
    except Exception:
        if board:
            current = pdb.get_project(conn, pid)
            if current and current.board_slug == board:
                _bind_board(conn, current, None)
        pdb.delete_project(conn, pid)
        raise
    project = pdb.get_project(conn, pid)
    emit(f"Created project {project.slug} ({pid})")
    _show(project)
    return 0


def _list(args, conn) -> int:
    active = pdb.get_active_id(conn)
    projects = pdb.list_projects(conn, include_archived=args.include_archived)
    if not projects:
        emit("No projects yet. Create one with `nerva project create <name>`.")
    for project in projects:
        flags = " (archived)" if project.archived else ""
        emit(f"{'*' if project.id == active else ' '} {project.slug:<24} "
             f"{project.name}{flags}  [{len(project.folders)} folder(s)]")
    return 0


def _show_command(args, conn) -> int:
    _show(_project(conn, args.project, allow_archived=True))
    return 0


def _add_folder(args, conn) -> int:
    project = _project(conn, args.project, allow_archived=True)
    path = pdb.add_folder(conn, project.id, args.path, label=args.label, is_primary=args.primary)
    emit(f"Added {path} to {project.slug}")
    return 0


def _remove_folder(args, conn) -> int:
    project = _project(conn, args.project, allow_archived=True)
    if not pdb.remove_folder(conn, project.id, args.path):
        return _error(f"folder not in project: {args.path}")
    emit(f"Removed {args.path} from {project.slug}")
    return 0


def _rename(args, conn) -> int:
    project = _project(conn, args.project, allow_archived=True)
    pdb.update_project(conn, project.id, name=args.name)
    emit(f"Renamed {project.slug} -> {args.name}")
    return 0


def _set_primary(args, conn) -> int:
    project = _project(conn, args.project, allow_archived=True)
    if not pdb.set_primary(conn, project.id, args.path):
        return _error(f"'{args.path}' is not a folder of {project.slug}; add it first with `nerva project add-folder`.")
    emit(f"Set primary of {project.slug} -> {args.path}")
    return 0


def _use(args, conn) -> int:
    if not args.project:
        pdb.set_active(conn, None)
        emit("Cleared active project")
        return 0
    project = _project(conn, args.project)
    pdb.set_active(conn, project.id)
    emit(f"Active project: {project.slug}")
    return 0


def _archive(args, conn) -> int:
    project = _project(conn, args.project, allow_archived=True)
    if project.board_slug:
        old = project.board_slug
        _change_board_link(conn, project, None,
                           after=lambda: pdb.archive_project(conn, project.id))
        emit(f"Archived {project.slug}; Unbound board {old}")
    else:
        if not project.archived:
            pdb.archive_project(conn, project.id)
        emit(f"Archived {project.slug}")
    return 0


def _restore(args, conn) -> int:
    project = _project(conn, args.project, allow_archived=True)
    if not project.archived:
        board_status = (f"board {project.board_slug} remains bound" if project.board_slug
                        else "board remains unbound")
        emit(f"Project {project.slug} already active; {board_status}")
        return 0
    if project.board_slug:
        _change_board_link(conn, project, None,
                           after=lambda: pdb.restore_project(conn, project.id))
    else:
        pdb.restore_project(conn, project.id)
    emit(f"Restored {project.slug}; board remains unbound")
    return 0


def _bind(args, conn) -> int:
    project = _project(conn, args.project)
    emit(_bind_board(conn, project, args.board))
    return 0


_ACTIONS = {
    "create": _create, "list": _list, "ls": _list, "show": _show_command,
    "add-folder": _add_folder, "remove-folder": _remove_folder,
    "rename": _rename, "set-primary": _set_primary, "use": _use,
    "archive": _archive, "restore": _restore, "bind-board": _bind,
}
