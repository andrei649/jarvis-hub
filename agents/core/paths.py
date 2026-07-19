"""Central runtime-data location resolver (audit F-08 / SEC-4 + the packaged app).

All persistent runtime state (SQLite DBs, JSON stores, tokens, audio, eval
datasets, …) lives under a single root so it can be relocated out of the source
checkout. Resolution order for :func:`data_root`:

  1. $JARVIS_HOME        — explicit data root (recommended for deployments)
  2. $JARVIS_MEMORY_DIR  — legacy override (kept for back-compat)
  3. <user home>/memory  — when a *user data home* is active (packaged app /
                           $JARVIS_USER_HOME) — see below
  4. <repo>/memory_logs  — default (unchanged; existing installs keep working)

The default is the *same* location as the old hardcoded ``memory_logs/`` (just
resolved to an absolute path), so behavior is identical unless one of the env
vars is set — at which point every store relocates together.

User data home (the "Documents folder")
---------------------------------------
When Jarvis runs as a packaged executable (PyInstaller sets ``sys.frozen``) or
``$JARVIS_USER_HOME`` is set, all sensitive/personal state of the local
instance lives in one owner-visible folder — by default
``~/Documents/Jarvis`` — instead of inside the install directory:

    Documents/Jarvis/
      README.md      what lives here + how to back it up
      .env           secrets/config (copied from .env.example on first run)
      memory/        every runtime store (settings.db, checkpoints, audit, …)
      skills/        user-installed/generated skills (discovered in addition
                     to the bundled ones; same name → the user's copy wins)
      souls/<id>/    SOUL.local.md / HEARTBEAT.local.md persona overlays
                     (win over both the repo-local overlay and the template)

In a dev checkout with no env vars set, :func:`user_home` is ``None`` and all
of this is inert — behavior stays byte-identical to before.

App root (frozen-aware anchoring)
---------------------------------
:func:`app_root` is the directory that holds the *shipped, read-only* tree
(``agents/``, ``skills/``, ``.env.example``): the repo checkout in dev, the
PyInstaller bundle dir (``sys._MEIPASS``) when frozen. Code that used to build
CWD-relative paths (``Path("skills")``, ``Path("agents/<id>/SOUL.md")``)
anchors on it so the app works regardless of the working directory.
"""
import os
import sys
from pathlib import Path

# agents/core/paths.py → parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ROOT = _REPO_ROOT / "memory_logs"

_USER_HOME_README = """\
# Jarvis — your data

Everything personal about this Jarvis instance lives in this folder — the
install directory holds only the application code and can be deleted or
upgraded at any time without losing anything.

| Item | What it is |
|------|------------|
| `.env` | Your configuration + API keys/secrets. Never share this file. |
| `memory/` | All runtime state: settings, conversation memory, checkpoints, the security audit log, autonomy queue, embeddings cache. |
| `skills/` | Skills you installed or Jarvis generated (with your approval). These load in addition to the bundled skills; a same-named skill here wins. |
| `souls/<agent>/SOUL.local.md` | Your personalized agent personas (and `HEARTBEAT.local.md` schedules). These override the shipped templates. |

**Backup:** copy this whole folder. **Full reset:** stop Jarvis and delete
`memory/`. **Uninstall:** delete the app install directory; this folder is
yours and is never touched by an uninstall.
"""


def is_frozen() -> bool:
    """True when running as a packaged executable (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """The read-only application tree: repo checkout in dev, bundle dir frozen.

    $JARVIS_APP_ROOT overrides both (tests + unusual deployments).
    """
    env = os.environ.get("JARVIS_APP_ROOT", "").strip()
    if env:
        return Path(env).expanduser()
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return _REPO_ROOT


def user_home() -> "Path | None":
    """The owner's data folder, or None when not active (plain dev checkout).

    $JARVIS_USER_HOME always wins; a frozen build defaults to
    ``~/Documents/Jarvis``. Returning None keeps every overlay/scaffold path
    inert so dev + test behavior is unchanged.
    """
    env = os.environ.get("JARVIS_USER_HOME", "").strip()
    if env:
        return Path(env).expanduser()
    if is_frozen():
        return Path.home() / "Documents" / "Jarvis"
    return None


def user_skills_dir() -> "Path | None":
    home = user_home()
    return home / "skills" if home else None


def user_souls_dir() -> "Path | None":
    home = user_home()
    return home / "souls" if home else None


def ensure_user_home() -> "Path | None":
    """First-run scaffold of the user data home. Idempotent, never overwrites.

    Creates the folder layout, writes README.md once, and copies
    ``.env.example`` → ``.env`` once so the owner has a ready-to-edit config.
    Returns the home path (or None when no user home is active).
    """
    home = user_home()
    if home is None:
        return None
    for sub in ("memory", "skills", "souls"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    readme = home / "README.md"
    if not readme.exists():
        readme.write_text(_USER_HOME_README, encoding="utf-8")
    env_file = home / ".env"
    if not env_file.exists():
        example = app_root() / ".env.example"
        if example.exists():
            env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return home


def data_root() -> Path:
    """Return the runtime-data root (honors $JARVIS_HOME / $JARVIS_MEMORY_DIR)."""
    env = os.environ.get("JARVIS_HOME", "").strip() or os.environ.get("JARVIS_MEMORY_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    home = user_home()
    if home is not None:
        return home / "memory"
    return _DEFAULT_ROOT


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
