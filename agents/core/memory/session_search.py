"""session_search.py — the model searches what was actually said (Hermes absorption 3a).

Recall is rich over *derived* facts — entities, the bitemporal graph, episodes — and had
nothing over the raw transcripts: "what did we decide about the dentist" had no tool to
answer it. This is a read-only, local search of the session snapshots ``save_memory``
writes (``<sid>.json`` in the data root), offered to the tool loop as ``session_search``.

H574 — the search runs on the CJK-aware FTS5 index over every session
(``session_index``: one row per turn, CJK runs as unigrams + bigrams, the rest as
``unicode61`` words), so a 1-2 character CJK keyword reaches the whole history, not the
newest :data:`MAX_SESSIONS`. A CJK keyword narrows through its n-grams, any other keyword
through its ``unicode61`` words (the last one as a prefix), and every candidate is then
re-checked for each keyword as a substring of the turn, so the index never adds a hit the
scan would not. Because the index matches non-CJK keywords from the start of a word, a
keyword that begins inside a word (``ntist`` for ``dentist``) is found only by the scan.
When this SQLite has no FTS5 (or the index cannot be opened), the bounded scan below
answers instead; ``engine`` in the result says which ran.

Containment, in the same spirit as the file tools:

* only files ``session_files`` recognises as sessions are read (name rule *and* payload
  rule), inside the data root; the scan reads them newest first, at most
  :data:`MAX_SESSIONS` of them and none over :data:`MAX_SNAPSHOT_BYTES`, and the index
  path reads at most :data:`MAX_INDEX_CANDIDATES` candidate turns;
* every hit is a bounded snippet, never the turn; a query is keywords that must all
  appear in one turn, never a regex (Python's ``re`` has no time bound);
* retrieved text is untrusted — a turn that trips the injection scanner is redacted the
  way ``rag_tool._sanitize_hit`` redacts a memory hit, says so, and raises the turn's
  recall taint (``recall_taint.mark_turn_recall_tainted``) so an action the model
  proposes after reading it is queued for approval rather than auto-executed;
* the scan has a wall-clock deadline; either path reports ``truncated`` when a cap
  stopped it.

Ungated: it reads what the owner already can (``nerva sessions``, the HUD) and nothing
else. Who may *ask* is the tool profile's decision (wave 3b), not this module's.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents.core.memory import session_index
from agents.core.memory.cjk_fts import has_cjk, match_expression, normalize, split_script_boundaries
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
MAX_TURN_CHARS = session_index.MAX_TURN_CHARS
MAX_INDEX_CANDIDATES = 5_000
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
    # H574: CJK is written without spaces between scripts, so a keyword is also split
    # where CJK meets non-CJK (``明天dentist`` → ``明天``, ``dentist``); both sides are
    # NFKC- and case-folded, as in the memory store's CJK index.
    terms = list(dict.fromkeys(
        piece
        for part in normalize(query).split() if part
        for piece in split_script_boundaries(part) if piece.strip()
    ))
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
    low = normalize(hay)
    score = 0
    first = len(low)
    for term in terms:
        index = low.find(term)
        if index < 0:
            return None
        first = min(first, index)
        score += min(MAX_TERM_SCORE, low.count(term))
    if len(low) != len(hay):
        first = _original_index(hay, first)
    return score, first, hay


def _original_index(hay: str, folded_index: int) -> int:
    """Where in *hay* the character at *folded_index* of ``normalize(hay)`` came from:
    NFKC and case folding can change the length, so each original character's folded
    length is walked rather than rescaled."""
    seen = 0
    for position, char in enumerate(hay):
        seen += len(normalize(char))
        if seen > folded_index:
            return position
    return len(hay)


def _hit(sid: str, index: int, turn: Mapping, score: int, first: int, hay: str) -> dict[str, Any]:
    """One bounded hit; a turn the injection scanner flags is redacted, never quoted."""
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
    if turn.get("media"):
        hit["image_derived"] = True   # H586: a committed image reading is untrusted input
    return hit


Ranked = list[tuple[int, int, int, dict]]


def _scan(root: Path, terms: list[str], role: str | None,
          session_id: str | None) -> tuple[Ranked, int, int, str | None]:
    """The fallback when there is no FTS5: a bounded scan of the newest snapshots."""
    deadline = time.monotonic() + MAX_SEARCH_SECONDS
    ranked: Ranked = []
    scanned = skipped = 0
    stopped_by: str | None = None
    for path in _candidates(root, session_id):
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
            ranked.append((score, mtime, index, _hit(sid, index, turn, score, first, hay)))
    return ranked, scanned, skipped, stopped_by


def match_for_terms(terms: list[str]) -> str | None:
    """The FTS5 ``MATCH`` that narrows to turns that can hold every term, or None when no
    term gives the index anything to match on (punctuation only): then the scan answers.

    A CJK term is its n-grams (``cjk_fts.match_expression``); any other term is one quoted
    phrase of its ``unicode61`` words with the last one as a prefix. Every piece is a
    quoted string, so FTS5 syntax in the owner's words is never parsed."""
    parts: list[str] = []
    for term in terms:
        if has_cjk(term):
            expression = match_expression(term)
            if expression:
                parts.append(expression)
        elif any(char.isalnum() for char in term):
            parts.append('"' + term.replace('"', '""') + '"*')
    return " AND ".join(parts) if parts else None


