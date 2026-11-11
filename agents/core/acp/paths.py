"""Paths the editor names, confined to the session's working directory (G11).

The editor launched ``nerva acp`` and is trusted to be the owner's, but what it sends is
still input: a ``cwd`` on ``session/new``, a file in a prompt's resource link, a path on
an approval card the diff is drawn for. Every one of them goes through here:

* the session folder must be an absolute, existing directory and not a filesystem root;
* a path is resolved (symlinks included) and must stay inside that folder — ``..``, an
  absolute path elsewhere, or a symlink that leaves the folder is refused;
* a NUL or an over-long path is refused before any filesystem call;
* a read is bounded (:data:`MAX_READ_BYTES`) and only text is returned.

The hub applies its own, independent scope as well (its file roots, ``FileScope``): this
module only decides what the *editor side* reads and shows.
"""

from __future__ import annotations

import os
from pathlib import Path

MAX_PATH_CHARS = 4096
#: The most of one file read to draw a diff (the editor's own buffer is asked first).
MAX_READ_BYTES = 2 * 1024 * 1024


class AcpPathError(ValueError):
    """A path the session may not use; ``reason`` is a fixed machine word."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _clean(raw: object) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > MAX_PATH_CHARS or "\x00" in raw:
        raise AcpPathError("invalid_path")
    return raw


def session_root(raw: object) -> Path:
    """The editor's working directory for a session: absolute, an existing directory, not
    a filesystem root. Returned resolved (symlinks followed)."""
    text = _clean(raw)
    path = Path(text)
    if not path.is_absolute():
        raise AcpPathError("cwd_not_absolute")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise AcpPathError("cwd_missing") from None
    if not resolved.is_dir():
        raise AcpPathError("cwd_not_a_directory")
    if resolved.parent == resolved:
        raise AcpPathError("cwd_is_filesystem_root")
    return resolved


def confine(root: Path, raw: object) -> Path:
    """*raw* (absolute, or relative to *root*) resolved inside *root*, or AcpPathError."""
    text = _clean(raw)
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        raise AcpPathError("invalid_path") from None
    try:
        resolved.relative_to(root)
    except ValueError:
        raise AcpPathError("outside_session") from None
    return resolved


def read_text(path: Path) -> str | None:
    """The file's text for a diff, or None when it does not exist. Refuses a file over
    :data:`MAX_READ_BYTES` or one that is not UTF-8 text (AcpPathError)."""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError:
        raise AcpPathError("unreadable") from None
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(MAX_READ_BYTES + 1)
    if len(data) > MAX_READ_BYTES:
        raise AcpPathError("too_large")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise AcpPathError("not_text") from None


__all__ = ["AcpPathError", "MAX_READ_BYTES", "confine", "read_text", "session_root"]
