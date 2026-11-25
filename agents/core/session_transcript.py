"""Owner-only projection of the exact session's retained conversation text.

This is neither the compacted archive nor the opt-in training trajectory store.
Loading uses the existing identity/import/rewind fences and never resumes a session.
"""

import asyncio
import hashlib
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


def _revision(identity_value, session_id, row):
    material = [identity_value[0].isoformat(), identity_value[1], session_id,
                row["turn"], row["role"], row["timestamp"], row["agent_id"], row["content"]]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


async def read_transcript(orch, session_id, *, references=False):
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
        eligible = []
        ineligible = False
        if references:
            from .foreign_history import status_locked
            with cp._lock:
                ineligible = status_locked(cp._conn, session_id).tainted
        for turn, row in enumerate(history):
            if not isinstance(row, dict) or row.get("role") not in {"user", "assistant", "system"}:
                raise ContinuationRefused("invalid_history")
            if row["role"] == "system":
                continue
            if references and (row.get("media") or row.get("foreign_origin") or row.get("history_source")):
                ineligible = True
            content, agent, timestamp = row.get("content"), row.get("agent_id"), row.get("timestamp")
            if (not isinstance(content, str) or not isinstance(timestamp, str)
                    or (agent is not None and not isinstance(agent, str))):
                raise ContinuationRefused("invalid_history")
            turns.append({"turn": turn, "role": row["role"], "content": content,
                          "agent_id": agent, "timestamp": timestamp})
            eligible.append(not ineligible)
        document = {"schema_version": 1, "session_id": session_id,
                    "scope": "retained_current_history", "redacted": True,
                    "turn_count": len(turns), "turns": turns}
        # Refuse a large projection before running the scanner, and again after it.
        _encode(document)
        scanner = SecretScanner()
        for row, can_reference in zip(turns, eligible, strict=True):
            for field in ("content", "agent_id", "timestamp"):
                if row[field] is not None:
                    value = scanner.redact(row[field])
                    if not isinstance(value, str):
                        raise RuntimeError("transcript redaction unavailable")
                    row[field] = value
            if references and can_reference:
                row["reference_revision"] = _revision(expected, session_id, row)
        raw = _encode(document)
        with cp._lock:
            if identity(cp._conn, session_id) != expected:
                raise ContinuationRefused("history_identity_changed")
        return raw


async def resolve_history_reference(orch, reference):
    """Verify a reviewed, native source and return data for the fenced chat attachment."""
    from .security.quarantine import detect_injection_normalized

    document = json.loads(await read_transcript(orch, reference.session_id, references=True))
    row = next((row for row in document["turns"] if row["turn"] == reference.turn), None)
    if row is None or row.get("reference_revision") != reference.revision:
        raise ContinuationRefused("history_source_changed", 409)
    if detect_injection_normalized(row["content"]):
        raise ContinuationRefused("history_source_untrusted", 409)
    if reference.excerpt not in row["content"]:
        raise ContinuationRefused("history_excerpt_changed", 409)
    trust = getattr(orch, "session_trust", None)
    if callable(trust) and await asyncio.to_thread(trust, reference.session_id) == "unclean":
        raise ContinuationRefused("history_source_untrusted", 409)
    citation = {"session_id": reference.session_id, "message": row["turn"] + 1,
                "role": row["role"], "agent_id": row["agent_id"], "timestamp": row["timestamp"]}
    return {"name": f"History {reference.session_id} #{row['turn'] + 1}",
            "text": f"Source: {json.dumps(citation, ensure_ascii=False)}\n\n{reference.excerpt}"}, {
                "session_id": reference.session_id, "turn": row["turn"],
                "revision": reference.revision, "role": row["role"]}
