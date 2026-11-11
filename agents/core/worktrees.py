"""worktrees.py — G18: one shared, hardened git-worktree helper.

Three callers make and reclaim git worktrees, and they all go through here:

* **Kanban tasks** (``agents/core/kanban/workspaces.py``): a ``worktree`` card runs in
  ``<repo>/.worktrees/<task_id>`` on ``wt/<task_id>``.
* **Delegated children** (H402, :mod:`agents.core.subagents`): with
  ``autonomy.subagent_worktrees`` on, each child spawned against a git project gets
  ``<repo>/.worktrees/sub-<n>`` on ``sub/<spawn id>``, branched from the project's HEAD,
  and its file tools are confined to that tree.
* **Owner sessions** (H474, ``/worktree new``): a conversation is moved into its own
  tree on ``nerva/<name>``; its turns read the project from there and its file tools
  resolve inside it until ``/worktree off``.

Adapted from Hermes ``hermes_cli/worktree_ops.py`` (MIT): the ``.worktrees`` layout, the
classification of every tree by age, size, verdict and reason, protected branches, and
"dirty or unpushed work is never removed". Nerva's differences:

**Git never runs a program a repository chose.** A repository's config can make git
run code (a ``filter.<x>.smudge`` on checkout, ``core.sshCommand``, ``gpg.program``, an
``include`` that brings any of those, an alias, a diff driver). Every operation here first
asks :func:`agents.core.verify.workspace.config_refusal` — the G5 allowlist of plain keys
— and refuses a repository whose config holds anything else. The commands then run with
G5's command-line overrides (hooks to ``/dev/null``, no fsmonitor, no external diff, no
signatures, no ssh command, every transport refused, no credential helper), no system or
global config, no terminal prompt, a deadline and a bounded output. There is no fetch:
a tree branches from the local HEAD (or a branch the owner names).

**Nothing is removed unless it is clean and pushed.** A tree with a staged or modified
tracked file, a commit that no remote-tracking ref (or, with no remote, the trunk) holds,
a lock, a protected branch (``main``, ``master``, ``trunk``, ``develop``, ``release/*``,
or the primary checkout's own branch), or a live binding (a running child, a session that
is using it) is kept, and the classification says which rule kept it. Removal is the
non-force ``git worktree remove``; a generated branch is then deleted with the safe
``git branch -d``, which itself refuses an unmerged branch.

**Scratch is archived, never deleted.** Untracked files in an otherwise clean tree are
copied into ``<data>/worktrees/archive/<tree>-<time>.tar.gz`` first; only the archived
files are then unlinked (one by one, by the path that was archived), so a file that
appears after the archive keeps the tree, because the non-force removal then refuses.
"""
from __future__ import annotations

import contextlib
import fnmatch
import json
import logging
import os
import re
import selectors
import subprocess  # nosec B404 - fixed git argv, hardened per the module doc
import tarfile
import threading
import time
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.worktrees")

GIT_TIMEOUT = 15.0
GIT_OUTPUT = 256_000
#: Where a repository's managed trees live (Hermes's layout).
TREES_DIR = ".worktrees"
#: Branches that are never removed, whatever their state (fnmatch patterns).
PROTECTED_BRANCHES = ("main", "master", "trunk", "develop", "dev", "release/*", "production", "prod")
#: Branch prefixes Nerva generates; only these are deleted after a tree is removed.
GENERATED_PREFIXES = ("wt/", "sub/", "nerva/")
#: Kanban card trees: never classified removable here (the board reclaims its own).
KANBAN_PREFIX = "wt/"
#: The most untracked scratch archived from one tree; past it the tree is kept.
ARCHIVE_MAX_BYTES = 64 * 1024 * 1024
ARCHIVE_MAX_FILES = 5000
#: Size walk bound for the classification (files counted, then "at least").
SIZE_WALK_MAX_FILES = 20_000
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class WorktreeRefused(PermissionError):
    """A git operation Nerva will not run, with the reason in plain words."""


# ── hardened git ──────────────────────────────────────────────────────────────

def _env(mutate: bool) -> dict[str, str]:
    from agents.core.verify.workspace import _env as g5_env

    env = g5_env()
    env["GIT_OPTIONAL_LOCKS"] = "1" if mutate else "0"
    return env


