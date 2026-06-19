"""Central runtime-data location resolver (audit F-08 / SEC-4).

All persistent runtime state (SQLite DBs, JSON stores, tokens, audio, eval
datasets, …) lives under a single root so it can be relocated out of the source
checkout. Resolution order:

  1. $JARVIS_HOME        — explicit data root (recommended for deployments)
  2. $JARVIS_MEMORY_DIR  — legacy override (kept for back-compat)
  3. <repo>/memory_logs  — default (unchanged; existing installs keep working)

The default is the *same* location as the old hardcoded ``memory_logs/`` (just
resolved to an absolute path), so behavior is identical unless one of the env
vars is set — at which point every store relocates together.
"""
import os
from pathlib import Path

# agents/core/paths.py → parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ROOT = _REPO_ROOT / "memory_logs"


def data_root() -> Path:
    """Return the runtime-data root (honors $JARVIS_HOME / $JARVIS_MEMORY_DIR)."""
    env = os.environ.get("JARVIS_HOME", "").strip() or os.environ.get("JARVIS_MEMORY_DIR", "").strip()
    return Path(env).expanduser() if env else _DEFAULT_ROOT


def data_path(*parts) -> Path:
    """Join *parts under the runtime-data root (does not create the path)."""
    return data_root().joinpath(*[str(p) for p in parts])


def is_inside_repo() -> bool:
    """True when the resolved data root lives inside this git checkout.

    Used for a startup warning: colocating private runtime state with source
    risks accidental commit/zip/share. Set $JARVIS_HOME to relocate it.
    """
    try:
        data_root().resolve().relative_to(_REPO_ROOT)
        return (_REPO_ROOT / ".git").exists()
    except ValueError:
        return False
