"""
notes.py — H10.21 Conversation Notes.

A free-text (markdown) scratchpad attached to a session. Its content is injected
as **persistent context** into the agent on every turn of that session, and can
be rewritten in place by an AI ("Rewrite with AI"). JSON-persisted, keyed by
session id.
"""

from __future__ import annotations

import time
from pathlib import Path
from .persistence import JsonStore

from .config import NOTES_MAX_LEN as MAX_LEN  # Q4: centralized limit

DEFAULT_PATH = Path("memory_logs/notes.json")


class NotesStore(JsonStore):
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._notes

    def _deserialize(self, raw) -> None:
        self._notes = raw if isinstance(raw, dict) else {}

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
