"""
persistence.py — Memory persistence: saves/loads conversation history across restarts.
"""

import json
import logging
from pathlib import Path

from agents.core.paths import data_root
from agents.core.persistence import atomic_write_json
from agents.core.session_files import is_session_stem, looks_like_session_snapshot
from agents.core.validation import is_valid_session_id

# Resolved LAZILY, not at import. `MEMORY_DIR = data_root()` bound the repo's
# memory_logs/ before a caller could redirect JARVIS_HOME, so scripts/install_smoke.py
# — which DOES set JARVIS_HOME to a temp dir — still wrote its fixture session into the
# live store, and every later boot restored "install_smoke" as the owner's session
# (2026-07-27 QA finding). Same class, and same fix, as the autonomy.db leak in #723.
# `MEMORY_DIR = None` means "ask data_root() each time". It stays a module attribute
# because tests pin it directly (monkeypatch.setattr(persistence, "MEMORY_DIR", tmp)),
# and that seam is worth keeping — it is how the traversal tests get a sandbox.
MEMORY_DIR: Path | None = None


def memory_dir() -> Path:
    """Where session state lives, resolved NOW — honors an explicit MEMORY_DIR override
    first, then the current JARVIS_HOME. Public because callers legitimately need the
    path (tests, the KG writing beside a snapshot); read it through this, never through
    a value captured at import."""
    return MEMORY_DIR if MEMORY_DIR is not None else data_root()


_memory_dir = memory_dir   # internal alias, kept so use sites read tersely

logger = logging.getLogger("jarvis.persistence")


def save_memory(session_id: str, turns: list[dict]):
    # AUD-5: never let an id that isn't an inert identifier reach the path — a
    # second line of defense behind the router validation, so any internal caller
    # is protected too.
    if not is_valid_session_id(session_id):
        logger.warning("refusing to save memory for invalid session_id")
        return
    _memory_dir().mkdir(parents=True, exist_ok=True)
    path = _memory_dir() / f"{session_id}.json"
    try:
        # tmp+replace, not open(path, "w"): the truncate-then-stream form left a
        # half-written snapshot on disk whenever the dump raised (or the process
        # died) mid-turn, and load_memory() reads that as an empty conversation.
        atomic_write_json(path, {"session_id": session_id, "turns": turns})
        logger.info(f"Memory saved: {path} ({len(turns)} turns)")
    except Exception as e:
        logger.warning(f"Failed to save memory: {e}")


def load_memory(session_id: str) -> list[dict]:
    if not is_valid_session_id(session_id):
        logger.warning("refusing to load memory for invalid session_id")
        return []
    path = _memory_dir() / f"{session_id}.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Memory loaded: {path} ({len(data.get('turns', []))} turns)")
        return data.get("turns", [])
    except Exception as e:
        logger.warning(f"Failed to load memory: {e}")
        return []


def list_sessions() -> list[str]:
    """Most-recent conversation sessions in the data root, newest first (max 5).

    The data root is shared with runtime state (`entities.json`, `decay.json`,
    `bitemporal_kg.json`, …), so a bare `*.json` glob does not identify sessions:
    `entities.json` is rewritten on any turn mentioning a proper noun and is
    therefore usually the newest `*.json` in the directory. Ranking it first made
    `ConversationMemory._load_latest_session()` "restore" a session that does not
    exist, silently dropping history across restarts on a default install — no
    flag involved. Candidates are now filtered by name and confirmed by payload
    shape (`agents.core.session_files`).
    """
    _memory_dir().mkdir(parents=True, exist_ok=True)
    sessions = []
    # Sort by nanosecond mtime (finer than float-seconds st_mtime) with the stem as
    # a deterministic tiebreak: when two sessions are written within one filesystem
    # mtime tick — common on Windows — a plain st_mtime sort ties them and the stable
    # sort keeps alphabetical (glob) order, restoring the OLDER session on restart.
    # On a tie, alphabetically-last wins, which matches "most recent" for both the
    # timestamp session names and sequentially-named ones.
    for f in sorted(
        _memory_dir().glob("*.json"),
        key=lambda p: (p.stat().st_mtime_ns, p.stem),
        reverse=True,
    ):
        sid = f.stem
        if sid in sessions or not is_session_stem(sid):
            continue
        # Confirm the payload before treating it as a session. Only reached for
        # name-plausible candidates, and the loop stops at 5, so this reads a
        # handful of small files at boot at most.
        if not looks_like_session_snapshot(f):
            continue
        sessions.append(sid)
        if len(sessions) == 5:
            break
    return sessions


def delete_memory(session_id: str):
    if not is_valid_session_id(session_id):
        logger.warning("refusing to delete memory for invalid session_id")
        return
    path = _memory_dir() / f"{session_id}.json"
    if path.exists():
        path.unlink()
        logger.info(f"Memory deleted: {path}")
