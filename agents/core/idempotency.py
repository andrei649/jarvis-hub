"""H659 — a retried external request returns the original run instead of starting a second one.

A sender that times out retries; before this, every retry of ``POST /api/actions/request``
queued a second approval card, every redelivered webhook ran a second turn (or sent the
owner a second message), and every re-sent A2A task became a second inbox row. Hermes
answers with an ``Idempotency-Key`` header, and so does Nerva:

- **The key.** 1–255 visible ASCII characters (``!`` … ``~``); anything else is refused with
  HTTP 400 ``invalid_idempotency_key`` before any work. No header: the request runs as it
  always did.
- **The reservation.** A row ``UNIQUE(scope, key)`` in a SQLite file, taken inside
  ``BEGIN IMMEDIATE`` so two workers or two processes cannot both win it, and surviving a
  restart. The scope comes from the authenticated caller (the webhook's id, the A2A peer, the
  owner's action intake), so two callers cannot collide on one key. The row stores the
  request's fingerprint (SHA-256 of method, path and body) and the *public* reference of what
  the request started (an action id, an inbox receipt, a webhook's outcome) — never the body,
  a reply or a credential.
- **The answer to a retry.** The same key with the same fingerprint returns the original
  reference with ``Idempotent-Replayed: true``, and nothing runs again. The same key with a
  different body is refused (409 ``idempotency_key_reused``). A retry while the first is still
  running is told to wait (409 ``idempotency_in_progress``, ``Retry-After``). A first attempt
  that failed (an exception or a 5xx) releases its key, so the retry runs; a first attempt that
  was abandoned by a dead process is taken over after :data:`STALE_PENDING_SECONDS`.
- **Placement.** The reservation is taken after the caller is authenticated and before the
  request is queued or run, so a duplicate never becomes a second approval item, a second
  kernel task or a second audit row. When the store cannot be written, a request that carries a
  key is refused (503 ``idempotency_unavailable``) rather than run without its guarantee.

Rows expire after :data:`TTL_SECONDS`; the store reports whether it is ``durable`` (a file,
not ``:memory:``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.idempotency")

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
MAX_KEY_CHARS = 255
TTL_SECONDS = 24 * 3600
STALE_PENDING_SECONDS = 600
BUSY_TIMEOUT_SECONDS = 5.0
MAX_REF_BYTES = 2_048

_KEY_RE = re.compile(rf"[\x21-\x7e]{{1,{MAX_KEY_CHARS}}}")

NEW, REPLAY, CONFLICT, IN_PROGRESS = "new", "replay", "conflict", "in_progress"
PENDING, DONE = "pending", "done"


class InvalidKey(ValueError):
    """The ``Idempotency-Key`` header is present but not 1–255 visible ASCII characters."""


def parse_key(value: str | None) -> str | None:
    """The header's key, ``None`` when the header is absent; :class:`InvalidKey` otherwise."""
    if value is None:
        return None
    if not isinstance(value, str) or not _KEY_RE.fullmatch(value):
        raise InvalidKey("Idempotency-Key must be 1-255 visible ASCII characters")
    return value


def fingerprint(method: str, path: str, body: bytes) -> str:
    """SHA-256 over the method, the path and the raw body — what makes a retry the same request."""
    digest = hashlib.sha256()
    for part in (str(method).upper().encode(), str(path).encode(), bytes(body or b"")):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


@dataclass(frozen=True)
class Reservation:
    state: str
    ref: dict | None = None
    status_code: int | None = None


class IdempotencyStore:
    """The durable ``UNIQUE(scope, key)`` reservations."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            from agents.core.paths import data_path
            path = data_path("idempotency.db")
        self.path = str(path)
        self._memory: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS idempotency ("
                " scope TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,"
                " state TEXT NOT NULL, ref TEXT, status_code INTEGER,"
                " created_at REAL NOT NULL, updated_at REAL NOT NULL,"
                " PRIMARY KEY (scope, key))")

    @property
    def durable(self) -> bool:
        """Whether a reservation survives this process (a file, not ``:memory:``)."""
        return self.path != ":memory:"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self.durable:
            if self._memory is None:
                self._memory = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
            yield self._memory
            return
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
        finally:
            conn.close()

    def reserve(self, scope: str, key: str, fp: str, *, now: float | None = None) -> Reservation:
        """Take ``(scope, key)`` for this fingerprint, or say why not: a replay of a finished
        request (with its reference), a different request under the same key, or one in flight."""
        now = time.time() if now is None else now
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM idempotency WHERE created_at < ?", (now - TTL_SECONDS,))
                row = conn.execute(
                    "SELECT fingerprint, state, ref, status_code, updated_at FROM idempotency"
                    " WHERE scope=? AND key=?", (scope, key)).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO idempotency (scope, key, fingerprint, state, ref, status_code,"
                        " created_at, updated_at) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)",
                        (scope, key, fp, PENDING, now, now))
                    result = Reservation(NEW)
                elif row[0] != fp:
                    result = Reservation(CONFLICT)
                elif row[1] == DONE:
                    result = Reservation(REPLAY, _load_ref(row[2]), row[3])
                elif now - row[4] >= STALE_PENDING_SECONDS:
                    # The first attempt's process died before it finished: the retry takes over.
                    conn.execute("UPDATE idempotency SET updated_at=? WHERE scope=? AND key=?",
                                 (now, scope, key))
                    result = Reservation(NEW)
                else:
                    result = Reservation(IN_PROGRESS)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return result

    def complete(self, scope: str, key: str, fp: str, ref: dict, status_code: int = 200) -> bool:
        """Record what the reserved request started (its public reference only)."""
        text = json.dumps(ref, ensure_ascii=False, sort_keys=True, default=str)
        if len(text.encode()) > MAX_REF_BYTES:
            raise ValueError("an idempotency reference is a public id or status, not a body")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE idempotency SET state=?, ref=?, status_code=?, updated_at=?"
                " WHERE scope=? AND key=? AND fingerprint=? AND state=?",
                (DONE, text, int(status_code), time.time(), scope, key, fp, PENDING))
            return cur.rowcount == 1

    def release(self, scope: str, key: str, fp: str) -> bool:
        """Give a failed first attempt's key back, so its retry runs."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM idempotency WHERE scope=? AND key=? AND fingerprint=? AND state=?",
                (scope, key, fp, PENDING))
            return cur.rowcount == 1

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0])


