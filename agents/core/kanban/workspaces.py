"""Scoped Nerva adapter for pinned Hermes Kanban workspace algorithms.

Resolution, branch reuse and conservative worktree reclamation are adapted from
Hermes 59b2aeef6c7a, hermes_cli/kanban_db_workspace.py and worktree_ops.py (MIT).
The board engine remains in ``upstream``; this module supplies its filesystem
boundary without process cwd, environment, network or tmux effects.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import sqlite3
import stat
import subprocess  # nosec B404 - bounded local Git adapter; no shell/network commands
import tempfile
import time
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace

from agents.core.file_tools import FileScope

from .context import require_mutation
from .upstream import kanban_db as kb
from .workspace_context import workspace_lifecycle_is_bound, workspace_reclamation_guard

_TERMINAL = frozenset({"done", "archived", "failed", "cancelled"})
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_GIT_TIMEOUT = 10
_GIT_OUTPUT = 4096


class WorkspaceSpec(dict):
    """JSON-serializable immutable snapshot; deserialized ordinary dicts also work."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("workspace specification is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable


def _git(cwd: Path, *args: str, mutate: bool = False) -> subprocess.CompletedProcess[str]:
    # Explicit argv/cwd and a clean Git environment prevent ambient overrides,
    # hooks, fsmonitor and network prompts from changing the operation.
    env = {
        "PATH": os.defpath,
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "1" if mutate else "0",
    }
    argv = ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false", *args]
    with subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:  # nosec B603 - fixed Git executable/operations; validated paths/branch, hooks and filters disabled
        if proc.stdout is None:
            proc.kill()
            proc.wait()
            raise RuntimeError("Git output pipe is unavailable")
        output = bytearray()
        deadline = time.monotonic() + _GIT_TIMEOUT
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    proc.kill()
                    proc.wait()
                    raise subprocess.TimeoutExpired(argv, _GIT_TIMEOUT)
                if not selector.select(remaining):
                    continue
                chunk = os.read(proc.stdout.fileno(), min(4096, _GIT_OUTPUT + 1 - len(output)))
                if not chunk:
                    selector.unregister(proc.stdout)
                else:
                    output.extend(chunk)
                    if len(output) > _GIT_OUTPUT:
                        proc.kill()
                        proc.wait()
                        return subprocess.CompletedProcess(argv, 1, "", "Git output exceeded bound")
        remaining = deadline - time.monotonic()
        try:
            code = proc.wait(timeout=max(0.001, remaining))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise
    decoded = output.decode("utf-8", errors="replace")
    return subprocess.CompletedProcess(argv, code, decoded, "")


def _git_out(cwd: Path, *args: str) -> str | None:
    result = _git(cwd, *args)
    return result.stdout.strip() if result.returncode == 0 else None


def _same_path(left: Path | str, right: Path | str) -> bool:
    return unicodedata.normalize("NFC", str(left)) == unicodedata.normalize("NFC", str(right))


