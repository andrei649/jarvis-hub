"""H386 — Session-stable tiered system prompt assembly, memoization, and cache boundary.

System prompts are structured into three ordered tiers so local KV caches
(llama.cpp / Ollama / LM Studio) and cloud prefix caches (Anthropic, OpenAI,
Gemini, DeepSeek) keep their prefix warm across turns, midnight clock rebuilds,
and context-compaction skill pruning:

  1. ``stable``   — Shared identity contract, environment hint, sanitized SOUL,
                    and static model/surface/toolset operating guidance.
  2. ``context``  — Session-frozen context (e.g. ``Conversation started: ...``),
                    invariant for the lifetime of one session.
  3. ``volatile`` — Per-rebuild / per-fold tail lines (cross-midnight
                    ``Today's date (as of the last context rebuild): ...`` and
                    compaction ``[Skills pruned during compression ...]`` notices).

``TieredSystemPrompt`` subclasses ``OperatingPrompt`` (``str``) so all existing
string callers remain byte-compatible while Anthropic's dialect adapter can emit
``[prefix_with_cache_control, uncached_volatile_tail]`` blocks.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import data_path

_CLOCK_TAIL_RE = re.compile(
    r"(?:\n\n|^)(Conversation started: [A-Za-z]+, [A-Za-z]+ \d{2}, \d{4} \([^\n]+\))"
    r"(?:\n\n?(Today's date \(as of the last context rebuild\): [^\n]+))?\Z"
)

MAX_MEMO_ENTRIES = 256
MAX_PERSISTED_SESSIONS = 1024


def strip_clock_lines(text: str) -> tuple[str, str, str]:
    """Split trailing H671 clock lines from *text* -> ``(body, start_line, today_line)``."""
    if not text:
        return "", "", ""
    match = _CLOCK_TAIL_RE.search(text)
    if match is None:
        return text, "", ""
    body = text[: match.start()]
    start_line = match.group(1) or ""
    today_line = match.group(2) or ""
    return body, start_line, today_line


def split_pruned_notice(text: str) -> tuple[str, str]:
    """Split a trailing H389 pruned-skill notice -> ``(without_notice, notice)``."""
    from .skills.tools import (
        PRUNED_DATA_NOTICE_HEADER,
        PRUNED_NOTICE_END,
        PRUNED_NOTICE_HEADER,
    )

    if not text or not text.endswith(PRUNED_NOTICE_END):
        return text, ""
    idx = max(text.rfind(PRUNED_NOTICE_HEADER), text.rfind(PRUNED_DATA_NOTICE_HEADER))
    if idx < 0:
        return text, ""
    notice = text[idx:]
    cut = idx - 2 if idx >= 2 and text[idx - 2 : idx] == "\n\n" else idx
    return text[:cut], notice


def split_system_cache_boundary(system: str) -> tuple[str, str]:
    """Split a rendered system prompt into ``(cacheable_prefix, volatile_tail)``.

    Works both on ``TieredSystemPrompt`` instances and on plain strings after
    JSON/profile message preparation:
    - ``stable`` + ``context`` (including ``Conversation started: ...``) stay in
      the cached prefix because they never change within a session.
    - Cross-midnight ``Today's date (as of the last context rebuild): ...`` and
      compaction ``[Skills pruned ...]`` notices move into ``volatile_tail`` so
      changing them never invalidates the cached prefix block.
    """
    raw = str(system or "")
    if not raw:
        return "", ""
    from .operating_prompt import TieredSystemPrompt

    if isinstance(system, TieredSystemPrompt):
        prefix = system.prefix_block
        volatile = system.volatile_block
        if prefix:
            return prefix, volatile
        return raw, ""

    without_notice, notice = split_pruned_notice(raw)
    body, start_line, today_line = strip_clock_lines(without_notice)
    prefix_parts = [part for part in (body, start_line) if part]
    prefix = "\n\n".join(prefix_parts)
    volatile_parts: list[str] = []
    if today_line:
        volatile_parts.append(today_line)
    if notice:
        volatile_parts.append(notice)
    volatile = "\n\n".join(volatile_parts)
    if not prefix:
        return raw, ""
    return prefix, volatile


def runtime_identity_digest(
    *,
    agent_id: str,
    base_authority: str,
    model: str,
    provider: str = "",
    surface: str = "",
    offered_tools: tuple[str, ...] = (),
    guidance_signature: str = "",
) -> str:
    """Deterministic SHA-256 over every runtime input that governs the stable tier."""
    payload = json.dumps(
        {
            "v": 1,
            "agent_id": str(agent_id or ""),
            "base_sha256": hashlib.sha256((base_authority or "").encode("utf-8")).hexdigest(),
            "model": str(model or ""),
            "provider": str(provider or ""),
            "surface": str(surface or ""),
            "tools": list(offered_tools),
            "guidance_sig": str(guidance_signature or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PromptTiers:
    """Three ordered system-prompt tiers before string rendering."""

    stable: str
    context: str = ""
    volatile: str = ""
    identity_digest: str = ""

    @property
    def prefix_block(self) -> str:
        return "\n\n".join(part for part in (self.stable, self.context) if part)

    @property
    def rendered(self) -> str:
        return "\n\n".join(part for part in (self.stable, self.context, self.volatile) if part)

    def blocks(self) -> list[str]:
        prefix = self.prefix_block
        if prefix and self.volatile:
            return [prefix, self.volatile]
        full = self.rendered
        return [full] if full else []


class SystemPromptMemo:
    """Bounded thread-safe LRU memo for stable-tier operating prompt assembly."""

    def __init__(self, max_entries: int = MAX_MEMO_ENTRIES) -> None:
        self._max = max(8, int(max_entries))
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[str, str], str] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, agent_id: str, digest: str) -> str | None:
        key = (str(agent_id or ""), str(digest or ""))
        with self._lock:
            value = self._entries.get(key)
            if value is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return value

    def put(self, agent_id: str, digest: str, stable_text: str) -> None:
        key = (str(agent_id or ""), str(digest or ""))
        with self._lock:
            self._entries[key] = stable_text
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def invalidate(self, agent_id: str | None = None) -> int:
        """Drop cached stable tiers (all, or only *agent_id*'s)."""
        with self._lock:
            if agent_id is None:
                removed = len(self._entries)
                self._entries.clear()
                return removed
            target = str(agent_id)
            keys = [k for k in self._entries if k[0] == target]
            for k in keys:
                del self._entries[k]
            return len(keys)


PROMPT_MEMO = SystemPromptMemo()


class SessionPromptStore:
    """SQLite-backed byte-exact persistence & verification of ``[stable, context]`` per session.

    Restores a persisted prefix ONLY when the caller's live ``identity_digest`` matches
    what was recorded for ``(session_id, agent_id)``. Any change in SOUL, shared identity
    contract, model, surface, or offered toolset produces a different digest and refuses
    stale restoration automatically.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path is not None else data_path("memory", "prompt_tiers.db")
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS session_prompt_tiers (
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    identity_digest TEXT NOT NULL,
                    stable_text TEXT NOT NULL,
                    context_text TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (session_id, agent_id)
                )"""
            )
            conn.commit()
            self._conn = conn
        return self._conn

    def save(self, session_id: str, agent_id: str, *, model: str, tiers: PromptTiers) -> None:
        if not session_id or not agent_id or not tiers.identity_digest:
            return
        now = time.time()
        with self._lock:
            conn = self._connection()
            conn.execute(
                """INSERT INTO session_prompt_tiers
                   (session_id, agent_id, model, identity_digest, stable_text, context_text, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id, agent_id) DO UPDATE SET
                     model = excluded.model,
                     identity_digest = excluded.identity_digest,
                     stable_text = excluded.stable_text,
                     context_text = excluded.context_text,
                     updated_at = excluded.updated_at""",
                (str(session_id)[:128], str(agent_id)[:80], str(model or "")[:256],
                 tiers.identity_digest, tiers.stable, tiers.context, now),
            )
            count = conn.execute("SELECT COUNT(*) FROM session_prompt_tiers").fetchone()[0]
            if count > MAX_PERSISTED_SESSIONS:
                excess = count - MAX_PERSISTED_SESSIONS
                conn.execute(
                    """DELETE FROM session_prompt_tiers WHERE rowid IN (
                        SELECT rowid FROM session_prompt_tiers ORDER BY updated_at ASC LIMIT ?
                    )""",
                    (excess,),
                )
            conn.commit()

    def restore(
        self,
        session_id: str,
        agent_id: str,
        *,
        expected_digest: str,
        volatile: str = "",
    ) -> PromptTiers | None:
        """Restore byte-exact ``PromptTiers`` when ``identity_digest`` matches; else ``None``."""
        if not session_id or not agent_id or not expected_digest:
            return None
        with self._lock:
            conn = self._connection()
            row = conn.execute(
                """SELECT identity_digest, stable_text, context_text
                   FROM session_prompt_tiers WHERE session_id = ? AND agent_id = ?""",
                (str(session_id)[:128], str(agent_id)[:80]),
            ).fetchone()
        if row is None or row["identity_digest"] != expected_digest:
            return None
        return PromptTiers(
            stable=row["stable_text"],
            context=row["context_text"],
            volatile=volatile,
            identity_digest=expected_digest,
        )

    def invalidate_session(self, session_id: str, agent_id: str | None = None) -> int:
        if not session_id:
            return 0
        with self._lock:
            conn = self._connection()
            if agent_id is None:
                cur = conn.execute("DELETE FROM session_prompt_tiers WHERE session_id = ?", (str(session_id)[:128],))
            else:
                cur = conn.execute(
                    "DELETE FROM session_prompt_tiers WHERE session_id = ? AND agent_id = ?",
                    (str(session_id)[:128], str(agent_id)[:80]),
                )
            conn.commit()
            return int(cur.rowcount or 0)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


def guidance_signature_from(
    *,
    enabled: Mapping[str, Any] | None,
    environment: Mapping[str, Any] | None,
    platform_overrides: Mapping[str, Any] | None,
    profile: Any,
    steer_available: bool,
    kanban_task: str | None,
    coding: str,
) -> str:
    """Canonical digest of dynamic guidance inputs so live flag edits invalidate immediately."""
    blob = json.dumps(
        {
            "enabled": dict(enabled) if isinstance(enabled, Mapping) else enabled,
            "environment": dict(environment) if isinstance(environment, Mapping) else environment,
            "platform_overrides": dict(platform_overrides) if isinstance(platform_overrides, Mapping) else platform_overrides,
            "profile": profile,
            "steer": bool(steer_available),
            "kanban": kanban_task or "",
            "coding_sha": hashlib.sha256((coding or "").encode("utf-8")).hexdigest() if coding else "",
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
