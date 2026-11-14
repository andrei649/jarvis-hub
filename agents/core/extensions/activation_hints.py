"""Data-only forward activation hints for explicitly activated extensions.

This module never imports or executes extension packages. Callers remain responsible
for re-checking current consent, package admission, and enablement before activation.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .consent import declared_digest
from .manifest import ExtensionManifest, ManifestError, parse_manifest
from .store_lock import StoreLockError, locked_store

STORE_VERSION = 1
MAX_ROWS = 128
MAX_STORE_BYTES = 2 * 1024 * 1024
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_REVISION_RE = re.compile(r"[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MANIFEST_KEYS = {
    "manifest_version", "api_version", "id", "version", "capabilities",
    "tools", "commands", "events", "requires", "command_requires_args",
}
_ROW_KEYS = {"manifest", "package_hash", "declared_digest", "grant_revision"}
_TOP_KEYS = {"version", "hints"}


class ActivationHintStoreError(ValueError):
    """Bounded safe error; details never include stored data or filesystem paths."""

    def __init__(self, reason: str = "activation_hints_unavailable") -> None:
        self.reason = reason if reason in {
            "activation_hints_unavailable", "activation_hints_corrupt",
            "activation_hints_capacity", "activation_hint_invalid",
            "activation_hints_durability_uncertain",
        } else "activation_hints_unavailable"
        super().__init__(self.reason)


@dataclass(frozen=True, slots=True)
class ActivationHint:
    manifest: ExtensionManifest
    package_hash: str
    declared_digest: str
    grant_revision: str




def _json_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _manifest_data(manifest: ExtensionManifest) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "api_version": 1,
        "id": manifest.id,
        "version": manifest.version,
        "capabilities": list(manifest.capabilities),
        "tools": list(manifest.tools),
        "commands": list(manifest.commands),
        "events": list(manifest.events),
        "requires": {
            "extensions": dict(manifest.extension_requires),
            "python": dict(manifest.python_requires),
        },
        "command_requires_args": list(manifest.command_requires_args),
    }


def _manifest(value: Any, *, require_normalized: bool) -> ExtensionManifest:
    if not isinstance(value, dict) or set(value) - _MANIFEST_KEYS:
        raise ActivationHintStoreError("activation_hint_invalid")
    try:
        parsed = parse_manifest(value)
    except (ManifestError, TypeError, ValueError, RecursionError):
        raise ActivationHintStoreError("activation_hint_invalid") from None
    if require_normalized and value != _manifest_data(parsed):
        raise ActivationHintStoreError("activation_hints_corrupt")
    return parsed


def _validate_hint(manifest_value: Any, package_hash: Any, digest: Any,
                   grant_revision: Any, *, require_normalized: bool) -> ActivationHint:
    if (not isinstance(package_hash, str) or _HASH_RE.fullmatch(package_hash) is None
            or not isinstance(grant_revision, str) or _REVISION_RE.fullmatch(grant_revision) is None):
        raise ActivationHintStoreError("activation_hint_invalid")
    if not isinstance(digest, str) or _HASH_RE.fullmatch(digest) is None:
        raise ActivationHintStoreError("activation_hints_corrupt")
    parsed = _manifest(manifest_value, require_normalized=require_normalized)
    expected = declared_digest(parsed)
    if digest != expected:
        raise ActivationHintStoreError("activation_hints_corrupt")
    return ActivationHint(parsed, package_hash, expected, grant_revision)


def _validate_store(value: Any) -> dict[str, ActivationHint]:
    if (not isinstance(value, dict) or set(value) != _TOP_KEYS
            or type(value["version"]) is not int or value["version"] != STORE_VERSION
            or not isinstance(value["hints"], list) or len(value["hints"]) > MAX_ROWS):
        raise ActivationHintStoreError("activation_hints_corrupt")
    rows: dict[str, ActivationHint] = {}
    for item in value["hints"]:
        if not isinstance(item, dict) or set(item) != _ROW_KEYS:
            raise ActivationHintStoreError("activation_hints_corrupt")
        hint = _validate_hint(item["manifest"], item["package_hash"], item["declared_digest"],
                              item["grant_revision"], require_normalized=True)
        if hint.manifest.id in rows:
            raise ActivationHintStoreError("activation_hints_corrupt")
        rows[hint.manifest.id] = hint
    if list(rows) != sorted(rows):
        raise ActivationHintStoreError("activation_hints_corrupt")
    return rows


def _serialized(rows: dict[str, ActivationHint]) -> bytes:
    value = {
        "version": STORE_VERSION,
        "hints": [
            {"manifest": _manifest_data(rows[extension_id].manifest),
             "package_hash": rows[extension_id].package_hash,
             "declared_digest": rows[extension_id].declared_digest,
             "grant_revision": rows[extension_id].grant_revision}
            for extension_id in sorted(rows)
        ],
    }
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ActivationHintStoreError("activation_hints_unavailable") from None
    if len(raw) > MAX_STORE_BYTES:
        raise ActivationHintStoreError("activation_hints_capacity")
    return raw


def _lstat_regular_or_missing(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise ActivationHintStoreError() from None
    if not stat.S_ISREG(info.st_mode):
        raise ActivationHintStoreError("activation_hints_corrupt")
    return info


def _same_file_identity(left, right) -> bool:
    """Compare opened-file and pathname identities, including Windows fallback.

    POSIX also uses O_NOFOLLOW. On Windows that flag is unavailable, so both the
    pre-open lstat and this post-open identity check are required to reject a link
    introduced across the open race.
    """
    return (left.st_ino != 0 and right.st_ino != 0
            and left.st_dev == right.st_dev and left.st_ino == right.st_ino)


def _verify_opened_path(fd: int, path: Path, before=None) -> None:
    try:
        opened = os.fstat(fd)
        current = path.lstat()
    except OSError:
        raise ActivationHintStoreError("activation_hints_corrupt") from None
    if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode)
            or (before is not None and not _same_file_identity(before, current))
            or not _same_file_identity(opened, current)):
        raise ActivationHintStoreError("activation_hints_corrupt")


def _read_bytes(path: Path) -> bytes | None:
    before = _lstat_regular_or_missing(path)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError:
        raise ActivationHintStoreError("activation_hints_corrupt") from None
    try:
        _verify_opened_path(fd, path, before)
        chunks = []
        size = 0
        while size <= MAX_STORE_BYTES:
            chunk = os.read(fd, min(65536, MAX_STORE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > MAX_STORE_BYTES:
            raise ActivationHintStoreError("activation_hints_corrupt")
        return b"".join(chunks)
    except OSError:
        raise ActivationHintStoreError("activation_hints_corrupt") from None
    finally:
        os.close(fd)




def _write_atomic(path: Path, data: bytes) -> None:
    _lstat_regular_or_missing(path)
    temporary = None
    descriptor = None
    replaced = False
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        if os.name == "nt":  # pragma: no cover - Windows permission bits are limited
            # Windows does not implement fchmod's POSIX mode semantics. The temp
            # inherits the parent directory ACL; this store does not prove that ACL
            # is owner-private, so deployments must provide a private data directory.
            os.chmod(temporary, 0o600)
        else:
            os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "wb")
        descriptor = None  # fdopen owns it, including when write/fsync raises.
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Recheck immediately before replacing so a target changed to a symlink or
        # special file while preparing the temp is refused rather than clobbered.
        _lstat_regular_or_missing(path)
        os.replace(temporary, path)
        temporary = None
        replaced = True
        # Windows does not provide a portable directory-fsync operation. There the
        # replacement is atomic and file contents are flushed, but parent-directory
        # crash durability is not confirmed. POSIX fsync failures are surfaced as an
        # uncertain outcome because the replacement has already become visible.
        if os.name == "nt":  # pragma: no cover - Windows
            return
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            raise ActivationHintStoreError("activation_hints_durability_uncertain") from None
    except ActivationHintStoreError:
        raise
    except OSError:
        reason = "activation_hints_durability_uncertain" if replaced else "activation_hints_unavailable"
        raise ActivationHintStoreError(reason) from None
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


class ActivationHintStore:
    """Strict bounded store; the caller must independently reauthorize each hint."""

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            from ..paths import data_path
            path = data_path("extensions", "activation_hints.json")
        self._path = Path(path)

    def _load_for_mutation(self) -> dict[str, ActivationHint]:
        raw = _read_bytes(self._path)
        if raw is None:
            return {}
        try:
            value = json.loads(raw, object_pairs_hook=_json_no_duplicates)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ActivationHintStoreError("activation_hints_corrupt") from None
        return _validate_store(value)

    def read_all(self) -> tuple[ActivationHint, ...]:
        try:
            raw = _read_bytes(self._path)
            if raw is None:
                return ()
            try:
                value = json.loads(raw, object_pairs_hook=_json_no_duplicates)
                rows = _validate_store(value)
            except (ValueError, UnicodeDecodeError, RecursionError):
                return ()
            return tuple(rows[key] for key in sorted(rows))
        except ActivationHintStoreError:
            return ()

    def put(self, manifest: ExtensionManifest | dict, package_hash: str, grant_revision: str) -> None:
        if isinstance(manifest, ExtensionManifest):
            manifest_value = _manifest_data(manifest)
            parsed = _manifest(manifest_value, require_normalized=True)
        else:
            parsed = _manifest(manifest, require_normalized=False)
        manifest_data = _manifest_data(parsed)
        hint = _validate_hint(manifest_data, package_hash, declared_digest(parsed), grant_revision,
                              require_normalized=True)
        try:
            with locked_store(self._path):
                rows = self._load_for_mutation()
                if len(rows) >= MAX_ROWS and hint.manifest.id not in rows:
                    raise ActivationHintStoreError("activation_hints_capacity")
                rows[hint.manifest.id] = hint
                _write_atomic(self._path, _serialized(rows))
        except StoreLockError:
            raise ActivationHintStoreError("activation_hints_unavailable") from None

    def remove(self, extension_id: str) -> bool:
        if not isinstance(extension_id, str) or _ID_RE.fullmatch(extension_id) is None:
            raise ActivationHintStoreError("activation_hint_invalid")
        try:
            with locked_store(self._path):
                rows = self._load_for_mutation()
                if extension_id not in rows:
                    return False
                del rows[extension_id]
                _write_atomic(self._path, _serialized(rows))
                return True
        except StoreLockError:
            raise ActivationHintStoreError("activation_hints_unavailable") from None


__all__ = ["ActivationHint", "ActivationHintStore", "ActivationHintStoreError"]
