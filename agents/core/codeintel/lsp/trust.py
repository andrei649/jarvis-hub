"""trust.py — which workspaces the owner allowed language servers in.

A language server reads a workspace's configuration, and several of them can be led
by it into running code the workspace ships (a ``node_modules/typescript``, a
``pyrightconfig.json`` naming a venv's Python, Cargo build scripts). So no server
starts in a workspace until the owner has trusted that workspace for language
servers — an owner action (``POST /api/codeintel/lsp/trust``, admin; ``nerva lsp
trust``), recorded here by resolved root, never something the model can do — and
only in a git workspace (the root is the directory that holds ``.git``; there is no
fallback to a bare file root).

The record lives in ``<data root>/codeintel/lsp-trust.json``, outside the tools
directory that installs write and outside every server's sandbox.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
FORMAT = "nerva-lsp-trust/1"


def default_path() -> Path:
    from agents.core.paths import data_path

    return Path(data_path("codeintel", "lsp-trust.json"))


def git_root(path: Path, scope_root: Path) -> Path | None:
    """The nearest directory holding ``.git`` from *path* up to *scope_root*, or None."""
    scope_root = scope_root.resolve()
    current = path.resolve()
    if not current.is_dir():
        current = current.parent
    while current == scope_root or scope_root in current.parents:
        if (current / ".git").exists():
            return current
        if current == scope_root:
            break
        current = current.parent
    return None


class TrustStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else default_path()

    def _read(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        roots = data.get("roots") if isinstance(data, dict) else None
        return {k: v for k, v in roots.items() if isinstance(v, dict)} if isinstance(roots, dict) else {}

    def _write(self, roots: dict[str, dict]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"format": FORMAT, "roots": roots}, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def roots(self) -> dict[str, dict]:
        return self._read()

    def trusted(self, root: Path) -> bool:
        return str(root.resolve()) in self._read()

    def trust(self, root: Path, *, by: str = "owner") -> dict:
        key = str(root.resolve())
        with _LOCK:
            roots = self._read()
            roots[key] = {"trusted_at": time.time(), "by": by}
            self._write(roots)
        return {"root": key, **roots[key]}

    def revoke(self, root: Path) -> bool:
        key = str(root.resolve())
        with _LOCK:
            roots = self._read()
            if key not in roots:
                return False
            roots.pop(key)
            self._write(roots)
        return True


__all__ = ["TrustStore", "default_path", "git_root"]
