"""``pathlib.Path`` for the adopted verify recipes (rewrite rule ``verify-fs``, G5).

``agent/verify/recipes.py`` and ``environment.py`` look at a project the way a person
would: does ``package.json`` exist, what does ``Makefile`` say, is there a saved
``.hermes/environment.json``. Upstream does it with ``pathlib``. Here every one of those
looks goes through this stand-in, bound by Nerva's verify layer for one call
(:func:`bound`) to one project root that the owner's file scope admitted:

* **Confined.** A path is resolved (symlinks followed) and must stay under the bound
  root; anything else does not exist and cannot be read. With nothing bound every path
  is missing, so vendored code imported outside Nerva's verify layer sees an empty disk.
* **Never a secret.** A path with a secret-looking component (``.env``, ``id_rsa`` …,
  the file tools' own rule) does not exist here.
* **Bounded reads.** At most :data:`MAX_READ_BYTES` per file; a larger file reads as an
  error, which the recipes already treat as "not there".
* **Writes only where allowed.** ``write_text`` and ``mkdir`` work only for the exact
  manifest path the caller named in :func:`bound` (``/verify save``, the owner's
  command), and only under the root. Every other write is a ``PermissionError``.

Nothing here runs a process or opens the network.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path as _RealPath
from pathlib import PurePath

MAX_READ_BYTES = 256 * 1024


def _dot_parts(parts: tuple[str, ...]) -> bool:
    """The default hiding rule when the caller names none: every dot-name but ``.hermes``."""
    return any(part.startswith(".") and part != ".hermes" for part in parts)


@dataclass(frozen=True)
class _Binding:
    root: _RealPath
    writable: frozenset[_RealPath]
    hidden: Callable[[tuple[str, ...]], bool]


def _real(path: object) -> _RealPath:
    return _RealPath(str(path)).resolve(strict=False)


_BINDING: contextvars.ContextVar[_Binding | None] = contextvars.ContextVar("hermes_verify_fs", default=None)


@contextmanager
def bound(root: object, *, writable: tuple[object, ...] = (),
          hidden: Callable[[tuple[str, ...]], bool] | None = None):
    """Bind the project *root* (already admitted by the caller's file scope) for the
    duration of the block; *writable* names the only files a write may create; *hidden*
    says which relative paths do not exist (Nerva passes the file tools' secret rule)."""
    real_root = _real(root)
    allowed = frozenset(_real(p) for p in writable)
    token = _BINDING.set(_Binding(real_root, allowed, hidden or _dot_parts))
    try:
        yield real_root
    finally:
        _BINDING.reset(token)


class Path:
    """The subset of ``pathlib.Path`` the verify recipes use, confined to the bound root."""

    __slots__ = ("_pure",)

    def __init__(self, *parts: object) -> None:
        self._pure = PurePath(*(str(p) for p in parts))

    # ── pure operations ─────────────────────────────────────────────────────
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

    # ── confined effects ────────────────────────────────────────────────────
    def _inside(self) -> _RealPath | None:
        """The resolved path when it is under the bound root and not secret-looking."""
        binding = _BINDING.get()
        if binding is None or not self._pure.is_absolute():
            return None
        try:
            real = _real(self._pure)
            relative = real.relative_to(binding.root)
            if binding.hidden(relative.parts):
                return None
        except Exception:  # noqa: BLE001 — anything unclear is "not there"
            return None
        return real

    def exists(self) -> bool:
        real = self._inside()
        try:
            return real is not None and real.exists()
        except OSError:
            return False

    def is_file(self) -> bool:
        real = self._inside()
        try:
            return real is not None and real.is_file()
        except OSError:
            return False

    def is_dir(self) -> bool:
        real = self._inside()
        try:
            return real is not None and real.is_dir()
        except OSError:
            return False

    def read_text(self, encoding: str | None = "utf-8", errors: str | None = None) -> str:
        real = self._inside()
        if real is None:
            raise FileNotFoundError(str(self._pure))
        if not real.is_file():
            raise FileNotFoundError(str(self._pure))
        with real.open("rb") as handle:
            data = handle.read(MAX_READ_BYTES + 1)
        if len(data) > MAX_READ_BYTES:
            raise OSError(f"{self._pure.name}: larger than {MAX_READ_BYTES} bytes")
        return data.decode(encoding or "utf-8", errors or "strict")

    def _writable(self) -> _RealPath:
        binding = _BINDING.get()
        real = self._inside()
        if binding is None or real is None or real not in binding.writable:
            raise PermissionError(f"{self._pure}: not a path the verify layer may write")
        return real

    def write_text(self, data: str, encoding: str | None = "utf-8", errors: str | None = None) -> int:
        real = self._writable()
        return real.write_text(data, encoding=encoding or "utf-8", errors=errors or "strict")

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        binding = _BINDING.get()
        real = self._inside()
        if binding is None or real is None or not any(real == w.parent for w in binding.writable):
            raise PermissionError(f"{self._pure}: not a folder the verify layer may create")
        real.mkdir(mode=0o755, parents=False, exist_ok=exist_ok)


__all__ = ["MAX_READ_BYTES", "Path", "bound"]
