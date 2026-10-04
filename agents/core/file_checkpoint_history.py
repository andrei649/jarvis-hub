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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .file_tools import FileScope, Snapshot, SnapshotStore

if sys.platform != "win32":
    import fcntl

HISTORY_SUPPORTED = sys.platform != "win32" and hasattr(os, "O_DIRECTORY")
MAX_CAPTURE_BYTES = 16 * 1024 * 1024
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


def _state(parent: int, name: str, *, max_bytes: int) -> tuple[bool, str, int, int, bytes]:
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

    def plan_restore(self, entry_id: int) -> dict:
        """Read-only currentness preview for a future mediated restore caller."""
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
                    exists, sha, size, mode, _ = _state(parent, name,
                                                       max_bytes=row["post_size"])
            except CheckpointRefusal as exc:
                return {"ok": False, "reason": exc.reason}
            except OSError:
                return {"ok": False, "reason": "path_changed"}
            if (exists, sha, size, mode) != (
                bool(row["post_existed"]), row["post_sha"],
                row["post_size"], row["post_mode"]
            ):
                return {"ok": False, "reason": "changed_since_checkpoint"}
            return {"ok": True, "path": row["path"], "op": row["op"],
                    "pre_ref": row["pre_ref"], "post_sha": row["post_sha"],
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

    def restore(self, entry_id: int) -> dict:
        """Trusted primitive only; authority must be enforced by a future caller."""
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
                        parent, name, max_bytes=row["post_size"]
                    )
                    if (exists, sha, size, mode) != (
                        bool(row["post_existed"]), row["post_sha"],
                        row["post_size"], row["post_mode"]
                    ):
                        return {"ok": False, "reason": "changed_since_checkpoint"}
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

    def prune(self, entry_ids: list[int], *, dry_run: bool = True) -> dict:
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
