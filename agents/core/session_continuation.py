"""Explicit continuation: immutable seed and lineage share the checkpoint commit."""

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime

from .conversation_clock import ClockSnapshot, parse_started_at
from .validation import is_valid_session_id

MAX_SEED_BYTES = 512 * 1024
MAX_TURNS = 100
MAX_DEPTH = 128


class ContinuationRefused(RuntimeError):
    def __init__(self, reason="continuation_unavailable", status=409):
        self.reason, self.status = reason, status
        super().__init__(reason)


def initialize(conn):
    for table in ("sessions", "session_clock"):
        if "instance_id" not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN instance_id TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE sessions SET instance_id=lower(hex(randomblob(16))) WHERE instance_id=''")
    conn.execute(
        "UPDATE session_clock SET instance_id=COALESCE((SELECT instance_id FROM sessions WHERE id=session_id), '') WHERE instance_id=''"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS session_history_instances (
        session_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, allow_legacy INTEGER NOT NULL DEFAULT 0
    )""")
    conn.execute(
        "INSERT OR IGNORE INTO session_history_instances SELECT id, instance_id, 1 FROM sessions"
    )
    conn.execute("DROP TRIGGER IF EXISTS session_instance_on_insert")
    conn.execute("""CREATE TRIGGER session_instance_on_insert AFTER INSERT ON sessions
        BEGIN UPDATE sessions SET instance_id=lower(hex(randomblob(16))) WHERE id=NEW.id AND instance_id='';
        INSERT OR IGNORE INTO session_history_instances(session_id,instance_id,allow_legacy)
        SELECT id,instance_id,0 FROM sessions WHERE id=NEW.id; END""")
    conn.execute("""CREATE TABLE IF NOT EXISTS session_continuations (
        session_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE,
        parent_id TEXT NOT NULL, parent_instance_id TEXT NOT NULL,
        root_id TEXT NOT NULL, root_instance_id TEXT NOT NULL, root_birth_at TEXT NOT NULL,
        seed_json TEXT NOT NULL, seed_sha256 TEXT NOT NULL, created_at TEXT NOT NULL
    )""")


def identity(conn, sid):
    row = conn.execute("SELECT started_at, instance_id FROM sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        return None
    lineage = conn.execute(
        "SELECT instance_id, root_birth_at FROM session_continuations WHERE session_id=?", (sid,)
    ).fetchone()
    if lineage and lineage[0] != row[1]:
        return None
    birth = parse_started_at(lineage[1] if lineage else row[0])
    return (birth, row[1]) if birth else None


def history_identity(conn, sid):
    current = identity(conn, sid)
    binding = conn.execute(
        "SELECT instance_id,allow_legacy FROM session_history_instances WHERE session_id=?", (sid,)
    ).fetchone()
    if current is None or binding is None or binding[0] != current[1]:
        raise ContinuationRefused("history_identity_changed")
    return binding


def validate_seed(row):
    try:
        if not isinstance(row[8], str):
            raise ValueError
        raw = row[8].encode("utf-8")
        if len(raw) > MAX_SEED_BYTES or hashlib.sha256(raw).hexdigest() != row[9]:
            raise ValueError
        turns = json.loads(raw)
        if seed_json(turns) != row[8]:
            raise ValueError
        return turns
    except (ValueError, TypeError, UnicodeError, RecursionError, ContinuationRefused):
        raise ContinuationRefused("invalid_history") from None


def seed_json(turns):
    if not isinstance(turns, list) or not 0 < len(turns) <= MAX_TURNS:
        raise ContinuationRefused("invalid_or_oversized_history")
    result = []
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("role") not in {"user", "assistant", "system"}:
            raise ContinuationRefused("invalid_history")
        content = turn.get("content")
        agent = turn.get("agent_id")
        timestamp = turn.get("timestamp")
        count = turn.get("token_count", 0)
        if (
            not isinstance(content, str)
            or (agent is not None and not isinstance(agent, str))
            or parse_started_at(timestamp) is None
            or type(count) is not int
            or count < 0
        ):
            raise ContinuationRefused("invalid_history")
        result.append(
            {
                "role": turn["role"],
                "content": content,
                "agent_id": agent,
                "timestamp": timestamp,
                "token_count": count,
            }
        )
    try:
        value = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(value.encode("utf-8")) > MAX_SEED_BYTES:
            raise ContinuationRefused("invalid_or_oversized_history")
    except (TypeError, ValueError, UnicodeError):
        raise ContinuationRefused("invalid_history") from None
    return value


class ContinuationStore:
    def __init__(self, checkpoints):
        self.cp = checkpoints
        if checkpoints._conn is None:
            raise ContinuationRefused("continuation_unavailable", 503)

    def _receipt(self, row):
        # Never return seed bytes through the creation/status receipt.
        (
            sid,
            instance,
            request,
            parent,
            parent_instance,
            root,
            root_instance,
            birth,
            seed,
            digest,
            created,
        ) = row
        current = identity(self.cp._conn, sid)
        if current is None or current[1] != instance:
            raise ContinuationRefused("continuation_identity_changed")
        return {
            "session_id": sid,
            "parent_session_id": parent,
            "root_session_id": root,
            "request_id": request,
            "started_at": created,
            "conversation_started_at": birth,
            "carried_turns": len(validate_seed(row)),
        }

    def _replay(self, source, request):
        row = self.cp._conn.execute(
            "SELECT * FROM session_continuations WHERE request_id=?", (request,)
        ).fetchone()
        if row:
            parent = identity(self.cp._conn, source)
            if row[3] != source or parent is None or row[4] != parent[1]:
                raise ContinuationRefused("request_id_conflict")
            return self._receipt(row)
        return None

    def replay(self, source, request):
        with self.cp._lock:
            return self._replay(source, request)

    def seed(self, sid):
        with self.cp._lock:
            row = self.cp._conn.execute(
                "SELECT * FROM session_continuations WHERE session_id=?", (sid,)
            ).fetchone()
            if row is None:
                return None
            self._receipt(row)
            return validate_seed(row)

    def create(self, source, request, turns, clock):
        try:
            if not is_valid_session_id(source) or str(uuid.UUID(request)) != request:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ContinuationRefused("invalid_identifier", 422) from None
        value = seed_json(turns)
        if not isinstance(clock, ClockSnapshot) or clock.session_id != source:
            raise ContinuationRefused("source_clock_unavailable")
        conn = self.cp._conn
        if conn is None:
            raise ContinuationRefused("continuation_unavailable", 503)
        try:
            with self.cp._lock, conn:
                conn.execute("BEGIN IMMEDIATE")
                replay = self._replay(source, request)
                if replay:
                    return replay
                history_identity(conn, source)
                parent = identity(conn, source)
                if parent != (clock.started_at, clock.instance_id):
                    raise ContinuationRefused("source_identity_changed")
                current = conn.execute(
                    "SELECT revision, rebuilt_at FROM session_clock WHERE session_id=? AND instance_id=?",
                    (source, clock.instance_id),
                ).fetchone()
                if current != (clock.revision, clock.rebuilt_at.isoformat()):
                    raise ContinuationRefused("source_clock_changed")
                seen, cursor, root, root_instance = set(), source, source, parent[1]
                for _ in range(MAX_DEPTH):
                    if cursor in seen:
                        raise ContinuationRefused("invalid_ancestry")
                    seen.add(cursor)
                    current_identity = identity(conn, cursor)
                    if current_identity is None:
                        raise ContinuationRefused("invalid_ancestry")
                    ancestor = conn.execute(
                        "SELECT * FROM session_continuations WHERE session_id=?", (cursor,)
                    ).fetchone()
                    if not ancestor:
                        if current_identity[0] != clock.started_at:
                            raise ContinuationRefused("invalid_ancestry")
                        root, root_instance = cursor, current_identity[1]
                        break
                    upstream = identity(conn, ancestor[3])
                    if (
                        upstream is None
                        or upstream[1] != ancestor[4]
                        or current_identity[0] != clock.started_at
                    ):
                        raise ContinuationRefused("invalid_ancestry")
                    cursor = ancestor[3]
                else:
                    raise ContinuationRefused("invalid_ancestry")
                for previous in seen:
                    ancestor = conn.execute(
                        "SELECT root_id, root_instance_id FROM session_continuations WHERE session_id=?",
                        (previous,),
                    ).fetchone()
                    if ancestor and ancestor != (root, root_instance):
                        raise ContinuationRefused("invalid_ancestry")
                sid, instance = "session_" + uuid.uuid4().hex, uuid.uuid4().hex
                now = datetime.now(UTC).isoformat()
                conn.execute(
                    "INSERT INTO sessions(id, started_at, turn_count, instance_id) VALUES(?,?,?,?)",
                    (sid, now, len(turns), instance),
                )
                conn.execute(
                    "INSERT INTO session_continuations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sid,
                        instance,
                        request,
                        source,
                        parent[1],
                        root,
                        root_instance,
                        clock.started_at.isoformat(),
                        value,
                        hashlib.sha256(value.encode()).hexdigest(),
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO session_clock(session_id,birth_at,revision,rebuilt_at,instance_id) VALUES(?,?,0,?,?)",
                    (sid, clock.started_at.isoformat(), clock.rebuilt_at.isoformat(), instance),
                )
                result = self._replay(source, request)
            return result
        except sqlite3.Error:
            # Commit may have succeeded before the caller learned its outcome.
            with self.cp._lock:
                replay = self._replay(source, request)
            if replay:
                return replay
            raise ContinuationRefused("continuation_unavailable", 503) from None


def _load_locked(orch, sid):
    """Caller holds manager then conversation lock; never switches current ID."""
    from .memory import persistence
    from .memory.conversation import Turn

    conversation = orch.memory.conversation
    with orch.checkpoints._lock:
        instance, legacy = history_identity(orch.checkpoints._conn, sid)
    if sid in conversation.sessions:
        known = conversation.instances.get(sid)
        if known != instance and not (known is None and legacy):
            raise ContinuationRefused("history_identity_changed")
        turns = [turn.to_dict() for turn in conversation.sessions[sid]]
        seed_json(turns)
        return turns
    path = persistence.memory_dir() / f"{sid}.json"
    if path.exists():
        # Never silently fall back to an old seed when a newer snapshot is corrupt.
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_SEED_BYTES + 4097)
            if len(raw) > MAX_SEED_BYTES + 4096:
                raise ValueError
            document = json.loads(raw)
            if not isinstance(document, dict) or document.get("session_id") != sid:
                raise ValueError
            known = document.get("instance_id")
            if known != instance and not (known is None and legacy):
                raise ContinuationRefused("history_identity_changed")
            turns = document.get("turns")
            seed_json(turns)
        except (OSError, ValueError, TypeError):
            raise ContinuationRefused("invalid_history") from None
    else:
        turns = ContinuationStore(orch.checkpoints).seed(sid)
        if turns is None:
            raise ContinuationRefused("session_not_found", 404)
    restored = []
    for value in turns:
        turn = Turn(
            value["role"], value["content"], value.get("agent_id"), value.get("token_count", 0)
        )
        turn.timestamp = value["timestamp"]
        restored.append(turn)
    conversation.sessions[sid] = restored
    conversation.instances[sid] = instance
    return turns


async def prepare_session(orch, sid):
    """Load an explicitly addressed existing session without resuming the default."""
    if not is_valid_session_id(sid):
        raise ContinuationRefused("invalid_identifier", 422)
    if orch.checkpoints._conn is None:
        raise ContinuationRefused("continuation_unavailable", 503)
    with orch.checkpoints._lock:
        if identity(orch.checkpoints._conn, sid) is None:
            raise ContinuationRefused("session_not_found", 404)
    async with orch.memory._lock, orch.memory.conversation._lock:
        _load_locked(orch, sid)


async def create_continuation(orch, source, request):
    try:
        if not is_valid_session_id(source) or str(uuid.UUID(request)) != request:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ContinuationRefused("invalid_identifier", 422) from None
    store = ContinuationStore(orch.checkpoints)
    replay = store.replay(source, request)
    if replay:
        return replay
    async with orch.turn_lease(source) as acquired:
        if not acquired:
            raise ContinuationRefused("source_busy")
        async with orch.memory._lock, orch.memory.conversation._lock:
            clock = orch.checkpoints.clock_snapshot(source)
            if clock is None:
                raise ContinuationRefused("source_clock_unavailable")
            turns = _load_locked(orch, source)
            # No await from captured history through the one SQLite activation
            # commit. Cancellation/response loss after commit resolves by request ID.
            return store.create(source, request, turns, clock)


CONTINUATION_REFUSED_REPLY = (
    "I stopped this turn because this continued conversation could not be safely restored."
)


async def prepare_continuation_turn(orch, sid):
    """Guard continued sessions at the common entry, including restored defaults."""
    manager = getattr(orch, "checkpoints", None)
    if manager is None or getattr(manager, "_conn", None) is None:
        return
    with manager._lock:
        continued = manager._conn.execute(
            "SELECT 1 FROM session_continuations WHERE session_id=?", (sid,)
        ).fetchone()
    if continued is not None:
        await prepare_session(orch, sid)