def _load_ref(text: str | None) -> dict:
    try:
        ref = json.loads(text or "{}")
    except ValueError:
        return {}
    return ref if isinstance(ref, dict) else {}


_store: IdempotencyStore | None = None
_store_lock = threading.Lock()


def get_store() -> IdempotencyStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = IdempotencyStore()
        return _store


def set_store(store: IdempotencyStore | None) -> None:
    """Swap the process store (tests; ``None`` makes the next use open the default file)."""
    global _store
    with _store_lock:
        _store = store


# ── the route side ──────────────────────────────────────────────────────────────

@dataclass
class Claim:
    """A reservation this request holds: finish it with :meth:`done` or give it back."""

    store: IdempotencyStore
    scope: str
    key: str
    fp: str

    def done(self, ref: dict, status_code: int = 200) -> None:
        try:
            self.store.complete(self.scope, self.key, self.fp, ref, status_code)
        except Exception:
            logger.warning("idempotency: could not record the outcome of %s", self.scope, exc_info=True)

    def release(self) -> None:
        try:
            self.store.release(self.scope, self.key, self.fp)
        except Exception:
            logger.warning("idempotency: could not release a key in %s", self.scope, exc_info=True)


@dataclass
class Begin:
    """What a route does next: run under ``claim``, answer ``refusal``, or replay ``replay``."""

    claim: Claim | None = None
    refusal: Any = None
    replay: Reservation | None = None


def _json(status_code: int, error: str, detail: str, headers: dict | None = None):
    from fastapi.responses import JSONResponse

    return JSONResponse({"error": error, "detail": detail}, status_code=status_code,
                        headers={"Cache-Control": "no-store", **(headers or {})})


def check_header(request) -> Any:
    """A 400 response for a malformed header, else ``None`` (checked before any other work)."""
    try:
        parse_key(request.headers.get(HEADER))
    except InvalidKey as exc:
        return _json(400, "invalid_idempotency_key", str(exc))
    return None


def begin(request, scope: str, body: bytes, *, store: IdempotencyStore | None = None) -> Begin:
    """Reserve the request's key in ``scope`` (the authenticated caller). No header: an empty
    :class:`Begin`, and the route runs as before."""
    try:
        key = parse_key(request.headers.get(HEADER))
    except InvalidKey as exc:
        return Begin(refusal=_json(400, "invalid_idempotency_key", str(exc)))
    if key is None:
        return Begin()
    fp = fingerprint(request.method, request.url.path, body)
    try:
        store = store or get_store()
        got = store.reserve(scope, key, fp)
    except Exception:
        logger.warning("idempotency: the store could not be written for %s", scope, exc_info=True)
        return Begin(refusal=_json(503, "idempotency_unavailable",
                                   "the request carries an Idempotency-Key but it could not be reserved"))
    if got.state == NEW:
        return Begin(claim=Claim(store, scope, key, fp))
    if got.state == REPLAY:
        return Begin(replay=got)
    if got.state == CONFLICT:
        return Begin(refusal=_json(409, "idempotency_key_reused",
                                   "this Idempotency-Key was already used for a different request"))
    return Begin(refusal=_json(409, "idempotency_in_progress",
                               "a request with this Idempotency-Key is still running", {"Retry-After": "1"}))


def replayed(body: dict, status_code: int = 200):
    """The answer to a replay: the original reference, marked as replayed."""
    from fastapi.responses import JSONResponse

    return JSONResponse({**body, "replayed": True}, status_code=status_code,
                        headers={"Cache-Control": "no-store", REPLAYED_HEADER: "true"})


__all__ = [
    "Begin", "Claim", "HEADER", "IdempotencyStore", "InvalidKey", "REPLAYED_HEADER", "Reservation",
    "STALE_PENDING_SECONDS", "TTL_SECONDS", "begin", "check_header", "fingerprint", "get_store",
    "parse_key", "replayed", "set_store",
]
