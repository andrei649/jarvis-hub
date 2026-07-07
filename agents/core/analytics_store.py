"""analytics_store.py — first-party, local, offline web-analytics store (H22).

Privacy-first analytics in the lineage of Plausible: we own the raw event table
and aggregate **on read** with plain SQL `GROUP BY`, instead of shipping events to
a third party (GA4) and trusting their dashboards. No cookies, no cross-site IDs,
no PII required — `session_id` is an opaque caller-supplied string (a per-visit
hash), nothing here is joined back to a person.

Storage is a single SQLite table under the runtime-data root (`paths.data_path`,
gitignored), WAL + synchronous=NORMAL like the other stores (autonomy queue,
memory). One module-level connection guarded by a lock, since ingest comes from
the asyncio event loop and reads from request handlers.

Public surface:
  * ``record_event(name, path=..., referrer=..., props=..., session_id=..., ts=...)``
  * ``top_paths(days=..., limit=...)`` / ``event_counts(days=...)`` /
    ``unique_sessions(days=...)`` / ``timeseries(days=...)`` — the aggregates the
    KPI layer composes.
  * ``kpis(days=...)`` — the aggregate bundle the analytics plugin returns.

The analytics plugin (`plugins/analytics.py`) is a thin async wrapper over this so
the HUD/dashboard interface (`get_kpis()` / `get_summary()`) is unchanged.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from agents.core.env_config import env_int
from agents.core.paths import data_path

logger = logging.getLogger("jarvis.analytics.store")

DEFAULT_DB = data_path("analytics.db")

# Bound payload sizes so a public beacon can't bloat the table. The route also
# validates, but the store is the last line of defence for direct callers.
_MAX_STR = 512
_MAX_PROPS_BYTES = 2048

# Retention (review #3): keep at most this many newest events so the public
# ingest can't grow the table without bound (slow disk-fill DoS). 0 disables it.
# Pruned lazily (off the hot path) whenever a row id is a multiple of _PRUNE_EVERY
# — stateless, so no shared counter to race or carry across reopens.
_MAX_EVENTS = env_int("JARVIS_ANALYTICS_MAX_EVENTS", 200000, minimum=0)
_PRUNE_EVERY = 1000


class _DB:
    """Holder for the single shared connection plus the path it was opened with.

    Bundling the two as connection-state (rather than two separate module globals)
    keeps ``initialize()`` idempotent — the stored ``path`` is what lets a repeated
    same-path call return the cached connection instead of reopening — while making
    that role explicit and keeping the module's global surface to one object."""

    conn: Optional[sqlite3.Connection] = None
    path: Optional[str] = None


_db = _DB()
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: Optional[str], limit: int = _MAX_STR) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return s[:limit] if len(s) > limit else s


def initialize(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open (or reopen) the events DB and ensure the schema. Idempotent."""
    with _lock:
        if _db.conn is not None and (db_path is None or db_path == _db.path):
            return _db.conn
        if _db.conn is not None:
            _db.conn.close()
            _db.conn = None
        path = db_path or str(DEFAULT_DB)
        if path != ":memory:":
            DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL + synchronous=NORMAL: ingest is a single cheap INSERT per beacon;
        # keep those commits fast. (:memory: ignores journal_mode, which is fine.)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                name       TEXT NOT NULL,
                path       TEXT,
                referrer   TEXT,
                props_json TEXT NOT NULL DEFAULT '{}',
                session_id TEXT
            )
            """
        )
        # Aggregate-on-read filters by ts window then groups by path/name — index
        # ts so the period scan stays cheap as the table grows unboundedly.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        conn.commit()
        _db.conn = conn
        _db.path = path
        return _db.conn


def _require() -> sqlite3.Connection:
    if _db.conn is None:
        return initialize()
    return _db.conn


def close() -> None:
    with _lock:
        if _db.conn is not None:
            _db.conn.close()
            _db.conn = None
            _db.path = None


# ── writes ────────────────────────────────────────────────────────────

def record_event(
    name: str,
    *,
    path: Optional[str] = None,
    referrer: Optional[str] = None,
    props: Optional[dict] = None,
    session_id: Optional[str] = None,
    ts: Optional[str] = None,
) -> int:
    """Persist one analytics event (single INSERT). Returns the row id.

    Values are clipped to bounded lengths and ``props`` is serialized to JSON
    (non-dict / unserializable props degrade to ``{}`` rather than raising — a
    beacon must never 500 the ingest path on a bad prop bag)."""
    conn = _require()
    name = _clip(name) or "event"
    try:
        props_json = json.dumps(props or {}, ensure_ascii=False)
        if len(props_json.encode("utf-8")) > _MAX_PROPS_BYTES:
            props_json = "{}"
    except (TypeError, ValueError):
        props_json = "{}"
    row = (
        ts or _now_iso(),
        name,
        _clip(path),
        _clip(referrer),
        props_json,
        _clip(session_id, 128),
    )
    with _lock:
        cur = conn.execute(
            "INSERT INTO events (ts, name, path, referrer, props_json, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            row,
        )
        conn.commit()
        rowid = cur.lastrowid
    # Lazy retention: prune when a row id crosses a _PRUNE_EVERY boundary — keeps
    # the O(n) sweep off most inserts without a stateful counter. Run OUTSIDE the
    # lock (prune() takes it itself; threading.Lock isn't reentrant).
    due = bool(_MAX_EVENTS) and rowid is not None and rowid % _PRUNE_EVERY == 0
    if due:
        try:
            prune()
        except Exception:  # pragma: no cover - retention is best-effort
            logger.warning("analytics retention prune failed", exc_info=True)
    return rowid


