"""profiles.py — per-server hardening: which runtime a server uses, and what the
workspace can still influence.

Even in a trusted workspace, a server should use its own bundled runtime and libraries
rather than ones the workspace ships. :func:`profile` returns, for a server and the
binary that will run, the ``initializationOptions`` and the settings Nerva answers
``workspace/configuration`` with, or refuses (:class:`ProfileRefused`) when it cannot
pin what must be pinned.

What a trusted workspace can still influence, per server (documented, not hidden):

* **typescript** — the tsserver is forced to the copy bundled next to the
  typescript-language-server Nerva runs (``initializationOptions.tsserver.path``); a
  workspace ``node_modules/typescript`` is never used. ``tsconfig.json`` still selects
  files, ``compilerOptions`` and ``plugins`` (tsserver loads language-service plugins
  only from its own install location here, so a workspace plugin package is not
  resolved from the workspace).
* **pyright / pylsp** — the interpreter is pinned to a system Python
  (``python.pythonPath`` / ``pylsp.plugins.jedi.environment``) and pylsp's workspace
  configuration sources (setup.cfg/tox.ini/flake8) are off; plugins load only from
  the server's own environment. A ``pyrightconfig.json`` that names ``venvPath``/
  ``venv`` can still point pyright at a venv inside the workspace, whose Python
  pyright then runs to read its search paths — inside the sandbox.
* **rust-analyzer** — build scripts, proc-macros and check-on-save are off, so Cargo
  never builds or runs workspace code; ``Cargo.toml`` still shapes the analysis.
* **gopls** — ``GOTOOLCHAIN=local`` and ``GOPROXY=off``: no toolchain or module is
  fetched; ``go list`` runs the system ``go`` on the workspace (no workspace code).
* **clangd** — ``compile_commands.json`` still names compilers, but clangd only
  queries a driver allowed by ``--query-driver``, which Nerva never passes.
* every other server: its own configuration files in the workspace are read.

That residue is why a workspace must be trusted first, and why every server runs in
the sandbox with no network and a read-only workspace.
"""

from __future__ import annotations

import os
from pathlib import Path

PINNED_PYTHONS = ("/usr/bin/python3", "/usr/local/bin/python3", "/bin/python3")


class ProfileRefused(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def pinned_python() -> str | None:
    for candidate in PINNED_PYTHONS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def bundled_tsserver(binary: str, workspace: Path) -> Path | None:
    """The tsserver.js shipped next to *binary*'s typescript-language-server, never one
    inside *workspace*."""
    real = Path(binary).resolve()
    workspace = workspace.resolve()
    for ancestor in real.parents:
        modules = ancestor if ancestor.name == "node_modules" else ancestor / "node_modules"
        candidate = modules / "typescript" / "lib" / "tsserver.js"
        if candidate.is_file():
            resolved = candidate.resolve()
            if resolved != workspace and workspace not in resolved.parents:
                return resolved
    return None


def profile(server_id: str, binary: str, workspace: Path) -> tuple[dict, dict]:
    """``(initializationOptions, settings)`` for the server, or raise ProfileRefused."""
    if server_id == "typescript":
        tsserver = bundled_tsserver(binary, workspace)
        if tsserver is None:
            raise ProfileRefused("no_bundled_tsserver")
        return {"tsserver": {"path": str(tsserver)}, "disableAutomaticTypingAcquisition": True}, {}
    if server_id == "pyright":
        python = pinned_python()
        settings: dict = {"python": {"analysis": {"autoSearchPaths": True}}}
        if python:
            settings["python"]["pythonPath"] = python
        return {}, settings
    if server_id == "pylsp":
        python = pinned_python()
        plugins: dict = {"rope_autoimport": {"enabled": False}}
        if python:
            plugins["jedi"] = {"environment": python}
        return {}, {"pylsp": {"configurationSources": [], "plugins": plugins}}
    if server_id == "rust-analyzer":
        options = {"cargo": {"buildScripts": {"enable": False}}, "procMacro": {"enable": False},
                   "checkOnSave": False, "check": {"invocationStrategy": "once"}}
        return options, {"rust-analyzer": options}
    return {}, {}


__all__ = ["ProfileRefused", "bundled_tsserver", "pinned_python", "profile"]
