"""Durable, provenance-bound prompt views; source conversation turns stay intact."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import nullcontext
from pathlib import Path

from . import persistence

_MAX_SUMMARY_BYTES = 8192


def _digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot(session_id: str):
    path = Path(persistence._memory_dir()) / f"{session_id}.json"
    with path.open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    if (type(document) is not dict or document.get("session_id") != session_id
            or type(document.get("turns")) is not list
            or type(document.get("revision")) is not int
            or document.get("rewound") is True or document.get("foreign_history")):
        return None
    return document


def commit(manager, clock, *, history_revision: int, history_digest: str,
           covered_count: int, summary: str, protected_count: int = 0,
           lifetime=None, tier: str = "local-digest") -> bool:
    """CAS the source and clock, publishing the view in the same SQLite transaction."""
    from ..conversation_clock import ClockSnapshot

    if (manager._conn is None or not isinstance(clock, ClockSnapshot)
            or type(history_revision) is not int or history_revision < 0
            or type(covered_count) is not int or covered_count < 2
            or type(protected_count) is not int or protected_count < 0
            or not isinstance(summary, str) or not summary.strip()
            or len(summary.encode("utf-8")) > _MAX_SUMMARY_BYTES
            or type(history_digest) is not str or len(history_digest) != 64):
        return False
    if tier not in {"local-digest", "local-auxiliary"}:
        return False
    try:
        with manager._lock, persistence.session_snapshot_lock(clock.session_id):
            document = _snapshot(clock.session_id)
            if (document is None or document.get("instance_id") != clock.instance_id
                    or document["revision"] != history_revision
                    or persistence.snapshot_digest(document) != history_digest):
                return False
            turns = document["turns"]
            if (covered_count > len(turns) - 2 or covered_count % 2
                    or protected_count % 2 or protected_count >= covered_count):
                return False
            if any(type(row) is not dict for row in turns):
                return False
            from ..context_compressor import lineage_row

            payload = {
                "summary": summary,
                "covered_count": covered_count,
                "protected_count": protected_count,
                "history_revision": history_revision,
                "history_digest": history_digest,
                "history_count": len(turns),
                "history_turns_digest": _digest(turns),
                "covered_digest": _digest(turns[:covered_count]),
                "lineage": lineage_row(
                    session_id=clock.session_id, summary=summary,
                    evicted=covered_count - protected_count, images_dropped=0,
                    tier=tier, model="micro-view",
                ),
            }
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False)
            sha = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            conn = manager._conn
            guard = lifetime.transaction() if lifetime is not None else nullcontext(True)
            with guard as active:
                if not active:
                    return False
                with conn:
                    row = conn.execute(
                        "SELECT revision,rebuilt_at,instance_id FROM session_clock WHERE session_id=?",
                        (clock.session_id,),
                    ).fetchone()
                    owner = conn.execute(
                        "SELECT instance_id FROM sessions WHERE id=?", (clock.session_id,),
                    ).fetchone()
                    if row != (clock.revision, clock.rebuilt_at.isoformat(), clock.instance_id) or owner != (clock.instance_id,):
                        return False
                    from datetime import UTC, datetime

                    now = max(datetime.now(UTC), clock.rebuilt_at.astimezone(UTC)).isoformat()
                    updated = conn.execute(
                        "UPDATE session_clock SET revision=revision+1,rebuilt_at=?,compaction_sha256=? "
                        "WHERE session_id=? AND revision=? AND instance_id=?",
                        (now, sha, clock.session_id, clock.revision, clock.instance_id),
                    )
                    if updated.rowcount != 1:
                        return False
                    conn.execute(
                        "INSERT INTO session_micro_views(session_id,instance_id,clock_revision,"
                        "view_sha256,payload) VALUES(?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET "
                        "instance_id=excluded.instance_id,clock_revision=excluded.clock_revision,"
                        "view_sha256=excluded.view_sha256,payload=excluded.payload",
                        (clock.session_id, clock.instance_id, clock.revision + 1, sha, encoded),
                    )
            return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError, sqlite3.Error):
        return False


def load(manager, session_id: str) -> dict | None:
    """Accept only a committed view whose original history remains a prefix."""
    if manager._conn is None:
        return None
    try:
        with manager._lock, persistence.session_snapshot_lock(session_id):
            document = _snapshot(session_id)
            if document is None:
                return None
            row = manager._conn.execute(
                "SELECT instance_id,clock_revision,view_sha256,payload "
                "FROM session_micro_views WHERE session_id=?", (session_id,),
            ).fetchone()
            if row is None or row[0] != document.get("instance_id"):
                return None
            clock = manager._conn.execute(
                "SELECT revision,compaction_sha256,instance_id FROM session_clock WHERE session_id=?",
                (session_id,),
            ).fetchone()
            owner = manager._conn.execute(
                "SELECT instance_id FROM sessions WHERE id=?", (session_id,),
            ).fetchone()
            if clock != (row[1], row[2], row[0]) or owner != (row[0],):
                return None
            if hashlib.sha256(row[3].encode("utf-8")).hexdigest() != row[2]:
                return None
            payload = json.loads(row[3])
            if type(payload) is not dict or type(payload.get("summary")) is not str:
                return None
            count = payload.get("history_count")
            covered = payload.get("covered_count")
            protected = payload.get("protected_count")
            turns = document["turns"]
            if (type(count) is not int or type(covered) is not int
                    or type(protected) is not int or count > len(turns)
                    or covered < 2 or covered > count or covered % 2
                    or protected < 0 or protected % 2 or protected >= covered
                    or document["revision"] < payload.get("history_revision", -1)
                    or _digest(turns[:count]) != payload.get("history_turns_digest")
                    or _digest(turns[:covered]) != payload.get("covered_digest")):
                return None
            return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError, sqlite3.Error):
        return None
