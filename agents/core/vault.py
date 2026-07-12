"""Encrypted personal blob vault with fail-closed persistence semantics.

The vault stores ciphertext blobs plus an authenticated, encrypted metadata catalog.
Every mutation reloads that catalog while holding both an in-process and OS-backed
cross-process lock, so live instances cannot overwrite each other's quota decisions.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from secrets import token_urlsafe as _token_urlsafe

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError

DEFAULT_DIR = data_path("vault")

_MAX_ITEMS = 10_000
_MAX_TOTAL_BYTES = 1 << 40
_MAX_ITEM_BYTES = 1 << 30
_MAX_INDEX_BYTES = 16 << 20
_INDEX_SCHEMA = 1
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ENTRY_KEYS = {"id", "name", "kind", "bytes", "sha256", "created_at", "expires_at"}
_LOCK_TIMEOUT_SECONDS = 30.0

_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class VaultError(Exception):
    """The vault refused an unsafe, corrupt, or quota-breaching operation."""


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VaultError(f"{name} must be a positive integer")
    return value


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VaultError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise VaultError(f"{name} must be a finite number")
    return result


def _validate_id(value: object) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise VaultError("unsafe vault id")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _chmod_private(path: Path, *, directory: bool = False) -> None:
    mode = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if directory else 0)
    with suppress(OSError, NotImplementedError):  # pragma: no cover - odd filesystems
        path.chmod(mode)


def _atomic_replace_bytes(target: Path, temporary: Path, data: bytes, *, label: str) -> None:
    """Create a private temp file without following symlinks, then atomically replace."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, flags, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_private(temporary)
        os.replace(temporary, target)
        _chmod_private(target)
    except OSError as exc:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise VaultError(f"vault {label} commit failed: {exc}") from exc