def prune(max_events: Optional[int] = None) -> int:
    """Delete all but the newest *max_events* rows (newest = highest id). Returns
    the number of rows deleted. No-op when the cap is 0/None. Safe with id gaps:
    keeps an exact count via a subquery rather than arithmetic on ids."""
    cap = _MAX_EVENTS if max_events is None else max_events
    if not cap or cap <= 0:
        return 0
    conn = _require()
    with _lock:
        cur = conn.execute(
            "DELETE FROM events WHERE id NOT IN "
            "(SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (cap,),
        )
        conn.commit()
        return cur.rowcount or 0


# ── aggregate-on-read ─────────────────────────────────────────────────

def _since_iso(days: int) -> str:
    """Lower bound (ISO) for an N-day window. days<=0 means 'all time'."""
    if days is None or days <= 0:
        return ""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    return datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()


def _window(days: int) -> tuple[str, tuple]:
    since = _since_iso(days)
    if since:
        return "WHERE ts >= ?", (since,)
    return "", ()


def top_paths(days: int = 30, limit: int = 10) -> list[dict]:
    """Most-viewed paths in the window, descending. [{path, views}]."""
    conn = _require()
    where, params = _window(days)
    with _lock:
        rows = conn.execute(
            f"SELECT path, COUNT(*) AS views FROM events "
            f"{where} {'AND' if where else 'WHERE'} path IS NOT NULL "
            f"GROUP BY path ORDER BY views DESC, path ASC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
    return [{"path": r["path"], "views": r["views"]} for r in rows]


def event_counts(days: int = 30) -> dict[str, int]:
    """Count of events per event name in the window. {name: count}."""
    conn = _require()
    where, params = _window(days)
    with _lock:
        rows = conn.execute(
            f"SELECT name, COUNT(*) AS n FROM events {where} GROUP BY name",
            params,
        ).fetchall()
    return {r["name"]: r["n"] for r in rows}


def total_events(days: int = 30) -> int:
    conn = _require()
    where, params = _window(days)
    with _lock:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM events {where}", params
        ).fetchone()
    return int(row["n"]) if row else 0


def unique_sessions(days: int = 30) -> int:
    conn = _require()
    where, params = _window(days)
    with _lock:
        row = conn.execute(
            f"SELECT COUNT(DISTINCT session_id) AS n FROM events "
            f"{where} {'AND' if where else 'WHERE'} session_id IS NOT NULL",
            params,
        ).fetchone()
    return int(row["n"]) if row else 0


def timeseries(days: int = 30) -> list[dict]:
    """Per-day event counts in the window, ascending. [{day, count}]."""
    conn = _require()
    where, params = _window(days)
    with _lock:
        rows = conn.execute(
            f"SELECT substr(ts, 1, 10) AS day, COUNT(*) AS n FROM events "
            f"{where} GROUP BY day ORDER BY day ASC",
            params,
        ).fetchall()
    return [{"day": r["day"], "count": r["n"]} for r in rows]


def kpis(days: int = 30) -> dict:
    """Aggregate the headline KPIs the dashboard expects, on read.

    Shape-compatible with the old GA4 mock: ``daily_users``, ``page_views``,
    ``sessions``, ``conversion_rate``, ``revenue``, ``top_pages``. We derive what
    we honestly can from first-party events and report 0 for what we don't track
    (revenue) rather than fabricate it. ``mock`` is always False — this is real,
    local data (even when the table is empty)."""
    counts = event_counts(days)
    page_views = counts.get("pageview", 0)
    sessions = unique_sessions(days)
    total = total_events(days)
    # Conversion = share of events that are an explicit "conversion".
    conversions = counts.get("conversion", 0)
    conversion_rate = (conversions / total) if total else 0.0
    # "daily users" ≈ unique sessions spread over the window, but never report
    # fewer than the sessions we actually saw for short windows.
    daily_users = round(sessions / days) if days and days > 0 else sessions
    return {
        "daily_users": daily_users or sessions,
        "page_views": page_views,
        "sessions": sessions,
        "conversion_rate": round(conversion_rate, 4),
        "revenue": 0.0,
        "top_pages": top_paths(days, limit=5),
        "total_events": total,
        "mock": False,
    }