def _argv(*args: str) -> list[str]:
    from agents.core.verify.workspace import _BASE

    return ["git", *_BASE, *args]


def _collect(proc: subprocess.Popen, deadline: float, limit: int) -> tuple[bytes, bool]:
    """Read *proc*'s merged output until EOF; kill it at *deadline* (raises
    ``TimeoutExpired``) or past *limit* bytes (returns ``(output, False)``)."""
    stdout = proc.stdout
    if stdout is None:
        raise RuntimeError("git output pipe is unavailable")
    output = bytearray()
    if os.name == "nt":  # pragma: no cover - select() takes sockets only on Windows
        import queue as _queue

        chunks: _queue.Queue[bytes] = _queue.Queue()

        def pump() -> None:
            try:
                while True:
                    chunk = os.read(stdout.fileno(), 65536)
                    chunks.put(chunk)
                    if not chunk:
                        return
            except OSError:
                chunks.put(b"")

        threading.Thread(target=pump, daemon=True).start()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(proc.args, GIT_TIMEOUT)
            try:
                chunk = chunks.get(timeout=remaining)
            except _queue.Empty:
                continue
            if not chunk:
                return bytes(output), True
            output.extend(chunk)
            if len(output) > limit:
                proc.kill()
                proc.wait()
                return bytes(output[:limit]), False
    with selectors.DefaultSelector() as selector:
        selector.register(stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(proc.args, GIT_TIMEOUT)
            if not selector.select(remaining):
                continue
            chunk = os.read(stdout.fileno(), 65536)
            if not chunk:
                selector.unregister(stdout)
                continue
            output.extend(chunk)
            if len(output) > limit:
                proc.kill()
                proc.wait()
                return bytes(output[:limit]), False
    return bytes(output), True


def run_git(cwd: Path | str, *args: str, mutate: bool = False, timeout: float = GIT_TIMEOUT,
            limit: int = GIT_OUTPUT) -> subprocess.CompletedProcess:
    """Run one fixed git command in *cwd* with the G5 overrides and a clean environment.
    Output (stdout and stderr merged) is bounded; an overflow is exit code 1."""
    argv = _argv(*args)
    with subprocess.Popen(argv, cwd=str(cwd), env=_env(mutate), stdin=subprocess.DEVNULL,  # nosec B603 - fixed git argv, no shell
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
        deadline = time.monotonic() + timeout
        output, complete = _collect(proc, deadline, limit)
        if not complete:
            return subprocess.CompletedProcess(argv, 1, "", "git output exceeded its bound")
        try:
            code = proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise
    return subprocess.CompletedProcess(argv, code, output.decode("utf-8", errors="replace"), "")


def git_out(cwd: Path | str, *args: str) -> str | None:
    try:
        result = run_git(cwd, *args)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def config_refusal(repo: Path | str) -> str | None:
    """Why *repo*'s config could make git run a program (G5's allowlist), or None."""
    from agents.core.verify.workspace import config_refusal as g5_refusal

    return g5_refusal(Path(repo))


def require_plain(repo: Path | str) -> None:
    refused = config_refusal(repo)
    if refused is not None:
        raise WorktreeRefused(f"git refused: {refused} (Nerva runs git only on a repository "
                              "whose config cannot make it run a program)")


def check_branch(branch: str) -> None:
    if (not isinstance(branch, str) or not branch or len(branch) > 240 or branch.startswith(("-", "/"))
            or branch.endswith(("/", ".lock")) or any(p in {"", ".", ".."} for p in branch.split("/"))):
        raise ValueError("invalid worktree branch")
    try:
        result = run_git(Path("/"), "check-ref-format", "--branch", branch)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("invalid worktree branch") from exc
    if result.returncode:
        raise ValueError("invalid worktree branch")


def valid_name(name: str) -> bool:
    return isinstance(name, str) and bool(_NAME.fullmatch(name))


def repo_root(path: Path | str) -> Path | None:
    """The top of the checkout *path* is in (a linked tree's own top), or None."""
    path = Path(path)
    if not path.is_dir():
        return None
    out = git_out(path, "rev-parse", "--show-toplevel")
    return Path(out).resolve() if out else None


def main_repo(path: Path | str) -> Path | None:
    """The primary checkout behind *path* (the parent of the common ``.git``), or None."""
    out = git_out(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not out:
        return None
    common = Path(out).resolve()
    return common.parent if common.name == ".git" else None


def is_protected(branch: str | None, primary_branch: str | None = None) -> bool:
    if not branch:
        return False
    if primary_branch and branch == primary_branch:
        return True
    return any(fnmatch.fnmatchcase(branch, pattern) for pattern in PROTECTED_BRANCHES)


# ── trees ─────────────────────────────────────────────────────────────────────

@dataclass
class Tree:
    path: str
    branch: str | None = None
    head: str | None = None
    primary: bool = False
    locked: bool = False
    prunable: bool = False


def list_trees(repo: Path | str) -> list[Tree]:
    """Every worktree git knows for *repo* (the primary first)."""
    require_plain(repo)
    result = run_git(repo, "worktree", "list", "--porcelain", "-z")
    if result.returncode:
        raise RuntimeError("git worktree list failed")
    trees: list[Tree] = []
    current: Tree | None = None
    for field_ in result.stdout.split("\0"):
        if not field_:
            if current is not None:
                trees.append(current)
                current = None
            continue
        key, _, value = field_.partition(" ")
        if key == "worktree":
            if current is not None:
                trees.append(current)
            current = Tree(path=str(Path(value).resolve()))
        elif current is None:
            continue
        elif key == "HEAD":
            current.head = value
        elif key == "branch":
            current.branch = value.removeprefix("refs/heads/")
        elif key == "locked":
            current.locked = True
        elif key == "prunable":
            current.prunable = True
        elif key == "bare":
            current.primary = True
    if current is not None:
        trees.append(current)
    if trees:
        trees[0].primary = True
    return trees


def create(repo: Path | str, path: Path | str, branch: str, *, base: str = "HEAD") -> Tree:
    """Make the worktree *path* on *branch* (new from *base*, or the existing branch)."""
    repo, path = Path(repo), Path(path)
    require_plain(repo)
    check_branch(branch)
    if base != "HEAD":
        check_branch(base)
    if path.exists() or path.is_symlink():
        raise ValueError("worktree target is occupied")
    _require_inside(repo, path)
    exists = run_git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    args = (("worktree", "add", str(path), branch) if exists
            else ("worktree", "add", "-b", branch, str(path), base))
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_inside(repo, path)                  # again, now that the parent exists
    if path.parent == repo / TREES_DIR:
        _exclude_trees_dir(repo)
    result = run_git(repo, *args, mutate=True)
    if result.returncode:
        raise RuntimeError(f"git worktree add failed: {result.stdout.strip()[:300]}")
    head = git_out(path, "rev-parse", "HEAD")
    return Tree(path=str(path.resolve()), branch=branch, head=head)


def _require_inside(repo: Path, path: Path) -> None:
    """A tree is made only inside its repository, through no symlink: a committed
    ``.worktrees`` link (or any linked parent) pointing elsewhere is refused."""
    root = Path(repo).resolve()
    current = Path(path)
    while current != current.parent and current != Path(repo):
        if current.is_symlink():
            raise WorktreeRefused("a worktree path goes through a symbolic link; refused")
        current = current.parent
    parent = Path(path).parent
    resolved = (parent.resolve() if parent.exists() else Path(os.path.normpath(parent))) / Path(path).name
    if root not in resolved.parents:
        raise WorktreeRefused("a worktree must lie inside its repository; refused")


def _exclude_trees_dir(repo: Path) -> None:
    """Keep ``.worktrees/`` out of the primary checkout's status (Hermes does the same):
    one line in ``.git/info/exclude``, which is not config and runs nothing."""
    exclude = repo / ".git" / "info" / "exclude"
    try:
        if exclude.parent.is_symlink() or exclude.is_symlink() or not (repo / ".git").is_dir():
            return
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if f"/{TREES_DIR}/" in text.splitlines():
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write(("" if not text or text.endswith("\n") else "\n") + f"/{TREES_DIR}/\n")
    except OSError:
        logger.debug("could not add %s to the repository's exclude file", TREES_DIR, exc_info=True)


def tree_state(path: Path | str, *, base: str | None = None) -> dict[str, Any]:
    """Dirty tracked files, untracked files and commits not held anywhere else.

    ``unpushed`` counts the commits on HEAD that no remote-tracking ref holds (with no
    remote: that the trunk does not hold). With *base* (a child's starting commit) it
    counts the commits made since that base instead."""
    path = Path(path)
    status = run_git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching",
                     "--ignore-submodules=all", "--no-renames")
    if status.returncode:
        raise RuntimeError("git status failed")
    tracked: list[str] = []
    untracked: list[str] = []
    ignored: list[str] = []
    for entry in status.stdout.split("\0"):
        if len(entry) < 4:
            continue
        code, name = entry[:2], entry[3:]
        (untracked if code == "??" else ignored if code == "!!" else tracked).append(name)
    if base:
        count = git_out(path, "rev-list", "--count", f"{base}..HEAD")
    else:
        remotes = git_out(path, "for-each-ref", "--format=%(refname)", "refs/remotes")
        if remotes:
            count = git_out(path, "rev-list", "--count", "HEAD", "--not", "--remotes")
        else:
            trunk = next((name for name in ("main", "master", "trunk")
                          if run_git(path, "rev-parse", "--verify", "--quiet",
                                     f"refs/heads/{name}").returncode == 0), None)
            count = git_out(path, "rev-list", "--count", "HEAD", "--not", trunk) if trunk else None
    try:
        unpushed = int(count) if count is not None else -1
    except ValueError:
        unpushed = -1
    return {"tracked_changes": tracked, "untracked": untracked, "ignored": ignored, "unpushed": unpushed}


def _size(path: Path) -> tuple[int, bool]:
    total, files = 0, 0
    for root, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in names:
            files += 1
            if files > SIZE_WALK_MAX_FILES:
                return total, False
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(root, name)).st_size
    return total, True


def classify(repo: Path | str, tree: Tree, *, now: float | None = None, min_age_seconds: float = 0.0,
             in_use: set[str] | None = None, base: str | None = None) -> dict[str, Any]:
    """One tree's row: age, size, verdict (``removable`` or ``keep``) and the reason."""
    now = time.time() if now is None else now
    path = Path(tree.path)
    row: dict[str, Any] = {"path": tree.path, "branch": tree.branch, "head": (tree.head or "")[:12],
                           "primary": tree.primary, "locked": tree.locked}
    primary_branch = None
    if not tree.primary:
        with contextlib.suppress(Exception):
            primary_branch = list_trees(repo)[0].branch

    def verdict(value: str, reason: str) -> dict[str, Any]:
        row.update(verdict=value, reason=reason)
        return row

    if not path.exists():
        row.update(age_seconds=None, size_bytes=None)
        return verdict("keep" if tree.primary else "stale", "missing")
    try:
        row["age_seconds"] = round(max(0.0, now - path.stat().st_mtime), 1)
    except OSError:
        row["age_seconds"] = None
    size, complete = _size(path)
    row["size_bytes"] = size
    row["size_complete"] = complete
    if tree.primary:
        return verdict("keep", "primary_checkout")
    if tree.locked:
        return verdict("keep", "locked")
    if str(path) in (in_use if in_use is not None else in_use_paths()):
        return verdict("keep", "in_use")
    if is_protected(tree.branch, primary_branch):
        return verdict("keep", "protected_branch")
    if tree.branch is None:
        return verdict("keep", "detached_head")
    if tree.branch.startswith(KANBAN_PREFIX):
        # A kanban card's tree: the board's own cleanup decides, after the card ends.
        return verdict("keep", "kanban_managed")
    try:
        state = tree_state(path, base=base)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return verdict("keep", "state_unreadable")
    row["tracked_changes"] = len(state["tracked_changes"])
    row["untracked"] = len(state["untracked"])
    row["unpushed"] = state["unpushed"]
    row["ignored"] = len(state["ignored"])
    if state["tracked_changes"]:
        return verdict("keep", "uncommitted_changes")
    if state["ignored"]:
        # git's own removal deletes ignored files; scratch is never deleted, so keep it.
        return verdict("keep", "ignored_files")
    if state["unpushed"] != 0:
        return verdict("keep", "unpushed_commits" if state["unpushed"] > 0 else "push_state_unknown")
    if row["age_seconds"] is not None and row["age_seconds"] < min_age_seconds:
        return verdict("keep", "too_recent")
    return verdict("removable", "scratch_only" if state["untracked"] else "clean_and_pushed")


def classify_all(repo: Path | str, *, min_age_seconds: float = 0.0,
                 now: float | None = None) -> list[dict[str, Any]]:
    trees = list_trees(repo)
    live = in_use_paths()
    return [classify(repo, tree, now=now, min_age_seconds=min_age_seconds, in_use=live) for tree in trees]


def archive_root() -> Path:
    from agents.core.paths import data_path

    return data_path("worktrees", "archive")


def archive_scratch(tree_path: Path | str, files: list[str], root: Path | None = None) -> Path | None:
    """Copy the untracked *files* of *tree_path* into a tar.gz under *root*; returns it.

    Symlinks are stored as links, never followed. Over :data:`ARCHIVE_MAX_BYTES` or
    :data:`ARCHIVE_MAX_FILES` it refuses (the tree is then kept)."""
    if not files:
        return None
    tree_path = Path(tree_path).resolve()
    if len(files) > ARCHIVE_MAX_FILES:
        raise WorktreeRefused("too much untracked scratch to archive; the tree is kept")
    total = 0
    members: list[Path] = []
    for name in files:
        candidate = Path(os.path.normpath(tree_path / name))
        if tree_path not in candidate.parents:
            raise WorktreeRefused("an untracked path points outside the tree; the tree is kept")
        info = os.lstat(candidate)
        total += info.st_size
        members.append(candidate)
    if total > ARCHIVE_MAX_BYTES:
        raise WorktreeRefused("untracked scratch is larger than the archive limit; the tree is kept")
    root = Path(root) if root is not None else archive_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = root / f"{tree_path.name}-{stamp}-{os.getpid()}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        for member in members:
            archive.add(str(member), arcname=str(member.relative_to(tree_path)), recursive=False)
    return target


def _drop_archived(tree_path: Path, files: list[str]) -> None:
    """Unlink exactly the archived files, then the directories they leave empty."""
    tree_path = tree_path.resolve()
    parents: set[Path] = set()
    for name in files:
        candidate = Path(os.path.normpath(tree_path / name))
        if tree_path not in candidate.parents:
            continue
        with contextlib.suppress(FileNotFoundError):
            os.unlink(candidate)
        parents.update(p for p in candidate.parents if tree_path in p.parents)
    for directory in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        with contextlib.suppress(OSError):
            directory.rmdir()


def reclaim(repo: Path | str, tree_path: Path | str, *, min_age_seconds: float = 0.0,
            base: str | None = None, archive_to: Path | None = None) -> dict[str, Any]:
    """Remove one tree when it classifies ``removable``: scratch archived first, the
    non-force ``git worktree remove``, then a generated branch's safe delete."""
    repo, tree_path = Path(repo), Path(tree_path).resolve()
    trees = {Path(t.path): t for t in list_trees(repo)}
    tree = trees.get(tree_path)
    if tree is None:
        return {"path": str(tree_path), "removed": False, "reason": "not_a_worktree"}
    row = classify(repo, tree, min_age_seconds=min_age_seconds, base=base)
    out = {**row, "removed": False}
    if row["verdict"] == "stale":
        result = run_git(repo, "worktree", "prune", mutate=True)
        out.update(removed=result.returncode == 0, reason="stale_metadata_pruned")
        return out
    if row["verdict"] != "removable":
        return out
    archived = None
    if row["reason"] == "scratch_only":
        untracked = tree_state(tree_path, base=base)["untracked"]
        try:
            archived = archive_scratch(tree_path, untracked, archive_to)
        except (WorktreeRefused, OSError) as exc:
            out["reason"] = f"scratch_kept: {exc}"[:200]
            return out
        out["archive"] = str(archived) if archived else None
        _drop_archived(tree_path, untracked)
    removed = run_git(repo, "worktree", "remove", str(tree_path), mutate=True)
    if removed.returncode:
        out["reason"] = "git_remove_refused"
        return out
    out.update(removed=True, reason="removed")
    branch = tree.branch
    if branch and branch.startswith(GENERATED_PREFIXES):
        deleted = run_git(repo, "branch", "-d", branch, mutate=True)
        out["branch_deleted"] = deleted.returncode == 0
    return out


def prune(repo: Path | str, *, min_age_seconds: float, apply: bool = False,
          archive_to: Path | None = None) -> dict[str, Any]:
    """Classify every tree; with *apply*, reclaim the removable ones."""
    rows = classify_all(repo, min_age_seconds=min_age_seconds)
    results = []
    for row in rows:
        if apply and row["verdict"] in {"removable", "stale"}:
            results.append(reclaim(repo, row["path"], min_age_seconds=min_age_seconds, archive_to=archive_to))
        else:
            results.append({**row, "removed": False})
    return {"repo": str(repo), "applied": apply, "trees": results,
            "removed": sum(1 for r in results if r.get("removed"))}


# ── live bindings: who is using a tree right now ─────────────────────────────

_LEASES: dict[str, int] = {}
_LEASE_LOCK = threading.Lock()
_BOUND: ContextVar[Path | None] = ContextVar("nerva_worktree_bound", default=None)


def in_use_paths() -> set[str]:
    with _LEASE_LOCK:
        held = {path for path, count in _LEASES.items() if count > 0}
    held.update(_session_tree_paths())
    return held


def acquire(path: Path | str) -> None:
    """Hold *path* in use (a reclaim keeps it) until :func:`release`."""
    key = str(Path(path).resolve())
    with _LEASE_LOCK:
        _LEASES[key] = _LEASES.get(key, 0) + 1


def release(path: Path | str) -> None:
    key = str(Path(path).resolve())
    with _LEASE_LOCK:
        if key in _LEASES:
            _LEASES[key] -= 1
            if _LEASES[key] <= 0:
                del _LEASES[key]


@contextlib.contextmanager
def lease(path: Path | str) -> Iterator[None]:
    acquire(path)
    try:
        yield
    finally:
        release(path)


def bound_tree() -> Path | None:
    """The worktree the code in flight is confined to (a child's or a session's), or None."""
    return _BOUND.get()


@contextlib.contextmanager
def tree_scope(path: Path | str) -> Iterator[Path]:
    """Confine the code in this context to *path*: file tools resolve inside it, and the
    tree is held in use (a reclaim keeps it) until the block ends."""
    resolved = Path(path).resolve()
    token = _BOUND.set(resolved)
    try:
        with lease(resolved):
            yield resolved
    finally:
        _BOUND.reset(token)


# ── session trees (H474): /worktree new binds a conversation to its own tree ──

_SESSIONS_LOCK = threading.Lock()


def sessions_path() -> Path:
    from agents.core.paths import data_path

    return data_path("worktrees", "sessions.json")


def _read_sessions() -> dict[str, dict]:
    path = sessions_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("worktree session bindings unreadable; none applied")
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _write_sessions(data: dict[str, dict]) -> None:
    path = sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def session_tree(session_id: str) -> dict | None:
    with _SESSIONS_LOCK:
        return _read_sessions().get(str(session_id or "default"))


def set_session_tree(session_id: str, record: dict | None) -> None:
    with _SESSIONS_LOCK:
        data = _read_sessions()
        key = str(session_id or "default")
        if record is None:
            data.pop(key, None)
        else:
            data[key] = dict(record)
        _write_sessions(data)


def _session_tree_paths() -> set[str]:
    try:
        with _SESSIONS_LOCK:
            return {str(Path(v["path"]).resolve()) for v in _read_sessions().values() if v.get("path")}
    except Exception:
        return set()


def session_tree_or_none(session_id: str) -> dict | None:
    """The session's tree record (blocking read), or None — never raises."""
    try:
        return session_tree(session_id)
    except Exception:  # noqa: BLE001
        return None


def apply_session_tree(record: dict | None) -> Path | None:
    """At the start of a turn, in the turn's own context: confine it to the session's
    tree when *record* names one that exists, else clear any binding. Returns the tree."""
    path = Path(record["path"]) if isinstance(record, dict) and record.get("path") else None
    if path is not None and not path.is_dir():
        path = None
    resolved = path.resolve() if path is not None else None
    _BOUND.set(resolved)
    return resolved


def bind_session_tree(session_id: str) -> Path | None:
    """:func:`apply_session_tree` for *session_id* (reads the bindings file)."""
    return apply_session_tree(session_tree_or_none(session_id))


# ── the kernel and the switches: one gate for every write here ──────────────

def write_refusal(*, session_id: str | None = None, authorizer: Callable[..., Any] | None = None,
                  agent: str = "jarvis", title: str = "", payload: dict | None = None) -> str | None:
    """Why a worktree write may not run now, or None: the emergency stop, plan mode on
    the session, and — when the Action Kernel is on — anything but a ``file.write`` grant."""
    from agents.core import estop

    if estop.is_engaged():
        return "the emergency stop is engaged"
    try:
        from agents.core.kernel.plan_mode import action_denial

        denied = action_denial("file.write", session_id=session_id)
    except Exception:  # noqa: BLE001 - fail closed
        denied = "plan mode: state unavailable"
    if denied:
        return denied
    if authorizer is None:
        return None
    try:
        from agents.core.kernel import Action, Verdict, kernel_enabled

        if not kernel_enabled():
            return None
        decision = authorizer(Action(kind="file.write", agent=agent, title=title or "Git worktree",
                                     payload=dict(payload or {})))
    except Exception:  # noqa: BLE001 - fail closed
        return "the Action Kernel could not authorize it"
    if getattr(decision, "verdict", None) is Verdict.GRANT:
        return None
    return "the Action Kernel did not grant it: " + str(getattr(decision, "reason", ""))[:160]


@dataclass
class ChildTree:
    """A delegated child's tree (H402): where it is, its branch and the commit it began at."""

    repo: str
    path: str
    branch: str
    base: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


def child_tree_name(spawn_id: str) -> str:
    """A filesystem- and ref-safe name for a spawn id."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(spawn_id)).strip("-.")[:60]
    return cleaned or "child"


def create_child_tree(project: Path | str, spawn_id: str) -> ChildTree:
    """``<repo>/.worktrees/<spawn>`` on ``sub/<spawn>``, from the repository's HEAD."""
    root = repo_root(project)
    if root is None:
        raise WorktreeRefused("the project folder is not a git repository")
    repo = main_repo(root) or root
    require_plain(repo)
    base = git_out(root, "rev-parse", "HEAD")
    if not base:
        raise WorktreeRefused("the repository has no commit to branch from")
    name = child_tree_name(spawn_id)
    tree = create(repo, repo / TREES_DIR / name, f"sub/{name}", base=base)
    acquire(tree.path)        # in use from the moment it exists; finish_child_tree releases it
    return ChildTree(repo=str(repo), path=tree.path, branch=f"sub/{name}", base=base)


def finish_child_tree(child: ChildTree, *, archive_to: Path | None = None) -> dict[str, Any]:
    """After a child ends: remove its tree when it made nothing (clean, no commits since
    its base; scratch archived), else keep it and report the branch, commits and changed
    files — the reviewable artefact."""
    repo, path = Path(child.repo), Path(child.path)
    release(child.path)
    report: dict[str, Any] = {"path": child.path, "branch": child.branch, "base": child.base[:12]}
    try:
        state = tree_state(path, base=child.base)
    except Exception:  # noqa: BLE001
        report.update(kept=True, reason="state_unreadable")
        return report
    changed = git_out(path, "diff", "--name-only", "--no-renames", "--no-textconv", "--no-ext-diff",
                      child.base) or ""
    files = sorted({*changed.splitlines(), *state["tracked_changes"], *state["untracked"]})
    report.update(commits=state["unpushed"], changed_files=files[:50],
                  changed_files_total=len(files))
    if state["ignored"]:
        report.update(kept=True, reason="ignored_files")
        return report
    if state["tracked_changes"] or state["unpushed"] != 0:
        report.update(kept=True, reason="has_changes")
        return report
    try:
        result = reclaim(repo, path, base=child.base, archive_to=archive_to)
    except Exception as exc:  # noqa: BLE001
        report.update(kept=True, reason=f"reclaim_failed: {type(exc).__name__}")
        return report
    report.update(kept=not result.get("removed"), reason=result.get("reason"))
    if result.get("archive"):
        report["archive"] = result["archive"]
    return report


__all__ = [
    "ARCHIVE_MAX_BYTES", "ChildTree", "GENERATED_PREFIXES", "PROTECTED_BRANCHES", "TREES_DIR", "Tree",
    "WorktreeRefused", "apply_session_tree", "archive_scratch", "bind_session_tree", "bound_tree", "check_branch", "classify",
    "classify_all", "config_refusal", "create", "create_child_tree", "finish_child_tree", "git_out",
    "in_use_paths", "is_protected", "lease", "list_trees", "main_repo", "prune", "reclaim", "repo_root",
    "require_plain", "run_git", "session_tree", "set_session_tree", "tree_scope", "tree_state",
    "valid_name", "write_refusal",
]
