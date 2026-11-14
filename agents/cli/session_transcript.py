"""Strict CLI projection and create-only export of retained conversation text.

The hub supplies the redacted current history. This module neither loads local
session storage nor resumes a session.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from agents.core.validation import is_valid_session_id as valid_session_id

MAX_TRANSCRIPT_TURNS = 100
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024


def project_transcript(raw: Any, session_id: str) -> dict:
    """Validate required known fields and copy only the V64 public document."""
    invalid = "Invalid retained session transcript received from the hub"
    if (not valid_session_id(session_id) or not isinstance(raw, dict)
            or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1
            or raw.get("session_id") != session_id
            or raw.get("scope") != "retained_current_history"
            or raw.get("redacted") is not True
            or not isinstance(raw.get("turns"), list)
            or len(raw["turns"]) > MAX_TRANSCRIPT_TURNS
            or type(raw.get("turn_count")) is not int
            or raw["turn_count"] != len(raw["turns"])):
        raise ValueError(invalid)
    turns = []
    for turn in raw["turns"]:
        if (not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant")
                or not isinstance(turn.get("content"), str)
                or not isinstance(turn.get("timestamp"), str)
                or "agent_id" not in turn
                or not (turn["agent_id"] is None or isinstance(turn["agent_id"], str))):
            raise ValueError(invalid)
        if any(isinstance(turn[field], str) and len(turn[field]) > MAX_TRANSCRIPT_BYTES
               for field in ("content", "timestamp", "agent_id")):
            raise ValueError(invalid)
        turns.append({field: turn[field] for field in ("role", "content", "agent_id", "timestamp")})
    document = {"schema_version": 1, "session_id": session_id,
                "scope": "retained_current_history", "redacted": True,
                "turn_count": len(turns), "turns": turns}
    # Bound the compact UTF-8 projection, never untrusted unknown fields.
    _encode(document)
    return document


def _encode(document: dict) -> bytes:
    data = json.dumps(document, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_TRANSCRIPT_BYTES:
        raise ValueError("Invalid retained session transcript received from the hub")
    return data


def encode_transcript(raw: Any, session_id: str) -> bytes:
    return _encode(project_transcript(raw, session_id))


def write_transcript_file(path: str, data: bytes) -> None:
    """Publish a fully written owner-only file atomically without replacing a path.

    Hard-link support is required: a failure has no overwrite fallback. Temporary
    cleanup happens inside a private directory and never unlinks the destination.
    """
    if not callable(getattr(os, "fchmod", None)) or not callable(getattr(os, "link", None)):
        raise OSError("Secure retained transcript file export is unavailable")
    destination = Path(path)
    temporary = tempfile.TemporaryDirectory(prefix=".nerva-transcript-", dir=destination.parent)
    try:
        descriptor, source = tempfile.mkstemp(dir=temporary.name)
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(source, destination)
    finally:
        # A published file is complete even if its temporary link cannot be
        # cleaned up. Never remove the final path as part of recovery.
        with suppress(OSError):
            temporary.cleanup()
