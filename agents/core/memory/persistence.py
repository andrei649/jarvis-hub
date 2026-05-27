"""
persistence.py — Memory persistence: saves/loads conversation history across restarts.
"""

import json
import logging
from pathlib import Path

MEMORY_DIR = Path("memory_logs")

logger = logging.getLogger("jarvis.persistence")


def save_memory(session_id: str, turns: list[dict]):
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / f"{session_id}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"session_id": session_id, "turns": turns}, f, ensure_ascii=False, indent=2)
        logger.info(f"Memory saved: {path} ({len(turns)} turns)")
    except Exception as e:
        logger.warning(f"Failed to save memory: {e}")


def load_memory(session_id: str) -> list[dict]:
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
    for f in sorted(MEMORY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        sid = f.stem
        if sid not in sessions:
            sessions.append(sid)
    return sessions[:5]


def delete_memory(session_id: str):
    path = MEMORY_DIR / f"{session_id}.json"
    if path.exists():
        path.unlink()
        logger.info(f"Memory deleted: {path}")
