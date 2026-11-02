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
singleton hands every event to a background writer thread that appends it to
:class:`EgressLedgerStore`, one owner-only SQLite file under the data root
(``egress_ledger.db``), and :meth:`EgressMonitor.snapshot` reads that file back, so
``GET /api/admin/network/calls``
and the HUD network panel show the rows an earlier process (or another process on the
same data root, such as a CLI turn) recorded next to this process's live ones. Each
recent row says where it came from (``origin``: ``live`` / ``restored`` / ``unsaved``)
and the top-level ``ledger`` block says whether the file is being written. The store
is bounded — the newest ``_MAX_PERSISTED_EVENTS`` model rows and, separately, the
newest ``_MAX_PERSISTED_EVENTS`` plugin rows, so a chatty plugin can never evict a
model-backend (``llm:``) row. A plugin that sends a prompt itself
(``plugins/cloud_llm.py`` through the plugin choke point) is recorded under its own
plugin row, in the plugin class, and is not part of ``model_egress_total``. The store
holds **no prompt content**: the only columns are time,
row name, host, method, the allowed/local flags and a short reason with any URL
replaced by ``<url>``. Nothing here is ever handed a path, a query, a header or a
body. A write that fails keeps the event in memory (``origin: unsaved``) and reports
the error; observability never breaks egress.