def _search_index(root: Path, terms: list[str], role: str | None,
                  session_id: str | None) -> tuple[str, Ranked, int, int, str | None] | None:
    """The FTS5 path: ``(match, ranked, scanned, skipped, stopped_by)``, or None when the
    index cannot answer (no FTS5, no matchable term, an SQLite error) and the scan must."""
    match = match_for_terms(terms)
    if match is None:
        return None
    try:
        conn = session_index.open_index(root)
    except session_index.IndexUnavailable as exc:
        logger.info("session index unavailable, scanning instead: %s", exc)
        return None
    if conn is None:
        return None
    try:
        session_index.sync(conn, root)
        rows = conn.execute(
            "SELECT t.stem, t.session_id, t.turn_idx, t.role, t.content, t.ts, t.agent_id, t.media,"
            " s.mtime_ns FROM turn_fts JOIN turns t ON t.id = turn_fts.rowid"
            " JOIN sessions s ON s.stem = t.stem"
            " WHERE turn_fts MATCH ? AND (? IS NULL OR t.stem = ?) AND (? IS NULL OR t.role = ?)"
            " ORDER BY s.mtime_ns DESC, t.turn_idx DESC LIMIT ?",
            (match, session_id, session_id, role, role, MAX_INDEX_CANDIDATES + 1),
        ).fetchall()
        counts = conn.execute(
            "SELECT COALESCE(SUM(indexed), 0), COALESCE(SUM(1 - indexed), 0) FROM sessions"
            " WHERE ? IS NULL OR stem = ?",
            (session_id, session_id),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("session index query failed (%s); scanning instead", type(exc).__name__)
        return None
    finally:
        conn.close()
    stopped_by = None
    if len(rows) > MAX_INDEX_CANDIDATES:
        rows = rows[:MAX_INDEX_CANDIDATES]
        stopped_by = "max_candidates"
    ranked: Ranked = []
    present: dict[str, bool] = {}
    for row in rows:
        stem = row["stem"]
        if stem not in present:
            # The rows were synced a moment ago; a snapshot removed since never answers.
            present[stem] = (root / f"{stem}.json").is_file()
        if not present[stem]:
            continue
        turn = {"role": row["role"], "content": row["content"], "timestamp": row["ts"],
                "agent_id": row["agent_id"], "media": bool(row["media"])}
        matched = _match_turn(turn, terms, role)   # the index narrows, the substring decides
        if matched is None:
            continue
        score, first, hay = matched
        index = int(row["turn_idx"])
        ranked.append((score, int(row["mtime_ns"]), index,
                       _hit(str(row["session_id"]), index, turn, score, first, hay)))
    return match, ranked, int(counts[0]), int(counts[1]), stopped_by


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
    indexed = _search_index(root, terms, role, clean.get("session_id"))
    if indexed is not None:
        engine = "fts5"
        match, ranked, scanned, skipped, stopped_by = indexed
    else:
        engine, match = "scan", None
        ranked, scanned, skipped, stopped_by = _scan(root, terms, role, clean.get("session_id"))
    ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    hits = [row[3] for row in ranked[:limit]]
    if any(hit.get("injection_flagged") or hit.get("image_derived") for hit in hits):
        # SEC-B5, as for search_memory: the model is about to read text the scanner
        # flagged, or (H586) an image reading, so this turn's actions land in the
        # approval inbox, not on auto.
        mark_turn_recall_tainted()
    if len(ranked) > limit and stopped_by is None:
        stopped_by = "limit"
    out = {
        "ok": True,
        "engine": engine,
        "query": clean["query"],
        "terms": terms,
        "hits": hits,
        "total_matches": len(ranked),
        "sessions_scanned": scanned,
        "sessions_skipped": skipped,
        "truncated": stopped_by is not None,
        "stopped_by": stopped_by,
    }
    if match is not None:
        out["match"] = match
    return out


# ── the ToolRPC seam ─────────────────────────────────────────────────────────

def register_session_search(server: Any, *, directory: Path | None = None) -> str:
    """Expose ``session_search`` on a ToolRPC server (ungated, read-only)."""

    async def _handle(args: dict) -> dict:
        result = await asyncio.to_thread(
            search_sessions,
            args.get("query"),
            directory=directory,
            limit=args.get("limit", DEFAULT_LIMIT),
            session_id=args.get("session_id"),
            role=args.get("role"),
        )
        # The mark search_sessions sets runs in to_thread's context copy and cannot reach
        # the turn; declare it on the result, as search_memory does, so the tool loop and
        # the ToolRPC broker raise the turn's origin (H586 image readings, SEC-B5 flags).
        if result.get("ok"):
            result["tainted"] = any(hit.get("image_derived") or hit.get("injection_flagged")
                                    for hit in result.get("hits", []))
        return result

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
    "MAX_INDEX_CANDIDATES", "MAX_QUERY_CHARS", "MAX_SEARCH_SECONDS", "MAX_SESSIONS", "MAX_SNAPSHOT_BYTES", "MAX_TERMS",
    "ROLES", "SNIPPET_CHARS", "TOOL_NAME", "match_for_terms", "preflight", "register_session_search",
    "search_sessions",
]
