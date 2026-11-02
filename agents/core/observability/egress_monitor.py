"""egress_monitor.py — H23.16 network monitor: record every outbound attempt.

The plugin egress choke point (`core/http_client.py`) calls :func:`record` for every
HTTP request — *allowed and blocked alike* — so we have a single, truthful ledger of
what actually left (or tried to leave) the machine, per plugin and per host. The HUD
network panel reads :func:`snapshot` to **prove** that LOCAL_ONLY / no-network plugins
make zero outbound calls (and to surface any blocked attempt), which is the whole point
of the local-first kernel mediation story.

DRA-23: the ledger covers **model-backend egress** too. `core/llm/egress.py` records
every LLM request under an ``llm:<provider>`` row, so a turn served by a cloud model
shows up here instead of leaving invisibly; ``model_egress_total`` is that traffic's
share of ``external_egress_total``. Those rows have no plugin manifest, so
:meth:`_local_only_violations` skips them — a cloud call is honest egress, not a breach.

Design mirrors ``http_metrics.py``: a single in-process, thread-safe instance, no
external dependency. The in-process state — monotonic per-plugin counters plus a
bounded ring buffer of recent events — is this process's **live** record.

H381: the proof of where a prompt went now **survives a restart**. The module
singleton writes every event through to :class:`EgressLedgerStore`, one owner-only
SQLite file under the data root (``egress_ledger.db``), and
:meth:`EgressMonitor.snapshot` reads that file back, so ``GET /api/admin/network/calls``
and the HUD network panel show the rows an earlier process (or another process on the
same data root, such as a CLI turn) recorded next to this process's live ones. Each
recent row says where it came from (``origin``: ``live`` / ``restored`` / ``unsaved``)
and the top-level ``ledger`` block says whether the file is being written. The store
is bounded — the newest ``_MAX_PERSISTED_EVENTS`` model rows and, separately, the
newest ``_MAX_PERSISTED_EVENTS`` plugin rows, so a chatty plugin can never evict the
record of a prompt — and it holds **no prompt content**: the only columns are time,
row name, host, method, the allowed/local flags and a short reason with any URL
replaced by ``<url>``. Nothing here is ever handed a path, a query, a header or a
body. A write that fails keeps the event in memory (``origin: unsaved``) and reports
the error; observability never breaks egress.
"""

from __future__ import annotations

import contextlib
import re
import secrets
import sqlite3
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

# Recent-event ring buffer size. Bounded so a busy plugin can't grow memory without
# limit; the monotonic counters below keep exact totals regardless of eviction.
_MAX_EVENTS = 1000

# H381: on-disk bounds. Events are kept per class (``llm:`` model rows / plugin rows);
# tallies are kept for the ``_MAX_PERSISTED_ROWS`` most recently seen row names.
_MAX_PERSISTED_EVENTS = 1000
_MAX_PERSISTED_ROWS = 512
LEDGER_FILE = "egress_ledger.db"
# Busy timeout for the ledger file. The writer runs inside the request hook, so a
# contended file must cost a bounded wait, never a stalled turn: past it the event is
# kept in memory as ``unsaved`` and the request proceeds.
_STORE_TIMEOUT_S = 0.5

_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://\S*")
_HOST_CHARS = re.compile(r"[^A-Za-z0-9._:%\[\]\-]")
_MAX_NAME = 128
_MAX_HOST = 253
_MAX_REASON = 240


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _text(value: object, limit: int) -> str:
    text = _URL.sub("<url>", str(value or ""))
    return "".join(ch if ch.isprintable() else " " for ch in text)[:limit]


def _persistable(event: dict) -> dict:
    """The only fields that ever reach the disk, each bounded (no prompt content)."""
    method = re.sub(r"[^A-Z]", "", str(event.get("method") or "").upper())[:16]
    return {
        "ts": str(event["ts"])[:40],
        "plugin": _text(event.get("plugin"), _MAX_NAME) or "unknown",
        "host": _HOST_CHARS.sub("", str(event.get("host") or ""))[:_MAX_HOST],
        "method": method or "GET",
        "allowed": bool(event.get("allowed")),
        "local": bool(event.get("local")),
        "reason": _text(event.get("reason"), _MAX_REASON),
    }


