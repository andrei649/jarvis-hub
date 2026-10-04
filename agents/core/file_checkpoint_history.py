"""Private, scoped checkpoint index over FileTools' existing SnapshotStore blobs.

This is a storage/effect primitive, not an owner-facing authorization route. Callers
must retain their existing file.write kernel and durable approval mediation.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import os
import secrets
import sqlite3
import stat
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .file_tools import FileScope, Snapshot, SnapshotStore

if sys.platform != "win32":
    import fcntl

HISTORY_SUPPORTED = sys.platform != "win32" and hasattr(os, "O_DIRECTORY")
MAX_CAPTURE_BYTES = 16 * 1024 * 1024
MAX_SCOPE_BYTES = 128 * 1024 * 1024
MAX_SCOPE_FILES = 2000
MAX_SCOPE_DEPTH = 16
MAX_SCAN_SECONDS = 10
SCOPE_POLICY_VERSION = 1
_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".worktrees", ".venv", "venv", "node_modules",
    "vendor", "__pycache__", ".mypy_cache", ".pytest_cache", "build", "dist", "logs",
})
_EXCLUDED_SUFFIXES = frozenset({
    ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".mp4", ".mov", ".pdf",
    ".sqlite", ".db", ".so", ".dylib", ".exe", ".pyc", ".parquet",
})
_lock_state = threading.local()


class CheckpointRefusal(Exception):
    """An exact physical state/scope fence refused the effect."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CapturedPreimage:
    """Snapshot plus the exact scope-root inode observed before authorization."""

    snapshot: Snapshot
    root_dev: int
    root_ino: int


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fingerprint(state: tuple[bool, str, int, int, bytes]) -> list:
    return [*state[:4]]


def _valid_expected(value: object) -> bool:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return False
    exists, sha, size, mode = value
    return (type(exists) is bool and isinstance(sha, str) and len(sha) == 64
            and all(c in "0123456789abcdef" for c in sha)
            and type(size) is int and 0 <= size <= MAX_CAPTURE_BYTES
            and type(mode) is int and 0 <= mode <= 0o7777
            and (exists or (sha, size, mode) == (_sha(b""), 0, 0)))


def _canonical_selection(paths: object) -> bool:
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= 500:
        return False
    seen: set[str] = set()
    for path in paths:
        if (not isinstance(path, str) or not path or len(path) > 4096
                or path in seen or "\\" in path
                or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or path.startswith("/") or PurePosixPath(path).as_posix() != path
                or any(part in ("", ".", "..") for part in path.split("/"))):
            return False
        seen.add(path)
    return True


@contextlib.contextmanager
def _locked(directory: Path):
    if not HISTORY_SUPPORTED:
        raise CheckpointRefusal("history_unsupported_platform")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = str(directory.resolve())
    held = getattr(_lock_state, "held", None)
    if held is None:
        held = {}
        _lock_state.held = held
    if key in held:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    # The lock survives index pruning and is never part of its garbage collection.
    fd = os.open(directory / "history.lock", os.O_RDWR | os.O_CREAT
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        held[key] = 1
        yield
    finally:
        held.pop(key, None)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextlib.contextmanager
def _parent_fd(root: Path, target: Path, identity: tuple[int, int], *, create: bool):
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise CheckpointRefusal("outside_scope") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise CheckpointRefusal("outside_scope")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | nofollow)
    opened = [directory]
    try:
        info = os.fstat(directory)
        if (info.st_dev, info.st_ino) != identity:
            raise CheckpointRefusal("root_changed")
        for part in relative.parts[:-1]:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, mode=0o755, dir_fd=directory)
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | nofollow,
                                dir_fd=directory)
            opened.append(directory)
        yield directory, relative.parts[-1]
    except (OSError, NotImplementedError) as exc:
        raise CheckpointRefusal("path_changed") from exc
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _state(parent: int, name: str, *, max_bytes: int,
           expected_dev: int | None = None,
           single_link: bool = False) -> tuple[bool, str, int, int, bytes]:
    if type(max_bytes) is not int or max_bytes < 0 or max_bytes > MAX_CAPTURE_BYTES:
        raise CheckpointRefusal("checkpoint_too_large")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
                     dir_fd=parent)
    except FileNotFoundError:
        return False, _sha(b""), 0, 0, b""
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise CheckpointRefusal("not_a_file")
        if expected_dev is not None and info.st_dev != expected_dev:
            raise CheckpointRefusal("different_device")
        if single_link and info.st_nlink != 1:
            raise CheckpointRefusal("hard_link_excluded")
        if info.st_size > max_bytes:
            raise CheckpointRefusal("changed_since_checkpoint")
        with os.fdopen(os.dup(fd), "rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise CheckpointRefusal("changed_since_checkpoint")
        # The file may have changed while read; refuse rather than publish a mixed state.
        after = os.fstat(fd)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise CheckpointRefusal("changed_since_checkpoint")
        return True, _sha(data), len(data), stat.S_IMODE(info.st_mode), data
    finally:
        os.close(fd)


def _replace(parent: int, name: str, data: bytes, mode: int) -> None:
    temp = f".nerva-history-{secrets.token_hex(12)}"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode, dir_fd=parent, follow_symlinks=False)
        os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp, dir_fd=parent)
        raise


