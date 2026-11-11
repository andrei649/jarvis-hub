"""file_browser.py — the owner's HUD file browser over approved folders (G21 · H142).

The HUD's Files panel browses, previews, downloads and uploads files in a short list of
folders the owner approved, and asks the decision inbox before anything is renamed or
deleted. It is a door onto the owner's disk, so every rule refuses by default:

* **Approved folders only.** ``JARVIS_FILE_BROWSER_DIRS`` (``os.pathsep``-separated,
  absolute, existing directories); unset, the hub's own work folders that exist
  (``<data>/workspace``, ``<data>/outputs``, ``<data>/reports``). A folder that is, or
  contains, a protected place (``/``, the home directory, the data root, the code
  checkout, ``security``/``tokens``/``vault``/``secrets``/``config`` under the data root),
  or lies inside one or inside a private home folder (``~/.ssh``, ``~/.gnupg``,
  ``~/.config`` …), is dropped with a warning — the same policy as channel media delivery
  (``channels.media_delivery``). The Nerva Workspace's company data is never a root either
  (``workspace.config.hub_roots_without_workspace``). A folder is addressed by an opaque
  id; a request never carries an absolute path.
* **No escape.** A path is relative to its folder, ``/``-separated, with no empty, ``.``
  or ``..`` component, no backslash and no control character. It is opened one component
  at a time from the folder, each relative to the directory opened before it and with
  ``O_NOFOLLOW`` (``openat`` beneath, as ``media_delivery._open_beneath``): a symlink is
  never followed, and a folder swapped for a link mid-walk fails the walk. A file is
  opened non-blocking (a FIFO cannot hold the call), must be the very file the walk
  checked (inode and device), and a file with more than one name (a hard link, which can
  carry a protected file into an approved folder) is never read or downloaded.
* **Never credentials.** A name is refused — not listed, not read, not written, not
  created — when it is hidden (``.env``, ``.ssh``, ``.git`` …), looks like a secret by the
  file tools' policy (``file_tools.looks_secret_name``: ``*.pem``, ``id_rsa``,
  ``api_key.txt``, ``credentials.json`` …) or the media policy (``*token*``, ``passw*``),
  names a credential folder (``security``, ``tokens``, ``vault``, ``secrets``, ``keys``,
  ``ssh``, ``gnupg`` …) or is a data store (``*.db``, ``*.sqlite``, ``*.enc``, WAL and
  journal files). A listing counts what it hid without naming it.
* **Bounded.** A listing holds at most :data:`MAX_LIST_ENTRIES`; a preview at most
  :data:`PREVIEW_BYTES`; a download or an upload at most ``JARVIS_FILE_BROWSER_MAX_BYTES``
  (100 MiB by default, never above 1 GiB).
* **Writes.** An upload or a new folder is created in an approved folder and never
  replaces anything (``exists``): the upload is written to a hidden temporary file and
  linked into place without overwriting. **A rename or a delete is never applied by a
  request**: it is queued as a ``files.rename`` / ``files.delete`` card at the approval
  queue's irreversible tier (``autonomy.irreversible``; governed intake, so the Action
  Kernel mediates it when task mediation is on) and applied only from a human's accept,
  after the target is re-walked and found to be the same file the card showed (inode,
  device, size and modification time); anything else is ``changed_since_request``. A
  folder is deleted only when it is empty.

Refusals are bounded reason codes (:data:`REASONS`), never an echo of the request.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import logging
import os
import re
import stat
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.core.env_config import env_int, env_str

logger = logging.getLogger("jarvis.file_browser")

DIRS_ENV = "JARVIS_FILE_BROWSER_DIRS"
MAX_BYTES_ENV = "JARVIS_FILE_BROWSER_MAX_BYTES"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
MAX_BYTES_CEILING = 1024 * 1024 * 1024
PREVIEW_BYTES = 256 * 1024
MAX_LIST_ENTRIES = 2000
MAX_REL_CHARS = 1024
MAX_PARTS = 64
MAX_NAME_CHARS = 255
CHUNK = 64 * 1024

KIND_DELETE = "files.delete"
KIND_RENAME = "files.rename"
APPROVAL_KINDS = (KIND_DELETE, KIND_RENAME)

#: reason → (HTTP status, what the owner is told). The request is never echoed.
REASONS: dict[str, tuple[int, str]] = {
    "unknown_root": (404, "that folder is not an approved folder"),
    "root_changed": (409, "the approved folders changed since the request"),
    "bad_path": (400, "the path is not a plain relative path"),
    "bad_name": (400, "the name is not a plain file or folder name"),
    "denied_name": (403, "that name is never shown or written (credentials, keys, data stores, hidden files)"),
    "not_found": (404, "it does not exist"),
    "symlink": (403, "it is a link, and links are never followed"),
    "hard_link": (403, "it has other names (hard links), so where it really lives cannot be checked"),
    "not_a_directory": (400, "it is not a folder"),
    "not_a_file": (400, "it is not a regular file"),
    "too_large": (413, "it is larger than the file browser's limit"),
    "exists": (409, "something with that name already exists"),
    "not_empty": (409, "the folder is not empty"),
    "unreadable": (500, "it could not be read"),
    "unwritable": (500, "it could not be written"),
    "changed_since_request": (409, "it changed since the request"),
    "payload_invalid": (400, "the request is not one the file browser made"),
}


class FileBrowserError(Exception):
    """A refusal; ``reason`` is a bounded public code from :data:`REASONS`."""

    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in REASONS else "bad_path"
        super().__init__(self.reason)

    @property
    def status(self) -> int:
        return REASONS[self.reason][0]

    def payload(self) -> dict:
        return {"error": self.reason, "detail": REASONS[self.reason][1]}


# ── the denylist ───────────────────────────────────────────────────────────────

#: Folder (or file) names that hold credentials or the hub's private state.
DENIED_NAMES = frozenset({
    "security", "tokens", "token", "vault", "vaults", "secrets", "secret", "keys", "keyring",
    "keyrings", "ssh", "gnupg", "gpg", "credentials", "pairing", "mcp-tokens", "auth.json",
    "config.yaml", "settings.db",
})
_STORE_SUFFIX = re.compile(r"(\.(db|sqlite|sqlite3|db3|enc|kdbx|wal)|-(wal|shm|journal))$")


def denied_name(name: str) -> bool:
    """True when *name* is never listed, read or written (see the module doc)."""
    from agents.core.channels.media_delivery import _SECRET_NAME
    from agents.core.file_tools import looks_secret_name

    lowered = str(name or "").lower()
    if not lowered or lowered.startswith("."):
        return True
    return (lowered in DENIED_NAMES or looks_secret_name(name) or bool(_SECRET_NAME.search(lowered))
            or bool(_STORE_SUFFIX.search(lowered)))


def _check_name(name: object, *, reason: str = "bad_name") -> str:
    if (not isinstance(name, str) or not name or len(name) > MAX_NAME_CHARS or name in {".", ".."}
            or "/" in name or "\\" in name or name != name.strip()
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)):
        raise FileBrowserError(reason)
    if denied_name(name):
        raise FileBrowserError("denied_name")
    return name


def split_path(rel: object) -> tuple[str, ...]:
    """A request path as its checked components; ``""`` is the folder itself."""
    if rel is None:
        rel = ""
    if not isinstance(rel, str) or len(rel) > MAX_REL_CHARS or rel.startswith("/") or "\\" in rel:
        raise FileBrowserError("bad_path")
    text = rel[:-1] if rel.endswith("/") else rel
    if not text:
        return ()
    parts = tuple(text.split("/"))
    if len(parts) > MAX_PARTS:
        raise FileBrowserError("bad_path")
    for part in parts:
        _check_name(part, reason="bad_path")
    return parts


# ── approved folders ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Root:
    id: str
    path: Path
    label: str

    def view(self) -> dict:
        return {"id": self.id, "label": self.label, "path": str(self.path)}


def max_bytes() -> int:
    return min(env_int(MAX_BYTES_ENV, DEFAULT_MAX_BYTES, minimum=1), MAX_BYTES_CEILING)


def _root_id(path: Path) -> str:
    return "r" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


def _default_dirs() -> list[str]:
    from agents.core.paths import data_path

    return [str(data_path("workspace")), str(data_path("outputs")), str(data_path("reports"))]


def roots() -> list[Root]:
    """The approved folders in effect now (resolved, existing, policy-checked)."""
    from agents.core.channels import media_delivery as md

    configured = [p.strip() for p in env_str(DIRS_ENV).split(os.pathsep) if p.strip()]
    owner_listed = bool(configured)
    candidates = configured or _default_dirs()
    try:
        from agents.core.workspace import config as workspace_config

        candidates = workspace_config.hub_roots_without_workspace(DIRS_ENV, candidates)
    except Exception:  # noqa: BLE001 — no workspace module: nothing to protect from it
        logger.debug("workspace guard unavailable", exc_info=True)
    forbidden = md._forbidden_root_parents()
    inside_forbidden = md.protected_roots() + md._private_home_dirs()
    out: list[Root] = []
    for raw in candidates:
        candidate = Path(str(raw)).expanduser()
        if not candidate.is_absolute():
            logger.warning("%s: an entry is not an absolute path; ignored", DIRS_ENV)
            continue
        real = md._real(candidate)
        if real is None or not real.is_dir():
            if owner_listed:
                logger.warning("%s: an entry is not an existing folder; ignored", DIRS_ENV)
            continue
        if any(real == bad or md._within(bad, real) for bad in forbidden):
            logger.warning("%s: an entry is or contains a protected folder; ignored", DIRS_ENV)
            continue
        if any(md._within(real, bad) for bad in inside_forbidden):
            logger.warning("%s: an entry is inside a protected or private folder; ignored", DIRS_ENV)
            continue
        if any(r.path == real for r in out):
            continue
        out.append(Root(id=_root_id(real), path=real, label=real.name or str(real)))
    return out


def root_for(root_id: object) -> Root:
    if isinstance(root_id, str):
        for root in roots():
            if root.id == root_id:
                return root
    raise FileBrowserError("unknown_root")


# ── walking beneath a folder ───────────────────────────────────────────────────

_DIR_FLAGS = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
              | getattr(os, "O_CLOEXEC", 0))
_FILE_FLAGS = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
               | getattr(os, "O_CLOEXEC", 0))
_NEW_FILE_FLAGS = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                   | getattr(os, "O_CLOEXEC", 0))


def _lstat_at(name: str, dir_fd: int) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise FileBrowserError("not_found") from None
    except OSError:
        raise FileBrowserError("unreadable") from None


def _open_dir(root: Root, parts: tuple[str, ...]) -> int:
    """A directory fd for ``root/parts…``, opened component by component beneath the
    root with ``O_NOFOLLOW`` (the caller closes it)."""
    try:
        fd = os.open(root.path, _DIR_FLAGS)
    except OSError:
        raise FileBrowserError("unknown_root") from None
    try:
        for part in parts:
            st = _lstat_at(part, fd)
            if stat.S_ISLNK(st.st_mode):
                raise FileBrowserError("symlink")
            if not stat.S_ISDIR(st.st_mode):
                raise FileBrowserError("not_a_directory")
            try:
                nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                raise FileBrowserError("not_found") from None
            except OSError:      # ELOOP / ENOTDIR: it became a link (or not a folder) mid-walk
                raise FileBrowserError("symlink") from None
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _kind(mode: int) -> str:
    if stat.S_ISLNK(mode):
        return "link"
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def _open_file(root: Root, parts: tuple[str, ...]) -> tuple[int, os.stat_result]:
    """An fd on the regular, single-named file at ``root/parts…`` (the caller closes it)."""
    if not parts:
        raise FileBrowserError("not_a_file")
    dfd = _open_dir(root, parts[:-1])
    try:
        st = _lstat_at(parts[-1], dfd)
        if stat.S_ISLNK(st.st_mode):
            raise FileBrowserError("symlink")
        if not stat.S_ISREG(st.st_mode):
            raise FileBrowserError("not_a_file")
        try:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=dfd)
        except FileNotFoundError:
            raise FileBrowserError("not_found") from None
        except OSError:
            raise FileBrowserError("symlink") from None
    finally:
        os.close(dfd)
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            raise FileBrowserError("not_a_file")
        if (fst.st_ino, fst.st_dev) != (st.st_ino, st.st_dev):
            raise FileBrowserError("symlink")
        if fst.st_nlink > 1:
            raise FileBrowserError("hard_link")
        os.set_blocking(fd, True)
        return fd, fst
    except BaseException:
        os.close(fd)
        raise


# ── reads ──────────────────────────────────────────────────────────────────────

def list_dir(root_id: object, rel: object = "") -> dict:
    """The entries of a folder: dirs first, then files; denied names hidden and counted."""
    root = root_for(root_id)
    parts = split_path(rel)
    fd = _open_dir(root, parts)
    entries: list[dict] = []
    hidden = 0
    truncated = False
    try:
        with os.scandir(fd) as it:
            for entry in it:
                if denied_name(entry.name):
                    hidden += 1
                    continue
                if len(entries) >= MAX_LIST_ENTRIES:
                    truncated = True
                    break
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                kind = _kind(st.st_mode)
                row: dict[str, Any] = {"name": entry.name, "kind": kind, "modified": st.st_mtime}
                if kind == "file":
                    row["size"] = st.st_size
                    if st.st_nlink > 1:
                        row["hard_link"] = True
                entries.append(row)
    except OSError:
        raise FileBrowserError("unreadable") from None
    finally:
        os.close(fd)
    entries.sort(key=lambda r: (r["kind"] != "dir", r["name"].casefold()))
    return {"root": root.view(), "path": "/".join(parts), "entries": entries, "hidden": hidden,
            "truncated": truncated, "max_bytes": max_bytes()}


def read_preview(root_id: object, rel: object) -> dict:
    """At most :data:`PREVIEW_BYTES` of a file as text, or ``binary: true``."""
    root = root_for(root_id)
    parts = split_path(rel)
    fd, fst = _open_file(root, parts)
    try:
        data = os.read(fd, PREVIEW_BYTES + 1)
    except OSError:
        raise FileBrowserError("unreadable") from None
    finally:
        os.close(fd)
    truncated = len(data) > PREVIEW_BYTES
    data = data[:PREVIEW_BYTES]
    body: dict[str, Any] = {"root": root.id, "path": "/".join(parts), "size": fst.st_size,
                            "modified": fst.st_mtime, "truncated": truncated}
    if b"\x00" in data:
        return {**body, "binary": True, "text": None}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if truncated and exc.start >= len(data) - 3:     # a character cut at the page end
            text = data[:exc.start].decode("utf-8", errors="replace")
        else:
            return {**body, "binary": True, "text": None}
    return {**body, "binary": False, "text": text}


@dataclass(frozen=True)
class Download:
    root: Root
    parts: tuple[str, ...]
    name: str
    size: int
    identity: tuple[int, int]

    def chunks(self) -> Iterator[bytes]:
        """The file's bytes. The file is opened again here, beneath the root, and must
        still be the file that was checked; a file that grew stops at the checked size."""
        fd, fst = _open_file(self.root, self.parts)
        try:
            if (fst.st_ino, fst.st_dev) != self.identity:
                return
            left = self.size
            while left > 0:
                block = os.read(fd, min(CHUNK, left))
                if not block:
                    break
                left -= len(block)
                yield block
        finally:
            os.close(fd)


def prepare_download(root_id: object, rel: object) -> Download:
    root = root_for(root_id)
    parts = split_path(rel)
    fd, fst = _open_file(root, parts)
    os.close(fd)
    if fst.st_size > max_bytes():
        raise FileBrowserError("too_large")
    return Download(root=root, parts=parts, name=parts[-1], size=fst.st_size,
                    identity=(fst.st_ino, fst.st_dev))


# ── writes that replace nothing ────────────────────────────────────────────────

def make_dir(root_id: object, rel_dir: object, name: object) -> dict:
    root = root_for(root_id)
    parts = split_path(rel_dir)
    name = _check_name(name)
    dfd = _open_dir(root, parts)
    try:
        os.mkdir(name, 0o700, dir_fd=dfd)
    except FileExistsError:
        raise FileBrowserError("exists") from None
    except OSError:
        raise FileBrowserError("unwritable") from None
    finally:
        os.close(dfd)
    return {"root": root.id, "path": "/".join((*parts, name)), "kind": "dir"}


class Upload:
    """One upload: a hidden temporary file in the target folder, linked into place by
    :meth:`commit` without replacing anything. Always :meth:`close` it."""

    def __init__(self, root_id: object, rel_dir: object, name: object, *, limit: int | None = None):
        self.root = root_for(root_id)
        self.parts = split_path(rel_dir)
        self.name = _check_name(name)
        self.limit = max_bytes() if limit is None else int(limit)
        self.size = 0
        self._tmp = f".nerva-upload-{uuid.uuid4().hex}.part"
        self._dfd = _open_dir(self.root, self.parts)
        try:
            if self._exists(self.name):
                raise FileBrowserError("exists")
            self._fd: int | None = os.open(self._tmp, _NEW_FILE_FLAGS, 0o600, dir_fd=self._dfd)
        except FileBrowserError:
            os.close(self._dfd)
            raise
        except OSError:
            os.close(self._dfd)
            raise FileBrowserError("unwritable") from None
        self._linked = False

    def _exists(self, name: str) -> bool:
        try:
            os.stat(name, dir_fd=self._dfd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def write(self, data: bytes) -> None:
        if self._fd is None:
            raise FileBrowserError("unwritable")
        self.size += len(data)
        if self.size > self.limit:
            raise FileBrowserError("too_large")
        view = memoryview(data)
        try:
            while view:
                written = os.write(self._fd, view)
                view = view[written:]
        except OSError:
            raise FileBrowserError("unwritable") from None

    def commit(self) -> dict:
        if self._fd is None:
            raise FileBrowserError("unwritable")
        try:
            os.fsync(self._fd)
        except OSError:
            raise FileBrowserError("unwritable") from None
        os.close(self._fd)
        self._fd = None
        try:
            os.link(self._tmp, self.name, src_dir_fd=self._dfd, dst_dir_fd=self._dfd,
                    follow_symlinks=False)
        except FileExistsError:
            raise FileBrowserError("exists") from None
        except OSError as exc:
            if exc.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EXDEV, errno.EMLINK}:
                raise FileBrowserError("unwritable") from None
            # A filesystem without hard links: check, then rename (a narrow race only
            # against the owner's own writes in this folder).
            if self._exists(self.name):
                raise FileBrowserError("exists") from None
            try:
                os.rename(self._tmp, self.name, src_dir_fd=self._dfd, dst_dir_fd=self._dfd)
            except OSError:
                raise FileBrowserError("unwritable") from None
        self._linked = True
        return {"root": self.root.id, "path": "/".join((*self.parts, self.name)), "kind": "file",
                "size": self.size}

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._dfd is not None:
            try:
                os.unlink(self._tmp, dir_fd=self._dfd)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("an upload's temporary file could not be removed")
            os.close(self._dfd)
            self._dfd = None


# ── rename / delete: an approval card, applied from a human's accept ───────────

def _identity(st: os.stat_result) -> dict:
    return {"ino": st.st_ino, "dev": st.st_dev, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "kind": _kind(st.st_mode)}


def _target(root: Root, parts: tuple[str, ...]) -> tuple[int, os.stat_result]:
    """The parent folder's fd and the target's lstat (a link is its own entry)."""
    if not parts:
        raise FileBrowserError("bad_path")
    dfd = _open_dir(root, parts[:-1])
    try:
        return dfd, _lstat_at(parts[-1], dfd)
    except BaseException:
        os.close(dfd)
        raise


def _dir_empty(dfd: int, name: str) -> bool:
    fd = os.open(name, _DIR_FLAGS, dir_fd=dfd)
    try:
        with os.scandir(fd) as it:
            return next(iter(it), None) is None
    finally:
        os.close(fd)


def _human_size(size: int) -> str:
    step = 1024.0
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < step or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= step
    return f"{size} B"  # pragma: no cover


def delete_request(root_id: object, rel: object) -> dict:
    """``{title, payload, preview}`` for a ``files.delete`` card (nothing is deleted)."""
    root = root_for(root_id)
    parts = split_path(rel)
    dfd, st = _target(root, parts)
    try:
        kind = _kind(st.st_mode)
        if kind == "other":
            raise FileBrowserError("not_a_file")
        if kind == "dir" and not _dir_empty(dfd, parts[-1]):
            raise FileBrowserError("not_empty")
    except OSError:
        raise FileBrowserError("unreadable") from None
    finally:
        os.close(dfd)
    path = "/".join(parts)
    what = {"file": "file", "dir": "empty folder", "link": "link"}[kind]
    preview = {"action": f"Delete the {what}", "folder": root.label, "folder_path": str(root.path),
               "path": path, "kind": kind, "irreversible": True}
    if kind == "file":
        preview["size"] = _human_size(st.st_size)
    payload = {"op": "delete", "root_id": root.id, "root_path": str(root.path), "path": path,
               "target": _identity(st)}
    return {"title": f"Delete {path} in {root.label}", "payload": payload, "preview": preview}


def rename_request(root_id: object, rel: object, new_name: object) -> dict:
    """``{title, payload, preview}`` for a ``files.rename`` card within the same folder."""
    root = root_for(root_id)
    parts = split_path(rel)
    new_name = _check_name(new_name)
    if parts and new_name == parts[-1]:
        raise FileBrowserError("exists")
    dfd, st = _target(root, parts)
    try:
        if _kind(st.st_mode) == "other":
            raise FileBrowserError("not_a_file")
        try:
            os.stat(new_name, dir_fd=dfd, follow_symlinks=False)
            raise FileBrowserError("exists")
        except FileNotFoundError:
            pass
    finally:
        os.close(dfd)
    path = "/".join(parts)
    new_path = "/".join((*parts[:-1], new_name))
    preview = {"action": "Rename", "folder": root.label, "folder_path": str(root.path),
               "path": path, "new_path": new_path, "kind": _kind(st.st_mode), "irreversible": False}
    payload = {"op": "rename", "root_id": root.id, "root_path": str(root.path), "path": path,
               "new_name": new_name, "target": _identity(st)}
    return {"title": f"Rename {path} to {new_name} in {root.label}", "payload": payload,
            "preview": preview}


def _refused(reason: str) -> dict:
    return {"status": "refused", "reason": reason}


def _same(st: os.stat_result, target: dict) -> bool:
    now = _identity(st)
    keys = ("ino", "dev", "kind", "mtime_ns") + (("size",) if now["kind"] == "file" else ())
    return all(now[k] == target.get(k) for k in keys)


def apply_payload(payload: object, *, kind: str) -> dict:
    """Apply an accepted card's payload after re-walking it (sync; see apply_approved)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("target"), dict):
        return _refused("payload_invalid")
    op = payload.get("op")
    if (kind, op) not in {(KIND_DELETE, "delete"), (KIND_RENAME, "rename")}:
        return _refused("payload_invalid")
    try:
        root = root_for(payload.get("root_id"))
        if str(root.path) != payload.get("root_path"):
            return _refused("root_changed")
        parts = split_path(payload.get("path"))
        new_name = _check_name(payload.get("new_name")) if op == "rename" else None
        dfd, st = _target(root, parts)
    except FileBrowserError as exc:
        return _refused("root_changed" if exc.reason == "unknown_root" else exc.reason)
    try:
        if not _same(st, payload["target"]):
            return _refused("changed_since_request")
        name = parts[-1]
        if op == "delete":
            if stat.S_ISDIR(st.st_mode):
                os.rmdir(name, dir_fd=dfd)
            else:
                os.unlink(name, dir_fd=dfd)
            return {"status": "ok", "kind": kind, "deleted": "/".join(parts)}
        try:
            os.stat(new_name, dir_fd=dfd, follow_symlinks=False)
            return _refused("exists")
        except FileNotFoundError:
            pass
        if stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
            # No-replace for a file: a second name, then drop the first.
            try:
                os.link(name, new_name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
                os.unlink(name, dir_fd=dfd)
            except FileExistsError:
                return _refused("exists")
            except OSError:
                os.rename(name, new_name, src_dir_fd=dfd, dst_dir_fd=dfd)
        else:
            os.rename(name, new_name, src_dir_fd=dfd, dst_dir_fd=dfd)
        return {"status": "ok", "kind": kind, "renamed": "/".join(parts),
                "to": "/".join((*parts[:-1], new_name))}
    except OSError as exc:
        if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
            return _refused("not_empty" if op == "delete" else "exists")
        if isinstance(exc, FileNotFoundError):
            return _refused("changed_since_request")
        logger.warning("an approved %s could not be applied (%s)", kind, type(exc).__name__)
        return {"status": "failed", "reason": "apply_failed"}
    finally:
        os.close(dfd)


async def apply_approved(task: Any, orch: Any) -> dict:
    """Apply a ``files.delete`` / ``files.rename`` task a human accepted
    (``irreversible.execute`` checked who decided), then audit it."""
    kind = str(getattr(task, "kind", "") or "")
    result = await asyncio.to_thread(apply_payload, getattr(task, "payload", None), kind=kind)
    payload = getattr(task, "payload", None) or {}
    await audit(orch, f"{kind} task {getattr(task, 'id', None)} by {getattr(task, 'decided_by', '')}: "
                      f"{result.get('status')} {result.get('reason', '')} "
                      f"{payload.get('path', '') if isinstance(payload, dict) else ''}".strip(),
                "file_browser_" + ("delete" if kind == KIND_DELETE else "rename"))
    return result


async def audit(orch: Any, preview: str, action: str) -> None:
    """One audit row (never file contents); a missing or failing audit log is logged."""
    audit_log = getattr(orch, "audit", None) if orch is not None else None
    if audit_log is None:
        return
    from agents.core.security.types import SecurityEvent, SecurityEventType

    try:
        await asyncio.to_thread(audit_log.log, SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(),
            content_preview=preview[:500], action_taken=action))
    except Exception:  # noqa: BLE001
        logger.warning("a file browser audit row could not be written (%s)", action)


__all__ = ["APPROVAL_KINDS", "DIRS_ENV", "Download", "FileBrowserError", "KIND_DELETE", "KIND_RENAME",
           "MAX_BYTES_ENV", "REASONS", "Root", "Upload", "apply_approved", "apply_payload", "audit",
           "delete_request", "denied_name", "list_dir", "make_dir", "max_bytes", "prepare_download",
           "read_preview", "rename_request", "root_for", "roots", "split_path"]