:meth:`EgressMonitor.record` runs inside the async model-request hook and the plugin
choke point, i.e. on the event loop, so it never touches the disk: it queues the event
and returns. The writer drains the queue in batches on one long-lived connection (one
transaction per batch, no open/close/checkpoint per event), so a contended file costs
the writer a bounded wait and never stalls a turn or a stream. Queued events are part
of every snapshot (``origin: live``), and the queue is drained at interpreter exit (a
bounded wait) so a short CLI turn's row still reaches the file.
"""

from __future__ import annotations

import atexit
import contextlib
import re
import secrets
import sqlite3
import threading
import time
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
_MAX_WRITERS = 64   # per-process sequence watermarks kept (newest writers)
LEDGER_FILE = "egress_ledger.db"
# Busy timeout for the ledger file. Only the background writer and the (off-loop)
# readers wait on it — never the request hook; past it the batch is kept in memory as
# ``unsaved``.
_STORE_TIMEOUT_S = 0.5
# Write-behind queue: events per transaction, and how many may wait for the writer
# before the oldest are kept in memory as ``unsaved`` (a wedged file cannot grow memory).
_WRITE_BATCH = 256
_MAX_QUEUED = 4 * _MAX_EVENTS
# Interpreter exit waits at most this long for queued events to reach the file.
_EXIT_FLUSH_S = 2.0
# An idle writer closes its connection and exits; the next event starts a new one.
_WRITER_IDLE_S = 30.0
# Forgets remembered for the writer's in-flight batch (one is all a batch can predate).
_MAX_FORGETS = 16

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


def _under(path: Path | None, root: Path | None) -> bool:
    """True when *path* lies in *root* (every path, for ``root=None``)."""
    if root is None:
        return True
    if path is None:
        return False
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, RuntimeError, ValueError):
        return False


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
    like any other ``*.db`` under the data root (``data_purge`` deletes its rows, inside
    :meth:`EgressMonitor.forgetting`, so no queued write puts them back).

    Writes go through :meth:`append_many` on ONE long-lived connection (one transaction
    per batch), so WAL mode does its job: no per-event open/close and no checkpoint plus
    WAL delete on every close. Readers open a short-lived connection of their own.
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
        # The writer's one long-lived connection: (path, (st_dev, st_ino), connection).
        self._writer: tuple[str, tuple[int, int], sqlite3.Connection] | None = None
        self._write_lock = threading.Lock()

    @property
    def path(self) -> Path:
        if self._path is not None:
            return self._path
        from agents.core.paths import data_path

        return data_path(LEDGER_FILE)

    def _connect(self, path: Path | None = None) -> sqlite3.Connection:
        from agents.core.memory.private_db import ensure_private

        path = self.path if path is None else path
        key = str(path)
        fresh = key not in self._ready or not path.exists()
        if fresh:
            path.parent.mkdir(parents=True, exist_ok=True)
            ensure_private(path)
        conn = sqlite3.connect(path, timeout=_STORE_TIMEOUT_S, isolation_level=None,
                               check_same_thread=False)
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
                # Per writing process: the highest event sequence number committed, so
                # a reader can tell which of its own queued events are already on disk.
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS writers (boot TEXT PRIMARY KEY,"
                    " seq INTEGER NOT NULL, ts TEXT NOT NULL)"
                )
                ensure_private(path)  # narrow sidecars an older writer left looser
                with self._ready_lock:
                    self._ready.add(key)
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            conn.close()
            raise
        return conn

    def _writer_for(self, path: Path) -> sqlite3.Connection:
        """The long-lived write connection for *path* (caller holds ``_write_lock``).

        Reopened when the data root moves (a profile switch) or the file is gone or
        replaced (a restore), so rows never land in an unlinked inode."""
        key = str(path)
        try:
            st = path.stat()
            ident: tuple[int, int] | None = (st.st_dev, st.st_ino)
        except OSError:
            ident = None
        cached = self._writer
        if cached is not None and ident is not None and cached[:2] == (key, ident):
            return cached[2]
        self._close_writer()
        conn = self._connect(path)
        try:
            st = path.stat()
        except OSError:
            conn.close()
            raise
        self._writer = (key, (st.st_dev, st.st_ino), conn)
        return conn

    def _close_writer(self) -> None:
        cached, self._writer = self._writer, None
        if cached is not None:
            with contextlib.suppress(sqlite3.Error):
                cached[2].close()

    def append(self, boot: str, event: dict, seq: int = 0) -> None:
        """Write one event and its row's tally (see :meth:`append_many`). Raises on failure."""
        self.append_many(boot, [event], seq=seq)

    def append_many(self, boot: str, events: list[dict], path: Path | None = None,
                    *, seq: int = 0) -> None:
        """Write *events* and their rows' tallies in ONE transaction on the long-lived
        connection, then trim to the bounds; *seq* (the writer's highest sequence number
        in the batch) is committed with them. Raises on failure (nothing is written)."""
        rows = [_persistable(event) for event in events]
        if not rows:
            return
        target = self.path if path is None else Path(path)
        with self._write_lock:
            conn = self._writer_for(target)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('since', ?)",
                             (rows[0]["ts"],))
                classes = set()
                for row in rows:
                    model = 1 if row["plugin"].startswith("llm:") else 0
                    allowed = 1 if row["allowed"] else 0
                    external = 1 if row["allowed"] and not row["local"] else 0
                    classes.add(model)
                    conn.execute(
                        "INSERT INTO events (boot, model, ts, plugin, host, method, allowed,"
                        " local, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (boot, model, row["ts"], row["plugin"], row["host"], row["method"],
                         allowed, 1 if row["local"] else 0, row["reason"]),
                    )
                    conn.execute(
                        "INSERT INTO tallies (plugin, total, allowed, blocked, external, last_ts,"
                        " last_host) VALUES (?, 1, ?, ?, ?, ?, ?) ON CONFLICT (plugin) DO UPDATE"
                        " SET total = total + 1, allowed = allowed + excluded.allowed,"
                        " blocked = blocked + excluded.blocked,"
                        " external = external + excluded.external,"
                        " last_ts = excluded.last_ts, last_host = excluded.last_host",
                        (row["plugin"], allowed, 1 - allowed, external, row["ts"], row["host"]),
                    )
                for model in sorted(classes):
                    conn.execute(
                        "DELETE FROM events WHERE model = ? AND id <= (SELECT id FROM events"
                        " WHERE model = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
                        (model, model, self.max_events),
                    )
                conn.execute(
                    "DELETE FROM tallies WHERE plugin NOT IN (SELECT plugin FROM tallies"
                    " ORDER BY last_ts DESC LIMIT ?)",
                    (self.max_rows,),
                )
                conn.execute(
                    "INSERT INTO writers (boot, seq, ts) VALUES (?, ?, ?) ON CONFLICT (boot)"
                    " DO UPDATE SET seq = MAX(seq, excluded.seq), ts = excluded.ts",
                    (boot, int(seq), rows[-1]["ts"]),
                )
                conn.execute(
                    "DELETE FROM writers WHERE boot NOT IN (SELECT boot FROM writers"
                    " ORDER BY ts DESC LIMIT ?)",
                    (_MAX_WRITERS,),
                )
                conn.execute("COMMIT")
            except Exception:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                self._close_writer()   # a broken connection is reopened on the next batch
                raise

    def close(self) -> None:
        """Close the long-lived write connection (it reopens on the next write)."""
        with self._write_lock:
            self._close_writer()

    def read(self, boot: str, plugin: str | None, limit: int) -> dict:
        """Tallies, the newest *limit* events and the store's counts, from one consistent
        read transaction (with *boot*'s committed sequence number). Raises on failure."""
        conn = self._connect()
        try:
            conn.execute("BEGIN")
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
            written = conn.execute("SELECT seq FROM writers WHERE boot = ?", (boot,)).fetchone()
            conn.execute("COMMIT")
        finally:
            conn.close()
        return {
            "plugins": tallies,
            "recent": events,
            "stored_events": int(stored or 0),
            "restored_events": int(restored or 0),
            "oldest_event_ts": oldest,
            "since": since[0] if since else None,
            "written_seq": int(written[0]) if written else 0,
        }

    def clear(self) -> None:
        """Delete every row (test isolation only — nothing in the product calls this)."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM tallies")
            conn.execute("DELETE FROM meta")
            conn.execute("DELETE FROM writers")
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
    every event is queued for a background writer thread (write-behind: the caller —
    an async request hook on the event loop — never waits for SQLite) and the snapshot
    reads the store back, plus whatever is still queued; without one (the default for
    ad-hoc instances) the monitor is memory-only, exactly as before.
    """

    def __init__(
        self,
        max_events: int = _MAX_EVENTS,
        *,
        store: EgressLedgerStore | None = None,
    ) -> None:
        self._lock = threading.Lock()
        # Signals the writer (work queued) and flush() waiters (work done); shares _lock.
        self._cv = threading.Condition(self._lock)
        self._max_events = max_events
        self._events: deque[dict] = deque(maxlen=max_events)
        self._stats: dict[str, _PluginStat] = {}
        self._store = store
        # A per-process token: rows this process wrote read back as ``live``.
        self._boot = secrets.token_hex(8)
        # Write-behind: (target file, sequence number, event) waiting for the writer, and
        # the batch it is writing now. Both are part of every snapshot until they are on
        # disk; the store's committed sequence number for this boot says which already
        # are, so a snapshot counts each event once without ever waiting for the writer.
        self._seq = 0
        self._queued: deque[tuple[Path, int, dict]] = deque()
        self._inflight: list[tuple[int, dict]] = []
        self._inflight_targets: dict[int, Path] = {}
        # (highest sequence number recorded before it, data root) per forget: the writer
        # drops such an event even when it popped it before the forget began.
        self._forgotten: list[tuple[int, Path | None]] = []
        # Serialises a batch write with reset() (test isolation) — never taken by a reader.
        self._flush_lock = threading.Lock()
        self._writer: threading.Thread | None = None
        self._writer_lock = threading.Lock()
        self._exit_hook = False
        # (sequence number, event) whose write failed — kept so the snapshot never loses them.
        self._unsaved: deque[tuple[int, dict]] = deque(maxlen=max_events)
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
        """Record one outbound attempt. Never raises and never touches the disk — it runs
        on the event loop inside the request hook; persistence is the writer's job."""
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
        store = self._store
        target: Path | None = None
        target_error = ""
        if store is not None:
            # Resolved now (pure env/path arithmetic, no I/O), so the row lands in the
            # data root that was active when the request left, not when it is written.
            try:
                target = store.path
            except Exception as exc:
                target_error = f"path failed: {type(exc).__name__}"
        with self._cv:
            self._events.append(event)
            st = self._stats.get(event["plugin"])
            if st is None:
                st = self._stats[event["plugin"]] = _PluginStat()
            st.add(event)
            if store is None:
                return
            self._seq += 1
            if target is None:
                self._keep_unsaved(self._seq, event, target_error)
                return
            if len(self._queued) >= _MAX_QUEUED:
                _, oldest_seq, oldest = self._queued.popleft()
                self._keep_unsaved(oldest_seq, oldest, "write backlog full")
            self._queued.append((target, self._seq, event))
            self._cv.notify_all()
        # A thread that cannot start (interpreter shutdown) leaves the event queued: it is
        # still served live and kept as unsaved once the queue is full.
        with contextlib.suppress(Exception):
            self._ensure_writer()

    def _keep_unsaved(self, seq: int, event: dict, error: str) -> None:
        """Hold an event the store did not take (caller holds ``_lock``)."""
        self._store_error = error
        self._unsaved.append((seq, event))
        self._unsaved_total += 1
        unsaved = self._unsaved_stats.get(event["plugin"])
        if unsaved is None:
            unsaved = self._unsaved_stats[event["plugin"]] = _PluginStat()
        unsaved.add(event)

    # ── write-behind ─────────────────────────────────────────────────────────
    def _ensure_writer(self) -> None:
        writer = self._writer
        if writer is not None and writer.is_alive():
            return
        with self._writer_lock:
            if self._writer is not None and self._writer.is_alive():
                return
            thread = threading.Thread(target=self._drain, name="egress-ledger", daemon=True)
            thread.start()
            self._writer = thread
            if not self._exit_hook:
                # Daemon threads still run while atexit callbacks do: a short CLI turn's
                # queued row reaches the file before the interpreter goes away.
                atexit.register(self.flush, _EXIT_FLUSH_S)
                self._exit_hook = True

    def _drain(self) -> None:
        while True:
            with self._cv:
                idle_until = time.monotonic() + _WRITER_IDLE_S
                while not self._queued:
                    remaining = idle_until - time.monotonic()
                    if remaining <= 0:
                        # Under the lock with nothing queued: a record() after this sees
                        # no writer and starts one, so no event is ever stranded.
                        if self._writer is threading.current_thread():
                            self._writer = None
                        break
                    self._cv.wait(remaining)
                if not self._queued:
                    break
                batch = [self._queued.popleft()
                         for _ in range(min(_WRITE_BATCH, len(self._queued)))]
                self._inflight = [(seq, event) for _, seq, event in batch]
                self._inflight_targets = {seq: target for target, seq, _ in batch}
            try:
                self._write(batch)
            except Exception:  # pragma: no cover - _write keeps every failure in memory
                with self._cv:
                    self._inflight = []
                    self._cv.notify_all()
        with contextlib.suppress(Exception):
            self._store.close()

    def _write(self, batch: list[tuple[Path, int, dict]]) -> None:
        with self._flush_lock:
            # A forget that ran between this batch leaving the queue and this lock already
            # erased the file: an event recorded before it must not be written back.
            with self._cv:
                batch = [item for item in batch if not self._forgotten_event(item[0], item[1])]
            groups: list[tuple[Path, list[tuple[int, dict]]]] = []
            for target, seq, event in batch:
                if groups and groups[-1][0] == target:
                    groups[-1][1].append((seq, event))
                else:
                    groups.append((target, [(seq, event)]))
            ok = True
            for target, items in groups:
                try:
                    self._store.append_many(self._boot, [event for _, event in items], target,
                                            seq=items[-1][0])
                except Exception as exc:
                    ok = False
                    # Moved to unsaved in the same step it leaves the in-flight batch, so
                    # a concurrent snapshot sees it in exactly one of the two.
                    with self._cv:
                        for seq, event in items:
                            self._keep_unsaved(seq, event, f"write failed: {type(exc).__name__}")
                        done = {seq for seq, _ in items}
                        self._inflight = [x for x in self._inflight if x[0] not in done]
            with self._cv:
                self._inflight = []
                self._inflight_targets = {}
                if ok:
                    self._store_error = ""
                self._cv.notify_all()

    def _forgotten_event(self, target: Path | None, seq: int) -> bool:
        """Was the event (recorded as *seq*, for *target*) erased by a forget? (Caller
        holds ``_lock``.)"""
        return any(seq <= before and _under(target, root) for before, root in self._forgotten)

    @contextlib.contextmanager
    def forgetting(self, root: str | Path | None = None):
        """Run a forget of the data root *root* (every root, for ``None``) against the ledger.

        ``data_purge`` erases the ledger file like any other store, from its own connection.
        Without this, the write-behind writer could put back what the forget just erased:
        an event still queued, or a batch already popped and about to be written. Inside
        this block the writer is held off the file (a batch it is writing now commits
        first, so the purge erases it too), and every event recorded before the block
        began, for a file under *root*, is dropped: from the queue, from the batch the
        writer holds, and, when this process's ledger lives under *root*, from the memory
        tallies and the unsaved list. Events recorded during the forget are new activity
        and are written once it ends. Another process writing the same file keeps its own
        queue; a forget runs in the hub, which owns the ledger.
        """
        if self._store is None:
            yield
            return
        root_path = None if root is None else Path(root)
        with self._flush_lock:
            with self._cv:
                self._forgotten.append((self._seq, root_path))
                del self._forgotten[:-_MAX_FORGETS]
                self._queued = deque(item for item in self._queued
                                     if not _under(item[0], root_path))
                self._inflight = [(seq, event) for seq, event in self._inflight
                                  if not _under(self._inflight_targets.get(seq), root_path)]
                try:
                    active = self._store.path
                except Exception:
                    active = None
                if _under(active, root_path):
                    self._events.clear()
                    self._stats.clear()
                    self._unsaved.clear()
                    self._unsaved_stats.clear()
                    self._unsaved_total = 0
                    self._store_error = ""
                self._cv.notify_all()
            yield

    def flush(self, timeout: float | None = None) -> bool:
        """Wait until every queued event is written (or kept as unsaved); True when done.

        For interpreter exit (bounded) and deterministic tests — never the request path."""
        if self._store is None:
            return True
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        if self._queued:
            with contextlib.suppress(Exception):
                self._ensure_writer()
        with self._cv:
            while self._queued or self._inflight:
                writer = self._writer
                if writer is None or not writer.is_alive():
                    return False        # nothing will drain it (no thread could start)
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cv.wait(0.25 if remaining is None else min(remaining, 0.25))
        return True

    # ── reading ──────────────────────────────────────────────────────────────
    def snapshot(self, plugin: str | None = None, limit: int = 100) -> dict:
        """Return per-plugin summary + recent events, optionally filtered to one plugin.

        ``recent`` is newest-first and capped at *limit*. ``external_egress_total`` is the
        count of allowed calls that left the machine, of which ``model_egress_total`` is
        the ``llm:``-prefixed (model-backend) share; ``local_only_violations`` lists the
        plugins that *did* make an external call despite a local-only manifest (should
        always be empty — the gate blocks them — which is exactly what we want to show).

        H381: with a store, tallies and rows come from the on-disk ledger — every process
        on this data root, before and after a restart — plus this process's events still
        queued for the writer (``live``) and any event whose write failed (``unsaved``).
        ``ledger`` says which: ``persistent`` is False when there is no store or the file
        could not be read, and the figures are then this process's alone. It reads
        SQLite, so an async caller runs it in a worker thread.
        """
        limit = max(0, min(int(limit or 0), _MAX_EVENTS))
        persisted = None
        read_error = ""
        queued: list[dict] = []
        queued_total = 0
        captured: list[tuple[int, dict]] = []
        if self._store is not None:
            # Never waits for the writer. The queue is captured BEFORE the store is read:
            # an event committed in between has a sequence number at or below the one
            # committed with it (so it is counted from `persisted`); one still above it
            # was not on disk at the read; one whose write failed is in `_unsaved`.
            with self._lock:
                captured = [*self._inflight, *((seq, e) for _, seq, e in self._queued)]
            try:
                persisted = self._store.read(self._boot, plugin, limit)
            except Exception as exc:
                read_error = f"read failed: {type(exc).__name__}"
        with self._lock:
            if persisted is not None:
                written = persisted["written_seq"]
                failed = {seq for seq, _ in self._unsaved}
                waiting = [e for seq, e in captured if seq > written and seq not in failed]
                queued_total = len(waiting)
                queued = [e for e in waiting if plugin is None or e["plugin"] == plugin]
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
                extra: dict[str, _PluginStat] = {}
                for event in queued:
                    extra.setdefault(event["plugin"], _PluginStat()).add(event)
                for name, st in [*self._unsaved_stats.items(), *extra.items()]:
                    if plugin is not None and name != plugin:
                        continue
                    if name in plugins:
                        _merge_tally(plugins[name], st.as_dict())
                    else:
                        plugins[name] = st.as_dict()
                plugins = dict(sorted(plugins.items()))
                unsaved = [dict(e, origin="unsaved") for _, e in reversed(self._unsaved)
                           if plugin is None or e["plugin"] == plugin]
                waiting_rows = [dict(e, origin="live") for e in reversed(queued)]
                recent = sorted(persisted["recent"] + waiting_rows + unsaved,
                                key=lambda e: e["ts"], reverse=True)[:limit]
            ledger = {
                "persistent": persisted is not None,
                "store": LEDGER_FILE if self._store is not None else None,
                "since": persisted["since"] if persisted else None,
                "oldest_event_ts": persisted["oldest_event_ts"] if persisted else None,
                "stored_events": persisted["stored_events"] if persisted else 0,
                "restored_events": persisted["restored_events"] if persisted else 0,
                "live_events": live_total,
                "queued_events": queued_total,
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
        A forget clears the file through ``data_purge`` like any other store, inside
        :meth:`forgetting`. Queued events are written first, so none lands in the file
        after the clear.
        """
        self.flush(5.0)
        with self._flush_lock:
            with self._lock:
                self._events.clear()
                self._stats.clear()
                self._queued.clear()
                self._unsaved.clear()
                self._unsaved_stats.clear()
                self._unsaved_total = 0
                self._store_error = ""
            if self._store is not None:
                with contextlib.suppress(Exception):
                    self._store.clear()


# Module-level singleton shared by the choke point and the admin endpoint. Its writer
# thread persists to the data root's ledger file, so the proof survives a restart (H381).
EGRESS_MONITOR = EgressMonitor(store=EgressLedgerStore())