class FileCheckpointHistory:
    """One index for actual FileTools mutations, backed by SnapshotStore refs."""

    def __init__(self, snapshots: SnapshotStore, scope: FileScope) -> None:
        self.snapshots = snapshots
        self.scope = scope
        self._db = snapshots.directory / "history.sqlite3"

    @contextlib.contextmanager
    def _connection(self):
        directory = self.snapshots.directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._db.is_symlink():
            raise CheckpointRefusal("history_store_invalid")
        if not self._db.exists():
            fd = os.open(self._db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        connection = sqlite3.connect(self._db)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("""CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY, path TEXT NOT NULL, root TEXT NOT NULL,
                root_dev INTEGER NOT NULL, root_ino INTEGER NOT NULL,
                op TEXT NOT NULL, pre_ref TEXT NOT NULL, status TEXT NOT NULL,
                post_existed INTEGER, post_sha TEXT, post_size INTEGER, post_mode INTEGER,
                undo_ref TEXT, source_kind TEXT NOT NULL, tool_turn TEXT,
                created_at REAL NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS entries_path ON entries(path, id)")
            connection.execute("""CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY, root TEXT NOT NULL, root_dev INTEGER NOT NULL,
                root_ino INTEGER NOT NULL, source_kind TEXT NOT NULL,
                source_key TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL, finished_at REAL,
                excluded INTEGER NOT NULL DEFAULT 0, note TEXT,
                policy_version INTEGER NOT NULL DEFAULT 1,
                undo_group_id TEXT
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS group_files (
                group_id TEXT NOT NULL, path TEXT NOT NULL,
                pre_ref TEXT, pre_existed INTEGER NOT NULL,
                post_existed INTEGER, post_sha TEXT, post_size INTEGER,
                post_mode INTEGER, change_kind TEXT,
                undo_ref TEXT, restore_status TEXT,
                PRIMARY KEY (group_id, path)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS group_exclusions (
                group_id TEXT NOT NULL, path TEXT NOT NULL,
                PRIMARY KEY (group_id, path)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS group_runs (
                id TEXT PRIMARY KEY, group_id TEXT NOT NULL, target TEXT,
                argv_sha256 TEXT, status TEXT NOT NULL,
                started_at REAL NOT NULL, finished_at REAL
            )""")
            connection.commit()
            yield connection
        finally:
            connection.close()

    def _put_blob(self, data: bytes) -> str:
        from .file_tools import _atomic_write

        sha = _sha(data)
        blob = self.snapshots.directory / "blobs" / sha
        blob.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not blob.exists():
            _atomic_write(blob, data, mode=0o600)
        return sha

    def _blob_bytes(self, sha: object, size: object) -> bytes | None:
        """Verify a bounded regular blob without following a corrupted store path."""
        from .file_tools import _is_ref

        if not _is_ref(sha) or type(size) is not int or not 0 <= size <= MAX_CAPTURE_BYTES:
            return None
        parent = None
        try:
            parent = os.open(self.snapshots.directory / "blobs", os.O_RDONLY
                             | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
            exists, actual_sha, actual_size, _, data = _state(parent, sha, max_bytes=size)
            return data if exists and actual_sha == sha and actual_size == size else None
        except (OSError, CheckpointRefusal):
            return None
        finally:
            if parent is not None:
                os.close(parent)

    @staticmethod
    def _group_root(root: Path) -> tuple[Path, tuple[int, int]]:
        root = Path(root)
        if not root.is_absolute() or root == Path("/") or root == Path.home():
            raise CheckpointRefusal("scope_too_broad")
        info = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise CheckpointRefusal("scope_changed")
        return root, (info.st_dev, info.st_ino)

    def _protected_scope_paths(self, root: Path) -> set[str]:
        """Exclude this store and runtime state, including not-yet-created paths."""
        from .paths import data_root

        store = self.snapshots.directory.resolve()
        runtime = data_root().resolve()
        if root in (store, runtime) or store in root.parents:
            raise CheckpointRefusal("private_scope")
        protected = set()
        for path in (store, runtime):
            if root in path.parents:
                protected.add(str(path.relative_to(root)))
        return protected

    def _scan_group(self, root: Path, identity: tuple[int, int]) -> tuple[dict, set[str]]:
        """Bounded observed regular files. Unknown paths are never restore candidates."""
        from .file_tools import FileScopeError

        found: dict[str, tuple[str, int, int, bytes]] = {}
        excluded = self._protected_scope_paths(root)
        total = 0
        visited = 0
        started = time.monotonic()
        def walk_error(error: OSError) -> None:
            raise CheckpointRefusal("scope_scan_failed") from error

        for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            if time.monotonic() - started > MAX_SCAN_SECONDS:
                raise CheckpointRefusal("scope_scan_timeout")
            dirs.sort()
            files.sort()
            relative_dir = Path(directory).relative_to(root)
            kept = []
            for name in dirs:
                child = Path(directory) / name
                rel_child = str(relative_dir / name)
                try:
                    other_device = os.stat(child, follow_symlinks=False).st_dev != identity[0]
                except OSError:
                    other_device = True
                if (name in _EXCLUDED_DIRS or name.startswith(".nerva-history-")
                        or child.is_symlink() or other_device
                        or len(relative_dir.parts) >= MAX_SCOPE_DEPTH
                        or any(rel_child == prefix or rel_child.startswith(prefix + "/")
                               for prefix in excluded)):
                    excluded.add(rel_child)
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in files:
                visited += 1
                if visited > MAX_SCOPE_FILES:
                    raise CheckpointRefusal("scope_file_limit")
                path = Path(directory) / name
                rel = str(path.relative_to(root))
                if (path.suffix.lower() in _EXCLUDED_SUFFIXES
                        or any(rel == prefix or rel.startswith(prefix + "/")
                               for prefix in excluded)):
                    excluded.add(rel)
                    continue
                try:
                    if self.scope.resolve(str(path)) != path:
                        excluded.add(rel)
                        continue
                    with _parent_fd(root, path, identity, create=False) as (parent, leaf):
                        info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                        if info.st_size > MAX_CAPTURE_BYTES:
                            excluded.add(rel)
                            continue
                        if info.st_size > MAX_SCOPE_BYTES - total:
                            raise CheckpointRefusal("scope_byte_limit")
                        exists, sha, size, mode, data = _state(
                            parent, leaf, max_bytes=min(MAX_CAPTURE_BYTES, MAX_SCOPE_BYTES - total),
                            expected_dev=identity[0], single_link=True,
                        )
                    if not exists:
                        raise CheckpointRefusal("scope_changed")
                    if b"\x00" in data[:4096]:
                        excluded.add(rel)
                        continue
                except (FileScopeError, CheckpointRefusal, OSError) as exc:
                    if isinstance(exc, CheckpointRefusal) and exc.reason in {
                        "root_changed", "scope_byte_limit"
                    }:
                        raise
                    excluded.add(rel)
                    continue
                found[rel] = (sha, size, mode, data)
                total += size
                if total > MAX_SCOPE_BYTES:
                    raise CheckpointRefusal("scope_byte_limit")
        info = os.stat(root, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != identity:
            raise CheckpointRefusal("root_changed")
        return found, excluded

    def begin_scope(self, root: Path, *, source_kind: str,
                    source_key: str, target: str | None = None,
                    argv_sha256: str | None = None,
                    cancelled: threading.Event | None = None) -> dict:
        """Persist a full scoped preimage before a trusted local physical spawn."""
        root, identity = self._group_root(root)
        self._protected_scope_paths(root)
        if self.scope.roots != (root,):
            raise CheckpointRefusal("scope_changed")
        if source_kind not in ("terminal_invocation", "terminal_task", "terminal_turn") or (
            not isinstance(source_key, str) or not 1 <= len(source_key) <= 192
        ):
            raise CheckpointRefusal("invalid_source")
        if target is not None and (not isinstance(target, str) or len(target) > 64):
            raise CheckpointRefusal("invalid_source")
        if argv_sha256 is not None and (
            not isinstance(argv_sha256, str) or len(argv_sha256) != 64
            or any(c not in "0123456789abcdef" for c in argv_sha256)
        ):
            raise CheckpointRefusal("invalid_source")
        group_id = secrets.token_hex(16)
        run_id = secrets.token_hex(16)
        with _locked(self.snapshots.directory), self._connection() as db:
            overlap = False
            if source_kind in {"terminal_turn", "terminal_task"}:
                db.row_factory = sqlite3.Row
                active = db.execute("""SELECT id FROM groups WHERE root=?
                    AND root_dev=? AND root_ino=? AND source_kind=? AND source_key=?
                    AND status IN ('ready', 'running')""",
                    (str(root), *identity, source_kind, source_key)).fetchall()
                overlap = bool(active)
                if active:
                    db.executemany("UPDATE groups SET note='non_composable_overlap' WHERE id=?",
                                   [(item["id"],) for item in active])
                previous = db.execute("""SELECT * FROM groups
                    WHERE root=? AND root_dev=? AND root_ino=?
                    AND source_kind=? AND source_key=? AND status='finished'
                    AND note IS NULL
                    AND policy_version=?
                    ORDER BY created_at DESC LIMIT 1""",
                    (str(root), *identity, source_kind, source_key,
                     SCOPE_POLICY_VERSION)).fetchone()
                if previous is not None and not overlap:
                    # Sequential commands share the original preimage. A
                    # concurrently running group is never composed into it.
                    db.execute("UPDATE groups SET status='running' WHERE id=?",
                               (previous["id"],))
                    db.execute("""INSERT INTO group_runs
                        (id, group_id, target, argv_sha256, status, started_at)
                        VALUES (?, ?, ?, ?, 'running', ?)""",
                        (run_id, previous["id"], target, argv_sha256, time.time()))
                    db.commit()
                    covered = db.execute("""SELECT COUNT(*) FROM group_files
                        WHERE group_id=? AND pre_existed=1""", (previous["id"],)).fetchone()[0]
                    return {"id": previous["id"], "run_id": run_id, "root": str(root),
                            "root_identity": identity, "status": "running",
                            "covered": covered, "excluded": previous["excluded"],
                            "reused": True}
            db.execute("""INSERT INTO groups
                (id, root, root_dev, root_ino, source_kind, source_key,
                 status, created_at, note)
                VALUES (?, ?, ?, ?, ?, ?, 'capturing', ?, ?)""",
                (group_id, str(root), *identity, source_kind, source_key,
                 time.time(), "non_composable_overlap" if overlap else None))
            db.execute("""INSERT INTO group_runs
                (id, group_id, target, argv_sha256, status, started_at)
                VALUES (?, ?, ?, ?, 'capturing', ?)""",
                (run_id, group_id, target, argv_sha256, time.time()))
            db.commit()
            try:
                observed, excluded_paths = self._scan_group(root, identity)
                for rel, (_, _, mode, data) in observed.items():
                    snap = self.snapshots.take_captured(
                        root / rel, existed=True, data=data, mode=mode
                    )
                    db.execute("""INSERT INTO group_files
                        (group_id, path, pre_ref, pre_existed) VALUES (?, ?, ?, 1)""",
                        (group_id, rel, snap.ref))
                db.executemany("""INSERT INTO group_exclusions (group_id, path)
                    VALUES (?, ?)""", [(group_id, path) for path in excluded_paths])
                abandoned = cancelled is not None and cancelled.is_set()
                db.execute("""UPDATE groups SET status=?, excluded=?,
                    note=CASE WHEN note='non_composable_overlap' THEN note
                              WHEN ? THEN 'capture_cancelled' ELSE note END,
                    finished_at=? WHERE id=?""",
                    ("no_process" if abandoned else "ready", len(excluded_paths),
                     abandoned, time.time() if abandoned else None, group_id))
                db.execute("UPDATE group_runs SET status=?, finished_at=? WHERE id=?",
                           ("no_process" if abandoned else "ready",
                            time.time() if abandoned else None, run_id))
                db.commit()
            except BaseException:
                db.execute("UPDATE groups SET status='incomplete', note='pre_capture_failed' WHERE id=?",
                           (group_id,))
                db.execute("UPDATE group_runs SET status='incomplete' WHERE id=?", (run_id,))
                db.commit()
                raise
        return {"id": group_id, "run_id": run_id, "root": str(root),
                "root_identity": identity,
                "status": "no_process" if abandoned else "ready", "covered": len(observed),
                "excluded": len(excluded_paths), "reused": False}

    def mark_scope_no_process(self, group_id: str, *, reason: str,
                              run_id: str | None = None) -> None:
        with _locked(self.snapshots.directory), self._connection() as db:
            db.execute("""UPDATE groups SET status='no_process', note=?, finished_at=?
                WHERE id=? AND status='ready'""", (reason[:128], time.time(), group_id))
            db.execute("""UPDATE groups SET status='finished'
                WHERE id=? AND status='running'""", (group_id,))
            if run_id is not None:
                db.execute("""UPDATE group_runs SET status='no_process', finished_at=?
                    WHERE id=? AND group_id=?""", (time.time(), run_id, group_id))
            db.commit()

    def mark_scope_incomplete(self, group_id: str, *, reason: str,
                              run_id: str | None = None) -> None:
        with _locked(self.snapshots.directory), self._connection() as db:
            db.execute("""UPDATE groups SET status='incomplete', note=?, finished_at=?
                WHERE id=? AND status IN ('ready', 'running')""",
                       (reason[:128], time.time(), group_id))
            if run_id is not None:
                db.execute("""UPDATE group_runs SET status='incomplete', finished_at=?
                    WHERE id=? AND group_id=?""", (time.time(), run_id, group_id))
            db.commit()

    def finish_scope(self, group_id: str, *, reaped: bool,
                     run_id: str | None = None) -> dict:
        """Observe the scoped poststate only after process exit or confirmed reap."""
        with _locked(self.snapshots.directory), self._connection() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
            if row is None or row["status"] not in {"ready", "running"}:
                return {"id": group_id, "status": "incomplete", "reason": "group_not_ready"}
            if not reaped:
                db.execute("UPDATE groups SET status='incomplete', note='process_not_reaped' WHERE id=?",
                           (group_id,))
                if run_id is not None:
                    db.execute("""UPDATE group_runs SET status='incomplete', finished_at=?
                        WHERE id=? AND group_id=?""", (time.time(), run_id, group_id))
                db.commit()
                return {"id": group_id, "status": "incomplete", "reason": "process_not_reaped"}
            root = Path(row["root"])
            identity = row["root_dev"], row["root_ino"]
            try:
                if self._group_root(root)[1] != identity:
                    raise CheckpointRefusal("root_changed")
                observed, excluded_paths = self._scan_group(root, identity)
                permanent = {path for (path,) in db.execute(
                    "SELECT path FROM group_exclusions WHERE group_id=?", (group_id,)
                )}
                def outside_coverage(path: str) -> bool:
                    return any(path == prefix or path.startswith(prefix + "/")
                               for prefix in permanent)

                for rel in tuple(observed):
                    if outside_coverage(rel):
                        observed.pop(rel)
                db.executemany("""INSERT OR IGNORE INTO group_exclusions (group_id, path)
                    VALUES (?, ?)""", [(group_id, path) for path in excluded_paths])
                pre = {item["path"]: item for item in db.execute(
                    "SELECT * FROM group_files WHERE group_id=?", (group_id,)
                )}
                modified = created = deleted = 0
                for rel, item in pre.items():
                    post = observed.pop(rel, None)
                    if not item["pre_existed"]:
                        if post is None:
                            db.execute("""UPDATE group_files SET post_existed=0,
                                post_sha=?, post_size=0, post_mode=0,
                                change_kind='unchanged' WHERE group_id=? AND path=?""",
                                (_sha(b""), group_id, rel))
                        else:
                            sha, size, mode, data = post
                            self._put_blob(data)
                            db.execute("""UPDATE group_files SET post_existed=1,
                                post_sha=?, post_size=?, post_mode=?,
                                change_kind='created' WHERE group_id=? AND path=?""",
                                (sha, size, mode, group_id, rel))
                            created += 1
                        continue
                    snap = self.snapshots.load(item["pre_ref"])
                    if snap is None or snap.path != str(root / rel):
                        raise CheckpointRefusal("snapshot_changed")
                    if post is None:
                        # A now-excluded/oversized path is unknown, never a deletion.
                        if (outside_coverage(rel) or rel in excluded_paths
                                or (root / rel).exists() or (root / rel).is_symlink()):
                            excluded_paths.add(rel)
                            continue
                        self._put_blob(b"")
                        db.execute("""UPDATE group_files SET post_existed=0, post_sha=?,
                            post_size=0, post_mode=0, change_kind='deleted'
                            WHERE group_id=? AND path=?""", (_sha(b""), group_id, rel))
                        deleted += 1
                        continue
                    sha, size, mode, data = post
                    kind = "modified" if (sha, size, mode) != (
                        snap.blob_sha, snap.size, snap.mode
                    ) else "unchanged"
                    self._put_blob(data)
                    db.execute("""UPDATE group_files SET post_existed=1, post_sha=?,
                        post_size=?, post_mode=?, change_kind=?
                        WHERE group_id=? AND path=?""",
                        (sha, size, mode, kind, group_id, rel))
                    modified += kind == "modified"
                for rel, (sha, size, mode, data) in observed.items():
                    self._put_blob(data)
                    db.execute("""INSERT INTO group_files
                        (group_id, path, pre_existed, post_existed, post_sha,
                         post_size, post_mode, change_kind)
                        VALUES (?, ?, 0, 1, ?, ?, ?, 'created')""",
                        (group_id, rel, sha, size, mode))
                    created += 1
                db.executemany("""INSERT OR IGNORE INTO group_exclusions (group_id, path)
                    VALUES (?, ?)""", [(group_id, path) for path in excluded_paths])
                exclusion_count = db.execute("""SELECT COUNT(*) FROM group_exclusions
                    WHERE group_id=?""", (group_id,)).fetchone()[0]
                db.execute("""UPDATE groups SET status='finished', excluded=?,
                    finished_at=? WHERE id=?""", (exclusion_count, time.time(), group_id))
                if run_id is not None:
                    db.execute("""UPDATE group_runs SET status='finished', finished_at=?
                        WHERE id=? AND group_id=?""", (time.time(), run_id, group_id))
                db.commit()
                return {"id": group_id, "status": "finished", "root": str(root),
                        "modified": modified, "created": created, "deleted": deleted,
                        "excluded": exclusion_count,
                        "coverage": "scoped_observation_not_command_causality"}
            except Exception as exc:
                db.rollback()
                db.execute("UPDATE groups SET status='incomplete', note=?, finished_at=? WHERE id=?",
                           (getattr(exc, "reason", "post_capture_failed"), time.time(), group_id))
                if run_id is not None:
                    db.execute("""UPDATE group_runs SET status='incomplete', finished_at=?
                        WHERE id=? AND group_id=?""", (time.time(), run_id, group_id))
                db.commit()
                return {"id": group_id, "status": "incomplete",
                        "reason": getattr(exc, "reason", "post_capture_failed")}

    def list_groups(self, *, root: Path | None = None, limit: int = 100) -> list[dict]:
        """Browse scoped groups; this view is not an approval to restore."""
        if not self._db.exists():
            return []
        limit = min(max(limit, 0), 500)
        with _locked(self.snapshots.directory), self._connection() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM groups ORDER BY created_at DESC LIMIT ?", (limit,))
            result = []
            for row in rows:
                item = dict(row)
                try:
                    path, identity = self._group_root(Path(item["root"]))
                except (OSError, CheckpointRefusal):
                    continue
                if (identity != (item["root_dev"], item["root_ino"])
                        or self.scope.roots != (path,)
                        or (root is not None and path != root)):
                    continue
                result.append(item)
            return result

    def _group_row(self, db: sqlite3.Connection, group_id: str) -> dict | None:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
        return dict(row) if row else None

    def list_group_runs(self, group_id: str) -> list[dict]:
        if not self._db.exists():
            return []
        with _locked(self.snapshots.directory), self._connection() as db:
            row = self._group_row(db, group_id)
            if row is None:
                return []
            try:
                root, identity = self._group_root(Path(row["root"]))
            except (OSError, CheckpointRefusal):
                return []
            if self.scope.roots != (root,) or identity != (
                row["root_dev"], row["root_ino"]
            ):
                return []
            db.row_factory = sqlite3.Row
            return [dict(item) for item in db.execute(
                "SELECT * FROM group_runs WHERE group_id=? ORDER BY started_at", (group_id,)
            )]

    def _group_targets(self, db: sqlite3.Connection, group_id: str) -> list[dict]:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("""SELECT * FROM group_files
            WHERE group_id=? AND change_kind IN ('modified', 'created', 'deleted')
            ORDER BY path""", (group_id,))]

    def _group_current(self, root: Path, identity: tuple[int, int], item: dict,
                       *, pre: bool = False, force: bool = False
                       ) -> tuple[bool, str, int, int, bytes]:
        path = root / item["path"]
        if any(item["path"] == prefix or item["path"].startswith(prefix + "/")
               for prefix in self._protected_scope_paths(root)):
            raise CheckpointRefusal("private_scope")
        if self.scope.resolve(str(path)) != path:
            raise CheckpointRefusal("scope_changed")
        with _parent_fd(root, path, identity, create=False) as (parent, name):
            return _state(parent, name, max_bytes=(
                MAX_CAPTURE_BYTES if pre or force else item["post_size"]
            ), expected_dev=identity[0], single_link=True)

    def _selected_group_targets(self, db: sqlite3.Connection, group_id: str,
                                paths: list[str] | tuple[str, ...] | None
                                ) -> tuple[list[dict], str | None]:
        targets = self._group_targets(db, group_id)
        pending = {item["path"]: item for item in targets
                   if item["restore_status"] != "restored"}
        if paths is None:
            return list(pending.values()), None
        if not _canonical_selection(paths):
            return [], "invalid_selection"
        if any(path not in pending for path in paths):
            return [], "unknown_or_restored_path"
        return [pending[path] for path in paths], None

    def _group_coverage(self, db: sqlite3.Connection, group_id: str,
                        excluded: int) -> dict:
        covered, restored = db.execute("""SELECT COUNT(*),
            COALESCE(SUM(CASE WHEN restore_status='restored' THEN 1 ELSE 0 END), 0)
            FROM group_files WHERE group_id=?
            AND change_kind IN ('modified', 'created', 'deleted')""",
            (group_id,)).fetchone()
        remaining = covered - restored
        return {"covered": covered, "restored_total": restored,
                "remaining": remaining, "complete": remaining == 0 and excluded == 0}

    def plan_group_restore(self, group_id: str, *, paths: list[str] | tuple[str, ...] | None = None,
                           force: bool = False) -> dict:
        """Read-only currentness; a future caller supplies reversible-tier authority."""
        if type(force) is not bool:
            return {"ok": False, "reason": "invalid_force"}
        if not self._db.exists():
            return {"ok": False, "reason": "unknown_checkpoint"}
        with _locked(self.snapshots.directory), self._connection() as db:
            row = self._group_row(db, group_id)
            if row is None or row["status"] not in {"finished", "partial"}:
                return {"ok": False, "reason": "unknown_checkpoint"}
            if row["note"] == "non_composable_overlap":
                return {"ok": False, "reason": "overlapping_scope"}
            if db.execute("""SELECT 1 FROM group_files WHERE group_id=?
                AND restore_status='prepared' LIMIT 1""", (group_id,)).fetchone():
                return {"ok": False, "reason": "uncertain_restore"}
            root = Path(row["root"])
            try:
                if (self._group_root(root)[1] != (row["root_dev"], row["root_ino"])
                        or self.scope.roots != (root,)):
                    raise CheckpointRefusal("scope_changed")
            except (OSError, CheckpointRefusal):
                return {"ok": False, "reason": "scope_changed"}
            identity = row["root_dev"], row["root_ino"]
            selected, selection_error = self._selected_group_targets(db, group_id, paths)
            if selection_error:
                return {"ok": False, "reason": selection_error}
            eligible = skipped = 0
            planned_paths = []
            current_fingerprints = {}
            for item in selected:
                snap = self.snapshots.load(item["pre_ref"]) if item["pre_ref"] else None
                before = self._blob_bytes(snap.blob_sha, snap.size) if snap else None
                after = self._blob_bytes(item["post_sha"], item["post_size"])
                valid_pre = (not item["pre_existed"] or
                             (snap is not None and snap.path == str(root / item["path"])
                              and before is not None))
                try:
                    current = self._group_current(root, identity, item, force=force)
                    current_ok = force or current[:4] == (
                        bool(item["post_existed"]), item["post_sha"],
                        item["post_size"], item["post_mode"]
                    )
                    if force and current[0] and b"\x00" in current[4][:4096]:
                        current_ok = False
                except (OSError, CheckpointRefusal, ValueError):
                    current_ok = False
                reason = "ready" if valid_pre and after is not None and current_ok else (
                    "snapshot_changed" if not valid_pre or after is None
                    else "changed_since_checkpoint"
                )
                eligible += reason == "ready"
                skipped += reason != "ready"
                planned_paths.append({"path": item["path"], "change": item["change_kind"],
                                      "reason": reason})
                if force and reason == "ready":
                    current_fingerprints[item["path"]] = _fingerprint(current)
            return {"ok": True, "id": group_id, "root": str(root),
                    "eligible": eligible, "skipped": skipped,
                    "excluded": row["excluded"], "paths": planned_paths,
                    **({"current": current_fingerprints} if force else {}),
                    **self._group_coverage(db, group_id, row["excluded"]),
                    "requires_authority": True,
                    "coverage": "scoped_observation_not_command_causality"}

    def diff_group(self, group_id: str, *, max_bytes: int = 65536) -> dict:
        """Bounded, redacted historical preview of covered changes only."""
        max_bytes = min(max(max_bytes, 1), 65536)
        if not self._db.exists():
            return {"ok": False, "reason": "unknown_checkpoint"}
        from .security.log_redaction import SecretRedactionFilter
        from .security.scanner import PIIScanner

        with _locked(self.snapshots.directory), self._connection() as db:
            row = self._group_row(db, group_id)
            if row is None or row["status"] not in {"finished", "restored", "partial"}:
                return {"ok": False, "reason": "unknown_checkpoint"}
            try:
                root, identity = self._group_root(Path(row["root"]))
                if self.scope.roots != (root,) or identity != (
                    row["root_dev"], row["root_ino"]
                ):
                    raise CheckpointRefusal("scope_changed")
            except (OSError, CheckpointRefusal):
                return {"ok": False, "reason": "scope_changed"}
            chunks = []
            for item in self._group_targets(db, group_id):
                snap = self.snapshots.load(item["pre_ref"]) if item["pre_ref"] else None
                before = self._blob_bytes(snap.blob_sha, snap.size) if snap else b""
                after = self._blob_bytes(item["post_sha"], item["post_size"])
                if before is None or after is None:
                    return {"ok": False, "reason": "snapshot_changed"}
                if len(before) > max_bytes or len(after) > max_bytes:
                    chunks.append(f"{item['path']}: diff_too_large\n")
                    continue
                try:
                    old = before.decode("utf-8")
                    new = after.decode("utf-8")
                    if "\x00" in old or "\x00" in new:
                        raise UnicodeError
                except UnicodeError:
                    chunks.append(f"{item['path']}: binary_change\n")
                    continue
                chunks.extend(difflib.unified_diff(
                    old.splitlines(keepends=True), new.splitlines(keepends=True),
                    fromfile=f"before/{item['path']}", tofile=f"after/{item['path']}",
                ))
                if sum(len(part.encode("utf-8")) for part in chunks) > 4 * max_bytes:
                    break
            try:
                redacted = PIIScanner().redact(
                    SecretRedactionFilter().redact_text("".join(chunks))
                )
            except Exception:
                return {"ok": False, "reason": "redaction_failed"}
            encoded = redacted.encode("utf-8")
            return {"ok": True, "diff": encoded[:max_bytes].decode("utf-8", errors="ignore"),
                    "truncated": len(encoded) > max_bytes,
                    "excluded": row["excluded"]}

    def restore_group(self, group_id: str, *,
                      paths: list[str] | tuple[str, ...] | None = None,
                      force: bool = False, expected_current: Mapping[str, object] | None = None,
                      effect_check: Callable[[], bool] | None = None) -> dict:
        """Trusted effect primitive; caller must mediate each intended restore."""
        preview = self.plan_group_restore(group_id, paths=paths, force=force)
        if not preview.get("ok"):
            return preview
        if effect_check is not None and not callable(effect_check):
            return {"ok": False, "reason": "invalid_effect_check"}
        selected_paths = [item["path"] for item in preview["paths"]]
        if force:
            if expected_current is None:
                return {"ok": False, "reason": "expected_current_required"}
            if (type(expected_current) is not dict
                    or set(expected_current) != set(selected_paths)
                    or any(not _valid_expected(value)
                           for value in expected_current.values())
                    or any(list(expected_current[path]) != preview["current"].get(path)
                           for path in selected_paths)):
                return {"ok": False, "reason": "expected_current_mismatch"}
            bound_current = {path: tuple(expected_current[path]) for path in selected_paths}
        elif expected_current is not None:
            return {"ok": False, "reason": "unexpected_current"}
        else:
            bound_current = {}
        with _locked(self.snapshots.directory), self._connection() as db:
            row = self._group_row(db, group_id)
            if row is None or row["status"] not in {"finished", "partial"}:
                return {"ok": False, "reason": "unknown_checkpoint"}
            root = Path(row["root"])
            identity = row["root_dev"], row["root_ino"]
            try:
                if (self._group_root(root)[1] != identity
                        or self.scope.roots != (root,)):
                    raise CheckpointRefusal("scope_changed")
                protected = self._protected_scope_paths(root)
            except (OSError, CheckpointRefusal) as exc:
                return {"ok": False, "reason": getattr(exc, "reason", "scope_changed")}
            selected, selection_error = self._selected_group_targets(db, group_id, paths)
            if selection_error or [item["path"] for item in selected] != selected_paths:
                return {"ok": False, "reason": selection_error or "selection_changed"}
            skipped = 0
            candidates: list[tuple[dict, bytes, int, tuple]] = []
            for item in selected:
                target = root / item["path"]
                if any(item["path"] == prefix or item["path"].startswith(prefix + "/")
                       for prefix in protected):
                    if force:
                        return {"ok": False, "reason": "private_scope"}
                    skipped += 1
                    continue
                snap = self.snapshots.load(item["pre_ref"]) if item["pre_ref"] else None
                before = self._blob_bytes(snap.blob_sha, snap.size) if snap else b""
                if ((item["pre_existed"] and (snap is None or before is None
                     or snap.path != str(target)))
                        or self._blob_bytes(item["post_sha"], item["post_size"]) is None):
                    if force:
                        return {"ok": False, "reason": "snapshot_changed"}
                    skipped += 1
                    continue
                try:
                    if self._group_root(root)[1] != identity:
                        raise CheckpointRefusal("root_changed")
                    if self.scope.resolve(str(target)) != target:
                        raise CheckpointRefusal("scope_changed")
                    with _parent_fd(root, target, identity, create=False) as (parent, name):
                        current = _state(parent, name, max_bytes=(
                            MAX_CAPTURE_BYTES if force else item["post_size"]
                        ), expected_dev=identity[0], single_link=True)
                    expected = (bound_current[item["path"]] if force else
                                (bool(item["post_existed"]), item["post_sha"],
                                 item["post_size"], item["post_mode"]))
                    if current[:4] != expected or (force and current[0]
                                                   and b"\x00" in current[4][:4096]):
                        raise CheckpointRefusal("changed_since_plan" if force
                                                else "changed_since_checkpoint")
                    candidates.append((item, before, snap.mode if snap else 0, current))
                except (OSError, CheckpointRefusal, ValueError) as exc:
                    if force:
                        return {"ok": False, "reason": getattr(exc, "reason", "path_changed")}
                    skipped += 1

            prepared: list[tuple[dict, bytes, int, str]] = []
            for item, before, pre_mode, current in candidates:
                target = root / item["path"]
                try:
                    undo = self.snapshots.take_captured(
                        target, existed=current[0], data=current[4], mode=current[3]
                    )
                    if self._blob_bytes(undo.blob_sha, undo.size) is None:
                        raise CheckpointRefusal("snapshot_changed")
                    db.execute("""UPDATE group_files SET undo_ref=?, restore_status='prepared'
                        WHERE group_id=? AND path=?""", (undo.ref, group_id, item["path"]))
                    prepared.append((item, before, pre_mode, undo.ref))
                except (OSError, CheckpointRefusal, sqlite3.Error) as exc:
                    if force:
                        db.rollback()
                        return {"ok": False, "reason": getattr(exc, "reason", "snapshot_changed")}
                    skipped += 1
            undo_group_id = secrets.token_hex(16) if prepared else None
            if prepared:
                db.execute("""UPDATE groups SET status='restore_incomplete',
                    undo_group_id=? WHERE id=?""", (undo_group_id, group_id))
                db.commit()
            restored = 0
            undo_refs: list[str] = []

            def close_partial(reason: str) -> dict:
                db.execute("""UPDATE group_files SET restore_status='skipped'
                    WHERE group_id=? AND restore_status='prepared'""", (group_id,))
                coverage = self._group_coverage(db, group_id, row["excluded"])
                db.execute("UPDATE groups SET status='partial' WHERE id=?", (group_id,))
                db.commit()
                return {"ok": False, "reason": reason, "status": "partial",
                        "restored": restored, "skipped": skipped,
                        "excluded": row["excluded"], **coverage,
                        "undo_group_id": undo_group_id,
                        "undo_snapshot_refs": undo_refs}

            for item, before, pre_mode, undo_ref in prepared:
                target = root / item["path"]
                physical_started = False
                try:
                    if self._group_root(root)[1] != identity:
                        raise CheckpointRefusal("root_changed")
                    if any(item["path"] == prefix or item["path"].startswith(prefix + "/")
                           for prefix in self._protected_scope_paths(root)):
                        raise CheckpointRefusal("private_scope")
                    if self.scope.resolve(str(target)) != target:
                        raise CheckpointRefusal("scope_changed")
                    with _parent_fd(root, target, identity, create=False) as (parent, name):
                        current = _state(parent, name, max_bytes=(
                            MAX_CAPTURE_BYTES if force else item["post_size"]
                        ), expected_dev=identity[0], single_link=True)
                        expected = (bound_current[item["path"]] if force else
                                    (bool(item["post_existed"]), item["post_sha"],
                                     item["post_size"], item["post_mode"]))
                        if current[:4] != expected or (force and current[0]
                                                       and b"\x00" in current[4][:4096]):
                            raise CheckpointRefusal("changed_since_plan" if force
                                                    else "changed_since_checkpoint")
                        will_effect = bool(item["pre_existed"] or current[0])
                        if will_effect and effect_check is not None:
                            try:
                                permitted = effect_check()
                            except Exception:
                                permitted = False
                            if permitted is not True:
                                raise CheckpointRefusal("effect_check_failed")
                        if item["pre_existed"]:
                            physical_started = True
                            _replace(parent, name, before, pre_mode or 0o644)
                        elif current[0]:
                            physical_started = True
                            os.unlink(name, dir_fd=parent)
                            os.fsync(parent)
                    db.execute("""UPDATE group_files SET restore_status='restored'
                        WHERE group_id=? AND path=?""", (group_id, item["path"]))
                    db.commit()
                    restored += 1
                    undo_refs.append(undo_ref)
                except (OSError, CheckpointRefusal, ValueError, sqlite3.Error) as exc:
                    if not physical_started:
                        skipped += 1
                        return close_partial(getattr(exc, "reason", "path_changed"))
                    return {"ok": False, "reason": "effect_state_incomplete",
                            "restored": restored, "skipped": skipped + 1,
                            "undo_group_id": undo_group_id,
                            "undo_snapshot_refs": undo_refs}
            coverage = self._group_coverage(db, group_id, row["excluded"])
            status = "restored" if coverage["complete"] else "partial"
            db.execute("UPDATE groups SET status=? WHERE id=?", (status, group_id))
            db.commit()
            return {"ok": True, "status": status, "restored": restored,
                    "skipped": skipped, "excluded": row["excluded"], **coverage,
                    "undo_group_id": undo_group_id,
                    "undo_snapshot_refs": undo_refs}

    def prune_groups(self, group_ids: list[str], *, dry_run: bool = True) -> dict:
        """Internal irreversible maintenance primitive; no owner route here."""
        ids = sorted({item for item in group_ids if isinstance(item, str)
                      and len(item) == 32 and all(c in "0123456789abcdef" for c in item)})[:500]
        if not self._db.exists():
            return {"removed_groups": 0, "reclaimed_bytes": 0}
        with _locked(self.snapshots.directory), self._connection() as db:
            found = [item for item in ids if self._group_row(db, item)]
            if not dry_run:
                db.executemany("DELETE FROM group_files WHERE group_id=?", [(i,) for i in found])
                db.executemany("DELETE FROM group_exclusions WHERE group_id=?",
                               [(i,) for i in found])
                db.executemany("DELETE FROM group_runs WHERE group_id=?", [(i,) for i in found])
                db.executemany("DELETE FROM groups WHERE id=?", [(i,) for i in found])
                db.commit()
        gc = self.prune([], dry_run=dry_run, _exclude_groups=set(found) if dry_run else None)
        return {"removed_groups": len(found),
                "reclaimed_bytes": gc["reclaimed_bytes"],
                "would_reclaim_bytes": gc.get("would_reclaim_bytes", 0)}

    def capture_preimage(self, target: Path, root: Path, *, op: str) -> CapturedPreimage:
        """Capture a bounded preimage through a no-follow scoped descriptor."""
        with _locked(self.snapshots.directory):
            root_info = os.stat(root, follow_symlinks=False)
            identity = root_info.st_dev, root_info.st_ino
            if not stat.S_ISDIR(root_info.st_mode) or self.scope.resolve(str(target)) != target:
                raise CheckpointRefusal("path_changed")
            try:
                with _parent_fd(root, target, identity, create=False) as (parent, name):
                    try:
                        existed, _, _, mode, data = _state(parent, name,
                                                            max_bytes=MAX_CAPTURE_BYTES)
                    except CheckpointRefusal as exc:
                        if exc.reason == "changed_since_checkpoint":
                            raise CheckpointRefusal("checkpoint_too_large") from exc
                        raise
            except CheckpointRefusal as exc:
                if exc.reason != "path_changed" or target.exists():
                    raise
                # An absent nested parent is okay for a *future* write; the
                # physical apply creates it through no-follow dirfds later.
                existed, mode, data = False, 0, b""
            if op == "delete" and not existed:
                raise CheckpointRefusal("not_found")
            snap = self.snapshots.take_captured(target, existed=existed, data=data, mode=mode)
            return CapturedPreimage(snap, *identity)

    def apply_mutation(self, target: Path, root: Path, snap: Snapshot,
                       op: str, data: bytes, *, expected_root: tuple[int, int],
                       tool_turn: str | None = None) -> int:
        """Prepare durably, compare exact preimage, then perform one physical effect."""
        with _locked(self.snapshots.directory), self._connection() as db:
            root_info = os.stat(root, follow_symlinks=False)
            if not stat.S_ISDIR(root_info.st_mode):
                raise CheckpointRefusal("root_changed")
            identity = (root_info.st_dev, root_info.st_ino)
            if identity != expected_root:
                raise CheckpointRefusal("root_changed")
            if self.scope.resolve(str(target)) != target:
                raise CheckpointRefusal("path_changed")
            expected = self._blob_bytes(snap.blob_sha, snap.size)
            if expected is None or snap.path != str(target) or len(expected) != snap.size:
                raise CheckpointRefusal("snapshot_changed")
            post_sha = self._put_blob(data if op == "write" else b"")
            cursor = db.execute("""INSERT INTO entries
                (path, root, root_dev, root_ino, op, pre_ref, status,
                 source_kind, tool_turn, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'prepared', 'file_tools', ?, ?)""",
                (str(target), str(root), *identity, op, snap.ref,
                 tool_turn if isinstance(tool_turn, str) and len(tool_turn) <= 128 else None,
                 time.time()))
            entry_id = int(cursor.lastrowid)
            db.commit()
            effect_started = False
            try:
                with _parent_fd(root, target, identity, create=op == "write") as (parent, name):
                    try:
                        exists, sha, size, mode, _ = _state(parent, name,
                                                           max_bytes=snap.size)
                    except CheckpointRefusal as exc:
                        if exc.reason == "changed_since_checkpoint":
                            raise CheckpointRefusal("changed_since_snapshot") from exc
                        raise
                    if (exists, sha, size, mode) != (
                        snap.existed, snap.blob_sha, snap.size, snap.mode
                    ):
                        raise CheckpointRefusal("changed_since_snapshot")
                    effect_started = True
                    if op == "delete":
                        os.unlink(name, dir_fd=parent)
                        os.fsync(parent)
                    else:
                        _replace(parent, name, data, snap.mode if snap.existed else 0o644)
                    db.execute("""UPDATE entries SET status='applied', post_existed=?,
                        post_sha=?, post_size=?, post_mode=? WHERE id=?""",
                        (int(op == "write"), post_sha,
                         len(data) if op == "write" else 0,
                         (snap.mode if snap.existed else 0o644) if op == "write" else 0,
                         entry_id))
                    db.commit()
            except BaseException as exc:
                # A crash or uncertain effect leaves the durable prepared row visible.
                if effect_started:
                    raise CheckpointRefusal("effect_state_incomplete") from exc
                raise
            return entry_id

    def _row(self, db: sqlite3.Connection, entry_id: int) -> dict | None:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return dict(row) if row else None

    def _valid_scope(self, row: dict) -> bool:
        try:
            target = self.scope.resolve(row["path"])
            root = self.scope.root_for(target)
            info = os.stat(row["root"], follow_symlinks=False)
            return (str(target) == row["path"] and str(root) == row["root"]
                    and stat.S_ISDIR(info.st_mode)
                    and (info.st_dev, info.st_ino) == (row["root_dev"], row["root_ino"]))
        except (OSError, ValueError):
            return False

    def list_entries(self, *, path: str | None = None, limit: int = 100) -> list[dict]:
        limit = min(max(limit, 0), 500)
        if not self._db.exists():
            return []
        if path is not None:
            try:
                path = str(self.scope.resolve(path))
            except ValueError:
                return []
        with _locked(self.snapshots.directory), self._connection() as db:
            db.row_factory = sqlite3.Row
            if path is None:
                rows = db.execute("SELECT * FROM entries ORDER BY id DESC LIMIT ?", (limit,))
            else:
                rows = db.execute("SELECT * FROM entries WHERE path=? ORDER BY id DESC LIMIT ?",
                                  (path, limit))
            return [dict(row) for row in rows if self._valid_scope(dict(row))]

    def status(self) -> dict:
        """Storage status only; no authority or parity claim is implied."""
        if not self._db.exists():
            return {"entries": 0, "incomplete": 0}
        with _locked(self.snapshots.directory), self._connection() as db:
            rows = db.execute("SELECT status, COUNT(*) FROM entries GROUP BY status").fetchall()
            counts = dict(rows)
            return {"entries": sum(counts.values()),
                    "incomplete": counts.get("prepared", 0)
                    + counts.get("restore_incomplete", 0)}

    def plan_restore(self, entry_id: int, *, force: bool = False) -> dict:
        """Read-only currentness preview for a future mediated restore caller."""
        if type(force) is not bool:
            return {"ok": False, "reason": "invalid_force"}
        if not self._db.exists():
            return {"ok": False, "reason": "unknown_checkpoint"}
        with _locked(self.snapshots.directory), self._connection() as db:
            row = self._row(db, entry_id)
            if row is None or row["status"] != "applied":
                return {"ok": False, "reason": "unknown_checkpoint"}
            if not self._valid_scope(row):
                return {"ok": False, "reason": "scope_changed"}
            snap = self.snapshots.load(row["pre_ref"])
            if (snap is None or snap.path != row["path"]
                    or self._blob_bytes(snap.blob_sha, snap.size) is None):
                return {"ok": False, "reason": "snapshot_changed"}
            try:
                with _parent_fd(Path(row["root"]), Path(row["path"]),
                                (row["root_dev"], row["root_ino"]), create=False) as (parent, name):
                    exists, sha, size, mode, data = _state(
                        parent, name, max_bytes=(MAX_CAPTURE_BYTES if force else row["post_size"]),
                        expected_dev=row["root_dev"], single_link=True,
                    )
            except CheckpointRefusal as exc:
                return {"ok": False, "reason": exc.reason}
            except OSError:
                return {"ok": False, "reason": "path_changed"}
            if not force and (exists, sha, size, mode) != (
                bool(row["post_existed"]), row["post_sha"],
                row["post_size"], row["post_mode"]
            ):
                return {"ok": False, "reason": "changed_since_checkpoint"}
            if force and exists and b"\x00" in data[:4096]:
                return {"ok": False, "reason": "binary_current_excluded"}
            return {"ok": True, "path": row["path"], "op": row["op"],
                    "pre_ref": row["pre_ref"], "post_sha": row["post_sha"],
                    **({"current": [exists, sha, size, mode]} if force else {}),
                    "requires_authority": True}

    def diff(self, entry_id: int, *, max_bytes: int = 65536) -> dict:
        max_bytes = min(max(max_bytes, 1), 65536)
        if not self._db.exists():
            return {"ok": False, "reason": "unknown_checkpoint"}
        with _locked(self.snapshots.directory), self._connection() as db:
            row = self._row(db, entry_id)
            if row is None or not self._valid_scope(row) or row["status"] != "applied":
                return {"ok": False, "reason": "unknown_checkpoint"}
            snap = self.snapshots.load(row["pre_ref"])
            if snap is None or snap.path != row["path"]:
                return {"ok": False, "reason": "snapshot_changed"}
            before = self._blob_bytes(snap.blob_sha, snap.size)
            after = self._blob_bytes(row["post_sha"], row["post_size"])
            if before is None or after is None or _sha(after) != row["post_sha"]:
                return {"ok": False, "reason": "snapshot_changed"}
            if len(before) > max_bytes or len(after) > max_bytes:
                return {"ok": True, "binary": True, "reason": "diff_too_large",
                        "before_sha": snap.blob_sha, "post_sha": row["post_sha"]}
            try:
                before_text = before.decode("utf-8")
                after_text = after.decode("utf-8")
                if "\x00" in before_text or "\x00" in after_text:
                    raise UnicodeError
            except UnicodeError:
                return {"ok": True, "binary": True,
                        "before_sha": snap.blob_sha, "post_sha": row["post_sha"]}
            lines = difflib.unified_diff(before_text.splitlines(keepends=True),
                after_text.splitlines(keepends=True), fromfile="before", tofile="after")
            from .security.log_redaction import SecretRedactionFilter
            from .security.scanner import PIIScanner

            try:
                redacted = PIIScanner().redact(
                    SecretRedactionFilter().redact_text("".join(lines))
                )
            except Exception:
                return {"ok": False, "reason": "redaction_failed"}
            encoded = redacted.encode("utf-8")
            return {"ok": True, "binary": False,
                    "diff": encoded[:max_bytes].decode("utf-8", errors="ignore"),
                    "truncated": len(encoded) > max_bytes}

    def restore(self, entry_id: int, *, force: bool = False,
                expected_current: tuple | list | None = None,
                effect_check: Callable[[], bool] | None = None) -> dict:
        """Trusted primitive only; authority must be enforced by a future caller."""
        if type(force) is not bool:
            return {"ok": False, "reason": "invalid_force"}
        if effect_check is not None and not callable(effect_check):
            return {"ok": False, "reason": "invalid_effect_check"}
        if force and expected_current is None:
            return {"ok": False, "reason": "expected_current_required"}
        if force and not _valid_expected(expected_current):
            return {"ok": False, "reason": "expected_current_mismatch"}
        if not force and expected_current is not None:
            return {"ok": False, "reason": "unexpected_current"}
        bound_current = tuple(expected_current) if force else None
        if not self._db.exists():
            return {"ok": False, "reason": "unknown_checkpoint"}
        with _locked(self.snapshots.directory), self._connection() as db:
            row = self._row(db, entry_id)
            if row is None or row["status"] != "applied":
                return {"ok": False, "reason": "unknown_checkpoint"}
            if not self._valid_scope(row):
                return {"ok": False, "reason": "scope_changed"}
            snap = self.snapshots.load(row["pre_ref"])
            if snap is None or snap.path != row["path"]:
                return {"ok": False, "reason": "snapshot_changed"}
            before = self._blob_bytes(snap.blob_sha, snap.size)
            if before is None or len(before) != snap.size:
                return {"ok": False, "reason": "snapshot_changed"}
            root, target = Path(row["root"]), Path(row["path"])
            identity = row["root_dev"], row["root_ino"]
            armed = False
            try:
                with _parent_fd(root, target, identity, create=False) as (parent, name):
                    exists, sha, size, mode, current_data = _state(
                        parent, name, max_bytes=(MAX_CAPTURE_BYTES if force else row["post_size"]),
                        expected_dev=identity[0], single_link=True,
                    )
                    expected = (bound_current if force else
                                (bool(row["post_existed"]), row["post_sha"],
                                 row["post_size"], row["post_mode"]))
                    if (exists, sha, size, mode) != expected:
                        return {"ok": False, "reason": "changed_since_plan" if force
                                else "changed_since_checkpoint"}
                    if force and exists and b"\x00" in current_data[:4096]:
                        return {"ok": False, "reason": "binary_current_excluded"}
                    undo = self.snapshots.take_captured(
                        target, existed=exists, data=current_data, mode=mode
                    )
                    if self._blob_bytes(undo.blob_sha, undo.size) is None:
                        return {"ok": False, "reason": "snapshot_changed"}
                    # Mark uncertainty *before* actuation, then close it after fsync.
                    db.execute("UPDATE entries SET status='restore_incomplete', undo_ref=? WHERE id=?",
                               (undo.ref, entry_id))
                    db.commit()
                    armed = True
                    if (snap.existed or exists) and effect_check is not None:
                        try:
                            permitted = effect_check()
                        except Exception:
                            permitted = False
                        if permitted is not True:
                            db.execute("UPDATE entries SET status='applied' WHERE id=?",
                                       (entry_id,))
                            db.commit()
                            return {"ok": False, "reason": "effect_check_failed"}
                    if snap.existed:
                        _replace(parent, name, before, snap.mode or 0o644)
                    elif exists:
                        os.unlink(name, dir_fd=parent)
                        os.fsync(parent)
                    db.execute("UPDATE entries SET status='restored' WHERE id=?", (entry_id,))
                    db.commit()
                    return {"ok": True, "undo_snapshot_ref": undo.ref}
            except CheckpointRefusal as exc:
                return {"ok": False, "reason": "effect_state_incomplete" if armed else exc.reason}
            except sqlite3.Error:
                return {"ok": False, "reason": "effect_state_incomplete" if armed
                        else "history_store_invalid"}
            except OSError:
                return {"ok": False, "reason": "effect_state_incomplete" if armed else "path_changed"}

    def prune(self, entry_ids: list[int], *, dry_run: bool = True,
              _exclude_groups: set[str] | None = None) -> dict:
        """Internal maintenance primitive; never exposed without irreversible approval."""
        if not self._db.exists():
            return {"removed_entries": 0, "reclaimed_bytes": 0}
        ids = sorted({value for value in entry_ids if type(value) is int and value > 0})[:500]
        with _locked(self.snapshots.directory), self._connection() as db:
            found = [value for value in ids if (row := self._row(db, value)) and self._valid_scope(row)]
            if not dry_run:
                db.executemany("DELETE FROM entries WHERE id=?", [(value,) for value in found])
                db.commit()
            # Every generic take now uses the same lock. An invalid/unreadable
            # record makes ownership ambiguous, so retain every blob in that case.
            protected: set[str] = set()
            for record in self.snapshots.directory.glob("*.json"):
                if record.is_symlink():
                    return {"removed_entries": len(found), "reclaimed_bytes": 0,
                            "blob_gc": "retained_ambiguous_record"}
                snap = self.snapshots.load(record.stem)
                if snap is None:
                    return {"removed_entries": len(found), "reclaimed_bytes": 0,
                            "blob_gc": "retained_ambiguous_record"}
                protected.add(snap.blob_sha)
            for row_id, sha in db.execute(
                "SELECT id, post_sha FROM entries WHERE post_sha IS NOT NULL"
            ):
                if not dry_run or row_id not in found:
                    protected.add(sha)
            for group_id, sha in db.execute(
                "SELECT group_id, post_sha FROM group_files WHERE post_sha IS NOT NULL"
            ):
                if not _exclude_groups or group_id not in _exclude_groups:
                    protected.add(sha)
            reclaimable = []
            for blob in (self.snapshots.directory / "blobs").glob("*"):
                if (len(blob.name) == 64
                    and all(c in "0123456789abcdef" for c in blob.name)
                    and blob.name not in protected and blob.is_file()
                    and not blob.is_symlink()):
                    reclaimable.append(blob)
            reclaimed = sum(blob.stat().st_size for blob in reclaimable)
            if not dry_run:
                for blob in reclaimable:
                    blob.unlink()
            return {"removed_entries": len(found),
                    "reclaimed_bytes": reclaimed if not dry_run else 0,
                    "would_reclaim_bytes": reclaimed if dry_run else 0}
