"""
rooms.py — H10.20 Chat Channels / Rooms.

Themed chat rooms (per project/context). Each room carries its own context
(injected into every turn) and a roster of agents; inside a room you can
``@mention`` a specific agent to route the turn to it. Routing goes through the
full orchestrator pipeline (tools, RAG, filters) — same as the main chat.
JSON-persisted, with a bounded per-room history.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path("memory_logs/rooms.json")
_HISTORY_CAP = 200
_MENTION = re.compile(r"@([A-Za-z0-9_\-]+)")


class RoomStore:
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._rooms: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._rooms = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._rooms = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._rooms, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(self, name: str, description: str = "", agents: Optional[list] = None,
               default_agent: str = "jarvis") -> dict:
        room_id = uuid.uuid4().hex[:12]
        room = {
            "id": room_id,
            "name": name or "room",
            "description": description or "",
            "agents": list(agents or []),
            "default_agent": default_agent or "jarvis",
            "history": [],
            "created_at": time.time(),
        }
        with self._lock:
            self._rooms[room_id] = room
            self._save()
        return self._public(room)

    def get(self, room_id: str) -> Optional[dict]:
        with self._lock:
            room = self._rooms.get(room_id)
            return self._public(room) if room else None

    def list(self) -> list[dict]:
        with self._lock:
            rooms = [self._public(r) for r in self._rooms.values()]
        rooms.sort(key=lambda r: r["created_at"], reverse=True)
        return rooms

    def delete(self, room_id: str) -> bool:
        with self._lock:
            if room_id in self._rooms:
                del self._rooms[room_id]
                self._save()
                return True
            return False

    @staticmethod
    def _public(room: dict) -> dict:
        return {k: v for k, v in room.items() if k != "history"}

    # ── messages ─────────────────────────────────────────────────────────────

    def add_message(self, room_id: str, role: str, text: str, agent: str = "") -> Optional[dict]:
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            msg = {"role": role, "agent": agent, "text": text, "ts": time.time()}
            room["history"].append(msg)
            room["history"] = room["history"][-_HISTORY_CAP:]
            self._save()
            return dict(msg)

    def history(self, room_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return []
            return list(room["history"])[-max(1, limit):]

    # ── routing helpers ──────────────────────────────────────────────────────

    @staticmethod
    def parse_mentions(text: str) -> list[str]:
        """Extract @mentioned agent names in order, de-duplicated."""
        seen, out = set(), []
        for m in _MENTION.findall(text or ""):
            low = m.lower()
            if low not in seen:
                seen.add(low)
                out.append(low)
        return out

    def route(self, room_id: str, text: str) -> Optional[str]:
        """Pick the target agent for a turn: first @mention in the room roster,
        else the room's default agent."""
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            roster = {a.lower() for a in room["agents"]}
            for name in self.parse_mentions(text):
                if not roster or name in roster:
                    return name
            return room["default_agent"]

    def context_for(self, room_id: str) -> str:
        room = self.get(room_id)
        if not room or not room["description"].strip():
            return ""
        return f"[Room: {room['name']}]\n{room['description']}\n\n"
