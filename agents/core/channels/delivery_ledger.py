"""delivery_ledger.py — a durable receipt for every outbound reply, and the chats that are gone (H081).

Before this, a reply was fire-and-forget: ``ChannelManager.send`` returned a bool the
orchestrator never read, so a reply lost to an outage, a revoked bot or a crash left no
trace anywhere, while the audit log said a reply had been produced. Now every send through
the manager writes one row and moves it through honest checkpoints:

    pending      the row exists; nothing has been handed to the platform yet
    attempting   written immediately before the platform call
    sent         the platform acknowledged every part
    failed       the platform refused it, or it never left (connection refused, no chat id)
    partial      the platform took some parts and refused the rest
    unknown      the call may or may not have reached the platform (a read timeout, a crash
                 between "attempting" and the answer); the owner is told, nothing is resent
    skipped      not sent because the target is registered dead, or a duplicate of a
                 delivery that already went out (``delivery_key``)

**A crash never double-sends.** Nothing here ever resends on its own. At startup,
:meth:`ReliabilityStore.recover` closes the rows a dead process left open: ``pending``
becomes ``failed`` (provably never sent) and ``attempting`` becomes ``unknown`` (it may
have arrived). A caller that passes ``delivery_key`` gets idempotency on top: a second
send with the same key is suppressed while an earlier one is sent, in flight or unknown;
it may try again only after a definite failure, at most ``MAX_ATTEMPTS`` times.

**No message bodies.** A row keeps the channel, the target (the chat id the reply was
addressed to — the same identity ``channel_inbox`` already keeps), the length, a keyed
digest for idempotency (HMAC-SHA256 under a per-install random key, so the digest is not a
dictionary oracle for short replies) and the failure kind. Redelivering a lost reply would
need its text, so Nerva does not redeliver; it tells the owner instead (``GET
/api/channels/deliveries``).

**Dead targets.** A chat the platform says is gone for good — Telegram's 403 (bot blocked,
kicked, user deactivated) or a chat-level "chat not found" — is registered, and later sends
to it are skipped instead of retried on every job tick. A thread-level not-found (a deleted
forum topic) is never recorded. The flag heals by itself: a later successful send, or a new
inbound message from that chat, clears it; the owner can clear it too.

Retention: 7 days and 500 rows. Every ledger call is best effort — a ledger that cannot be
written never blocks a send (the send goes out and the failure is logged).

Shape adapted from Hermes ``gateway/delivery_ledger.py`` and ``gateway/dead_targets.py``
(MIT, reference only); Nerva keeps no bodies and never auto-redelivers.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.channels.delivery")

MAX_ATTEMPTS = 3
#: A delivery_key is matched against rows this recent.
IDEMPOTENCY_WINDOW_S = 24 * 3600
RETENTION_S = 7 * 24 * 3600
MAX_ROWS = 500
MAX_TARGET = 128

STATE_PENDING = "pending"
STATE_ATTEMPTING = "attempting"
STATE_SENT = "sent"
STATE_FAILED = "failed"
STATE_PARTIAL = "partial"
STATE_UNKNOWN = "unknown"
STATE_SKIPPED = "skipped"
STATES = (STATE_PENDING, STATE_ATTEMPTING, STATE_SENT, STATE_FAILED, STATE_PARTIAL,
          STATE_UNKNOWN, STATE_SKIPPED)
#: States a delivery_key may not send over again (sent, in flight, or maybe delivered).
_BLOCKING = (STATE_PENDING, STATE_ATTEMPTING, STATE_SENT, STATE_PARTIAL, STATE_UNKNOWN)

# One id per process: rows another process left open are recovered at startup.
_BOOT = uuid.uuid4().hex


def _clip(value: Any, limit: int = MAX_TARGET) -> str:
    text = "".join(ch for ch in str(value if value is not None else "") if 32 <= ord(ch) < 127)
    return text[:limit]


def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# ── what an adapter says about a failed send ────────────────────────────────


@dataclass
class SendOutcome:
    """Filled by an adapter while ``ChannelManager.send`` waits on it."""

    kind: str | None = None
    ambiguous: bool = False
    dead: bool = False
    partial: bool = False
    fatal: str | None = None


_OUTCOME: contextvars.ContextVar[SendOutcome | None] = contextvars.ContextVar(
    "channel-send-outcome", default=None)

_DEAD_400_PHRASES = ("chat not found", "user is deactivated", "group chat was deleted",
                     "chat was deleted", "peer_id_invalid")
_THREAD_PHRASES = ("thread not found", "topic", "message to reply not found",
                   "message to be replied not found")


def classify_send_failure(*, status: int | None = None, description: str = "",
                          exc: BaseException | None = None) -> SendOutcome:
    """What a failed platform send means for the ledger and the dead-target registry."""
    text = str(description or "").lower()
    if exc is not None and status is None:
        try:
            import httpx
        except ImportError:  # pragma: no cover
            httpx = None
        if httpx is not None and isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            try:
                body = exc.response.json()
                text = str(body.get("description") or "").lower() if isinstance(body, dict) else ""
            except Exception:
                text = ""
        elif httpx is not None and isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout,
                                                    httpx.PoolTimeout)):
            return SendOutcome(kind="not_connected")
        elif httpx is not None and isinstance(exc, httpx.TransportError):
            # The request may have reached the platform before the answer was lost.
            return SendOutcome(kind="no_answer", ambiguous=True)
        elif isinstance(exc, (TimeoutError, ConnectionResetError)):
            return SendOutcome(kind="no_answer", ambiguous=True)
        else:
            return SendOutcome(kind="error")
    if status is None:
        return SendOutcome(kind="error")
    if status == 401:
        return SendOutcome(kind="unauthorized", fatal="unauthorized")
    if status == 404 and "chat" not in text:
        return SendOutcome(kind="not_found", fatal="not_found")
    if status == 403:
        return SendOutcome(kind="forbidden", dead=True)
    if status in (400, 404) and any(p in text for p in _DEAD_400_PHRASES):
        if any(p in text for p in _THREAD_PHRASES):
            return SendOutcome(kind="thread_not_found")
        return SendOutcome(kind="chat_not_found", dead=True)
    if status == 429:
        return SendOutcome(kind="rate_limited")
    if 500 <= status <= 599:
        # The platform failed while handling it; it may have stored the message.
        return SendOutcome(kind="server_error", ambiguous=True)
    return SendOutcome(kind=f"http_{int(status)}")


def note_send_failure(*, status: int | None = None, description: str = "",
                      exc: BaseException | None = None, partial: bool = False,
                      channel_level: bool = False) -> None:
    """An adapter's report of why a send failed; a no-op outside ``ChannelManager.send``.
    ``channel_level``: the channel has one configured destination (ntfy's topic), so a
    refusal is the channel's credential, never a dead chat."""
    outcome = _OUTCOME.get()
    if outcome is None:
        return
    try:
        found = classify_send_failure(status=status, description=description, exc=exc)
    except Exception:
        found = SendOutcome(kind="error")
    if channel_level and found.dead:
        found.dead, found.fatal = False, found.kind
    outcome.kind = found.kind
    outcome.ambiguous = outcome.ambiguous or found.ambiguous
    outcome.dead = found.dead
    outcome.fatal = found.fatal or outcome.fatal
    outcome.partial = outcome.partial or partial


def note_partial() -> None:
    outcome = _OUTCOME.get()
    if outcome is not None:
        outcome.partial = True


def begin_outcome() -> tuple[SendOutcome, contextvars.Token]:
    outcome = SendOutcome()
    return outcome, _OUTCOME.set(outcome)


def end_outcome(token: contextvars.Token) -> None:
    try:
        _OUTCOME.reset(token)
    except ValueError:  # pragma: no cover - reset from another context
        _OUTCOME.set(None)


# ── the store ───────────────────────────────────────────────────────────────


class ReliabilityStore:
    """One SQLite file for the delivery ledger, dead targets and inbound cursors."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            from agents.core.paths import data_path
            path = data_path("channel_reliability.db")
        self.path = Path(path)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, channel TEXT NOT NULL, "
                "target TEXT NOT NULL, key TEXT, state TEXT NOT NULL, attempt INTEGER NOT NULL, "
                "error TEXT, chars INTEGER NOT NULL, digest TEXT NOT NULL, pid INTEGER NOT NULL, "
                "boot TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS deliveries_key ON deliveries(key)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS dead_targets (channel TEXT NOT NULL, target TEXT NOT NULL, "
                "reason TEXT NOT NULL, marked REAL NOT NULL, PRIMARY KEY (channel, target))")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS cursors (name TEXT PRIMARY KEY, value TEXT NOT NULL, "
                "updated REAL NOT NULL)")
            self._conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            row = self._conn.execute("SELECT v FROM meta WHERE k='digest_key'").fetchone()
            if row is None:
                key = secrets.token_hex(32)
                self._conn.execute("INSERT INTO meta (k, v) VALUES ('digest_key', ?)", (key,))
            else:
                key = row[0]
        self._digest_key = bytes.fromhex(key)
        self._dead: set[tuple[str, str]] = {
            (c, t) for c, t in self._conn.execute("SELECT channel, target FROM dead_targets")}

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── deliveries ──

    def digest(self, channel: str, target: str, body: str) -> str:
        message = "\x1f".join((channel, target, body)).encode("utf-8", "replace")
        return hmac.new(self._digest_key, message, hashlib.sha256).hexdigest()

    def open_delivery(self, channel: str, target: Any, body: Any, *,
                      key: str | None = None, now: float | None = None) -> Delivery:
        """Write the ``pending`` row; the returned handle says whether to send at all."""
        now = time.time() if now is None else now
        channel, target = _clip(channel, 32), _clip(target)
        text = str(body if body is not None else "")
        key = _clip(key, 200) if key else None
        attempt = 1
        with self._lock, self._conn:
            if key:
                rows = self._conn.execute(
                    "SELECT state FROM deliveries WHERE key=? AND channel=? AND created>=? "
                    "ORDER BY created DESC", (key, channel, now - IDEMPOTENCY_WINDOW_S)).fetchall()
                states = [r[0] for r in rows]
                if any(s in _BLOCKING for s in states):
                    duplicate_of_sent = STATE_SENT in states
                    row_id = self._insert(channel, target, key, STATE_SKIPPED, len(states) + 1,
                                          "duplicate", text, now)
                    return Delivery(self, row_id, send=False, already_sent=duplicate_of_sent)
                if len(states) >= MAX_ATTEMPTS:
                    row_id = self._insert(channel, target, key, STATE_SKIPPED, len(states) + 1,
                                          "attempts_exhausted", text, now)
                    return Delivery(self, row_id, send=False)
                attempt = len(states) + 1
            if (channel, target) in self._dead:
                row_id = self._insert(channel, target, key, STATE_SKIPPED, attempt, "dead_target",
                                      text, now)
                return Delivery(self, row_id, send=False, dead=True)
            row_id = self._insert(channel, target, key, STATE_PENDING, attempt, None, text, now)
            self._prune(now)
        return Delivery(self, row_id, send=True)

    def _insert(self, channel, target, key, state, attempt, error, text, now) -> str:
        row_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO deliveries (id, channel, target, key, state, attempt, error, chars, digest, "
            "pid, boot, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row_id, channel, target, key, state, attempt, error, len(text),
             self.digest(channel, target, text), os.getpid(), _BOOT, now, now))
        return row_id

    def _set_state(self, row_id: str, state: str, error: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE deliveries SET state=?, error=?, updated=? WHERE id=?",
                               (state, _clip(error, 40) if error else None, time.time(), row_id))

    def _prune(self, now: float) -> None:
        self._conn.execute("DELETE FROM deliveries WHERE updated < ? AND state NOT IN (?, ?)",
                           (now - RETENTION_S, STATE_PENDING, STATE_ATTEMPTING))
        self._conn.execute(
            "DELETE FROM deliveries WHERE id NOT IN (SELECT id FROM deliveries ORDER BY created DESC "
            "LIMIT ?) AND state NOT IN (?, ?)", (MAX_ROWS, STATE_PENDING, STATE_ATTEMPTING))

    def recover(self, *, alive=None) -> dict:
        """Close the rows a dead process left open. Never resends anything: a ``pending`` row
        never reached the platform (``failed``), an ``attempting`` one may have (``unknown``)."""
        alive = alive or _pid_alive
        counts = {"failed": 0, "unknown": 0}
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT id, state, pid, boot FROM deliveries WHERE state IN (?, ?)",
                (STATE_PENDING, STATE_ATTEMPTING)).fetchall()
            now = time.time()
            for row_id, state, pid, boot in rows:
                if boot == _BOOT or alive(pid):
                    continue
                if state == STATE_PENDING:
                    self._conn.execute("UPDATE deliveries SET state=?, error=?, updated=? WHERE id=?",
                                       (STATE_FAILED, "interrupted_before_send", now, row_id))
                    counts["failed"] += 1
                else:
                    self._conn.execute("UPDATE deliveries SET state=?, error=?, updated=? WHERE id=?",
                                       (STATE_UNKNOWN, "interrupted_during_send", now, row_id))
                    counts["unknown"] += 1
        if counts["failed"] or counts["unknown"]:
            logger.warning("Delivery ledger: %d reply(ies) interrupted before sending, %d during "
                           "sending (may have arrived); none is resent", counts["failed"],
                           counts["unknown"])
        return counts

    def recent(self, limit: int = 50, *, channel: str | None = None,
               states: tuple[str, ...] | None = None) -> list[dict]:
        limit = max(1, min(int(limit or 50), MAX_ROWS))
        query = ("SELECT id, channel, target, state, attempt, error, chars, created, updated, key "
                 "FROM deliveries")
        where, args = [], []
        if channel:
            where.append("channel=?")
            args.append(_clip(channel, 32))
        if states:
            where.append(f"state IN ({','.join('?' * len(states))})")
            args.extend(states)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r) -> dict:
        return {"id": r[0], "channel": r[1], "target": r[2], "state": r[3], "attempt": r[4],
                "error": r[5], "chars": r[6], "created": round(r[7], 3), "updated": round(r[8], 3),
                "keyed": bool(r[9])}

    def get(self, row_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, channel, target, state, attempt, error, chars, created, updated, key "
                "FROM deliveries WHERE id=?", (row_id,)).fetchone()
        return self._row(row) if row else None

    def stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT state, COUNT(*) FROM deliveries GROUP BY state").fetchall()
        counts = dict.fromkeys(STATES, 0)
        counts.update(dict(rows))
        return {"by_state": counts, "needs_attention": counts[STATE_FAILED] + counts[STATE_PARTIAL]
                + counts[STATE_UNKNOWN], "dead_targets": len(self._dead)}

    # ── dead targets ──

    def is_dead(self, channel: str, target: Any) -> bool:
        return (_clip(channel, 32), _clip(target)) in self._dead

    def mark_dead(self, channel: str, target: Any, reason: str) -> bool:
        key = (_clip(channel, 32), _clip(target))
        if not key[1]:
            return False
        with self._lock, self._conn:
            new = key not in self._dead
            self._conn.execute(
                "INSERT OR REPLACE INTO dead_targets (channel, target, reason, marked) VALUES (?,?,?,?)",
                (*key, _clip(reason, 40), time.time()))
            self._dead.add(key)
        if new:
            logger.info("Delivery: a %s chat is unreachable (%s); later sends to it are skipped "
                        "until it writes again or a send succeeds", key[0], reason)
        return new

    def clear_dead(self, channel: str, target: Any) -> bool:
        key = (_clip(channel, 32), _clip(target))
        if key not in self._dead:
            return False
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM dead_targets WHERE channel=? AND target=?", key)
            self._dead.discard(key)
        return True

    def dead_targets(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT channel, target, reason, marked FROM dead_targets ORDER BY marked DESC").fetchall()
        return [{"channel": c, "target": t, "reason": r, "marked": round(m, 3)} for c, t, r, m in rows]

    # ── inbound cursors (H116) ──

    def cursor(self, name: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM cursors WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def set_cursor(self, name: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO cursors (name, value, updated) VALUES (?,?,?)",
                               (name, str(value)[:16_384], time.time()))


class Delivery:
    """One send's ledger row. Every method is best effort and never raises."""

    def __init__(self, store: ReliabilityStore | None, row_id: str | None, *,
                 send: bool, already_sent: bool = False, dead: bool = False) -> None:
        self.store = store
        self.id = row_id
        self.send = send
        self.already_sent = already_sent
        self.dead = dead

    def _set(self, state: str, error: str | None = None) -> None:
        if self.store is None or self.id is None:
            return
        try:
            self.store._set_state(self.id, state, error)
        except Exception:
            logger.warning("Delivery ledger write failed (%s)", state, exc_info=True)

    def attempting(self) -> None:
        self._set(STATE_ATTEMPTING)

    def finished(self, ok: bool, outcome: SendOutcome | None = None) -> str:
        outcome = outcome or SendOutcome()
        if ok:
            state, error = STATE_SENT, None
        elif outcome.partial:
            state, error = STATE_PARTIAL, outcome.kind or "partial"
        elif outcome.ambiguous:
            state, error = STATE_UNKNOWN, outcome.kind or "no_answer"
        else:
            state, error = STATE_FAILED, outcome.kind or "not_sent"
        self._set(state, error)
        return state

    def raised(self, exc: BaseException) -> None:
        # The adapter raised mid-send: it may or may not have reached the platform.
        self._set(STATE_UNKNOWN, type(exc).__name__)


_STORE: ReliabilityStore | None = None
_STORE_LOCK = threading.Lock()


def store() -> ReliabilityStore | None:
    """The process store (``<data>/channel_reliability.db``), or None when it cannot open."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            try:
                _STORE = ReliabilityStore()
            except Exception:
                logger.warning("Channel reliability store unavailable", exc_info=True)
                return None
        return _STORE


def set_store(value: ReliabilityStore | None) -> None:
    """Swap the process store (tests; a profile switch)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = value


__all__ = [
    "Delivery", "IDEMPOTENCY_WINDOW_S", "MAX_ATTEMPTS", "MAX_ROWS", "ReliabilityStore",
    "RETENTION_S", "STATES", "SendOutcome", "begin_outcome", "classify_send_failure",
    "end_outcome", "note_partial", "note_send_failure", "set_store", "store",
]
