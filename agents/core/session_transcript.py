"""Owner-only projection of the exact session's retained conversation text.

This is neither the compacted archive nor the opt-in training trajectory store.
Loading uses the existing identity/import/rewind fences and never resumes a session.
"""

import json

from .memory.manager import RewindRefused
from .security.scanner import SecretScanner
from .session_continuation import (
    MAX_TURNS,
    ContinuationRefused,
    identity,
    prepare_session,
)
from .validation import is_valid_session_id

MAX_TRANSCRIPT_TURNS = MAX_TURNS
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024


def _encode(document):
    raw = json.dumps(document, ensure_ascii=False, allow_nan=False,
                     separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_TRANSCRIPT_BYTES:
        raise ContinuationRefused("transcript_too_large", 413)
    return raw


async def read_transcript(orch, session_id):
    """Return bounded UTF-8 JSON while holding the addressed session's turn lease."""
    if not is_valid_session_id(session_id):
        raise ContinuationRefused("invalid_identifier", 422)
    async with orch.turn_lease(session_id) as acquired:
        if not acquired:
            raise ContinuationRefused("source_busy")
        cp = orch.checkpoints
        if cp._conn is None:
            raise ContinuationRefused("continuation_unavailable", 503)
        with cp._lock:
            expected = identity(cp._conn, session_id)
            if expected is None:
                raise ContinuationRefused("session_not_found", 404)
        try:
            # Cold rewind snapshots are quarantined by ConversationMemory until the
            # manager verifies their durable head. Restore through that protocol
            # before prepare_session sees a cached copy, preserving active selection.
            async with orch.memory._lock:
                orch.memory._ensure_rewind_ready(session_id, activate=False)
            await prepare_session(orch, session_id)
            history = await orch.memory.get_history(session_id)
        except RewindRefused as exc:
            raise ContinuationRefused("invalid_history") from exc
        with cp._lock:
            if identity(cp._conn, session_id) != expected:
                raise ContinuationRefused("history_identity_changed")
        if not isinstance(history, list):
            raise ContinuationRefused("invalid_history")
        if len(history) > MAX_TRANSCRIPT_TURNS:
            raise ContinuationRefused("transcript_too_large", 413)
        turns = []
        for row in history:
            if not isinstance(row, dict) or row.get("role") not in {"user", "assistant", "system"}:
                raise ContinuationRefused("invalid_history")
            if row["role"] == "system":
                continue
            content, agent, timestamp = row.get("content"), row.get("agent_id"), row.get("timestamp")
            if (not isinstance(content, str) or not isinstance(timestamp, str)
                    or (agent is not None and not isinstance(agent, str))):
                raise ContinuationRefused("invalid_history")
            turns.append({"role": row["role"], "content": content,
                          "agent_id": agent, "timestamp": timestamp})
        document = {"schema_version": 1, "session_id": session_id,
                    "scope": "retained_current_history", "redacted": True,
                    "turn_count": len(turns), "turns": turns}
        # Refuse a large projection before running the scanner, and again after it.
        _encode(document)
        scanner = SecretScanner()
        for row in turns:
            for field in ("content", "agent_id", "timestamp"):
                if row[field] is not None:
                    value = scanner.redact(row[field])
                    if not isinstance(value, str):
                        raise RuntimeError("transcript redaction unavailable")
                    row[field] = value
        raw = _encode(document)
        with cp._lock:
            if identity(cp._conn, session_id) != expected:
                raise ContinuationRefused("history_identity_changed")
        return raw