class EgressLedgerStore:
    """The bounded, owner-only, content-free on-disk egress ledger (H381).

    One SQLite file — ``<data root>/egress_ledger.db`` unless a *path* is given — that
    every process on the data root appends to, so the hub reads back rows a CLI turn
    recorded and rows from before its own restart. The path is resolved on each use, so
    the store follows the active profile's data root. The file is created ``0600``
    before the first connect (``memory.private_db.ensure_private``; SQLite gives its
    ``-wal``/``-shm`` sidecars the same mode) and a looser file is narrowed. Tallies are
    per row name across every process; events carry the writing process's ``boot``
    token so a reader can tell its own live rows from restored ones. A forget erases it
    like any other ``*.db`` under the data root (``data_purge`` deletes its rows).
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        max_events: int = _MAX_PERSISTED_EVENTS,
        max_rows: int = _MAX_PERSISTED_ROWS,
    ) -> None:
        self._path = Path(path) if path is not None else None
        self.max_events = max(1, int(max_events))
        self.max_rows = max(1, int(max_rows))
        self._ready: set[str] = set()
        self._ready_lock = threading.Lock()

    @property
    def path(self) -> Path:
        if self._path is not None:
            return self._path
        from agents.core.paths import data_path

        return data_path(LEDGER_FILE)

    def _connect(self) -> sqlite3.Connection:
        from agents.core.memory.private_db import ensure_private

        path = self.path
        key = str(path)
        fresh = key not in self._ready or not path.exists()
        if fresh:
            path.parent.mkdir(parents=True, exist_ok=True)
            ensure_private(path)
        conn = sqlite3.connect(path, timeout=_STORE_TIMEOUT_S, isolation_level=None)
        try:
            if fresh:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY,"
                    " boot TEXT NOT NULL, model INTEGER NOT NULL, ts TEXT NOT NULL,"
                    " plugin TEXT NOT NULL, host TEXT NOT NULL, method TEXT NOT NULL,"
                    " allowed INTEGER NOT NULL, local INTEGER NOT NULL, reason TEXT NOT NULL)"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS events_class ON events (model, id)")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS tallies (plugin TEXT PRIMARY KEY,"
                    " total INTEGER NOT NULL, allowed INTEGER NOT NULL,"
                    " blocked INTEGER NOT NULL, external INTEGER NOT NULL,"
                    " last_ts TEXT, last_host TEXT)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                ensure_private(path)  # narrow sidecars an older writer left looser
                with self._ready_lock:
                    self._ready.add(key)
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            conn.close()
            raise
        return conn

    def append(self, boot: str, event: dict) -> None:
        """Write one event and its row's tally, then trim to the bounds. Raises on failure."""
        row = _persistable(event)
        model = 1 if row["plugin"].startswith("llm:") else 0
        allowed = 1 if row["allowed"] else 0
        external = 1 if row["allowed"] and not row["local"] else 0
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('since', ?)", (row["ts"],))
                conn.execute(
                    "INSERT INTO events (boot, model, ts, plugin, host, method, allowed, local, reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (boot, model, row["ts"], row["plugin"], row["host"], row["method"],
                     allowed, 1 if row["local"] else 0, row["reason"]),
                )
                conn.execute(
                    "DELETE FROM events WHERE model = ? AND id <= (SELECT id FROM events"
                    " WHERE model = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
                    (model, model, self.max_events),
                )
                conn.execute(
                    "INSERT INTO tallies (plugin, total, allowed, blocked, external, last_ts, last_host)"
                    " VALUES (?, 1, ?, ?, ?, ?, ?) ON CONFLICT (plugin) DO UPDATE SET"
                    " total = total + 1, allowed = allowed + excluded.allowed,"
                    " blocked = blocked + excluded.blocked, external = external + excluded.external,"
                    " last_ts = excluded.last_ts, last_host = excluded.last_host",
                    (row["plugin"], allowed, 1 - allowed, external, row["ts"], row["host"]),
                )
                conn.execute(
                    "DELETE FROM tallies WHERE plugin NOT IN (SELECT plugin FROM tallies"
                    " ORDER BY last_ts DESC LIMIT ?)",
                    (self.max_rows,),
                )
                conn.execute("COMMIT")
            except Exception:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def read(self, boot: str, plugin: str | None, limit: int) -> dict:
        """Tallies, the newest *limit* events and the store's counts. Raises on failure."""
        conn = self._connect()
        try:
            tallies = {
                name: {
                    "total": total, "allowed": ok, "blocked": blocked, "external": external,
                    "last_ts": last_ts, "last_host": last_host,
                }
                for name, total, ok, blocked, external, last_ts, last_host in conn.execute(
                    "SELECT plugin, total, allowed, blocked, external, last_ts, last_host"
                    " FROM tallies WHERE (? IS NULL OR plugin = ?) ORDER BY plugin",
                    (plugin, plugin))
            }
            events = []
            if limit > 0:
                for row_boot, ts, name, host, method, ok, local, reason in conn.execute(
                        "SELECT boot, ts, plugin, host, method, allowed, local, reason"
                        " FROM events WHERE (? IS NULL OR plugin = ?) ORDER BY id DESC LIMIT ?",
                        (plugin, plugin, limit)):
                    events.append({
                        "ts": ts, "plugin": name, "host": host, "method": method,
                        "allowed": bool(ok), "local": bool(local), "reason": reason,
                        "origin": "live" if row_boot == boot else "restored",
                    })
            stored, oldest = conn.execute("SELECT COUNT(*), MIN(ts) FROM events").fetchone()
            restored = conn.execute("SELECT COUNT(*) FROM events WHERE boot != ?", (boot,)).fetchone()[0]
            since = conn.execute("SELECT value FROM meta WHERE key = 'since'").fetchone()
        finally:
            conn.close()
        return {
            "plugins": tallies,
            "recent": events,
            "stored_events": int(stored or 0),
            "restored_events": int(restored or 0),
            "oldest_event_ts": oldest,
            "since": since[0] if since else None,
        }

    def clear(self) -> None:
        """Delete every row (test isolation only — nothing in the product calls this)."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM tallies")
            conn.execute("DELETE FROM meta")
        finally:
            conn.close()


class _PluginStat:
    """Monotonic per-plugin tallies (survive ring-buffer eviction)."""

    __slots__ = ("total", "allowed", "blocked", "external", "last_ts", "last_host")

    def __init__(self) -> None:
        self.total = 0
        self.allowed = 0
        self.blocked = 0
        self.external = 0  # allowed calls to a non-local host
        self.last_ts: str | None = None
        self.last_host: str | None = None

    def add(self, event: dict) -> None:
        self.total += 1
        self.last_ts = event["ts"]
        self.last_host = event["host"]
        if event["allowed"]:
            self.allowed += 1
            if not event["local"]:
                self.external += 1
        else:
            self.blocked += 1

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "external": self.external,
            "last_ts": self.last_ts,
            "last_host": self.last_host,
        }


def _merge_tally(into: dict, extra: dict) -> None:
    for key in ("total", "allowed", "blocked", "external"):
        into[key] += extra[key]
    if (extra["last_ts"] or "") >= (into["last_ts"] or ""):
        into["last_ts"], into["last_host"] = extra["last_ts"], extra["last_host"]


class EgressMonitor:
    """Ledger of HTTP egress attempts: live in memory, optionally persisted (H381).

    One module-level instance (:data:`EGRESS_MONITOR`) is shared by the egress choke
    point (writer) and the admin endpoint (reader); a single lock guards both so the
    snapshot is consistent while requests record concurrently. Built with a *store*,
    every event is written through and the snapshot is read back from it; without one
    (the default for ad-hoc instances) the monitor is memory-only, exactly as before.
    """

    def __init__(
        self,
        max_events: int = _MAX_EVENTS,
        *,
        store: EgressLedgerStore | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._max_events = max_events
        self._events: deque[dict] = deque(maxlen=max_events)
        self._stats: dict[str, _PluginStat] = {}
        self._store = store
        # A per-process token: rows this process wrote read back as ``live``.
        self._boot = secrets.token_hex(8)
        # Events whose write to the store failed — kept so the snapshot never loses them.
        self._unsaved: deque[dict] = deque(maxlen=max_events)
        self._unsaved_stats: dict[str, _PluginStat] = {}
        self._unsaved_total = 0
        self._store_error = ""

    def record(
        self,
        plugin: str,
        host: str,
        method: str,
        *,
        allowed: bool,
        local: bool,
        reason: str = "",
    ) -> None:
        """Record one outbound attempt. Never raises — observability must not break egress."""
        ts = _now_iso()
        event = {
            "ts": ts,
            "plugin": plugin or "unknown",
            "host": host or "",
            "method": (method or "GET").upper(),
            "allowed": bool(allowed),
            "local": bool(local),
            "reason": reason or "",
        }
        with self._lock:
            self._events.append(event)
            st = self._stats.get(event["plugin"])
            if st is None:
                st = self._stats[event["plugin"]] = _PluginStat()
            st.add(event)
        store = self._store
        if store is None:
            return
        try:
            store.append(self._boot, event)
        except Exception as exc:
            with self._lock:
                self._store_error = f"write failed: {type(exc).__name__}"
                self._unsaved.append(event)
                self._unsaved_total += 1
                unsaved = self._unsaved_stats.get(event["plugin"])
                if unsaved is None:
                    unsaved = self._unsaved_stats[event["plugin"]] = _PluginStat()
                unsaved.add(event)
        else:
            if self._store_error.startswith("write"):
                with self._lock:
                    self._store_error = ""

    def snapshot(self, plugin: str | None = None, limit: int = 100) -> dict:
        """Return per-plugin summary + recent events, optionally filtered to one plugin.

        ``recent`` is newest-first and capped at *limit*. ``external_egress_total`` is the
        count of allowed calls that left the machine, of which ``model_egress_total`` is
        the ``llm:``-prefixed (model-backend) share; ``local_only_violations`` lists the
        plugins that *did* make an external call despite a local-only manifest (should
        always be empty — the gate blocks them — which is exactly what we want to show).

        H381: with a store, tallies and rows come from the on-disk ledger — every process
        on this data root, before and after a restart — plus any event whose write
        failed. ``ledger`` says which: ``persistent`` is False when there is no store or
        the file could not be read, and the figures are then this process's alone.
        """
        limit = max(0, min(int(limit or 0), _MAX_EVENTS))
        persisted = None
        read_error = ""
        if self._store is not None:
            try:
                persisted = self._store.read(self._boot, plugin, limit)
            except Exception as exc:
                read_error = f"read failed: {type(exc).__name__}"
        with self._lock:
            live_total = sum(st.total for st in self._stats.values())
            if persisted is None:
                items = [e for e in self._events if plugin is None or e["plugin"] == plugin]
                recent = [dict(e, origin="live") for e in reversed(items)][:limit]
                plugins = {
                    name: st.as_dict()
                    for name, st in sorted(self._stats.items())
                    if plugin is None or name == plugin
                }
            else:
                plugins = persisted["plugins"]
                for name, st in self._unsaved_stats.items():
                    if plugin is not None and name != plugin:
                        continue
                    if name in plugins:
                        _merge_tally(plugins[name], st.as_dict())
                    else:
                        plugins[name] = st.as_dict()
                plugins = dict(sorted(plugins.items()))
                unsaved = [dict(e, origin="unsaved") for e in reversed(self._unsaved)
                           if plugin is None or e["plugin"] == plugin]
                recent = sorted(persisted["recent"] + unsaved,
                                key=lambda e: e["ts"], reverse=True)[:limit]
            ledger = {
                "persistent": persisted is not None,
                "store": LEDGER_FILE if self._store is not None else None,
                "since": persisted["since"] if persisted else None,
                "oldest_event_ts": persisted["oldest_event_ts"] if persisted else None,
                "stored_events": persisted["stored_events"] if persisted else 0,
                "restored_events": persisted["restored_events"] if persisted else 0,
                "live_events": live_total,
                "unsaved_events": self._unsaved_total,
                "max_events": self._store.max_events if self._store is not None else self._max_events,
                "error": read_error or self._store_error,
            }
        external_total = sum(p["external"] for p in plugins.values())
        # DRA-23: the model-backend share of the external total, so a surface can say
        # "local-first" about plugin traffic without implying it about the models.
        model_total = sum(
            p["external"] for name, p in plugins.items() if name.startswith("llm:")
        )
        violations = self._local_only_violations(plugins)
        return {
            "plugins": plugins,
            "recent": recent,
            "external_egress_total": external_total,
            "model_egress_total": model_total,
            "local_only_violations": violations,
            "clean": not violations,
            "events_kept": len(recent),
            "ledger": ledger,
        }

    @staticmethod
    def _local_only_violations(plugins: dict) -> list[str]:
        """Plugins that made an allowed external call despite a local-only manifest.

        Cross-checks recorded egress against the declared network policy — the proof
        that the kernel's mediation held. Best-effort: if the manifest registry can't be
        imported, we can't classify, so we report none rather than guess.
        """
        try:
            from agents.core.plugin_gate import BUILTIN_PLUGINS, NetworkAccess
        except Exception:
            return []
        out = []
        for name, p in plugins.items():
            if p["external"] <= 0:
                continue
            manifest = BUILTIN_PLUGINS.get(name)
            if manifest is not None and manifest.network_access in (
                NetworkAccess.NONE,
                NetworkAccess.LAN,
            ):
                out.append(name)
        return out

    def reset(self) -> None:
        """Clear all state, persisted rows included (test isolation only).

        Nothing in the product calls this: no route, CLI verb or job erases the ledger.
        A forget clears the file through ``data_purge`` like any other store.
        """
        with self._lock:
            self._events.clear()
            self._stats.clear()
            self._unsaved.clear()
            self._unsaved_stats.clear()
            self._unsaved_total = 0
            self._store_error = ""
        if self._store is not None:
            with contextlib.suppress(Exception):
                self._store.clear()


# Module-level singleton shared by the choke point and the admin endpoint. It writes
# through to the data root's ledger file, so the proof survives a restart (H381).
EGRESS_MONITOR = EgressMonitor(store=EgressLedgerStore())
