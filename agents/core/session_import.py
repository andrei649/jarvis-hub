"""Strict, owner-attested foreign conversation seed in one SQLite transaction."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime

from .foreign_history import MARKER, SOURCES, ForeignHistoryRefused, status
from .session_continuation import seed_json


def _canonical(source: str, turns: list[dict]) -> str:
    if source not in SOURCES or not isinstance(turns, list) or not 0 < len(turns) <= 100:
        raise ForeignHistoryRefused("invalid_import", 422)
    prepared = []
    for value in turns:
        if not isinstance(value, dict) or value.get("role") not in {"user", "assistant"}:
            raise ForeignHistoryRefused("invalid_import", 422)
        content, timestamp = value.get("content"), value.get("timestamp")
        if not isinstance(content, str) or not 0 < len(content) <= 32768 or not isinstance(timestamp, str):
            raise ForeignHistoryRefused("invalid_import", 422)
        try:
            if datetime.fromisoformat(timestamp).tzinfo is None:
                raise ValueError
        except ValueError as exc:
            raise ForeignHistoryRefused("invalid_import", 422) from exc
        names = value.get("tools", [])
        if (not isinstance(names, list) or len(names) > 20
                or any(not isinstance(name, str) or not 0 < len(name) <= 64 for name in names)):
            raise ForeignHistoryRefused("invalid_import", 422)
        turn = {"role": value["role"], "content": content,
                "agent_id": None, "timestamp": timestamp, "token_count": len(content) // 4,
                "foreign_origin": source}
        if names:
            turn["tools"] = names
        prepared.append(turn)
    try:
        return seed_json(prepared)
    except Exception as exc:
        raise ForeignHistoryRefused("invalid_import", 422) from exc


def import_turns(checkpoints, *, source: str, external_id: str, turns: list[dict],
                 request_id: str, source_sha256: str | None = None) -> dict:
    """Commit record, identity, clock and immutable seed together; replay after lost replies."""
    try:
        if (not isinstance(external_id, str) or not 0 < len(external_id) <= 128
                or str(uuid.UUID(request_id)) != request_id):
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise ForeignHistoryRefused("invalid_import", 422) from exc
    value = _canonical(source, turns)
    digest = hashlib.sha256(value.encode()).hexdigest()
    if source_sha256 is not None and (not isinstance(source_sha256, str)
                                      or len(source_sha256) != 64
                                      or any(char not in "0123456789abcdef" for char in source_sha256)):
        raise ForeignHistoryRefused("invalid_import", 422)
    conn = getattr(checkpoints, "_conn", None)
    if conn is None:
        raise ForeignHistoryRefused()
    try:
        with checkpoints._lock, conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT session_id,source,external_id,content_sha256 FROM session_imports WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if existing is None:
                existing = conn.execute(
                    "SELECT session_id,source,external_id,content_sha256 FROM session_imports "
                    "WHERE source=? AND external_id=? AND content_sha256=?",
                    (source, external_id, digest),
                ).fetchone()
            if existing is not None:
                if existing[1:] != (source, external_id, digest):
                    raise ForeignHistoryRefused("request_id_conflict", 409)
                sid = existing[0]
            else:
                sid, instance, now = ("session_" + uuid.uuid4().hex,
                                      uuid.uuid4().hex, datetime.now(UTC).isoformat())
                metadata = json.dumps({MARKER: {"kind": "imported", "source": source,
                                                "instance_id": instance}}, separators=(",", ":"))
                conn.execute(
                    "INSERT INTO sessions(id,started_at,turn_count,metadata,instance_id) VALUES(?,?,?,?,?)",
                    (sid, now, len(turns), metadata, instance),
                )
                conn.execute(
                    "INSERT INTO session_clock(session_id,birth_at,revision,rebuilt_at,instance_id) "
                    "VALUES(?,?,0,?,?)", (sid, now, now, instance),
                )
                conn.execute(
                    "INSERT INTO session_imports(session_id,instance_id,kind,source,external_id,content_sha256,"
                    "source_sha256,request_id,seed_json,seed_sha256,parent_id,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, instance, "imported", source, external_id, digest,
                     source_sha256 or digest, request_id, value, digest, None, now),
                )
                changed = conn.execute(
                    "UPDATE session_history_instances SET foreign_lineage=1 "
                    "WHERE session_id=? AND instance_id=?", (sid, instance),
                )
                if changed.rowcount != 1:
                    raise ForeignHistoryRefused("import_identity_changed")
        origin = status(checkpoints, sid)
        if origin.kind != "imported":
            raise ForeignHistoryRefused()
        return {"session_id": sid, "source": source, "external_id": external_id,
                "content_sha256": digest, "turn_count": len(turns)}
    except sqlite3.Error as exc:
        raise ForeignHistoryRefused() from exc
