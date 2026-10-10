import asyncio
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agents.core.paths import data_root

from .persistence import RewindPersistenceError, list_sessions, load_memory_snapshot, save_memory

logger = logging.getLogger("jarvis.memory.conversation")


class UnverifiedRewind(RuntimeError):
    """A rewound JSON snapshot needs its durable checkpoint head before use."""

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


class Turn:
    __slots__ = ("role", "content", "agent_id", "timestamp", "token_count", "tools", "media", "foreign_origin")

    def __init__(self, role: str, content: str, agent_id: str = None, token_count: int = 0,
                 tools: list[str] | None = None, media: dict | None = None,
                 foreign_origin: str | None = None):
        if foreign_origin is not None and foreign_origin not in {"claude", "codex"}:
            raise ValueError("invalid foreign origin")
        self.role = role
        self.content = content
        self.agent_id = agent_id
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.token_count = token_count
        # H441 — the tools a reply called (names only), so a recap can collapse them.
        self.tools = _tool_names(tools)
        self.media = validated_media(media) if media is not None else None
        self.foreign_origin = foreign_origin

    def to_dict(self):
        out = {
            "role": self.role,
            "content": self.content,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "token_count": self.token_count,
        }
        if self.tools:               # absent when none: older readers see the shape they know
            out["tools"] = list(self.tools)
        if self.media is not None:
            out["media"] = dict(self.media)
        if self.foreign_origin is not None:
            out["foreign_origin"] = self.foreign_origin
        return out


def _tool_names(value) -> list[str]:
    """A stored ``tools`` list as short names; anything else (an old or edited snapshot) is none."""
    if not isinstance(value, list):
        return []
    return [name.strip()[:64] for name in value[:200] if isinstance(name, str) and name.strip()]


_BACKEND_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def validated_media(value: object) -> dict:
    """Keep bounded image provenance in history; never keep image bytes there."""
    if not isinstance(value, dict) or set(value) != {"kind", "count", "model", "backend", "local"}:
        raise ValueError("invalid image provenance")
    count, model, backend, local = (value[key] for key in ("count", "model", "backend", "local"))
    if (value["kind"] != "image" or type(count) is not int or not 1 <= count <= 8
            or not isinstance(model, str) or not 0 < len(model) <= 512
            or any(ord(char) < 33 or ord(char) == 127 for char in model)
            or any(token in model.lower() for token in ("data:", "base64,", "authorization", "api_key"))
            or not isinstance(backend, str) or _BACKEND_ID.fullmatch(backend) is None
            or type(local) is not bool):
        raise ValueError("invalid image provenance")
    return {"kind": "image", "count": count, "model": model, "backend": backend, "local": local}


def restored_media(value: object) -> dict | None:
    try:
        return validated_media(value) if value is not None else None
    except ValueError:
        return None


