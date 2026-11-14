"""Bounded owner history scans over the existing read-only session page route."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from agents.core.validation import is_valid_session_id as valid_session_id

MAX_STRING_BYTES = 16 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_TEXT_FIELDS = ("agent_id", "started_at", "ended_at", "summary", "title", "title_source",
                "archived_at", "pinned_at")
_BOOL_FIELDS = ("archived", "pinned", "earlier_part")
_INT_FIELDS = ("turn_count", "continuations")
_INVALID = "Invalid session history page"


def valid_cursor(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,512}", value) is not None


def validate_options(*, archived=False, limit=100, max_pages=10, cursor=None, agent=None,
                     unassigned=False, older_than_days=None, query=None, as_of=None):
    """Validate caller input before constructing a client or requesting a page."""
    if (type(archived) is not bool or type(unassigned) is not bool
            or type(limit) is not int or not 1 <= limit <= 1000
            or type(max_pages) is not int or not 1 <= max_pages <= 100
            or (cursor is not None and not valid_cursor(cursor))
            or (agent is not None and (not isinstance(agent, str) or not agent.strip()
                                       or len(agent) > 128 or not agent.isprintable()))
            or (agent is not None and unassigned)
            or (older_than_days is not None and (type(older_than_days) is not int
                                                or not 0 <= older_than_days <= 36500))
            or (query is not None and (not isinstance(query, str) or not query.strip()
                                       or len(query) > 256))
            or (as_of is not None and not isinstance(as_of, datetime))):
        raise ValueError("Invalid session history options")


def _text(value):
    if value is not None and (not isinstance(value, str)
                              or len(value.encode("utf-8")) > MAX_STRING_BYTES):
        raise ValueError(_INVALID)
    return value


def project_page(raw, requested_limit):
    """Copy the public metadata contract; never inspect or expose raw metadata."""
    if (not isinstance(raw, dict) or not isinstance(raw.get("sessions"), list)
            or len(raw["sessions"]) > requested_limit or "next_cursor" not in raw):
        raise ValueError(_INVALID)
    cursor = raw["next_cursor"]
    if cursor is not None and not valid_cursor(cursor):
        raise ValueError(_INVALID)
    rows = []
    for raw_row in raw["sessions"]:
        if not isinstance(raw_row, dict):
            raise ValueError(_INVALID)
        row = {}
        for field in ("id", "session_id", "resume_id"):
            if field in raw_row:
                if not valid_session_id(raw_row[field]):
                    raise ValueError(_INVALID)
                row[field] = raw_row[field]
        if not ("id" in row or "session_id" in row):
            raise ValueError(_INVALID)
        if "id" in row and "session_id" in row and row["id"] != row["session_id"]:
            raise ValueError(_INVALID)
        for field in _TEXT_FIELDS:
            if field in raw_row:
                row[field] = _text(raw_row[field])
        for field in _BOOL_FIELDS:
            if field in raw_row:
                if type(raw_row[field]) is not bool:
                    raise ValueError(_INVALID)
                row[field] = raw_row[field]
        for field in _INT_FIELDS:
            if field in raw_row:
                if type(raw_row[field]) is not int or not 0 <= raw_row[field] <= 2**63 - 1:
                    raise ValueError(_INVALID)
                row[field] = raw_row[field]
        rows.append(row)
    if not rows and cursor is not None:
        raise ValueError(_INVALID)
    return rows, cursor


def _timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def encode_history(document):
    data = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if len(data.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError(_INVALID)
    return data


def collect_history(client, *, archived=False, limit=100, max_pages=10, cursor=None,
                    agent=None, unassigned=False, older_than_days=None, query=None, as_of=None):
    validate_options(archived=archived, limit=limit, max_pages=max_pages, cursor=cursor,
                     agent=agent, unassigned=unassigned, older_than_days=older_than_days,
                     query=query, as_of=as_of)
    now = as_of or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    cutoff = now - timedelta(days=older_than_days) if older_than_days is not None else None
    matches, seen_ids = [], set()
    seen_cursors = {cursor} if cursor is not None else set()
    pages, scanned, matched_bytes = 0, 0, 0
    folded = query.casefold() if query is not None else None
    while True:
        requested = min(100, limit - len(matches))
        params = {"archived": str(archived).lower(), "limit": requested}
        if cursor is not None:
            params["cursor"] = cursor
        rows, next_cursor = project_page(client.get("/sessions/page?" + urlencode(params)), requested)
        if next_cursor is not None and next_cursor in seen_cursors:
            raise ValueError(_INVALID)
        if next_cursor is not None:
            seen_cursors.add(next_cursor)
        pages += 1
        scanned += len(rows)
        for row in rows:
            sid = row.get("id") or row["session_id"]
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            if agent is not None and row.get("agent_id") != agent:
                continue
            if unassigned and row.get("agent_id") not in (None, ""):
                continue
            if cutoff is not None:
                stamp = _timestamp(row.get("started_at"))
                if stamp is None or stamp > cutoff:
                    continue
            if folded is not None and not any(folded in value.casefold()
                                              for value in row.values() if isinstance(value, str)):
                continue
            matched_bytes += len(json.dumps(row, ensure_ascii=False, allow_nan=False,
                                            indent=2).encode("utf-8"))
            if matched_bytes > MAX_OUTPUT_BYTES:
                raise ValueError(_INVALID)
            matches.append(row)
        cursor = next_cursor
        if cursor is None:
            reason = "exhausted"
            break
        if len(matches) >= limit:
            reason = "result_limit"
            break
        if pages >= max_pages:
            reason = "page_limit"
            break
    result = {"sessions": matches, "next_cursor": cursor, "has_more": cursor is not None,
              "scanned_pages": pages, "scanned_rows": scanned, "stop_reason": reason,
              "filters": {"archived": archived, "agent": agent, "unassigned": unassigned,
                          "older_than_days": older_than_days, "query": query}, "as_of": now.isoformat()}
    encode_history(result)
    return result


def display_text(value):
    """Keep human output on one terminal line without server control sequences."""
    return "".join(char if char.isprintable() else " " for char in str(value or ""))
