"""
notes.py — H10.21 Conversation Notes.

A free-text (markdown) scratchpad attached to a session. Its content is injected
as **persistent context** into the agent on every turn of that session, and can
be rewritten in place by an AI ("Rewrite with AI"). JSON-persisted, keyed by
session id.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

DEFAULT_PATH = Path("memory_logs/notes.json")
MAX_LEN = 20000


class NotesStore:
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._notes: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._notes = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._notes = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._notes, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, session_id: str) -> str:
        with self._lock:
            return (self._notes.get(session_id) or {}).get("content", "")

    def set(self, session_id: str, content: str) -> dict:
        content = (content or "")[:MAX_LEN]
        with self._lock:
            self._notes[session_id] = {"content": content, "updated_at": time.time()}
            self._save()
            return dict(self._notes[session_id])

    def clear(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._notes:
                del self._notes[session_id]
                self._save()
                return True
            return False

    def context_for(self, session_id: str) -> str:
        """Render the session note as a context block, or '' if empty."""
        note = self.get(session_id).strip()
        return f"[Session notes]\n{note}\n\n" if note else ""