class ConversationMemory:
    def __init__(self, max_turns: int = 100, persist: bool = True):
        from agents.core.llm.vision_history import ActiveImageHistory

        self.sessions: dict[str, list[Turn]] = {}
        self.instances: dict[str, str] = {}
        self.foreign_origins: dict[str, object] = {}
        self.revisions: dict[str, int] = {}
        self.rewound_sessions: set[str] = set()
        self.pending_rewinds: set[str] = set()
        self._rewind_checkpoint_mgr = None
        self.active_images = ActiveImageHistory()
        self._active_image_instances: dict[str, str] = {}
        self.max_turns = max_turns
        self.persist = persist
        self.current_session_id: Optional[str] = None
        self._dirty = set()
        self._lock = asyncio.Lock()

        if persist:
            self._load_latest_session()

    def _load_latest_session(self):
        sessions = list_sessions()
        if sessions:
            sid = sessions[0]
            snapshot = load_memory_snapshot(sid)
            turns_data = snapshot.get("turns")
            if snapshot.get("session_id") == sid and isinstance(turns_data, list):
                if isinstance(snapshot.get("foreign_history"), dict):
                    from ..foreign_history import Origin
                    self.foreign_origins[sid] = Origin(**snapshot["foreign_history"])
                if snapshot.get("instance_id"):
                    self.instances[sid] = snapshot["instance_id"]
                self.revisions[sid] = snapshot.get("revision", 0)
                if snapshot.get("rewound") is True:
                    self.pending_rewinds.add(sid)
                    return
                self.sessions[sid] = []
                for t in turns_data:
                    turn = Turn(t["role"], t["content"], t.get("agent_id"), t.get("token_count", 0),
                                tools=t.get("tools"), media=restored_media(t.get("media")),
                                foreign_origin=t.get("foreign_origin"))
                    turn.timestamp = t.get("timestamp") or turn.timestamp
                    self.sessions[sid].append(turn)
                self.current_session_id = sid
                logger.info(f"Restored session {sid} ({len(turns_data)} turns)")

    async def new_session(self, session_id: str = None) -> str:
        async with self._lock:
            sid = session_id or datetime.now(timezone.utc).strftime("session_%Y%m%d_%H%M%S")
            if sid in self.pending_rewinds:
                raise UnverifiedRewind("conversation rewind head unverified")
            if sid not in self.sessions:
                self.sessions[sid] = []
                self.revisions[sid] = 0
                logger.info(f"New session: {sid}")
            self.current_session_id = sid
            return sid

    def active_image_instance(self, session_id: str) -> str | None:
        """Separate process-local image history from any durable session ID reuse."""
        if session_id not in self.sessions:
            return None
        return self._active_image_instances.setdefault(session_id, secrets.token_urlsafe(24))

    def invalidate_active_images(self, session_id: str) -> None:
        self.active_images.clear(session_id)
        self._active_image_instances.pop(session_id, None)

    async def resume_session(self, session_id: str) -> bool:
        """Make a specific past session current, loading it from disk if needed.

        Unlike `_load_latest_session` (init-only, newest), this resumes any
        chosen session by id. Returns False if it has no in-memory or on-disk turns.
        """
        async with self._lock:
            if session_id in self.pending_rewinds:
                raise UnverifiedRewind("conversation rewind head unverified")
            if session_id not in self.sessions:
                self.invalidate_active_images(session_id)
                snapshot = load_memory_snapshot(session_id)
                turns_data = snapshot.get("turns")
                if snapshot.get("session_id") != session_id or not isinstance(turns_data, list):
                    return False
                if isinstance(snapshot.get("foreign_history"), dict):
                    from ..foreign_history import Origin
                    self.foreign_origins[session_id] = Origin(**snapshot["foreign_history"])
                if snapshot.get("instance_id"):
                    self.instances[session_id] = snapshot["instance_id"]
                if snapshot.get("rewound") is True:
                    self.pending_rewinds.add(session_id)
                    raise UnverifiedRewind("conversation rewind head unverified")
                self.sessions[session_id] = []
                self.revisions[session_id] = snapshot.get("revision", 0)
                for t in turns_data:
                    turn = Turn(t["role"], t["content"], t.get("agent_id"), t.get("token_count", 0),
                                tools=t.get("tools"), media=restored_media(t.get("media")),
                                foreign_origin=t.get("foreign_origin"))
                    turn.timestamp = t.get("timestamp") or turn.timestamp
                    self.sessions[session_id].append(turn)
                logger.info(f"Resumed session {session_id} ({len(turns_data)} turns)")
            self.current_session_id = session_id
            return True

    def restore_verified_rewind(self, session_id: str, snapshot: dict) -> None:
        """Only the bound manager calls this after validating the SQLite head."""
        marker = snapshot.get("foreign_history")
        if marker is not None:
            from ..foreign_history import Origin
            if not isinstance(marker, dict) or set(marker) != {"kind", "source", "instance_id"}:
                raise ValueError("invalid foreign rewind marker")
            self.foreign_origins[session_id] = Origin(**marker)
        else:
            self.foreign_origins.pop(session_id, None)
        rows = snapshot["turns"]
        restored = []
        for value in rows:
            turn = Turn(value["role"], value["content"], value.get("agent_id"),
                        value.get("token_count", 0), tools=value.get("tools"),
                        media=restored_media(value.get("media")), foreign_origin=value.get("foreign_origin"))
            turn.timestamp = value.get("timestamp") or turn.timestamp
            restored.append(turn)
        self.invalidate_active_images(session_id)
        self.sessions[session_id] = restored
        self.instances[session_id] = snapshot["instance_id"]
        self.revisions[session_id] = snapshot["revision"]
        self.rewound_sessions.add(session_id)
        self.pending_rewinds.discard(session_id)
        self.current_session_id = session_id

    async def add_turn(self, session_id: str, role: str, content: str, agent_id: str = None,
                       tools: list[str] | None = None, media: dict | None = None):
        async with self._lock:
            if session_id in self.pending_rewinds:
                raise UnverifiedRewind("conversation rewind head unverified")
            if session_id not in self.sessions:
                self.sessions[session_id] = []
            prior_turns = list(self.sessions[session_id])
            prior_revision = self.revisions.get(session_id, 0)
            was_dirty = session_id in self._dirty
            turn = Turn(role, content, agent_id, token_count=len(content) // 4,
                        tools=tools, media=media)
            self.sessions[session_id].append(turn)
            if len(self.sessions[session_id]) > self.max_turns:
                self.sessions[session_id].pop(0)
            self.revisions[session_id] = self.revisions.get(session_id, 0) + 1
            self._dirty.add(session_id)
            if self.persist:
                # AUD-7 / F9: both the append-log and the full-snapshot write are
                # blocking disk I/O. On the SSE hot path that would stall the event
                # loop (the snapshot rewrites the whole session every turn). Build the
                # JSON-able data here (cheap, under the lock so it can't tear) and do
                # the actual writes in a worker thread so streaming is never blocked.
                turn_dict = turn.to_dict()
                turns_data = [t.to_dict() for t in self.sessions[session_id]]
                try:
                    await asyncio.to_thread(self._persist_turn, session_id, turn_dict, turns_data,
                                            self.instances.get(session_id), self.revisions[session_id],
                                            session_id in self.rewound_sessions)
                except Exception:
                    self.sessions[session_id] = prior_turns
                    self.revisions[session_id] = prior_revision
                    if not was_dirty:
                        self._dirty.discard(session_id)
                    raise

    def _persist_turn(self, session_id: str, turn_dict: dict, turns_data: list[dict],
                      instance_id: str | None = None, revision: int | None = None,
                      require_rewind: bool = False):
        """Blocking persistence, run off the event loop (see add_turn). Per-turn
        durability is unchanged: the snapshot is still written every turn — only the
        thread it runs on differs."""
        self._append_log_dict(session_id, turn_dict)
        try:
            if instance_id:
                save_memory(session_id, turns_data, instance_id=instance_id, revision=revision,
                            checkpoint_mgr=self._rewind_checkpoint_mgr,
                            require_rewind=require_rewind,
                            foreign_origin=self.foreign_origins.get(session_id))
            else:
                save_memory(session_id, turns_data, revision=revision,
                            checkpoint_mgr=self._rewind_checkpoint_mgr,
                            require_rewind=require_rewind,
                            foreign_origin=self.foreign_origins.get(session_id))
        except RewindPersistenceError:
            raise
        except Exception as e:
            if session_id in self.foreign_origins:
                raise RewindPersistenceError("foreign conversation append not persisted") from e
            logger.warning(f"Snapshot save failed: {e}")

    def _save_snapshot(self, session_id: str):
        """Full JSON save of the session (kept for direct/synchronous callers)."""
        try:
            turns_data = [t.to_dict() for t in self.sessions.get(session_id, [])]
            instance_id = self.instances.get(session_id)
            if instance_id:
                save_memory(session_id, turns_data, instance_id=instance_id,
                            revision=self.revisions.get(session_id, 0),
                            checkpoint_mgr=self._rewind_checkpoint_mgr,
                            require_rewind=session_id in self.rewound_sessions,
                            foreign_origin=self.foreign_origins.get(session_id))
            else:
                save_memory(session_id, turns_data, revision=self.revisions.get(session_id, 0),
                            checkpoint_mgr=self._rewind_checkpoint_mgr,
                            require_rewind=session_id in self.rewound_sessions,
                            foreign_origin=self.foreign_origins.get(session_id))
        except RewindPersistenceError:
            raise
        except Exception as e:
            logger.warning(f"Snapshot save failed: {e}")

    async def get_history(self, session_id: str, last_n: int = None) -> list[dict]:
        async with self._lock:
            if session_id in self.pending_rewinds:
                raise UnverifiedRewind("conversation rewind head unverified")
            turns = self.sessions.get(session_id, [])
            if last_n is not None:
                turns = turns[-last_n:] if last_n > 0 else []
            return [t.to_dict() for t in turns]

    async def get_context(self, session_id: str, last_n: int = 10) -> str:
        turns = await self.get_history(session_id, last_n)
        if not turns:
            return ""
        from ..foreign_history import render_turn
        tainted = session_id in self.foreign_origins
        lines = []
        for t in turns:
            lines.append(render_turn(t, tainted=tainted))
        return "\n".join(lines)

    async def clear(self, session_id: str = None):
        async with self._lock:
            if session_id:
                self.invalidate_active_images(session_id)
                self.sessions.pop(session_id, None)
                self.instances.pop(session_id, None)
                self.foreign_origins.pop(session_id, None)
                self.revisions.pop(session_id, None)
                self.rewound_sessions.discard(session_id)
                self.pending_rewinds.discard(session_id)
            else:
                self.active_images.clear()
                self._active_image_instances.clear()
                self.sessions.clear()
                self.instances.clear()
                self.foreign_origins.clear()
                self.revisions.clear()
                self.rewound_sessions.clear()
                self.pending_rewinds.clear()

    def _append_log(self, session_id: str, turn: Turn):
        self._append_log_dict(session_id, turn.to_dict())

    def _append_log_dict(self, session_id: str, turn_dict: dict):
        try:
            _memory_dir().mkdir(parents=True, exist_ok=True)
            log_path = _memory_dir() / f"{session_id}.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn_dict, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to persist turn: {e}")
