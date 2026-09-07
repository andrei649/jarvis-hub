"""session_search.py — the model searches what was actually said (Hermes absorption 3a).

Recall is rich over *derived* facts — entities, the bitemporal graph, episodes — and had
nothing over the raw transcripts: "what did we decide about the dentist" had no tool to
answer it. This is a bounded, read-only, local scan of the session snapshots
``save_memory`` writes (``<sid>.json`` in the data root), offered to the tool loop as
``session_search``.

Containment, in the same spirit as the file tools:

* only files ``session_files`` recognises as sessions are read (name rule *and* payload
  rule), inside the data root, newest first, at most :data:`MAX_SESSIONS` of them and none
  over :data:`MAX_SNAPSHOT_BYTES`;
* every hit is a bounded snippet, never the turn; a query is keywords that must all
  appear in one turn, never a regex (Python's ``re`` has no time bound);
* retrieved text is untrusted — a turn that trips the injection scanner is redacted the
  way ``rag_tool._sanitize_hit`` redacts a memory hit, says so, and raises the turn's
  recall taint (``recall_taint.mark_turn_recall_tainted``) so an action the model
  proposes after reading it is queued for approval rather than auto-executed;
* the scan has a wall-clock deadline and reports ``truncated`` when any cap stopped it.

Ungated: it reads what the owner already can (``nerva sessions``, the HUD) and nothing
else. Who may *ask* is the tool profile's decision (wave 3b), not this module's.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents.core.memory.persistence import memory_dir
from agents.core.security.quarantine import detect_injection
from agents.core.security.rag_guard import REDACTION
from agents.core.security.recall_taint import mark_turn_recall_tainted
from agents.core.session_files import is_session_snapshot_payload, is_session_stem
from agents.core.tool_rpc import ToolRPCValidationError
from agents.core.validation import is_valid_session_id

logger = logging.getLogger("jarvis.session_search")

TOOL_NAME = "session_search"
CAPABILITY_ID = "tool:session_search"
MAX_QUERY_CHARS = 256
MAX_TERMS = 8
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_SESSIONS = 200
MAX_SNAPSHOT_BYTES = 8_000_000
MAX_TURN_CHARS = 20_000
MAX_TERM_SCORE = 10
SNIPPET_CHARS = 240
MAX_SEARCH_SECONDS = 5.0
ROLES = ("user", "assistant")

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_CHARS},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
        "session_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "role": {"type": "string", "enum": list(ROLES)},
    },
    "required": ["query"],
    "additionalProperties": False,
}

DESCRIPTION = (
    "Search the owner's past conversations (session transcripts) for keywords; every "
    "keyword must appear in one turn. Returns bounded snippets, most relevant and newest "
    "first, and says when a cap stopped the search."
)


# ── validation ───────────────────────────────────────────────────────────────

def _terms(query: object) -> list[str]:
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ToolRPCValidationError("bad_query")
    if "\x00" in query:
        raise ToolRPCValidationError("bad_query")
    terms = list(dict.fromkeys(part for part in query.lower().split() if part))
    if not terms or len(terms) > MAX_TERMS:
        raise ToolRPCValidationError("bad_query")
    return terms


def preflight(args: dict) -> Mapping:
    """Shape check shared by the ToolRPC seam and the function itself."""
    clean: dict[str, Any] = {"query": args.get("query")}
    _terms(clean["query"])
    if "limit" in args:
        value = args["limit"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ToolRPCValidationError("bad_limit")
        clean["limit"] = min(value, MAX_LIMIT)
    if args.get("session_id") is not None:
        sid = args["session_id"]
        if not isinstance(sid, str) or not is_valid_session_id(sid) or not is_session_stem(sid):
            raise ToolRPCValidationError("bad_session_id")
        clean["session_id"] = sid
    if args.get("role") is not None:
        role = args["role"]
        if role not in ROLES:
            raise ToolRPCValidationError("bad_role")
        clean["role"] = role
    return clean


# ── the scan ─────────────────────────────────────────────────────────────────

def _candidates(root: Path, session_id: str | None) -> list[Path]:
    if session_id is not None:
        path = root / f"{session_id}.json"
        return [path] if path.is_file() else []
    try:
        files = [p for p in root.glob("*.json") if is_session_stem(p.stem)]
    except OSError:
        return []
    keyed: list[tuple[int, str, Path]] = []
    for path in files:
        try:
            keyed.append((path.stat().st_mtime_ns, path.stem, path))
        except OSError:
            continue
    keyed.sort(reverse=True)
    return [path for _mtime, _stem, path in keyed]


def _load(path: Path) -> dict | None:
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return None
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if is_session_snapshot_payload(data) else None


def _snippet(text: str, index: int) -> str:
    if len(text) <= SNIPPET_CHARS:
        return text
    start = max(0, index - SNIPPET_CHARS // 3)
    end = min(len(text), start + SNIPPET_CHARS)
    start = max(0, end - SNIPPET_CHARS)
    out = text[start:end]
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


def _match_turn(turn: object, terms: list[str], role: str | None) -> tuple[int, int, str] | None:
    """``(score, first_index, hay)`` when every term is in the turn, else None."""
    if not isinstance(turn, dict):
        return None
    content = turn.get("content")
    if not isinstance(content, str) or not content:
        return None
    if role is not None and str(turn.get("role") or "") != role:
        return None
    hay = content[:MAX_TURN_CHARS]
    low = hay.lower()
    score = 0
    first = len(low)
    for term in terms:
        index = low.find(term)
        if index < 0:
            return None
        first = min(first, index)
        score += min(MAX_TERM_SCORE, low.count(term))
    return score, first, hay


def search_sessions(
    query: object,
    *,
    directory: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    session_id: str | None = None,
    role: str | None = None,
) -> dict:
    """Search the session snapshots for *query*'s keywords. Never raises for bad input —
    the refusal is a bounded ``reason`` the model can act on."""
    try:
        clean = preflight({"query": query, "limit": limit, "session_id": session_id, "role": role})
    except ToolRPCValidationError as exc:
        return {"ok": False, "reason": exc.reason}
    terms = _terms(clean["query"])
    limit = int(clean.get("limit", DEFAULT_LIMIT))
    role = clean.get("role")
    root = Path(directory) if directory is not None else memory_dir()
    deadline = time.monotonic() + MAX_SEARCH_SECONDS

    ranked: list[tuple[int, int, int, dict]] = []
    scanned = skipped = 0
    stopped_by: str | None = None
    for path in _candidates(root, clean.get("session_id")):
        if time.monotonic() > deadline:
            stopped_by = "deadline"
            break
        if scanned >= MAX_SESSIONS:
            stopped_by = "max_sessions"
            break
        payload = _load(path)
        if payload is None:
            skipped += 1
            continue
        scanned += 1
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        sid = str(payload.get("session_id"))
        for index, turn in enumerate(payload["turns"]):
            matched = _match_turn(turn, terms, role)
            if matched is None:
                continue
            score, first, hay = matched
            flags = detect_injection(hay)
            hit: dict[str, Any] = {
                "session_id": sid,
                "turn": index,
                "role": str(turn.get("role") or ""),
                "timestamp": turn.get("timestamp") if isinstance(turn.get("timestamp"), str) else None,
                "agent_id": turn.get("agent_id") if isinstance(turn.get("agent_id"), str) else None,
                "snippet": REDACTION if flags else _snippet(hay, first),
                "score": score,
            }
            if flags:
                hit["injection_flagged"] = True
                hit["flags"] = flags
            ranked.append((score, mtime, index, hit))
    ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    hits = [row[3] for row in ranked[:limit]]
    if any(hit.get("injection_flagged") for hit in hits):
        # SEC-B5, as for search_memory: the model is about to read text the scanner
        # flagged, so this turn's actions land in the approval inbox, not on auto.
        mark_turn_recall_tainted()
    if len(ranked) > limit and stopped_by is None:
        stopped_by = "limit"
    return {
        "ok": True,
        "query": clean["query"],
        "terms": terms,
        "hits": hits,
        "total_matches": len(ranked),
        "sessions_scanned": scanned,
        "sessions_skipped": skipped,
        "truncated": stopped_by is not None,
        "stopped_by": stopped_by,
    }


# ── the ToolRPC seam ─────────────────────────────────────────────────────────

def register_session_search(server: Any, *, directory: Path | None = None) -> str:
    """Expose ``session_search`` on a ToolRPC server (ungated, read-only)."""

    async def _handle(args: dict) -> dict:
        return await asyncio.to_thread(
            search_sessions,
            args.get("query"),
            directory=directory,
            limit=args.get("limit", DEFAULT_LIMIT),
            session_id=args.get("session_id"),
            role=args.get("role"),
        )

    server.register_tool(
        TOOL_NAME,
        _handle,
        gated=False,
        description=DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        capability_id=CAPABILITY_ID,
        preflight=preflight,
    )
    return TOOL_NAME


__all__ = [
    "CAPABILITY_ID", "DEFAULT_LIMIT", "DESCRIPTION", "INPUT_SCHEMA", "MAX_LIMIT",
    "MAX_QUERY_CHARS", "MAX_SEARCH_SECONDS", "MAX_SESSIONS", "MAX_SNAPSHOT_BYTES", "MAX_TERMS",
    "ROLES", "SNIPPET_CHARS", "TOOL_NAME", "preflight", "register_session_search",
    "search_sessions",
]