def _thread_lock_for(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _file_lock(path: Path, timeout: float = _LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Portable advisory exclusive lock over the first byte of *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
        opened = os.fstat(descriptor)
        linked = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(linked.st_mode) or (opened.st_dev, opened.st_ino) != (
            linked.st_dev,
            linked.st_ino,
        ):
            raise VaultError("unsafe vault lock path")
        handle = os.fdopen(descriptor, "r+b")
        descriptor = None
    except (OSError, VaultError) as exc:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if isinstance(exc, VaultError):
            raise
        raise VaultError(f"unsafe vault lock path: {exc}") from exc
    _chmod_private(path)
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - exercised by Linux CI
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise VaultError("timed out waiting for vault lock") from exc
                time.sleep(0.01)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - exercised by Linux CI
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class Vault:
    """Encrypted blob vault with bounded, transactional catalog operations."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        key: str | None = None,
        max_items: int = _MAX_ITEMS,
        max_total_bytes: int = _MAX_TOTAL_BYTES,
        max_item_bytes: int = _MAX_ITEM_BYTES,
    ) -> None:
        self.root = (Path(root) if root else DEFAULT_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        _chmod_private(self.root, directory=True)
        self.max_items = _positive_integer("max_items", max_items)
        self.max_total_bytes = _positive_integer("max_total_bytes", max_total_bytes)
        self.max_item_bytes = _positive_integer("max_item_bytes", max_item_bytes)
        self._index_path = self.root / "index.enc"
        self._lock_path = self.root / "vault.lock"
        self._thread_lock = _thread_lock_for(self._lock_path)
        self._root_binding = hashlib.sha256(
            os.path.normcase(str(self.root)).encode("utf-8")
        ).hexdigest()
        self._memory_cleared = False
        with self._exclusive():
            # SecretStore key/salt creation is protected by the same cross-process lock.
            self._cipher = SecretStore(self.root / "vault.keys", key=key)
            self._index = self._load_index(reconcile=True)

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        with self._thread_lock, _file_lock(self._lock_path):
            yield

    def _blob_path(self, vid: str) -> Path:
        safe_id = _validate_id(vid)
        candidate = self.root / f"{safe_id}.blob"
        if candidate.parent != self.root:
            raise VaultError("unsafe vault id path")
        return candidate

    def _payload(self, index: dict[str, dict]) -> dict:
        return {"schema": _INDEX_SCHEMA, "root": self._root_binding, "entries": index}

    def _validate_entry(self, key: object, entry: object) -> dict:
        vid = _validate_id(key)
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise VaultError("vault index entry schema is invalid")
        if entry.get("id") != vid:
            raise VaultError("vault index id mismatch")
        name = entry.get("name")
        kind = entry.get("kind")
        size = entry.get("bytes")
        digest = entry.get("sha256")
        if not isinstance(name, str) or len(name) > 200:
            raise VaultError("vault index name is invalid")
        if not isinstance(kind, str) or len(kind) > 40:
            raise VaultError("vault index kind is invalid")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= _MAX_ITEM_BYTES:
            raise VaultError("vault index byte count is invalid")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise VaultError("vault index digest is invalid")
        created_at = _finite_number("vault index created_at", entry.get("created_at"))
        expires_raw = entry.get("expires_at")
        expires_at = (
            None if expires_raw is None else _finite_number("vault index expires_at", expires_raw)
        )
        return {
            "id": vid,
            "name": name,
            "kind": kind,
            "bytes": size,
            "sha256": digest,
            "created_at": created_at,
            "expires_at": expires_at,
        }

    def _validate_payload(self, payload: object) -> dict[str, dict]:
        if not isinstance(payload, dict) or set(payload) != {"schema", "root", "entries"}:
            raise VaultError("vault index schema is invalid")
        if payload.get("schema") != _INDEX_SCHEMA:
            raise VaultError("vault index schema version is unsupported")
        if payload.get("root") != self._root_binding:
            raise VaultError("vault index belongs to a different vault root")
        entries = payload.get("entries")
        if not isinstance(entries, dict) or len(entries) > _MAX_ITEMS:
            raise VaultError("vault index entries are invalid")
        validated = {key: self._validate_entry(key, value) for key, value in entries.items()}
        if sum(entry["bytes"] for entry in validated.values()) > _MAX_TOTAL_BYTES:
            raise VaultError("vault index byte total is invalid")
        return validated

    def _load_index(self, *, reconcile: bool) -> dict[str, dict]:
        if self._index_path.is_symlink():
            raise VaultError("unsafe vault index path")
        if not self._index_path.exists():
            # A pre-hardening vault root carries a plaintext `index.json`. Starting
            # with an empty catalog here would let _reconcile delete its blobs as
            # crash residue — fail loudly instead of silently discarding data.
            legacy = self.root / "index.json"
            if legacy.is_symlink() or legacy.exists():
                raise VaultError(
                    "legacy plaintext vault index detected (pre-hardening format); "
                    "refusing to open — move the old vault root aside and re-put its content"
                )
            index: dict[str, dict] = {}
        else:
            try:
                token = self._index_path.read_bytes()
                if len(token) > _MAX_INDEX_BYTES:
                    raise VaultError("vault index exceeds its size limit")
                plain = self._cipher.decrypt_bytes(token)
                payload = json.loads(plain.decode("utf-8"), parse_constant=_reject_json_constant)
                index = self._validate_payload(payload)
            except VaultError:
                raise
            except (OSError, UnicodeError, ValueError, SecretStoreError) as exc:
                raise VaultError(f"vault index is corrupt or unauthenticated: {exc}") from exc

        for vid in index:
            path = self._blob_path(vid)
            if path.is_symlink() or not path.is_file():
                raise VaultError(f"vault index references a missing or unsafe blob: {vid}")
        if reconcile:
            self._reconcile(index)
        return index

    def _reconcile(self, index: dict[str, dict]) -> None:
        referenced = {f"{vid}.blob" for vid in index}
        for path in self.root.glob("*.blob"):
            if path.name not in referenced and (path.is_file() or path.is_symlink()):
                path.unlink(missing_ok=True)
        for pattern in ("*.blob.tmp", "index.enc.tmp"):
            for path in self.root.glob(pattern):
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)

    def _save_index(self, index: dict[str, dict]) -> None:
        try:
            plain = json.dumps(
                self._payload(index),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            token = self._cipher.encrypt_bytes(plain)
            tmp = self._index_path.with_suffix(".enc.tmp")
            _atomic_replace_bytes(self._index_path, tmp, token, label="index")
        except (OSError, ValueError, SecretStoreError) as exc:
            raise VaultError(f"vault index commit failed: {exc}") from exc

    def _write_blob(self, path: Path, token: bytes) -> None:
        tmp = path.with_suffix(".blob.tmp")
        _atomic_replace_bytes(path, tmp, token, label="blob")

    def put(
        self,
        data: bytes,
        *,
        name: str = "",
        kind: str = "blob",
        now: float = 0.0,
        expires_at: float | None = None,
    ) -> dict:
        if not isinstance(data, (bytes, bytearray)):
            raise VaultError("vault stores bytes")
        created = _finite_number("now", now)
        expiry = None if expires_at is None else _finite_number("expires_at", expires_at)
        raw = bytes(data)
        size = len(raw)
        if size > self.max_item_bytes:
            raise VaultError(f"item exceeds per-item cap ({size} > {self.max_item_bytes})")
        try:
            token = self._cipher.encrypt_bytes(raw)
        except SecretStoreError as exc:
            raise VaultError(f"cannot encrypt vault item: {exc}") from exc

        with self._exclusive():
            index = self._load_index(reconcile=True)
            if len(index) >= self.max_items:
                raise VaultError(f"vault item cap reached ({self.max_items})")
            if sum(entry["bytes"] for entry in index.values()) + size > self.max_total_bytes:
                raise VaultError("vault byte quota reached")
            vid = ""
            for _ in range(32):
                candidate = _token_urlsafe(12)
                _validate_id(candidate)
                if candidate not in index and not self._blob_path(candidate).exists():
                    vid = candidate
                    break
            if not vid:
                raise VaultError("could not allocate a unique safe vault id")
            path = self._blob_path(vid)
            entry = {
                "id": vid,
                "name": str(name or "")[:200],
                "kind": str(kind or "blob")[:40],
                "bytes": size,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "created_at": created,
                "expires_at": expiry,
            }
            self._write_blob(path, token)
            updated = dict(index)
            updated[vid] = entry
            try:
                self._save_index(updated)
            except (VaultError, OSError) as exc:
                path.unlink(missing_ok=True)
                raise VaultError(f"vault index commit failed: {exc}") from exc
            self._index = updated
            self._memory_cleared = False
            return dict(entry)

    def get(self, vid: str) -> bytes:
        safe_id = _validate_id(vid)
        if self._memory_cleared:
            raise VaultError(f"no such vault item: {safe_id}")
        with self._exclusive():
            index = self._load_index(reconcile=True)
            entry = index.get(safe_id)
            if entry is None:
                raise VaultError(f"no such vault item: {safe_id}")
            path = self._blob_path(safe_id)
            try:
                token = path.read_bytes()
            except OSError as exc:
                raise VaultError(f"vault blob missing on disk: {safe_id}") from exc
            self._index = index
        try:
            data = self._cipher.decrypt_bytes(token)
        except SecretStoreError as exc:
            raise VaultError(f"cannot decrypt vault item {safe_id}: {exc}") from exc
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise VaultError(f"vault item {safe_id} failed integrity check")
        return data

    def list(self) -> list[dict]:
        if self._memory_cleared:
            return []
        with self._exclusive():
            self._index = self._load_index(reconcile=True)
            return sorted(
                (dict(entry) for entry in self._index.values()),
                key=lambda entry: -entry["created_at"],
            )

    def remove(self, vid: str) -> bool:
        safe_id = _validate_id(vid)
        with self._exclusive():
            index = self._load_index(reconcile=True)
            if safe_id not in index:
                self._index = index
                self._memory_cleared = False
                return False
            updated = dict(index)
            updated.pop(safe_id)
            self._save_index(updated)
            self._blob_path(safe_id).unlink(missing_ok=True)
            self._index = updated
            self._memory_cleared = False
            return True

    def stats(self) -> dict:
        if self._memory_cleared:
            used = 0
            items = 0
        else:
            with self._exclusive():
                self._index = self._load_index(reconcile=True)
                used = sum(entry["bytes"] for entry in self._index.values())
                items = len(self._index)
        return {
            "items": items,
            "bytes": used,
            "max_items": self.max_items,
            "max_bytes": self.max_total_bytes,
        }

    def sweep(self, now: float) -> dict:
        cutoff = _finite_number("now", now)
        with self._exclusive():
            index = self._load_index(reconcile=True)
            expired = [
                vid
                for vid, entry in index.items()
                if entry["expires_at"] is not None and entry["expires_at"] <= cutoff
            ]
            if expired:
                updated = {vid: entry for vid, entry in index.items() if vid not in expired}
                self._save_index(updated)
                for vid in expired:
                    self._blob_path(vid).unlink(missing_ok=True)
                self._index = updated
            else:
                self._index = index
            self._memory_cleared = False
        return {"removed": expired, "count": len(expired)}

    def clear_memory(self) -> None:
        """Drop only this object's live catalog; persistent mutations always reload disk."""
        with self._thread_lock:
            self._index = {}
            self._memory_cleared = True

    def purge(self) -> int:
        """Erase every contained blob independent of the in-memory or disk catalog."""
        with self._exclusive():
            blobs = [
                path for path in self.root.glob("*.blob") if path.is_file() or path.is_symlink()
            ]
            self._save_index({})
            removed = 0
            for path in blobs:
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                except OSError as exc:
                    raise VaultError(f"vault purge could not remove {path.name}: {exc}") from exc
            self._index = {}
            self._memory_cleared = False
            return removed