def _scope_path(scope: FileScope, raw: Path | str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("workspace paths must be absolute")
    return scope.resolve(str(path))


def _metadata_in_scope(scope: FileScope, path: Path) -> None:
    for flag in ("--git-dir", "--git-common-dir"):
        out = _git_out(path, "rev-parse", "--path-format=absolute", flag)
        if not out:
            raise ValueError("Git metadata is unavailable")
        candidate = Path(out).resolve(strict=False)
        if scope.root_for(candidate) is None:
            raise PermissionError("Git metadata is outside the owner's FileScope")


def _git_root(scope: FileScope, path: Path) -> Path | None:
    out = _git_out(path, "rev-parse", "--show-toplevel") if path.is_dir() else None
    if not out:
        return None
    root = _scope_path(scope, out)
    _metadata_in_scope(scope, path)
    return root


def _main_repo(scope: FileScope, checkout: Path) -> Path:
    common = _git_out(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        raise ValueError("Git common directory is unavailable")
    common_path = Path(common).resolve(strict=False)
    if scope.root_for(common_path) is None or common_path.name != ".git":
        raise PermissionError("Git common directory is outside the owner's FileScope")
    return _scope_path(scope, common_path.parent)


def _nearest_repo(scope: FileScope, path: Path) -> Path | None:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    while scope.root_for(current.resolve(strict=False)) is not None:
        root = _git_root(scope, current)
        if root is not None:
            return root
        if current == current.parent:
            break
        current = current.parent
    return None


def _check_branch(branch: str) -> None:
    if not branch or len(branch) > 240 or branch.startswith("-") or branch.startswith("/"):
        raise ValueError("invalid worktree branch")
    if any(part in {"", ".", ".."} for part in branch.split("/")):
        raise ValueError("invalid worktree branch")
    result = _git(Path("/"), "check-ref-format", "--branch", branch)
    if result.returncode:
        raise ValueError("invalid worktree branch")


def _reject_checkout_commands(repo: Path) -> None:
    """Refuse repository-configured clean/smudge/process commands before checkout."""
    configured = _git(repo, "config", "--get-regexp", r"^filter\..*\.(process|smudge|clean)$")
    if configured.returncode == 0:
        raise PermissionError("Git checkout filters can execute repository commands")
    if configured.returncode != 1:
        raise ValueError("Git checkout filter configuration is unreadable")


def _canonical_board(context, board: str | None) -> str:
    selected = board or context.board
    if selected != context.board and (context.task_id is not None or context.run_id is not None
                                      or selected != kb.get_current_board()):
        raise PermissionError("workspace board differs from active scope")
    return kb._require_slug(selected)


def _scratch_path(context, board: str, task_id: str) -> Path:
    if board == kb.DEFAULT_BOARD:
        return context.home.resolve() / "kanban" / "workspaces" / task_id
    return context.home.resolve() / "kanban" / "boards" / board / "workspaces" / task_id


def plan_workspace(task, *, board: str | None = None, project_root: str | Path | None = None) -> WorkspaceSpec:
    """Return a canonical, pure, JSON-safe workspace proposal for signing."""
    context = require_mutation()
    board = _canonical_board(context, board)
    task_id = str(task.id)
    if not _TASK_ID.fullmatch(task_id):
        raise ValueError("invalid task id for workspace")
    if context.task_id is not None and context.task_id != task_id:
        raise PermissionError("workspace task differs from active scope")
    scope = FileScope.from_env()
    roots = tuple(str(root) for root in scope.roots)
    kind = task.workspace_kind or "scratch"
    requested = task.workspace_path or None
    project = str(_scope_path(scope, project_root)) if project_root is not None else None
    meta = kb.read_board_metadata(board)
    board_default = meta.get("default_workdir") or None
    if board_default is not None:
        board_default = str(_scope_path(scope, board_default))
    repo: Path | None = None
    branch: str | None = None
    if kind == "scratch":
        path = _scratch_path(context, board, task_id)
        if requested is not None and not _same_path(_scope_path(FileScope([context.home]), requested), path):
            raise PermissionError("scratch authority is limited to the exact board/task path")
        if path.is_symlink() or path.resolve(strict=False) != path:
            raise PermissionError("scratch path redirects outside its managed location")
    elif kind == "dir":
        if requested is None:
            raise ValueError("dir workspace needs an absolute path")
        path = _scope_path(scope, requested)
    elif kind == "worktree":
        branch = (task.branch_name or "").strip() or f"wt/{task_id}"
        _check_branch(branch)
        anchor_raw = requested or project or board_default
        if not anchor_raw:
            raise ValueError("worktree workspace needs a repo or board default_workdir")
        anchor = _scope_path(scope, anchor_raw)
        direct_root = _git_root(scope, anchor)
        if anchor.is_dir() and direct_root is not None:
            git_dir = _git_out(anchor, "rev-parse", "--path-format=absolute", "--git-dir")
            common = _git_out(anchor, "rev-parse", "--path-format=absolute", "--git-common-dir")
            if git_dir and common and not _same_path(Path(git_dir).resolve(), Path(common).resolve()):
                actual = _git_out(anchor, "branch", "--show-current")
                if actual == branch:
                    repo, path = _main_repo(scope, anchor), anchor
                else:
                    repo = _main_repo(scope, anchor)
                    path = _scope_path(scope, repo / ".worktrees" / task_id)
            else:
                repo, path = direct_root, _scope_path(scope, direct_root / ".worktrees" / task_id)
        else:
            repo = _nearest_repo(scope, anchor.parent)
            if repo is None:
                raise ValueError("worktree target is not anchored in a local Git repo")
            path = anchor
        _metadata_in_scope(scope, repo)
        _reject_checkout_commands(repo)
        if path.exists() and path != repo:
            if not path.is_dir() or _git_root(scope, path) != path or _main_repo(scope, path) != repo:
                raise ValueError("worktree target is occupied")
            actual = _git_out(path, "branch", "--show-current")
            if actual != branch:
                raise ValueError("worktree target has a different branch")
    else:
        raise ValueError(f"unknown workspace kind: {kind}")
    values = {
        "version": 1, "board": board, "task_id": task_id, "run_id": None,
        "home": str(context.home.resolve()), "kind": kind, "path": str(path),
        "requested_path": requested, "repo_root": str(repo) if repo else None,
        "branch": branch, "file_roots": roots,
        "board_default_workdir": board_default, "project_root": project,
    }
    return WorkspaceSpec(values)


def _require_live(still_current: Callable[[], bool], task_id: str, expected_run_id: int | None) -> None:
    context = require_mutation()
    if context.task_id != task_id or context.run_id is None:
        raise PermissionError("workspace requires the current task execution")
    if expected_run_id is not None and context.run_id != expected_run_id:
        raise PermissionError("workspace run differs from active scope")
    if not callable(still_current):
        raise PermissionError("workspace needs a live execution callback")
    try:
        valid = still_current()
    except Exception as exc:
        raise PermissionError("workspace execution is no longer current") from exc
    if valid is not True:
        raise PermissionError("workspace execution is no longer current")


def _scratch_record_path(path: Path) -> Path:
    # Keep ownership outside the worker's file root; never adopt a symlinked
    # record or storage directory, including after an approved scope changes.
    record = path.parent / ".ownership" / f"{path.name}.json"
    if record.is_symlink() or record.resolve(strict=False) != record:
        raise PermissionError("scratch ownership storage redirects")
    return record


def _scratch_record(path: Path) -> dict[str, object]:
    context = require_mutation()
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise PermissionError("scratch workspace is not a directory")
    return {"version": 1, "home": str(context.home.resolve()), "board": context.board,
            "task_id": context.task_id, "path": str(path), "dev": info.st_dev, "ino": info.st_ino}


def _record_scratch_creation(path: Path, still_current: Callable[[], bool], run_id: int | None) -> None:
    record = _scratch_record_path(path)
    ownership = _scratch_record(path)
    _require_live(still_current, path.name, run_id)
    record.parent.mkdir(exist_ok=True)
    record = _scratch_record_path(path)
    _require_live(still_current, path.name, run_id)
    fd, temporary = tempfile.mkstemp(prefix=".new-", dir=record.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(ownership, stream, sort_keys=True)
        _require_live(still_current, path.name, run_id)
        if _scratch_record(path) != ownership or _scratch_record_path(path) != record:
            raise PermissionError("scratch directory changed before ownership was recorded")
        os.replace(temporary, record)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _owns_scratch(path: Path) -> bool:
    try:
        record = _scratch_record_path(path)
        fd = os.open(record, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                return False
            contents = stream.read(4097)
            return len(contents) <= 4096 and json.loads(contents) == _scratch_record(path)
    except (OSError, ValueError, PermissionError):
        return False


def materialize_workspace(
    spec: Mapping[str, object], *, still_current: Callable[[], bool], expected_run_id: int | None = None,
) -> Path:
    """Create or reuse exactly the signed proposal under a live consumed run."""
    if not isinstance(spec, Mapping) or spec.get("version") != 1 or spec.get("run_id") is not None:
        raise ValueError("invalid workspace specification")
    task_id = spec.get("task_id")
    if not isinstance(task_id, str):
        raise ValueError("invalid workspace task")
    _require_live(still_current, task_id, expected_run_id)
    planned = plan_workspace(
        SimpleNamespace(id=task_id, workspace_kind=spec.get("kind"),
                        workspace_path=spec.get("requested_path"), branch_name=spec.get("branch")),
        board=spec.get("board"), project_root=spec.get("project_root"),
    )
    supplied = dict(spec)
    if isinstance(supplied.get("file_roots"), list):
        supplied["file_roots"] = tuple(supplied["file_roots"])
    if supplied != dict(planned):
        raise PermissionError("workspace proposal or live configuration changed")
    path = Path(planned["path"])
    _require_live(still_current, task_id, expected_run_id)
    if planned["kind"] == "scratch":
        path.parent.mkdir(parents=True, exist_ok=True)
        _require_live(still_current, task_id, expected_run_id)
        if path.resolve(strict=False) != path or path.is_symlink():
            raise PermissionError("scratch path redirects outside its managed location")
        try:
            path.mkdir()
        except FileExistsError:
            if not path.is_dir():
                raise ValueError("scratch workspace target is occupied") from None
        else:
            _record_scratch_creation(path, still_current, expected_run_id)
        return path
    if planned["kind"] == "dir":
        path.mkdir(parents=True, exist_ok=True)
        return path
    repo = Path(planned["repo_root"])
    branch = planned["branch"]
    if path.exists():
        return path
    _scope_path(FileScope.from_env(), path.parent)
    _reject_checkout_commands(repo)
    exists = _git(repo, "show-ref", "--verify", f"refs/heads/{branch}").returncode == 0
    args = ("worktree", "add", str(path), branch) if exists else ("worktree", "add", "-b", branch, str(path))
    _require_live(still_current, task_id, expected_run_id)
    result = _git(repo, *args, mutate=True)
    if result.returncode:
        raise RuntimeError(f"git worktree add failed: {result.stderr or result.stdout}")
    return path


def _attachment_ref(conn: sqlite3.Connection, path: Path) -> bool:
    for row in conn.execute("SELECT stored_path FROM task_attachments"):
        raw = row[0]
        if raw:
            supplied = Path(raw).expanduser()
            if supplied.is_absolute():
                for target in (supplied, supplied.resolve(strict=False)):
                    if target == path or path in target.parents:
                        return True
    return False


def _active_child(conn: sqlite3.Connection, task_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM task_links l LEFT JOIN tasks t ON t.id=l.child_id "
        "WHERE l.parent_id=? AND (t.status IS NULL OR "
        "t.status NOT IN ('done','archived','failed','cancelled')) LIMIT 1",
        (task_id,),
    ).fetchone()
    if row is not None:
        return True
    # Older boards have no child approval store. Once present, a prepared row
    # is deliberately treated as active even if queue binding never finished.
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nerva_child_approvals'"
    ).fetchone() is None:
        return False
    return conn.execute(
        "SELECT 1 FROM nerva_child_approvals WHERE task_id=? "
        "AND state IN ('prepared','queued','executing') LIMIT 1", (task_id,)
    ).fetchone() is not None


def _clean_worktree(repo: Path, path: Path) -> bool:
    # Pinned donor rule: preserve when dirty or any commit is unreachable from
    # all remote-tracking refs; without remote refs compare against local trunk.
    status = _git_out(path, "status", "--porcelain")
    if status is None or status:
        return False
    remotes = _git_out(path, "for-each-ref", "--format=%(refname)", "refs/remotes")
    if remotes is None:
        return False
    if remotes:
        baseline = ("--remotes",)
    else:
        trunk = next((name for name in ("main", "master")
                      if _git(path, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0), None)
        if trunk is None:
            main = _git_out(repo, "branch", "--show-current")
            trunk = main or None
        if trunk is None:
            return False
        baseline = (trunk,)
    return _git_out(path, "log", "--format=%H", "HEAD", "--not", *baseline) == ""


def cleanup_workspace(
    conn: sqlite3.Connection, task_id: str, *, expected_run_id: int,
    still_current: Callable[[], bool], workspace_spec: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Conservatively reclaim only a terminal task's managed scratch/worktree."""
    _require_live(still_current, task_id, expected_run_id)
    context = require_mutation()
    row = conn.execute(
        "SELECT status, workspace_kind, workspace_path, branch_name, current_run_id "
        "FROM tasks WHERE id=?", (task_id,),
    ).fetchone()
    result: dict[str, object] = {"removed": False, "reason": "missing", "path": None}
    if not row:
        return result
    status, kind, raw, branch, current_run = tuple(row)
    if workspace_spec is not None:
        planned = plan_workspace(
            SimpleNamespace(id=task_id, workspace_kind=kind, workspace_path=raw, branch_name=branch),
            project_root=workspace_spec.get("project_root"),
        )
        supplied = dict(workspace_spec)
        if isinstance(supplied.get("file_roots"), list):
            supplied["file_roots"] = tuple(supplied["file_roots"])
        if supplied != dict(planned):
            raise PermissionError("cleanup workspace differs from the approved specification")
        raw = str(planned["path"])
        branch = planned["branch"]
    result["path"] = raw
    if workspace_lifecycle_is_bound(task_id, path=raw):
        result["reason"] = "bound_workspace"
        return result
    if status not in _TERMINAL or current_run not in (None, expected_run_id):
        result["reason"] = "active_task"
        return result
    run = conn.execute("SELECT status FROM task_runs WHERE id=? AND task_id=?", (expected_run_id, task_id)).fetchone()
    latest = conn.execute("SELECT MAX(id) FROM task_runs WHERE task_id=?", (task_id,)).fetchone()
    if run is None or run[0] == "running" or latest is None or latest[0] != expected_run_id:
        result["reason"] = "wrong_run"
        return result
    if _active_child(conn, task_id):
        result["reason"] = "active_child"
        return result
    if kind == "dir" or not raw:
        result["reason"] = "user_path"
        return result
    path = Path(raw).expanduser()
    if not path.is_absolute():
        result["reason"] = "invalid_path"
        return result
    if kind == "scratch":
        canonical = _scratch_path(context, context.board, task_id)
        if path != canonical or path.is_symlink() or path.resolve(strict=False) != canonical:
            result["reason"] = "foreign_scratch"
            return result
    elif kind == "worktree":
        scope = FileScope.from_env()
        try:
            path = _scope_path(scope, path)
            checkout = _git_root(scope, path)
            repo = _main_repo(scope, path) if checkout is not None else None
            if repo is None or path == repo or checkout != path:
                result["reason"] = "foreign_worktree"
                return result
            _metadata_in_scope(scope, path)
        except (ValueError, PermissionError):
            result["reason"] = "foreign_worktree"
            return result
    else:
        result["reason"] = "unknown_kind"
        return result
    if _attachment_ref(conn, path):
        result["reason"] = "attachment_reference"
        return result
    if not path.exists():
        result["reason"] = "absent"
        return result
    if kind == "worktree" and not _clean_worktree(repo, path):
        result["reason"] = "dirty_or_unpushed"
        return result
    with workspace_reclamation_guard(task_id, path) as ready:
        if not ready:
            result["reason"] = "bound_workspace"
            return result
        _require_live(still_current, task_id, expected_run_id)
        if kind == "scratch":
            if not _owns_scratch(path):
                result["reason"] = "unowned_scratch"
                return result
            try:
                # Retire ownership before removal, so a crash or reused inode
                # cannot make a replacement directory appear owned afterward.
                _scratch_record_path(path).unlink(missing_ok=True)
            except OSError:
                result["reason"] = "ownership_record_retained"
                return result
            _require_live(still_current, task_id, expected_run_id)
            shutil.rmtree(path)
        else:
            removed = _git(repo, "worktree", "remove", str(path), mutate=True)
            if removed.returncode:
                result["reason"] = "git_remove_failed"
                return result
            # Deleting the generated branch is safe only after a successful
            # non-force worktree removal. Custom branches are preserved.
            if branch == f"wt/{task_id}":
                try:
                    _require_live(still_current, task_id, expected_run_id)
                    deleted = _git(repo, "branch", "-d", branch, mutate=True)
                    if deleted.returncode:
                        result.update(removed=True, reason="removed_branch_retained")
                        return result
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    result.update(removed=True, reason="removed_branch_retained")
                    return result
    result["removed"] = True
    result["reason"] = "removed"
    return result
