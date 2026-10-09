"""Bounded, owner-private H011 payloads beside the generic SnapshotStore.

This is storage only. A ref, inventory row or successful write supplies no restore,
GC, owner, queue or kernel authority. Existing generic snapshot bytes are untouched.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import secrets
import stat
import time
from collections.abc import Iterator
from pathlib import Path

from .file_checkpoint_history import HISTORY_SUPPORTED, MAX_CAPTURE_BYTES, _locked
from .file_tools import Snapshot, SnapshotStore

MAX_METADATA_BYTES = 64 * 1024
MAX_INVENTORY_ASSETS = 10_000
MAX_INVENTORY_READ_BYTES = 512 * 1024 * 1024
_NAMESPACE = "checkpoint_payloads-v1"
_MARKER = b'{"domain":"nerva.checkpoint.payloads","version":1}\n'
_RECORD_KEYS = frozenset({"path", "existed", "blob_sha", "size", "mode", "created_at"})
_OPEN_DIR = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_OPEN_FILE = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


class PayloadRefusal(Exception):
    """The owned namespace, requested bytes or their physical identity are untrusted."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ref(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _fingerprint(info: os.stat_result) -> dict:
    return {"dev": info.st_dev, "ino": info.st_ino, "size": info.st_size,
            "mode": stat.S_IMODE(info.st_mode), "nlink": info.st_nlink,
            "uid": info.st_uid, "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns}


def _require_supported() -> None:
    if not HISTORY_SUPPORTED or not hasattr(os, "O_NOFOLLOW"):
        raise PayloadRefusal("unsupported_platform")


def _dir_info(fd: int, *, private: bool, owned: bool = True) -> os.stat_result:
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode)
            or (private and (info.st_mode & 0o077))
            or (owned and hasattr(os, "geteuid") and info.st_uid != os.geteuid())):
        raise PayloadRefusal("directory_invalid")
    return info


def _open_path(path: Path, *, create: bool) -> int | None:
    """Walk from / with dirfds so even ancestors cannot redirect via symlinks."""
    _require_supported()
    if not path.is_absolute() or str(path) != os.path.normpath(str(path)) or path == Path("/"):
        raise PayloadRefusal("invalid_store_path")
    try:
        fd = os.open("/", _OPEN_DIR)
    except OSError as exc:
        raise PayloadRefusal("directory_invalid") from exc
    try:
        for part in path.parts[1:]:
            if part in {"", ".", ".."}:
                raise PayloadRefusal("invalid_store_path")
            try:
                next_fd = os.open(part, _OPEN_DIR, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    os.close(fd)
                    return None
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
                next_fd = os.open(part, _OPEN_DIR, dir_fd=fd)
            try:
                _dir_info(next_fd, private=False, owned=False)
            except BaseException:
                os.close(next_fd)
                raise
            os.close(fd)
            fd = next_fd
        _dir_info(fd, private=False)
        return fd
    except (OSError, NotImplementedError) as exc:
        os.close(fd)
        raise PayloadRefusal("directory_invalid") from exc
    except BaseException:
        os.close(fd)
        raise


def _open_child(parent: int, name: str, *, create: bool, private: bool) -> int | None:
    try:
        fd = os.open(name, _OPEN_DIR, dir_fd=parent)
    except FileNotFoundError:
        if not create:
            return None
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        try:
            fd = os.open(name, _OPEN_DIR, dir_fd=parent)
        except OSError as exc:
            raise PayloadRefusal("directory_invalid") from exc
    except OSError as exc:
        raise PayloadRefusal("directory_invalid") from exc
    try:
        _dir_info(fd, private=private)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_file(parent: int, name: str, *, cap: int) -> tuple[bytes, os.stat_result] | None:
    try:
        fd = os.open(name, _OPEN_FILE, dir_fd=parent)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PayloadRefusal("asset_invalid") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or (before.st_mode & 0o077)
                or (hasattr(os, "geteuid") and before.st_uid != os.geteuid())):
            raise PayloadRefusal("asset_invalid")
        if before.st_size > cap or before.st_size < 0:
            raise PayloadRefusal("asset_too_large")
        chunks = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        if (len(data) != before.st_size or _fingerprint(before) != _fingerprint(after)):
            raise PayloadRefusal("asset_changed")
        return data, after
    except OSError as exc:
        raise PayloadRefusal("asset_invalid") from exc
    finally:
        os.close(fd)


