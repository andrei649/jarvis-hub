"""``pathlib.Path`` for the adopted verify recipes (rewrite rule ``verify-fs``, G5).

``agent/verify/recipes.py`` and ``environment.py`` look at a project the way a person
would: does ``package.json`` exist, what does ``Makefile`` say, is there a saved
``.hermes/environment.json``. Upstream does it with ``pathlib``. Here the stand-in does
no I/O of its own: every look is handed to the file-system object Nerva's verify layer
bound for the call (:func:`bound`; ``agents/core/verify/project.ConfinedFS``), which
confines it to one project root admitted by the owner's file scope — no symlink
component, no hard-linked file, no secret-looking path, bounded reads, and a write only
to the exact manifest ``/verify save`` names, opened without following links.

With nothing bound every path is missing and every write is refused, so vendored code
imported outside Nerva's verify layer sees an empty, read-only disk. This module imports
no Nerva module, ``os`` or I/O library.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from pathlib import PurePath
from typing import Any

_FS: contextvars.ContextVar[Any] = contextvars.ContextVar("hermes_verify_fs", default=None)


@contextmanager
def bound(fs: Any):
    """Bind *fs* (an object with ``exists``, ``is_file``, ``is_dir``, ``read_text``,
    ``write_text`` and ``mkdir`` taking a ``PurePath``) for the block."""
    token = _FS.set(fs)
    try:
        yield fs
    finally:
        _FS.reset(token)


class Path:
    """The subset of ``pathlib.Path`` the verify recipes use; effects go to the bound fs."""

    __slots__ = ("_pure",)

    def __init__(self, *parts: object) -> None:
        self._pure = PurePath(*(str(p) for p in parts))

    def __truediv__(self, other: object) -> Path:
        return Path(self, other)

    def __rtruediv__(self, other: object) -> Path:
        return Path(other, self)

    def __str__(self) -> str:
        return str(self._pure)

    def __repr__(self) -> str:
        return f"Path({str(self._pure)!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Path) and other._pure == self._pure

    def __hash__(self) -> int:
        return hash(self._pure)

    @property
    def name(self) -> str:
        return self._pure.name

    @property
    def suffix(self) -> str:
        return self._pure.suffix

    @property
    def parent(self) -> Path:
        return Path(self._pure.parent)

    def exists(self) -> bool:
        fs = _FS.get()
        return bool(fs is not None and fs.exists(self._pure))

    def is_file(self) -> bool:
        fs = _FS.get()
        return bool(fs is not None and fs.is_file(self._pure))

    def is_dir(self) -> bool:
        fs = _FS.get()
        return bool(fs is not None and fs.is_dir(self._pure))

    def read_text(self, encoding: str | None = "utf-8", errors: str | None = None) -> str:
        fs = _FS.get()
        if fs is None:
            raise FileNotFoundError(str(self._pure))
        return fs.read_text(self._pure, encoding=encoding or "utf-8", errors=errors or "strict")

    def write_text(self, data: str, encoding: str | None = "utf-8", errors: str | None = None) -> int:
        fs = _FS.get()
        if fs is None:
            raise PermissionError(f"{self._pure}: nothing may be written here")
        return fs.write_text(self._pure, data, encoding=encoding or "utf-8", errors=errors or "strict")

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        fs = _FS.get()
        if fs is None:
            raise PermissionError(f"{self._pure}: nothing may be created here")
        fs.mkdir(self._pure, exist_ok)


__all__ = ["Path", "bound"]
