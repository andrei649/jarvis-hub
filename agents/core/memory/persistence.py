"""
persistence.py — Memory persistence: saves/loads conversation history across restarts.
"""

import json
import logging

from agents.core.paths import data_root
from agents.core.validation import is_valid_session_id

MEMORY_DIR = data_root()

logger = logging.getLogger("jarvis.persistence")


def save_memory(session_id: str, turns: list[dict]):
    # AUD-5: never let an id that isn't an inert identifier reach the path — a
    # second line of defense behind the router validation, so any internal caller
    # is protected too.
    if not is_valid_session_id(session_id):
        logger.warning("refusing to save memory for invalid session_id")
        return
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / f"{session_id}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"session_id": session_id, "turns": turns}, f, ensure_ascii=False, indent=2)
        logger.info(f"Memory saved: {path} ({len(turns)} turns)")
    except Exception as e:
        logger.warning(f"Failed to save memory: {e}")


def load_memory(session_id: str) -> list[dict]:
    if not is_valid_session_id(session_id):
        logger.warning("refusing to load memory for invalid session_id")
        return []
    path = MEMORY_DIR / f"{session_id}.json"
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
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    sessions = []
    # Sort by nanosecond mtime (finer than float-seconds st_mtime) with the stem as
    # a deterministic tiebreak: when two sessions are written within one filesystem
    # mtime tick — common on Windows — a plain st_mtime sort ties them and the stable
    # sort keeps alphabetical (glob) order, restoring the OLDER session on restart.
    # On a tie, alphabetically-last wins, which matches "most recent" for both the
    # timestamp session names and sequentially-named ones.
    for f in sorted(
        MEMORY_DIR.glob("*.json"),
        key=lambda p: (p.stat().st_mtime_ns, p.stem),
        reverse=True,
    ):
        sid = f.stem
        if sid not in sessions:
            sessions.append(sid)
    return sessions[:5]


def delete_memory(session_id: str):
    if not is_valid_session_id(session_id):
        logger.warning("refusing to delete memory for invalid session_id")
        return
    path = MEMORY_DIR / f"{session_id}.json"
    if path.exists():
        path.unlink()
        logger.info(f"Memory deleted: {path}")