def _install(parent: int, name: str, data: bytes, *, cap: int) -> os.stat_result:
    if len(data) > cap:
        raise PayloadRefusal("asset_too_large")
    previous = _read_file(parent, name, cap=cap)
    if previous is not None:
        if previous[0] != data:
            raise PayloadRefusal("asset_conflict")
        return previous[1]
    temporary = ".nerva-payload-" + secrets.token_hex(16)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent)
    except OSError as exc:
        raise PayloadRefusal("asset_write_failed") from exc
    try:
        try:
            os.fchmod(fd, 0o600)
            written = 0
            while written < len(data):
                count = os.write(fd, data[written:])
                if count <= 0:
                    raise PayloadRefusal("asset_write_failed")
                written += count
            os.fsync(fd)
        finally:
            os.close(fd)
        # A non-cooperating writer may race; verify the final exact bytes below.
        with contextlib.suppress(FileExistsError):
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent,
                    follow_symlinks=False)
        os.fsync(parent)
    except OSError as exc:
        raise PayloadRefusal("asset_write_failed") from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)
    installed = _read_file(parent, name, cap=cap)
    if installed is None or installed[0] != data:
        raise PayloadRefusal("asset_conflict")
    return installed[1]


class CheckpointPayloadStore:
    """Versioned content-addressed payloads, never generic undo refs."""

    def __init__(self, snapshots: SnapshotStore) -> None:
        if type(snapshots) is not SnapshotStore:
            raise PayloadRefusal("invalid_store")
        self.snapshots = snapshots
        self.directory = snapshots.directory / _NAMESPACE
        self._pinned: dict[str, tuple[int, int]] = {}

    def _pin(self, key: str, fd: int) -> None:
        identity = _identity(_dir_info(fd, private=key != "generic"))
        previous = self._pinned.setdefault(key, identity)
        if previous != identity:
            raise PayloadRefusal("directory_changed")

    @contextlib.contextmanager
    def _owned(self, generic: int, *, create: bool) -> Iterator[tuple[int, int, int] | None]:
        namespace = records = blobs = None
        try:
            namespace = _open_child(generic, _NAMESPACE, create=create, private=True)
            if namespace is None:
                yield None
                return
            self._pin("namespace", namespace)
            names = set(os.listdir(namespace))
            if "format.json" not in names:
                if not create or names:
                    raise PayloadRefusal("marker_missing")
                _install(namespace, "format.json", _MARKER, cap=MAX_METADATA_BYTES)
                names.add("format.json")
            marker = _read_file(namespace, "format.json", cap=MAX_METADATA_BYTES)
            if marker is None or marker[0] != _MARKER:
                raise PayloadRefusal("marker_invalid")
            if names - {"format.json", "records", "blobs"}:
                raise PayloadRefusal("namespace_unknown_content")
            records = _open_child(namespace, "records", create=create, private=True)
            blobs = _open_child(namespace, "blobs", create=create, private=True)
            if records is None or blobs is None:
                raise PayloadRefusal("namespace_incomplete")
            self._pin("records", records)
            self._pin("blobs", blobs)
            yield namespace, records, blobs
        except OSError as exc:
            raise PayloadRefusal("namespace_invalid") from exc
        finally:
            for fd in (blobs, records, namespace):
                if fd is not None:
                    os.close(fd)

    @contextlib.contextmanager
    def _read(self) -> Iterator[tuple[int, int, int, int] | None]:
        generic = _open_path(self.snapshots.directory, create=False)
        if generic is None:
            yield None
            return
        try:
            self._pin("generic", generic)
            with self._owned(generic, create=False) as child:
                yield (generic, *child) if child is not None else None
                if child is not None:
                    self._check_paths()
        finally:
            os.close(generic)

    @contextlib.contextmanager
    def _write(self) -> Iterator[tuple[int, int, int, int]]:
        generic = _open_path(self.snapshots.directory, create=True)
        if generic is None:
            raise PayloadRefusal("directory_changed")
        try:
            self._pin("generic", generic)
            original = _identity(os.fstat(generic))
        finally:
            os.close(generic)
        # _locked is the existing index/journal lock. Its own path-based open has a
        # precheck-to-acquisition race; no owned asset uses that path after locking.
        with _locked(self.snapshots.directory):
            generic = _open_path(self.snapshots.directory, create=False)
            if generic is None:
                raise PayloadRefusal("directory_changed")
            try:
                if _identity(os.fstat(generic)) != original:
                    raise PayloadRefusal("directory_changed")
                self._pin("generic", generic)
                with self._owned(generic, create=True) as child:
                    if child is None:
                        raise PayloadRefusal("directory_changed")
                    self._check_paths()
                    yield generic, *child
                    self._check_paths()
            finally:
                os.close(generic)

    def _check_paths(self) -> None:
        generic = _open_path(self.snapshots.directory, create=False)
        if generic is None:
            raise PayloadRefusal("directory_changed")
        try:
            self._pin("generic", generic)
            namespace = _open_child(generic, _NAMESPACE, create=False, private=True)
            if namespace is None:
                raise PayloadRefusal("directory_changed")
            try:
                self._pin("namespace", namespace)
                marker = _read_file(namespace, "format.json", cap=MAX_METADATA_BYTES)
                if marker is None or marker[0] != _MARKER:
                    raise PayloadRefusal("marker_invalid")
                if set(os.listdir(namespace)) != {"format.json", "records", "blobs"}:
                    raise PayloadRefusal("namespace_unknown_content")
                for name in ("records", "blobs"):
                    child = _open_child(namespace, name, create=False, private=True)
                    if child is None:
                        raise PayloadRefusal("directory_changed")
                    try:
                        self._pin(name, child)
                    finally:
                        os.close(child)
            finally:
                os.close(namespace)
        finally:
            os.close(generic)

    @staticmethod
    def _captured(target: Path, existed: bool, data: bytes, mode: int,
                  now: float | None) -> Snapshot:
        if (not isinstance(target, Path) or not target.is_absolute()
                or str(target) != os.path.normpath(str(target))
                or len(str(target)) > 4096
                or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in str(target))
                or type(existed) is not bool or type(data) is not bytes
                or len(data) > MAX_CAPTURE_BYTES
                or type(mode) is not int or not 0 <= mode <= 0o7777
                or (not existed and (data or mode))):
            raise PayloadRefusal("invalid_capture")
        timestamp = time.time() if now is None else now
        try:
            valid_time = (type(timestamp) in {int, float}
                          and math.isfinite(timestamp) and timestamp >= 0)
        except OverflowError:
            valid_time = False
        if not valid_time:
            raise PayloadRefusal("invalid_timestamp")
        return Snapshot(path=str(target), existed=existed, blob_sha=_sha(data),
                        size=len(data), mode=mode, created_at=float(timestamp))

    def take_captured(self, target: Path, *, existed: bool, data: bytes,
                      mode: int, now: float | None = None) -> Snapshot:
        snap = self._captured(target, existed, data, mode, now)
        record = snap.canonical().encode("utf-8")
        if len(record) > MAX_METADATA_BYTES:
            raise PayloadRefusal("record_too_large")
        with self._write() as (_generic, _namespace, records, blobs):
            _install(blobs, snap.blob_sha, data, cap=MAX_CAPTURE_BYTES)
            _install(records, snap.ref + ".json", record, cap=MAX_METADATA_BYTES)
        return snap

    def put_blob(self, data: bytes) -> str:
        if type(data) is not bytes or len(data) > MAX_CAPTURE_BYTES:
            raise PayloadRefusal("invalid_blob")
        sha = _sha(data)
        with self._write() as (_generic, _namespace, _records, blobs):
            _install(blobs, sha, data, cap=MAX_CAPTURE_BYTES)
        return sha

    @staticmethod
    def _record(raw: bytes, ref: str) -> Snapshot:
        try:
            obj = json.loads(raw)
            if type(obj) is not dict or set(obj) != _RECORD_KEYS:
                raise ValueError
            if (type(obj["path"]) is not str or not obj["path"]
                    or not Path(obj["path"]).is_absolute()
                    or len(obj["path"]) > 4096
                    or obj["path"] != os.path.normpath(obj["path"])
                    or any(ord(char) < 32 or 127 <= ord(char) <= 159
                           for char in obj["path"])
                    or type(obj["existed"]) is not bool
                    or not _ref(obj["blob_sha"])
                    or type(obj["size"]) is not int
                    or not 0 <= obj["size"] <= MAX_CAPTURE_BYTES
                    or type(obj["mode"]) is not int or not 0 <= obj["mode"] <= 0o7777
                    or (not obj["existed"] and (obj["size"] or obj["mode"]
                                                    or obj["blob_sha"] != _sha(b"")))
                    or type(obj["created_at"]) not in {int, float}
                    or not math.isfinite(obj["created_at"]) or obj["created_at"] < 0):
                raise ValueError
            snap = Snapshot(**obj)
            if snap.canonical().encode("utf-8") != raw or snap.ref != ref:
                raise ValueError
            return snap
        except (UnicodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise PayloadRefusal("record_invalid") from exc

    def load(self, ref: str) -> Snapshot | None:
        if not _ref(ref):
            raise PayloadRefusal("invalid_ref")
        with self._read() as handles:
            if handles is None:
                return None
            _generic, _namespace, records, _blobs = handles
            found = _read_file(records, ref + ".json", cap=MAX_METADATA_BYTES)
            return None if found is None else self._record(found[0], ref)

    def blob(self, sha: str, size: int) -> bytes | None:
        if not _ref(sha) or type(size) is not int or not 0 <= size <= MAX_CAPTURE_BYTES:
            raise PayloadRefusal("invalid_blob_ref")
        with self._read() as handles:
            if handles is None:
                return None
            _generic, _namespace, _records, blobs = handles
            found = _read_file(blobs, sha, cap=MAX_CAPTURE_BYTES)
            if found is None:
                return None
            if len(found[0]) != size or _sha(found[0]) != sha:
                raise PayloadRefusal("blob_invalid")
            return found[0]

    def inventory(self) -> dict:
        with self._read() as handles:
            if handles is None:
                return {"complete": True, "state": "absent", "physical_bytes": 0,
                        "record_bytes": 0, "blob_bytes": 0, "marker_bytes": 0,
                        "records": {}, "blobs": {}, "identity": {}}
            generic, namespace, records_dir, blobs_dir = handles
            marker = _read_file(namespace, "format.json", cap=MAX_METADATA_BYTES)
            if marker is None:
                raise PayloadRefusal("marker_missing")
            record_names = sorted(os.listdir(records_dir))
            blob_names = sorted(os.listdir(blobs_dir))
            if len(record_names) + len(blob_names) > MAX_INVENTORY_ASSETS:
                return {"complete": False, "state": "limit_exceeded",
                        "physical_bytes": None, "records": {}, "blobs": {},
                        "identity": {}}
            record_rows = {}
            blob_rows = {}
            record_bytes = blob_bytes = 0
            for name in record_names:
                ref = name[:-5] if name.endswith(".json") else None
                if not _ref(ref):
                    raise PayloadRefusal("record_name_invalid")
                info = os.stat(name, dir_fd=records_dir, follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_METADATA_BYTES):
                    raise PayloadRefusal("record_invalid")
                if record_bytes + info.st_size > MAX_INVENTORY_READ_BYTES:
                    return {"complete": False, "state": "limit_exceeded",
                            "physical_bytes": None, "records": {}, "blobs": {},
                            "identity": {}}
                found = _read_file(records_dir, name, cap=MAX_METADATA_BYTES)
                if found is None:
                    raise PayloadRefusal("inventory_changed")
                snap = self._record(found[0], ref)
                record_bytes += found[1].st_size
                record_rows[ref] = {"blob_sha": snap.blob_sha, "size": snap.size,
                                    "created_at": snap.created_at, "path": snap.path,
                                    "physical_size": found[1].st_size,
                                    "fingerprint": _fingerprint(found[1])}
            for name in blob_names:
                if not _ref(name):
                    raise PayloadRefusal("blob_name_invalid")
                info = os.stat(name, dir_fd=blobs_dir, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CAPTURE_BYTES:
                    raise PayloadRefusal("blob_invalid")
                if record_bytes + blob_bytes + info.st_size > MAX_INVENTORY_READ_BYTES:
                    return {"complete": False, "state": "limit_exceeded",
                            "physical_bytes": None, "records": {}, "blobs": {},
                            "identity": {}}
                found = _read_file(blobs_dir, name, cap=MAX_CAPTURE_BYTES)
                if found is None or _sha(found[0]) != name:
                    raise PayloadRefusal("blob_invalid")
                blob_bytes += found[1].st_size
                blob_rows[name] = {"physical_size": found[1].st_size,
                                   "fingerprint": _fingerprint(found[1])}
            if (sorted(os.listdir(records_dir)) != record_names
                    or sorted(os.listdir(blobs_dir)) != blob_names):
                raise PayloadRefusal("inventory_changed")
            for ref, row in record_rows.items():
                info = os.stat(ref + ".json", dir_fd=records_dir, follow_symlinks=False)
                if _fingerprint(info) != row["fingerprint"]:
                    raise PayloadRefusal("inventory_changed")
            for sha, row in blob_rows.items():
                info = os.stat(sha, dir_fd=blobs_dir, follow_symlinks=False)
                if _fingerprint(info) != row["fingerprint"]:
                    raise PayloadRefusal("inventory_changed")
            return {"complete": all(row["blob_sha"] in blob_rows for row in record_rows.values()),
                    "state": "ready", "physical_bytes": marker[1].st_size
                    + record_bytes + blob_bytes,
                    "record_bytes": record_bytes, "blob_bytes": blob_bytes,
                    "marker_bytes": marker[1].st_size, "records": record_rows,
                    "blobs": blob_rows,
                    "identity": {"generic": _fingerprint(os.fstat(generic)),
                                 "namespace": _fingerprint(os.fstat(namespace)),
                                 "records": _fingerprint(os.fstat(records_dir)),
                                 "blobs": _fingerprint(os.fstat(blobs_dir)),
                                 "marker": _fingerprint(marker[1])}}
