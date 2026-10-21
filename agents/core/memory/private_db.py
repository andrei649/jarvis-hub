"""private_db.py — owner-only SQLite files for the memory stores (H574 review).

``sqlite3.connect`` creates a database with ``0o666 & ~umask`` (``0644`` under the
default umask), and the data root is a plain ``mkdir``, so a database holding transcript
text or facts would be readable by every local user, while the JSON snapshots it mirrors
are written ``0600`` on purpose (``atomic_write_json``). :func:`ensure_private`
pre-creates the file at ``0600`` before the first connect and narrows an existing one (a
file an earlier version created at ``0644``). SQLite creates its ``-journal`` / ``-wal``
/ ``-shm`` sidecars with the main file's permissions, so they follow; any that already
exist are narrowed too.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

PRIVATE_MODE = 0o600
_SIDECARS = ("-journal", "-wal", "-shm")


def ensure_private(path: Path) -> None:
    """Create *path* owner-only when missing, and narrow it and its sidecars to
    :data:`PRIVATE_MODE` when they exist. A symlink is never followed (``O_NOFOLLOW``);
    a chmod the filesystem refuses (Windows, a foreign owner) is left to the connect."""
    path = Path(path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    with contextlib.suppress(OSError):
        os.close(os.open(path, flags, PRIVATE_MODE))
    for candidate in (path, *(Path(str(path) + suffix) for suffix in _SIDECARS)):
        try:
            if candidate.is_symlink() or not candidate.exists():
                continue
            if candidate.stat().st_mode & 0o777 != PRIVATE_MODE:
                os.chmod(candidate, PRIVATE_MODE)
        except OSError:
            continue


__all__ = ["PRIVATE_MODE", "ensure_private"]
