"""
queue.py — Autonomy Loop & Self-Tasking Queue (H6.1).

SQLite-backed task queue with a strict state machine:

    proposed → approved → running → done | failed
       │          │
       │          └→ blocked  (needs a human decision)
       └→ blocked / rejected / deferred

Hard bounds (anti-AutoGPT, from the research): retry cap, no re-entry after a
terminal state, append-only audit via the security AuditLogger (wired by the
worker). See docs/superpowers/specs/2026-05-31-horizon6-autonomous-jarvis-design.md.
"""

from __future__ import annotations

if __name__ != "agents.core.autonomy.queue":
    raise ImportError("TaskQueue authority must be imported as agents.core.autonomy.queue")

import hashlib
import json
import logging
import math
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from agents.core.approval_outcomes import (
    MAX_PER_CONSUMER,
    MAX_PER_TURN,
    TERMINAL_RETENTION_DAYS,
    ApprovalTurnContext,
    current_tool_approval,
    render_chat_outcomes,
)
from agents.core.autonomy.mediation import (
    ZERO_HASH,
    DetachedHMACSigner,
    KernelIntakeEvidence,
    MediationEvent,
    MediationHead,
    MediationReceipt,
    MonotonicHeadAnchor,
    ReceiptExpectation,
    canonical_digest,
    canonical_json,
    make_event,
    verify_event_chain,
    verify_intake_evidence,
    verify_receipt,
)
from agents.core.env_config import env_str
from agents.core.paths import data_path

from .consent_ledger import ConsentCategory, ConsentLedger, _valid_context
from .consent_types import (
    ConsentClaim,
    ConsentDecisionResult,
    ConsentDescriptor,
    ConsentOffer,
    OwnerConsentActor,
)
from .decision_reasons import normalize_reason
from .owner_once import OwnerOnceClaim, OwnerOnceOffer, OwnerOnceOwner
from .smart_approvals import SmartApprovalResult

logger = logging.getLogger("jarvis.autonomy.queue")

DEFAULT_DB = data_path("autonomy.db")
MAX_ATTEMPTS = 3
_DATABASE_INIT_LOCK = threading.Lock()
_HUMAN_REASON_UNSET = object()
_SMART_TERMINAL_PURPOSE = "nerva.smart-terminal-approval"
_SMART_EXECUTION_PURPOSE = "nerva.smart-terminal-execution"
_OWNER_ONCE_PURPOSE = "nerva.owner-once-terminal-approval"
_OWNER_ONCE_EXECUTION_PURPOSE = "nerva.owner-once-terminal-execution"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_GUARDIAN_EPOCH_HEX = re.compile(r"[0-9a-f]{32}\Z")
_TERMINAL_TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_GUARDIAN_DENIAL_LIMIT = 1_000_000
_GUARDIAN_CONSUMER_LIMIT = 256
_OWNER_ONCE_LIMIT = 256


def _guardian_denial_threshold() -> int:
    """Read the trusted live warning threshold; zero disables warnings."""
    raw = env_str("JARVIS_SMART_DENIAL_BREAKER_THRESHOLD", "3").strip()
    if re.fullmatch(r"[+-]?[0-9]+", raw) is None:
        return 3
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 3
    return min(_GUARDIAN_DENIAL_LIMIT, value) if value > 0 else 0


def _smart_terminal_args(task: Task) -> dict | None:
    """Accept only a bounded, exact ToolRPC terminal request."""
    payload = task.payload
    if (
        task.kind != "toolrpc.terminal_run"
        or task.autonomy_level != "ask"
        or type(payload) is not dict
        or not {"tool", "args"} <= set(payload)
        or set(payload) - {"tool", "args", "target", "tainted", "taint_source"}
        or payload.get("tool") != "terminal_run"
        or ("target" in payload and payload["target"] != "terminal_run")
    ):
        return None
    if ("tainted" in payload and payload["tainted"] is not True) or (
        "taint_source" in payload and (
            payload.get("tainted") is not True
            or type(payload["taint_source"]) is not str
            or not payload["taint_source"]
            or len(payload["taint_source"]) > 256
            or "\x00" in payload["taint_source"]
        )
    ):
        return None
    args = payload.get("args")
    if type(args) is not dict or not {"target", "command"} <= set(args):
        return None
    if set(args) - {"target", "command", "cwd", "timeout"}:
        return None
    target, command = args["target"], args["command"]
    if (
        type(target) is not str or _TERMINAL_TARGET.fullmatch(target) is None
        or type(command) is not str or not command.strip() or len(command) > 4000
        or "\x00" in command
    ):
        return None
    if "cwd" in args and (
        type(args["cwd"]) is not str or len(args["cwd"]) > 1024 or "\x00" in args["cwd"]
    ):
        return None
    if "timeout" in args and (
        type(args["timeout"]) is not int or not 1 <= args["timeout"] <= 600
    ):
        return None
    return args


def normalize_approval_deadline(value: str | None) -> str | None:
    """Validate an explicit aware ISO instant; no implicit expiry window."""
    if value is None:
        return None
    if (type(value) is not str or len(value) > 64
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value)):
        raise ValueError('approval deadline must be an aware ISO datetime')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return instant.astimezone(timezone.utc).isoformat(timespec='microseconds')
    except (ValueError, OverflowError) as exc:
        raise ValueError('approval deadline must be a valid UTC instant') from exc


def _approval_now(now: datetime | None = None) -> datetime:
    instant = datetime.now(timezone.utc) if now is None else now
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('approval clock must be an aware datetime')
    try:
        return instant.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError('approval clock must be a valid UTC instant') from exc


def approval_is_pending(task: Task, *, now: datetime | None = None) -> bool:
    instant = _approval_now(now)
    if task.status not in {'proposed', 'blocked'}:
        return False
    try:
        deadline = normalize_approval_deadline(task.approval_deadline_at)
        return deadline is None or datetime.fromisoformat(deadline) > instant
    except ValueError:
        return False


def _canonical_mediation_classification(kind: str) -> bool | None:
    """Project the canonical Action Kernel registry into the persisted-task universe."""

    try:
        from agents.core.kernel.registry import Mediation, classify

        # The registered ToolRPC terminal producer persists its queue task as
        # toolrpc.terminal_run, while the physical Action Kernel owns
        # terminal.exec. Only this exact producer kind uses that contract;
        # other toolrpc kinds remain unclassified by the kernel registry.
        registry_kind = "terminal.exec" if kind == "toolrpc.terminal_run" else kind
        mediation = classify(registry_kind)
        if mediation is Mediation.KERNEL:
            return True
        if mediation is Mediation.INTENTIONALLY_DIRECT:
            return False
    except Exception:
        logger.warning("canonical mediation classification failed closed", exc_info=True)
    return None


class TaskStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    QUARANTINED = "quarantined"
    EXPIRED = "expired"


TERMINAL = {
    TaskStatus.DONE,
    TaskStatus.FAILED,
    TaskStatus.REJECTED,
    TaskStatus.QUARANTINED,
    TaskStatus.EXPIRED,
}

# Allowed transitions. Keys/values are TaskStatus.
_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PROPOSED: {
        TaskStatus.APPROVED,
        TaskStatus.BLOCKED,
        TaskStatus.REJECTED,
        TaskStatus.DEFERRED,
    },
    TaskStatus.BLOCKED: {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.DEFERRED},
    TaskStatus.DEFERRED: {TaskStatus.APPROVED, TaskStatus.BLOCKED, TaskStatus.REJECTED},
    TaskStatus.APPROVED: {TaskStatus.RUNNING, TaskStatus.BLOCKED},
    TaskStatus.RUNNING: {
        TaskStatus.DONE,
        TaskStatus.FAILED,
        TaskStatus.APPROVED,
    },  # APPROVED = retry
    # terminal states have no outgoing transitions
    TaskStatus.DONE: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.REJECTED: set(),
    TaskStatus.QUARANTINED: set(),
    TaskStatus.EXPIRED: set(),
}


class TaskQueueError(Exception):
    """Raised on an illegal state transition."""


class MediationStateUnavailable(TaskQueueError):
    """The mediated-execution state could not be read or checked — the database, the
    head anchor or the receipt signer raised (review round 6, item 2). Machinery, not a
    governance answer: a caller reports it as a failure (``mediation_state_unavailable``),
    never as the hold ``mediation_execution_required`` that a task the store holds but
    does not authorise gets (``validate_mediated_execution`` returns False for that)."""


@dataclass
class Task:
    id: int
    agent: str
    kind: str
    title: str
    payload: dict
    risk_tier: int
    status: str
    autonomy_level: str
    # Keyword-only default keeps direct pre-H33 Task construction compatible
    # while preserving the legacy queue behavior for unsolicited decisions.
    attention_mode: str = field(default="interrupt", kw_only=True)
    origin: str  # "manual" (user-curated) | "generated" (self-proposed) | "inbound"
    attempts: int
    result: Optional[dict]
    decided_by: Optional[str]
    decision: Optional[str]
    pushed: int  # 1 if a decision card has been pushed to the inbox
    created_at: str
    updated_at: str
    mediation_enqueue_id: Optional[str] = field(default=None, kw_only=True)
    mediation_enqueue_revision: Optional[int] = field(default=None, kw_only=True)
    mediation_scope: Optional[str] = field(default=None, kw_only=True)
    mediation_policy_revision: Optional[str] = field(default=None, kw_only=True)
    mediation_receipt: Optional[dict] = field(default=None, kw_only=True)
    mediation_task_sha256: Optional[str] = field(default=None, kw_only=True)
    mediation_execution_id: Optional[str] = field(default=None, kw_only=True)
    kernel_intake_id: Optional[str] = field(default=None, kw_only=True)
    kernel_intake_evidence: Optional[dict] = field(default=None, kw_only=True)
    human_decision: Optional[dict] = field(default=None, kw_only=True)
    approval_deadline_at: str | None = field(default=None, kw_only=True)
    expired_at: str | None = field(default=None, kw_only=True)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        if not self.human_decision or not self.human_decision.get("reason"):
            d.pop("human_decision", None)
        for name in ('approval_deadline_at', 'expired_at'):
            if d.get(name) is None:
                d.pop(name, None)
        return d


@dataclass(frozen=True)
class ApprovalExpiryEffect:
    task_id: int
    expired_at: str
    group_id: str | None = None


@dataclass(frozen=True)
class ApprovalPromotionEffect:
    group_id: str
    task_id: int
    revision: str


@dataclass(frozen=True)
class ApprovalExpiryBatch:
    tasks: tuple[Task, ...]
    group_ids: tuple[str, ...]
    effects: tuple[ApprovalExpiryEffect, ...] = field(default=(), kw_only=True)


class TaskApprovalExpired(TaskQueueError):
    """Expiry has already committed; callers may process the durable effects."""
    def __init__(self, batch: ApprovalExpiryBatch):
        self.batch = batch
        super().__init__('task approval deadline passed')


class TaskQueue:
    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        mediation_mode: str = "off",
        mediation_signer: DetachedHMACSigner | None = None,
        mediation_head_anchor: MonotonicHeadAnchor | None = None,
        mediation_classifier: Callable[[str], object] | None = None,
        mediation_scope: str = "autonomy.queue",
        mediation_policy_revision: str = "v1",
        mediation_clock_ms: Callable[[], int] | None = None,
        consent_categories: tuple[ConsentCategory, ...] = (),
        consent_head_anchor: MonotonicHeadAnchor | None = None,
    ):
        if db_path is None:
            # Resolve at init (not module import) so a JARVIS_HOME set *after* this
            # module was imported is honored — pytest's conftest redirects
            # JARVIS_HOME to a temp dir, but a stale module-level binding pointed a
            # test's queue at the production autonomy.db, which is how test fixtures
            # reached the live Decision Inbox (2026-07-24 QA finding). Lazy resolution
            # makes the redirect effective regardless of import order.
            default = data_path("autonomy.db")
            default.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(default)
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # Guard concurrent access; the autonomy worker calls queue methods
        # from an asyncio task running on a thread-pool thread (H7.4).
        self._lock = threading.Lock()
        mode = str(mediation_mode or "").strip().lower()
        if mode not in {"off", "enforce", "hold"}:
            raise ValueError("mediation mode must be off, enforce, or hold")
        self.mediation_mode = mode
        self._mediation_signer = mediation_signer or DetachedHMACSigner(None)
        self._owner_once_key = object()
        self._owner_once_claims: dict[int, OwnerOnceClaim] = {}
        self._mediation_head_anchor = mediation_head_anchor or MonotonicHeadAnchor(None, None)
        self._mediation_classifier = mediation_classifier or _canonical_mediation_classification
        self._mediation_scope = str(mediation_scope or "").strip()
        self._mediation_policy_revision = str(mediation_policy_revision or "").strip()
        self._mediation_clock_ms = mediation_clock_ms or (lambda: int(time.time() * 1000))
        self._consent_categories = tuple(consent_categories)
        self._consent_head_anchor = consent_head_anchor
        self._consent_ledger: ConsentLedger | None = None
        self._consent_resolver: Callable[[Task, dict], ConsentDescriptor | None] | None = None
        self._consent_queue_key = object()
        self._consent_claims: dict[int, ConsentClaim] = {}

    # ── lifecycle ─────────────────────────────────────────────────
    def initialize(self) -> "TaskQueue":
        with _DATABASE_INIT_LOCK:
            try:
                return self._initialize_locked()
            except Exception:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
                raise

    def _initialize_locked(self) -> "TaskQueue":
        # check_same_thread=False: queue is accessed from asyncio.to_thread
        # helpers; the threading.Lock above serialises every operation.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=30000")
        # WAL + synchronous=NORMAL: the autonomy worker commits on every task
        # state transition in a continuous loop — keep those commits cheap.
        for attempt in range(300):
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 299:
                    raise
                time.sleep(0.05)
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # Serialize schema discovery and migration across processes. A
        # module-level lock only protects threads in this interpreter; without
        # a database write lock, two workers can both observe a missing legacy
        # column and race the same ALTER TABLE.
        self._conn.execute("BEGIN IMMEDIATE")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                risk_tier INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'proposed',
                autonomy_level TEXT NOT NULL DEFAULT 'ask',
                attention_mode TEXT NOT NULL DEFAULT 'interrupt',
                origin TEXT NOT NULL DEFAULT 'generated',
                attempts INTEGER NOT NULL DEFAULT 0,
                result TEXT,
                decided_by TEXT,
                decision TEXT,
                pushed INTEGER NOT NULL DEFAULT 0,
                mediation_enqueue_id TEXT,
                mediation_enqueue_revision INTEGER,
                mediation_scope TEXT,
                mediation_policy_revision TEXT,
                mediation_receipt TEXT,
                mediation_task_sha256 TEXT,
                mediation_execution_id TEXT,
                kernel_intake_id TEXT,
                kernel_intake_evidence TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Advisory opinions are outside Task and every signed execution payload.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_judgement_revisions (
                task_id INTEGER PRIMARY KEY,
                revision INTEGER NOT NULL
            )
        """)
        self._conn.execute("""CREATE TABLE IF NOT EXISTS chat_approval_origins (
            origin_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            session_instance TEXT NOT NULL, principal_key TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        self._conn.execute("""CREATE INDEX IF NOT EXISTS idx_chat_approval_consumer
            ON chat_approval_origins(session_id,session_instance,principal_key)""")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS chat_approval_tasks (
            task_id INTEGER PRIMARY KEY, origin_id TEXT NOT NULL, tool TEXT NOT NULL,
            task_birth TEXT NOT NULL, intent_sha256 TEXT, ready INTEGER NOT NULL DEFAULT 0,
            acknowledged_revision TEXT, acknowledged_at TEXT
        )""")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_approval_origin ON chat_approval_tasks(origin_id)")
        # H485 is observational metadata only. An event is bound to the exact
        # committed denial snapshot; the separate per-consumer tally has a new
        # epoch after every owner approval, so old events cannot revive warnings.
        chat_columns = {row['name'] for row in self._conn.execute('PRAGMA table_info(chat_approval_tasks)')}
        for name, sql_type in (
            ('denial_snapshot_sha256', 'TEXT'),
            ('denial_count', 'INTEGER'),
            ('denial_epoch', 'TEXT'),
            ('denial_sequence', 'INTEGER'),
        ):
            if name not in chat_columns:
                self._conn.execute(f'ALTER TABLE chat_approval_tasks ADD COLUMN {name} {sql_type}')
        self._conn.execute('''CREATE TABLE IF NOT EXISTS chat_guardian_denial_tallies (
            session_id TEXT NOT NULL, session_instance TEXT NOT NULL,
            principal_key TEXT NOT NULL, consecutive_denials INTEGER NOT NULL,
            epoch TEXT NOT NULL, updated_at TEXT NOT NULL, last_sequence INTEGER NOT NULL,
            PRIMARY KEY(session_id,session_instance,principal_key)
        )''')
        tally_columns = {row['name'] for row in self._conn.execute(
            'PRAGMA table_info(chat_guardian_denial_tallies)')}
        if 'last_sequence' not in tally_columns:
            self._conn.execute('''ALTER TABLE chat_guardian_denial_tallies
                ADD COLUMN last_sequence INTEGER NOT NULL DEFAULT 0''')
        self._conn.execute('''CREATE INDEX IF NOT EXISTS idx_chat_guardian_denial_recent
            ON chat_guardian_denial_tallies(last_sequence)''')
        self._conn.execute('''CREATE TABLE IF NOT EXISTS chat_approval_retention (
            id INTEGER PRIMARY KEY CHECK(id=1), last_task_id INTEGER NOT NULL
        )''')
        self._conn.execute('INSERT OR IGNORE INTO chat_approval_retention VALUES(1,0)')
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_judgements (
                task_id INTEGER NOT NULL,
                snapshot_sha256 TEXT NOT NULL,
                annotation TEXT NOT NULL,
                PRIMARY KEY (task_id, snapshot_sha256)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_smart_approvals (
                task_id INTEGER PRIMARY KEY,
                snapshot_sha256 TEXT NOT NULL,
                annotation TEXT NOT NULL,
                receipt TEXT,
                signature TEXT
            )
        """)
        self._conn.execute("""CREATE TABLE IF NOT EXISTS task_owner_once (
            task_id INTEGER PRIMARY KEY, task_birth TEXT NOT NULL,
            denial_snapshot_sha256 TEXT NOT NULL, denial_annotation_sha256 TEXT NOT NULL,
            origin_id TEXT NOT NULL, session_id TEXT NOT NULL,
            session_instance TEXT NOT NULL, principal_key TEXT NOT NULL,
            intent_sha256 TEXT NOT NULL, offer_nonce_sha256 TEXT NOT NULL,
            deadline_at TEXT NOT NULL, state TEXT NOT NULL,
            chat_id INTEGER, user_id INTEGER, message_id INTEGER, generation TEXT,
            owner_decision_id TEXT, approval_receipt TEXT, signature TEXT,
            mediation_execution_id TEXT, claimed_at TEXT, dispatch_at TEXT
        )""")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_approval_group_state (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_approval_groups (
                task_id INTEGER PRIMARY KEY, group_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, member_sha256 TEXT NOT NULL,
                snapshot TEXT NOT NULL, binding_sha256 TEXT
            )
        """)
        group_columns = {row['name'] for row in self._conn.execute('PRAGMA table_info(task_approval_groups)')}
        if 'binding_sha256' not in group_columns:
            self._conn.execute('ALTER TABLE task_approval_groups ADD COLUMN binding_sha256 TEXT')
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_task_approval_groups ON task_approval_groups(group_id)")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS task_approval_promotion_effects (
            group_id TEXT PRIMARY KEY, task_id INTEGER NOT NULL, revision TEXT NOT NULL
        )""")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_task_approval_promotion_task "
                           "ON task_approval_promotion_effects(task_id)")
        self._conn.execute("INSERT OR IGNORE INTO task_approval_group_state(key,value) VALUES ('namespace',?)",
                           (uuid.uuid4().hex,))
        self._group_namespace = self._conn.execute(
            "SELECT value FROM task_approval_group_state WHERE key='namespace'"
        ).fetchone()['value']
        from .consent_sources import initialize as initialize_consent_sources
        initialize_consent_sources(self._conn)
        self._conn.execute('''CREATE TABLE IF NOT EXISTS task_consent_proofs (
            task_id INTEGER PRIMARY KEY, payload BLOB NOT NULL, signature TEXT NOT NULL,
            claim_payload BLOB, claim_signature TEXT, state TEXT NOT NULL
        )''')
        if self._consent_head_anchor is not None:
            self._consent_ledger = ConsentLedger(
                self._conn, self._mediation_signer, categories=self._consent_categories,
                head_anchor=self._consent_head_anchor,
            )
            self._consent_ledger.initialize()

        # H33.2: old autonomy databases predate the ask/digest/interrupt split.
        # Preserve their previous push behavior while new ambient proposals set
        # the mode explicitly.
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "attention_mode" not in columns:
            self._conn.execute(
                "ALTER TABLE tasks ADD COLUMN attention_mode TEXT NOT NULL DEFAULT 'interrupt'"
            )
        if "human_decision" not in columns:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN human_decision TEXT")
        for name in ('approval_deadline_at', 'expired_at'):
            if name not in columns:
                self._conn.execute(f'ALTER TABLE tasks ADD COLUMN {name} TEXT')
        self._conn.execute("""CREATE TABLE IF NOT EXISTS task_approval_expiry_effects (
            task_id INTEGER PRIMARY KEY, expired_at TEXT NOT NULL, group_id TEXT
        )""")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS task_approval_expiry_state (
            key TEXT PRIMARY KEY, last_task_id INTEGER NOT NULL
        )""")
        mediation_columns = {
            "mediation_enqueue_id": "TEXT",
            "mediation_enqueue_revision": "INTEGER",
            "mediation_scope": "TEXT",
            "mediation_policy_revision": "TEXT",
            "mediation_receipt": "TEXT",
            "mediation_task_sha256": "TEXT",
            "mediation_execution_id": "TEXT",
            "kernel_intake_id": "TEXT",
            "kernel_intake_evidence": "TEXT",
        }
        for name, column_type in mediation_columns.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {column_type}")
        # The worker polls runnable()/pending_decisions() and the inbox calls
        # list() in a continuous loop — all filtered by status — while the table
        # grows unboundedly as decided tasks accumulate. Index status so those
        # reads stay O(log n) instead of degrading to full scans at scale.
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, id)")
        self._conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_mediation_enqueue
               ON tasks(mediation_enqueue_id)
               WHERE mediation_enqueue_id IS NOT NULL"""
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_kernel_intake "
            "ON tasks(kernel_intake_id) WHERE kernel_intake_id IS NOT NULL"
        )
        had_events_table = (
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_mediation_events'"
            ).fetchone()
            is not None
        )
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_mediation_events (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                version INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                task_id INTEGER NOT NULL,
                enqueue_id TEXT NOT NULL,
                receipt_id TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                occurred_at_ms INTEGER NOT NULL,
                previous_event_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                signature TEXT NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mediation_execution_id "
            "ON task_mediation_events(execution_id) WHERE execution_id != ''"
        )
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_mediation_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                last_sequence INTEGER NOT NULL,
                last_event_hash TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                integrity_broken INTEGER NOT NULL DEFAULT 0,
                signature TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS capability_outcomes (
                capability_id TEXT PRIMARY KEY,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                last_outcome_at TEXT NOT NULL
            )
        """)
        with self._lock:
            state = self._conn.execute("SELECT * FROM task_mediation_state WHERE id=1").fetchone()
            if state is None:
                mediated_tasks = self._conn.execute(
                    "SELECT 1 FROM tasks WHERE mediation_enqueue_id IS NOT NULL LIMIT 1"
                ).fetchone()
                event = self._conn.execute("SELECT 1 FROM task_mediation_events LIMIT 1").fetchone()
                self._initialize_mediation_state_locked(
                    broken=bool(had_events_table or mediated_tasks or event),
                    uninitialized=(
                        self.mediation_mode == "off"
                        and not had_events_table
                        and not mediated_tasks
                        and not event
                    ),
                )
            elif state["integrity_broken"] == 2 and self.mediation_mode in {"enforce", "hold"}:
                event = self._conn.execute("SELECT 1 FROM task_mediation_events LIMIT 1").fetchone()
                mediated_tasks = self._conn.execute(
                    "SELECT 1 FROM tasks WHERE mediation_enqueue_id IS NOT NULL LIMIT 1"
                ).fetchone()
                self._initialize_mediation_state_locked(
                    broken=bool(event or mediated_tasks), uninitialized=False
                )
            if self.mediation_mode in {"enforce", "hold"}:
                local_head = self._local_mediation_head_locked()
                anchored_head = self._mediation_head_anchor.read()
                anchor_matches = local_head is not None and anchored_head == local_head
                if local_head is not None and anchored_head is None:
                    mediated_tasks = self._conn.execute(
                        "SELECT 1 FROM tasks WHERE mediation_enqueue_id IS NOT NULL LIMIT 1"
                    ).fetchone()
                    event = self._conn.execute(
                        "SELECT 1 FROM task_mediation_events LIMIT 1"
                    ).fetchone()
                    anchor_matches = (
                        not mediated_tasks
                        and not event
                        and local_head.last_sequence == 0
                        and local_head.event_count == 0
                        and self._mediation_head_anchor.advance(None, local_head)
                    )
                if not anchor_matches:
                    self._mark_mediation_integrity_broken_locked()
        self._conn.commit()
        if self.mediation_mode in {"enforce", "hold"}:
            self.scan_unmediated_tasks()
        return self

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── B7 mediation evidence ────────────────────────────────────
    def _classification(self, kind: str) -> bool | None:
        """Return kernel classification, or ``None`` when classification failed."""

        if self.mediation_mode == "off":
            return False
        try:
            if not callable(self._mediation_classifier):
                return None
            value = self._mediation_classifier(str(kind))
            if isinstance(value, bool):
                return value
            if value is None:
                return None
            normalized = str(value).strip().lower()
            if normalized == "kernel":
                return True
            if normalized == "direct":
                return False
            return None
        except Exception:
            return None

    def _clock_ms(self) -> int:
        try:
            value = self._mediation_clock_ms()
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("invalid mediation clock")
            return value
        except Exception as exc:
            raise TaskQueueError("mediation clock unavailable") from exc

    @staticmethod
    def _mediation_state_payload(
        *, last_sequence: int, last_event_hash: str, event_count: int, integrity_broken: int
    ) -> dict[str, object]:
        return {
            "version": 1,
            "last_sequence": last_sequence,
            "last_event_hash": last_event_hash,
            "event_count": event_count,
            "integrity_broken": integrity_broken,
        }

    def _current_mediation_head_locked(self) -> tuple[int, str, int]:
        row = self._conn.execute(
            """SELECT sequence, event_hash,
                      (SELECT COUNT(*) FROM task_mediation_events) AS event_count
                 FROM task_mediation_events
                ORDER BY sequence DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            return 0, ZERO_HASH, 0
        return int(row["sequence"]), str(row["event_hash"]), int(row["event_count"])

    def _local_mediation_head_locked(self) -> MediationHead | None:
        state = self._conn.execute("SELECT * FROM task_mediation_state WHERE id=1").fetchone()
        if state is None or int(state["integrity_broken"]) != 0 or int(state["version"]) != 1:
            return None
        sequence, event_hash, count = self._current_mediation_head_locked()
        payload = self._mediation_state_payload(
            last_sequence=int(state["last_sequence"]),
            last_event_hash=str(state["last_event_hash"]),
            event_count=int(state["event_count"]),
            integrity_broken=int(state["integrity_broken"]),
        )
        if not (
            int(state["last_sequence"]) == sequence
            and str(state["last_event_hash"]) == event_hash
            and int(state["event_count"]) == count
            and self._mediation_signer.verify(canonical_json(payload), state["signature"])
        ):
            return None
        try:
            return MediationHead(
                version=1,
                last_sequence=sequence,
                last_event_hash=event_hash,
                event_count=count,
                signature=str(state["signature"]),
            )
        except ValueError:
            return None

    def _initialize_mediation_state_locked(
        self, *, broken: bool, uninitialized: bool = False
    ) -> None:
        sequence, event_hash, count = self._current_mediation_head_locked()
        payload = self._mediation_state_payload(
            last_sequence=sequence,
            last_event_hash=event_hash,
            event_count=count,
            integrity_broken=0,
        )
        signature = (
            None
            if broken or uninitialized
            else self._mediation_signer.sign(canonical_json(payload))
        )
        self._conn.execute(
            """INSERT OR REPLACE INTO task_mediation_state
                   (id, version, last_sequence, last_event_hash, event_count,
                    integrity_broken, signature)
               VALUES (1, 1, ?, ?, ?, ?, ?)""",
            (
                sequence,
                event_hash,
                count,
                2 if uninitialized else (1 if broken or signature is None else 0),
                signature or "",
            ),
        )

    def _validated_mediation_snapshot_locked(
        self,
    ) -> tuple[MediationHead, list[dict[str, object]]] | None:
        """Authenticate the global head and reconcile all executable evidence."""

        rows = self._conn.execute(
            "SELECT * FROM task_mediation_events ORDER BY sequence"
        ).fetchall()
        task_rows = self._conn.execute(
            """SELECT id, mediation_enqueue_id, mediation_execution_id
                 FROM tasks WHERE mediation_enqueue_id IS NOT NULL"""
        ).fetchall()
        local_head = self._local_mediation_head_locked()
        if local_head is None or self._mediation_head_anchor.read() != local_head:
            return None

        fields = MediationEvent.__dataclass_fields__
        events = [{name: row[name] for name in fields} for row in rows]
        if events and not verify_event_chain(self._mediation_signer, events):
            return None

        task_by_id = {int(row["id"]): row for row in task_rows}
        authorized: dict[int, list[dict[str, object]]] = {}
        governed: dict[int, list[dict[str, object]]] = {}
        for event in events:
            if event["outcome"] == "authorized_enqueue":
                authorized.setdefault(int(event["task_id"]), []).append(event)
            elif event["outcome"] == "governed":
                governed.setdefault(int(event["task_id"]), []).append(event)
        for task_id, row in task_by_id.items():
            auth_events = authorized.get(task_id, [])
            if len(auth_events) != 1 or auth_events[0]["enqueue_id"] != row["mediation_enqueue_id"]:
                return None
            execution_id = row["mediation_execution_id"]
            run_events = governed.get(task_id, [])
            if execution_id:
                if (
                    len(run_events) != 1
                    or run_events[0]["execution_id"] != execution_id
                    or run_events[0]["enqueue_id"] != row["mediation_enqueue_id"]
                ):
                    return None
            elif run_events:
                return None
        if any(task_id not in task_by_id for task_id in authorized | governed):
            return None

        return local_head, events

    def _update_mediation_state_locked(self, previous_state: MediationHead) -> None:
        sequence, event_hash, count = self._current_mediation_head_locked()
        payload = self._mediation_state_payload(
            last_sequence=sequence,
            last_event_hash=event_hash,
            event_count=count,
            integrity_broken=0,
        )
        signature = self._mediation_signer.sign(canonical_json(payload))
        if signature is None:
            raise TaskQueueError("could not seal mediation chain head")
        updated = self._conn.execute(
            """UPDATE task_mediation_state
                  SET version=1, last_sequence=?, last_event_hash=?, event_count=?,
                      integrity_broken=0, signature=?
                WHERE id=1 AND version=? AND last_sequence=?
                  AND last_event_hash=? AND event_count=?
                  AND integrity_broken=0 AND signature=?""",
            (
                sequence,
                event_hash,
                count,
                signature,
                previous_state.version,
                previous_state.last_sequence,
                previous_state.last_event_hash,
                previous_state.event_count,
                previous_state.signature,
            ),
        )
        if updated.rowcount != 1:
            raise TaskQueueError("mediation chain head is unavailable")
        replacement = MediationHead(
            version=1,
            last_sequence=sequence,
            last_event_hash=event_hash,
            event_count=count,
            signature=signature,
        )
        if not self._mediation_head_anchor.advance(previous_state, replacement):
            raise TaskQueueError("mediation latest-head anchor is unavailable")

    def _mark_mediation_integrity_broken_locked(self) -> None:
        sequence, event_hash, count = self._current_mediation_head_locked()
        self._conn.execute(
            """INSERT INTO task_mediation_state
                   (id, version, last_sequence, last_event_hash, event_count,
                    integrity_broken, signature)
               VALUES (1, 1, ?, ?, ?, 1, '')
               ON CONFLICT(id) DO UPDATE SET integrity_broken=1, signature=''""",
            (sequence, event_hash, count),
        )

    @staticmethod
    def _task_binding(
        *,
        agent: str,
        kind: str,
        title: str,
        origin: str,
        scope: str,
        payload: object,
        effective_tier: int,
        policy_revision: str,
        enqueue_revision: int,
    ) -> dict:
        return {
            "agent": agent,
            "kind": kind,
            "title": title,
            "origin": origin,
            "scope": scope,
            "payload": payload,
            "effective_tier": effective_tier,
            "policy_revision": policy_revision,
            "enqueue_revision": enqueue_revision,
        }

    def _append_mediation_event_locked(
        self,
        *,
        outcome: str,
        task_id: int,
        enqueue_id: str,
        receipt: MediationReceipt | Mapping[str, object] | None,
        execution_id: str = "",
        verified_state: MediationHead | None = None,
    ) -> MediationEvent:
        if verified_state is None:
            snapshot = self._validated_mediation_snapshot_locked()
            if snapshot is None:
                raise TaskQueueError("mediation chain head is invalid")
            verified_state = snapshot[0]
        sequence = verified_state.last_sequence + 1
        previous_hash = verified_state.last_event_hash
        occurred_at_ms = self._clock_ms()
        if verified_state.last_sequence:
            previous_event = self._conn.execute(
                "SELECT occurred_at_ms FROM task_mediation_events WHERE sequence=?",
                (verified_state.last_sequence,),
            ).fetchone()
            if previous_event is None:
                raise TaskQueueError("mediation chain head is invalid")
            if occurred_at_ms < int(previous_event["occurred_at_ms"]):
                raise TaskQueueError("mediation clock regressed")
        event = make_event(
            self._mediation_signer,
            event_id=str(uuid.uuid4()),
            sequence=sequence,
            outcome=outcome,
            task_id=task_id,
            enqueue_id=enqueue_id,
            receipt=receipt,
            execution_id=execution_id,
            occurred_at_ms=occurred_at_ms,
            previous_event_hash=previous_hash,
        )
        if event is None:
            raise TaskQueueError("could not seal mediation evidence")
        value = event.to_dict()
        self._conn.execute(
            """INSERT INTO task_mediation_events
                   (sequence, event_id, version, outcome, task_id, enqueue_id,
                    receipt_id, receipt_sha256, execution_id, occurred_at_ms,
                    previous_event_hash, event_hash, signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                value["sequence"],
                value["event_id"],
                value["version"],
                value["outcome"],
                value["task_id"],
                value["enqueue_id"],
                value["receipt_id"],
                value["receipt_sha256"],
                value["execution_id"],
                value["occurred_at_ms"],
                value["previous_event_hash"],
                value["event_hash"],
                value["signature"],
            ),
        )
        self._update_mediation_state_locked(verified_state)
        return event

    def mediation_events(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM task_mediation_events ORDER BY sequence"
            ).fetchall()
        fields = MediationEvent.__dataclass_fields__
        return [{name: row[name] for name in fields} for row in rows]

    def verified_mediation_stats(self) -> dict[str, int | bool]:
        counters: dict[str, int | bool] = {
            "valid": False,
            "authorized_enqueue": 0,
            "governed": 0,
            "refused_unmediated": 0,
            "ungoverned_detected": 0,
        }
        with self._lock:
            snapshot = self._validated_mediation_snapshot_locked()
        if snapshot is None:
            return counters
        _state, events = snapshot

        counters["valid"] = True
        for event in events:
            outcome = event["outcome"]
            if outcome in counters:
                counters[outcome] = int(counters[outcome]) + 1
        return counters

    @staticmethod
    def execution_fingerprint(task: Task) -> str | None:
        """Digest every immutable persisted execution/authority field."""

        try:
            immutable = {
                "id": task.id,
                "agent": task.agent,
                "kind": task.kind,
                "title": task.title,
                "payload": task.payload,
                "risk_tier": task.risk_tier,
                "autonomy_level": task.autonomy_level,
                "attention_mode": task.attention_mode,
                "origin": task.origin,
                "decided_by": task.decided_by,
                "decision": task.decision,
                "created_at": task.created_at,
                "mediation_enqueue_id": task.mediation_enqueue_id,
                "mediation_enqueue_revision": task.mediation_enqueue_revision,
                "mediation_scope": task.mediation_scope,
                "mediation_policy_revision": task.mediation_policy_revision,
                "mediation_receipt": task.mediation_receipt,
                "mediation_task_sha256": task.mediation_task_sha256,
                "mediation_execution_id": task.mediation_execution_id,
            }
            # Queue rows historically accept JSON larger than the bounded B7
            # receipt domain.  Fingerprinting must not add a new eligibility
            # limit to intentionally-direct tasks, while still rejecting
            # non-JSON or otherwise unserialisable substitutions.
            encoded = json.dumps(
                immutable,
                # Preserve the queue's legacy JSON domain: enqueue() has always
                # accepted Python's deterministic NaN/Infinity spellings.
                allow_nan=True,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            return hashlib.sha256(encoded).hexdigest()
        except Exception:
            return None

    @staticmethod
    def detach_execution_task(task: Task) -> Task | None:
        """Rebuild an untrusted task as a plain, recursively detached ``Task``.

        ``copy.deepcopy`` delegates to attacker-controlled ``__deepcopy__``
        hooks on Task/container subclasses.  A JSON round trip over the exact
        persisted schema strips those hooks; the subsequent fingerprint check
        still requires the rebuilt values to equal the authenticated row.
        """

        try:
            values = {
                name: getattr(task, name)
                for name in Task.__dataclass_fields__
            }
            encoded = json.dumps(
                values,
                allow_nan=True,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            return Task(**json.loads(encoded))
        except Exception:
            return None

    def execution_snapshot(
        self, task_id: int, *, presented_kind: str
    ) -> tuple[Task | None, bool]:
        """Authenticate the head, load the row, and classify it atomically.

        A missing/malformed row or degraded global head returns a fail-closed
        sentinel.  The caller must not infer direct authority from missing
        task-local provenance.
        """

        with self._lock:
            try:
                if (
                    self.mediation_mode in {"enforce", "hold"}
                    and self._validated_mediation_snapshot_locked() is None
                ):
                    return None, True
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    return None, True
                task = _row_to_task(row)
                required = (
                    self._row_requires_mediation_locked(row)
                    or self._classification(presented_kind) is not False
                )
                return task, required
            except Exception:
                return None, True

    def classify_mediation(self, kind: str) -> bool | None:
        """Return this queue's trusted classification result for *kind*."""

        return self._classification(kind)

    @staticmethod
    def _row_has_mediation_provenance(row: sqlite3.Row) -> bool:
        """Treat every persisted B7 binding field as an irreversible boundary."""

        return any(
            row[name] is not None and row[name] != ""
            for name in (
                "mediation_enqueue_id",
                "mediation_enqueue_revision",
                "mediation_scope",
                "mediation_policy_revision",
                "mediation_receipt",
                "mediation_task_sha256",
                "mediation_execution_id",
            )
        )

    def _row_requires_mediation_locked(self, row: sqlite3.Row) -> bool:
        if self._classification(row["kind"]) is not False:
            return True
        if self._row_has_mediation_provenance(row):
            return True
        return (
            self._conn.execute(
                "SELECT 1 FROM task_mediation_events WHERE task_id=? LIMIT 1",
                (row["id"],),
            ).fetchone()
            is not None
        )

    def mediation_required(self, task_id: int, *, kind: str = "") -> bool:
        """Return the durable boundary for a task, never just its mutable kind."""

        if self.mediation_mode == "off":
            return False
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is not None:
                return (
                    self._row_requires_mediation_locked(row)
                    or self._classification(kind) is not False
                )
        return self._classification(kind) is not False

    @property
    def mediation_policy_revision(self) -> str:
        return self._mediation_policy_revision

    def _scope_allowed(self, scope: str) -> bool:
        return self._mediation_scope == "*" or scope == self._mediation_scope

    def record_mediation_refusal(self, kind: str) -> bool:
        """Persist one real refused-classified event without creating a task."""

        if self.mediation_mode not in {"enforce", "hold"}:
            return False
        if self._classification(kind) is False:
            return False
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._append_mediation_event_locked(
                    outcome="refused_unmediated",
                    task_id=0,
                    enqueue_id=str(uuid.uuid4()),
                    receipt=None,
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    self._mark_mediation_integrity_broken_locked()
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                return False


    @staticmethod
    def _expiry_limit(limit):
        if type(limit) is not int or limit < 0:
            raise ValueError('expiry limit must be a nonnegative integer')
        return min(100, limit)

    def _expiry_batch_locked(self, effects) -> ApprovalExpiryBatch:
        tasks = []
        for effect in effects:
            row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (effect.task_id,)).fetchone()
            if row is not None and row['status'] == 'expired' and row['expired_at'] == effect.expired_at:
                tasks.append(_row_to_task(row))
        return ApprovalExpiryBatch(tuple(tasks), tuple(dict.fromkeys(
            effect.group_id for effect in effects if effect.group_id)), effects=tuple(effects))

    def _expire_approval_locked(self, row, now, *, reopening=False) -> ApprovalExpiryEffect | None:
        if row['status'] not in {'proposed', 'blocked'} and not reopening:
            return None
        try:
            deadline = normalize_approval_deadline(row['approval_deadline_at'])
        except ValueError as exc:
            logger.warning('task approval deadline unreadable; task retained')
            raise TaskQueueError('task approval deadline is unreadable') from exc
        if deadline is None or datetime.fromisoformat(deadline) > now:
            return None
        at = now.isoformat(timespec='microseconds')
        cursor = self._conn.execute("UPDATE tasks SET status='expired', expired_at=?, updated_at=? "
                                    'WHERE id=? AND status=?', (at, at, row['id'], row['status']))
        if cursor.rowcount != 1:
            return None
        group_id = self._withdraw_task_group_locked(row['id'])
        self._conn.execute('INSERT INTO task_approval_expiry_effects(task_id,expired_at,group_id) VALUES(?,?,?)',
                           (row['id'], at, group_id))
        return ApprovalExpiryEffect(row['id'], at, group_id)

    def _raise_due_approval_locked(self, row, now, *, reopening=False):
        if row['status'] == TaskStatus.EXPIRED.value:
            raise TaskQueueError('expired task cannot be changed')
        effect = self._expire_approval_locked(row, now, reopening=reopening)
        if effect is not None:
            batch = self._expiry_batch_locked((effect,))
            self._conn.commit()
            raise TaskApprovalExpired(batch)

    def _expiry_scan_locked(self, key, query, params, limit):
        self._conn.execute('INSERT OR IGNORE INTO task_approval_expiry_state VALUES(?,0)', (key,))
        cursor = self._conn.execute('SELECT last_task_id FROM task_approval_expiry_state WHERE key=?',
                                    (key,)).fetchone()[0]
        rows = self._conn.execute(query + ' AND task_id>? ORDER BY task_id LIMIT ?',
                                  (*params, cursor, limit)).fetchall()
        if len(rows) < limit and cursor:
            rows += self._conn.execute(query + ' AND task_id<=? ORDER BY task_id LIMIT ?',
                                       (*params, cursor, limit-len(rows))).fetchall()
        if rows:
            self._conn.execute('UPDATE task_approval_expiry_state SET last_task_id=? WHERE key=?',
                               (rows[-1]['task_id'], key))
        return rows

    def expire_pending_approvals(self, *, now: datetime | None = None, limit: int = 100) -> ApprovalExpiryBatch:
        limit = self._expiry_limit(limit)
        # Validate an explicitly supplied clock even when no rows are scanned.
        if now is not None:
            _approval_now(now)
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                instant = _approval_now(now)
                rows = self._expiry_scan_locked('due', "SELECT *, id AS task_id FROM tasks WHERE "
                    "status IN ('proposed','blocked') AND approval_deadline_at IS NOT NULL", (), limit)
                effects = []
                for row in rows:
                    try:
                        effect = self._expire_approval_locked(row, instant)
                    except TaskQueueError:
                        continue  # corrupt metadata stays fail-closed without starving later rows
                    if effect is not None:
                        effects.append(effect)
                batch = self._expiry_batch_locked(effects)
                self._conn.commit()
                return batch
            except Exception:
                self._conn.rollback()
                raise

    def pending_approval_expiry_effects(self, *, limit: int = 100) -> ApprovalExpiryBatch:
        limit = self._expiry_limit(limit)
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                rows = self._expiry_scan_locked('effects', 'SELECT * FROM task_approval_expiry_effects WHERE 1=1',
                                               (), limit)
                batch = self._expiry_batch_locked([ApprovalExpiryEffect(row['task_id'], row['expired_at'],
                                                                       row['group_id']) for row in rows])
                self._conn.commit()
                return batch
            except Exception:
                self._conn.rollback()
                raise

    def ack_approval_expiry_effects(self, batch: ApprovalExpiryBatch) -> int:
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                count = 0
                for effect in batch.effects:
                    count += self._conn.execute('DELETE FROM task_approval_expiry_effects '
                        'WHERE task_id=? AND expired_at=?', (effect.task_id, effect.expired_at)).rowcount
                self._conn.commit()
                return count
            except Exception:
                self._conn.rollback()
                raise

    def pending_approval_promotion_effects(self, *, limit: int = 100,
                                           group_id: str | None = None) -> tuple[ApprovalPromotionEffect, ...]:
        limit = self._expiry_limit(limit)
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                if group_id is None:
                    rows = self._expiry_scan_locked(
                        'promotion', 'SELECT * FROM task_approval_promotion_effects WHERE 1=1', (), limit)
                else:
                    rows = self._conn.execute('SELECT * FROM task_approval_promotion_effects '
                                              'WHERE group_id=?', (group_id,)).fetchall()
                self._conn.commit()
                return tuple(ApprovalPromotionEffect(row['group_id'], row['task_id'], row['revision'])
                             for row in rows)
            except Exception:
                self._conn.rollback()
                raise

    def ack_approval_promotion_effects(self, effects: tuple[ApprovalPromotionEffect, ...]) -> int:
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                count = 0
                for effect in effects:
                    count += self._conn.execute(
                        'DELETE FROM task_approval_promotion_effects WHERE group_id=? AND revision=?',
                        (effect.group_id, effect.revision),
                    ).rowcount
                self._conn.commit()
                return count
            except Exception:
                self._conn.rollback()
                raise

    def _record_promotion_effect_locked(self, group_id: str | None, task_id: int) -> None:
        if group_id is None:
            return
        self._conn.execute(
            'INSERT INTO task_approval_promotion_effects(group_id,task_id,revision) VALUES(?,?,?) '
            'ON CONFLICT(group_id) DO UPDATE SET task_id=excluded.task_id,revision=excluded.revision',
            (group_id, task_id, uuid.uuid4().hex),
        )

    # ── writes ────────────────────────────────────────────────────
    def enqueue(
        self,
        agent: str,
        kind: str,
        title: str,
        payload: dict = None,
        risk_tier: int = 3,
        autonomy_level: str = "ask",
        origin: str = "generated",
        attention_mode: str = "interrupt",
        kernel_intake_evidence: KernelIntakeEvidence | Mapping[str, object] | None = None,
        *, approval_deadline_at: str | None = None,
    ) -> int:
        approval_deadline_at = normalize_approval_deadline(approval_deadline_at)
        payload = dict(payload or {})
        # Legacy payload metadata is caller-controlled and has no authority.
        payload.pop("kernel_mediation", None)
        attention_mode = str(attention_mode or "").strip().lower()
        if attention_mode not in {"none", "digest", "interrupt"}:
            raise ValueError("attention mode is invalid")
        classification = self._classification(kind)
        if self.mediation_mode in {"enforce", "hold"} and classification is not False:
            message = (
                "mediation hold refuses classified enqueue"
                if self.mediation_mode == "hold"
                else "classified task requires mediation"
            )
            self.record_mediation_refusal(kind)
            raise TaskQueueError(message)
        now = _now()
        intake_id, intake_json = _intake_evidence_columns(kernel_intake_evidence)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    """INSERT INTO tasks (agent, kind, title, payload, risk_tier, status,
                           autonomy_level, attention_mode, origin, attempts, pushed,
                           kernel_intake_id, kernel_intake_evidence,
                           created_at, updated_at, approval_deadline_at)
                       VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)""",
                    (
                        agent,
                        kind,
                        title,
                        json.dumps(payload, ensure_ascii=False),
                        int(risk_tier),
                        autonomy_level,
                        attention_mode,
                        origin,
                        intake_id,
                        intake_json,
                        now,
                        now,
                        approval_deadline_at,
                    ),
                )
                self._associate_chat_approval_locked(int(cur.lastrowid), now)
                self._conn.commit()
                return cur.lastrowid
            except Exception:
                self._conn.rollback()
                raise

    def attach_kernel_intake_evidence(
        self, task_id: int, evidence: KernelIntakeEvidence | Mapping[str, object]
    ) -> bool:
        """Atomically attach evidence whose signature binds this durable task ID."""

        try:
            sealed = (
                evidence
                if isinstance(evidence, KernelIntakeEvidence)
                else KernelIntakeEvidence.from_dict(evidence)
            )
            if sealed.task_id != task_id:
                return False
            intake_id, intake_json = _intake_evidence_columns(sealed)
        except Exception:
            return False
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                updated = self._conn.execute(
                    """UPDATE tasks
                          SET kernel_intake_id=?, kernel_intake_evidence=?
                        WHERE id=? AND kernel_intake_id IS NULL
                          AND kernel_intake_evidence IS NULL""",
                    (intake_id, intake_json, task_id),
                )
                self._conn.commit()
                return updated.rowcount == 1
            except Exception:
                self._conn.rollback()
                return False

    def validate_kernel_intake_evidence(
        self, task: Task, signer: DetachedHMACSigner, *, now_ms: int
    ) -> bool:
        """Validate signed QA4 evidence against the current durable task row."""

        with self._lock:
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task.id,)).fetchone()
                if row is None:
                    return False
                persisted = _row_to_task(row)
                if self.execution_fingerprint(persisted) != self.execution_fingerprint(task):
                    return False
                return verify_intake_evidence(
                    signer,
                    persisted.kernel_intake_evidence,
                    agent=persisted.agent,
                    kind=persisted.kind,
                    title=persisted.title,
                    origin=persisted.origin,
                    payload=persisted.payload,
                    tier=None,
                    task_tier=persisted.risk_tier,
                    now_ms=now_ms,
                    task_id=persisted.id,
                )
            except Exception:
                return False

    def enqueue_mediated(
        self,
        agent: str,
        kind: str,
        title: str,
        payload: dict | None = None,
        *,
        receipt: MediationReceipt | Mapping[str, object],
        scope: str | None = None,
        autonomy_level: str = "ask",
        origin: str = "generated",
        attention_mode: str = "interrupt",
        kernel_intake_evidence: KernelIntakeEvidence | Mapping[str, object] | None = None,
        approval_deadline_at: str | None = None,
    ) -> int:
        """Insert exact task bytes, receipt, and authorization event atomically."""

        approval_deadline_at = normalize_approval_deadline(approval_deadline_at)
        if self.mediation_mode == "hold":
            raise TaskQueueError("mediation hold refuses classified enqueue")
        if self._classification(kind) is not True:
            raise TaskQueueError("classified mediation is unavailable")
        attention_mode = str(attention_mode or "").strip().lower()
        if attention_mode not in {"none", "digest", "interrupt"}:
            raise ValueError("attention mode is invalid")
        try:
            sealed = (
                receipt
                if isinstance(receipt, MediationReceipt)
                else MediationReceipt.from_dict(receipt)
            )
            # Detach exact bounded task bytes before verification so a caller that
            # retains and mutates its input dict cannot race the receipt check versus
            # the later SQLite serialization.
            body = json.loads(canonical_json(payload or {}).decode("utf-8"))
            authority_scope = self._mediation_scope if scope is None else str(scope)
            if not self._scope_allowed(authority_scope):
                raise TaskQueueError("invalid mediation receipt")
            expectation = ReceiptExpectation(
                enqueue_id=sealed.enqueue_id,
                agent=agent,
                kind=kind,
                title=title,
                origin=origin,
                scope=authority_scope,
                payload=body,
                effective_tier=sealed.effective_tier,
                policy_revision=self._mediation_policy_revision,
                enqueue_revision=sealed.enqueue_revision,
            )
            if not verify_receipt(
                self._mediation_signer,
                sealed,
                expected=expectation,
                now_ms=self._clock_ms(),
            ):
                raise TaskQueueError("invalid mediation receipt")
            binding = self._task_binding(
                agent=agent,
                kind=kind,
                title=title,
                origin=origin,
                scope=authority_scope,
                payload=body,
                effective_tier=sealed.effective_tier,
                policy_revision=self._mediation_policy_revision,
                enqueue_revision=sealed.enqueue_revision,
            )
            task_sha256 = canonical_digest(binding)
            receipt_json = json.dumps(
                sealed.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            payload_json = json.dumps(body, ensure_ascii=False)
            intake_id, intake_json = _intake_evidence_columns(kernel_intake_evidence)
        except TaskQueueError:
            raise
        except Exception as exc:
            raise TaskQueueError("invalid mediation receipt") from exc

        now = _now()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                snapshot = self._validated_mediation_snapshot_locked()
                if snapshot is None:
                    raise TaskQueueError("mediation chain head is invalid")
                verified_state = snapshot[0]
                duplicate = self._conn.execute(
                    "SELECT 1 FROM tasks WHERE mediation_enqueue_id=?",
                    (sealed.enqueue_id,),
                ).fetchone()
                if duplicate:
                    raise TaskQueueError("invalid mediation receipt: enqueue replay")
                cur = self._conn.execute(
                    """INSERT INTO tasks
                           (agent, kind, title, payload, risk_tier, status,
                            autonomy_level, attention_mode, origin, attempts, pushed,
                            mediation_enqueue_id, mediation_enqueue_revision,
                            mediation_scope, mediation_policy_revision,
                             mediation_receipt, mediation_task_sha256,
                             kernel_intake_id, kernel_intake_evidence,
                             created_at, updated_at, approval_deadline_at)
                        VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?, ?, 0, 0,
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        agent,
                        kind,
                        title,
                        payload_json,
                        sealed.effective_tier,
                        autonomy_level,
                        attention_mode,
                        origin,
                        sealed.enqueue_id,
                        sealed.enqueue_revision,
                        authority_scope,
                        self._mediation_policy_revision,
                        receipt_json,
                        task_sha256,
                        intake_id,
                        intake_json,
                        now,
                        now,
                        approval_deadline_at,
                    ),
                )
                task_id = int(cur.lastrowid)
                self._associate_chat_approval_locked(task_id, now)
                self._append_mediation_event_locked(
                    outcome="authorized_enqueue",
                    task_id=task_id,
                    enqueue_id=sealed.enqueue_id,
                    receipt=sealed,
                    verified_state=verified_state,
                )
                self._conn.commit()
                return task_id
            except TaskQueueError:
                self._conn.rollback()
                raise
            except Exception as exc:
                self._conn.rollback()
                raise TaskQueueError("could not persist mediation evidence") from exc

    def _row_receipt_and_expectation(
        self, row: sqlite3.Row
    ) -> tuple[MediationReceipt, ReceiptExpectation, str]:
        receipt = MediationReceipt.from_dict(json.loads(row["mediation_receipt"]))
        payload = json.loads(row["payload"] or "{}")
        expectation = ReceiptExpectation(
            enqueue_id=row["mediation_enqueue_id"],
            agent=row["agent"],
            kind=row["kind"],
            title=row["title"],
            origin=row["origin"],
            scope=row["mediation_scope"],
            payload=payload,
            effective_tier=int(row["risk_tier"]),
            policy_revision=row["mediation_policy_revision"],
            enqueue_revision=row["mediation_enqueue_revision"],
        )
        task_sha256 = canonical_digest(
            self._task_binding(
                agent=expectation.agent,
                kind=expectation.kind,
                title=expectation.title,
                origin=expectation.origin,
                scope=expectation.scope,
                payload=expectation.payload,
                effective_tier=expectation.effective_tier,
                policy_revision=expectation.policy_revision,
                enqueue_revision=expectation.enqueue_revision,
            )
        )
        return receipt, expectation, task_sha256

    def _event_chain_valid_locked(self) -> bool:
        rows = self._conn.execute(
            "SELECT * FROM task_mediation_events ORDER BY sequence"
        ).fetchall()
        if not rows:
            return False
        fields = MediationEvent.__dataclass_fields__
        events = [{name: row[name] for name in fields} for row in rows]
        return verify_event_chain(self._mediation_signer, events)

    def _quarantine_locked(
        self,
        row: sqlite3.Row,
        *,
        verified_state: MediationHead | None = None,
    ) -> None:
        enqueue_id = row["mediation_enqueue_id"] or str(uuid.uuid4())
        self._conn.execute(
            """UPDATE tasks
                  SET status='quarantined', mediation_execution_id=NULL, updated_at=?
                WHERE id=?""",
            (_now(), row["id"]),
        )
        try:
            self._append_mediation_event_locked(
                outcome="ungoverned_detected",
                task_id=int(row["id"]),
                enqueue_id=enqueue_id,
                receipt=None,
                verified_state=verified_state,
            )
        except Exception:
            # Quarantine is the authority boundary. A missing signer must never
            # keep a suspicious row executable merely because evidence degraded.
            self._mark_mediation_integrity_broken_locked()
            logger.exception("Could not persist B7 quarantine evidence")

    def claim_mediated(self, task_id: int, *, execution_id: str) -> Optional[Task]:
        """CAS an approved mediated row to running after persisted revalidation."""

        if self.mediation_mode != "enforce":
            return None
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                snapshot = self._validated_mediation_snapshot_locked()
                if snapshot is None:
                    self._conn.rollback()
                    return None
                verified_state = snapshot[0]
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None or row["status"] != TaskStatus.APPROVED.value:
                    self._conn.rollback()
                    return None
                if self._consent_marked_locked(row):
                    self._conn.rollback()
                    return None
                if row['decided_by'] == 'owner_once' or row['decision'] == 'owner-once':
                    self._conn.rollback()
                    return None
                if self._classification(row["kind"]) is not True:
                    self._quarantine_locked(row, verified_state=verified_state)
                    self._conn.commit()
                    return None
                try:
                    receipt, expectation, current_sha256 = self._row_receipt_and_expectation(row)
                    authorized = self._conn.execute(
                        """SELECT 1 FROM task_mediation_events
                           WHERE task_id=? AND enqueue_id=?
                             AND outcome='authorized_enqueue'
                           LIMIT 1""",
                        (task_id, expectation.enqueue_id),
                    ).fetchone()
                    valid = (
                        row["mediation_execution_id"] is None
                        and int(row["risk_tier"]) == receipt.effective_tier
                        and self._scope_allowed(expectation.scope)
                        and expectation.policy_revision == self._mediation_policy_revision
                        and authorized is not None
                        and current_sha256 == row["mediation_task_sha256"]
                        and self._event_chain_valid_locked()
                        and verify_receipt(
                            self._mediation_signer,
                            receipt,
                            expected=expectation,
                            now_ms=self._clock_ms(),
                        )
                    )
                except Exception:
                    valid = False
                if not valid:
                    self._quarantine_locked(row, verified_state=verified_state)
                    self._conn.commit()
                    return None
                changed = self._conn.execute(
                    """UPDATE tasks
                          SET status='running', mediation_execution_id=?, updated_at=?
                        WHERE id=? AND status='approved'
                          AND mediation_execution_id IS NULL""",
                    (execution_id, _now(), task_id),
                )
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return None
                self._append_mediation_event_locked(
                    outcome="governed",
                    task_id=task_id,
                    enqueue_id=expectation.enqueue_id,
                    receipt=receipt,
                    execution_id=execution_id,
                    verified_state=verified_state,
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                return None
        return self.get(task_id)

    def validate_mediated_execution(self, task: Task, expected_fingerprint: str) -> bool:
        """Revalidate a claimed task and its full persisted tuple at dispatch.

        The one-use worker permit proves which in-memory snapshot was claimed;
        this check independently proves that the same snapshot is still the
        authenticated RUNNING row in durable storage immediately before a
        handler receives it.

        False is the governance answer: the store was read and does not authorise this
        execution. A check that could not complete — the database, the head anchor, a
        stored receipt or the signer raised — raises :class:`MediationStateUnavailable`
        (review round 6, item 2): it used to read as False, so a broken store was
        reported as a mediation hold (a refusal, or a withheld result) instead of a
        failure.
        """

        if self.mediation_mode != "enforce" or not expected_fingerprint:
            return False
        with self._lock:
            try:
                snapshot = self._validated_mediation_snapshot_locked()
                if snapshot is None:
                    return False
                row = self._conn.execute(
                    "SELECT * FROM tasks WHERE id=?", (getattr(task, "id", 0),)
                ).fetchone()
                if (
                    row is None
                    or row["status"] != TaskStatus.RUNNING.value
                    or self._classification(row["kind"]) is not True
                    or not self._row_requires_mediation_locked(row)
                ):
                    return False

                persisted = _row_to_task(row)
                persisted_fingerprint = self.execution_fingerprint(persisted)
                presented_fingerprint = self.execution_fingerprint(task)
                if not (
                    persisted_fingerprint
                    and persisted_fingerprint == expected_fingerprint
                    and presented_fingerprint == expected_fingerprint
                    and persisted.mediation_execution_id
                    and task.status == TaskStatus.RUNNING.value
                ):
                    return False

                receipt, expectation, current_sha256 = self._row_receipt_and_expectation(row)
                receipt_sha256 = canonical_digest(receipt.to_dict())
                authorized = self._conn.execute(
                    """SELECT COUNT(*) AS count FROM task_mediation_events
                       WHERE task_id=? AND enqueue_id=?
                         AND outcome='authorized_enqueue'
                         AND receipt_id=? AND receipt_sha256=?""",
                    (
                        task.id,
                        expectation.enqueue_id,
                        receipt.receipt_id,
                        receipt_sha256,
                    ),
                ).fetchone()
                governed = self._conn.execute(
                    """SELECT COUNT(*) AS count FROM task_mediation_events
                       WHERE task_id=? AND enqueue_id=?
                         AND outcome='governed' AND execution_id=?
                         AND receipt_id=? AND receipt_sha256=?""",
                    (
                        task.id,
                        expectation.enqueue_id,
                        persisted.mediation_execution_id,
                        receipt.receipt_id,
                        receipt_sha256,
                    ),
                ).fetchone()
                return (
                    int(row["risk_tier"]) == receipt.effective_tier
                    and self._scope_allowed(expectation.scope)
                    and expectation.policy_revision == self._mediation_policy_revision
                    and current_sha256 == row["mediation_task_sha256"]
                    and authorized is not None
                    and int(authorized["count"]) == 1
                    and governed is not None
                    and int(governed["count"]) == 1
                    and verify_receipt(
                        self._mediation_signer,
                        receipt,
                        expected=expectation,
                        now_ms=self._clock_ms(),
                    )
                )
            except Exception as exc:
                raise MediationStateUnavailable("mediation state unavailable") from exc

    def scan_unmediated_tasks(self) -> list[int]:
        """Quarantine executable classified rows without a valid B7 binding."""

        if self.mediation_mode not in {"enforce", "hold"}:
            return []
        quarantined: list[int] = []
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM tasks
                   WHERE status IN ('proposed', 'approved', 'running')
                   ORDER BY id"""
            ).fetchall()
            for row in rows:
                classification = self._classification(row["kind"])
                if classification is False and not self._row_requires_mediation_locked(row):
                    continue
                valid = False
                if classification is True and row["mediation_receipt"]:
                    try:
                        receipt, expectation, current_sha256 = self._row_receipt_and_expectation(
                            row
                        )
                        authorized = self._conn.execute(
                            """SELECT 1 FROM task_mediation_events
                               WHERE task_id=? AND enqueue_id=?
                                 AND outcome='authorized_enqueue'
                               LIMIT 1""",
                            (row["id"], expectation.enqueue_id),
                        ).fetchone()
                        valid = (
                            int(row["risk_tier"]) == receipt.effective_tier
                            and self._scope_allowed(expectation.scope)
                            and expectation.policy_revision == self._mediation_policy_revision
                            and current_sha256 == row["mediation_task_sha256"]
                            and authorized is not None
                            and self._event_chain_valid_locked()
                            and verify_receipt(
                                self._mediation_signer,
                                receipt,
                                expected=expectation,
                                now_ms=self._clock_ms(),
                            )
                        )
                    except Exception:
                        valid = False
                if valid:
                    continue
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    self._quarantine_locked(row)
                    self._conn.commit()
                    quarantined.append(int(row["id"]))
                except Exception:
                    self._conn.rollback()
                    # A write failure leaves the row untouched, but claim still
                    # independently denies it under enforce and hold never claims.
                    logger.exception("Could not quarantine unmediated task %s", row["id"])
        return quarantined

    @staticmethod
    def _human_decision_record(action: str, by: str, reason: str | None, at: str,
                               *, previous: str | None = None) -> dict:
        if action not in {"accept", "edit", "reject", "defer"} or not isinstance(by, str) or not by:
            raise TaskQueueError("human decision requires an action and decider")
        first_at = at if previous is None else None
        if previous is not None:
            try:
                old = json.loads(previous)
                candidate = normalize_approval_deadline(old.get('first_at')) if isinstance(old, dict) else None
                if candidate is not None and datetime.fromisoformat(candidate) <= datetime.fromisoformat(at):
                    first_at = candidate
            except (TypeError, ValueError):
                first_at = None  # A damaged or legacy last-decision record proves no first cutoff.
        return {"id": uuid.uuid4().hex, "action": action, "reason": reason, "by": by,
                "at": at, "first_at": first_at}

    def transition(
        self, task_id: int, new_status: TaskStatus, *, decided_by: str = None,
        decision: str = None, result: dict = None,
        human_reason: str | None | object = _HUMAN_REASON_UNSET,
        expected_status: TaskStatus | None = None,
    ) -> Task:
        task, _group_id = self.transition_with_group(
            task_id, new_status, decided_by=decided_by, decision=decision,
            result=result, human_reason=human_reason,
            expected_status=expected_status,
        )
        return task

    def transition_with_group(
        self,
        task_id: int,
        new_status: TaskStatus,
        *,
        decided_by: str = None,
        decision: str = None,
        result: dict = None,
        human_reason: str | None | object = _HUMAN_REASON_UNSET,
        expected_status: TaskStatus | None = None,
    ) -> tuple[Task, str | None]:
        """Settle and capture private promotion identity, including a singleton, atomically."""
        # Execution passes result only; a successful human decision explicitly
        # passes human_reason, including None to clear an earlier attribution.
        record_human = human_reason is not _HUMAN_REASON_UNSET
        reason = normalize_reason(human_reason) if record_human else None
        new_status = TaskStatus(new_status)
        with self._lock:
            # Keep validation and mutation in one write transaction, including
            # against other queue connections/processes racing this decision.
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                task = _row_to_task(row) if row else None
                if task is None:
                    raise TaskQueueError(f"task {task_id} not found")
                cur_status = TaskStatus(task.status)
                instant = _approval_now()
                self._raise_due_approval_locked(row, instant,
                    reopening=cur_status == TaskStatus.DEFERRED and new_status == TaskStatus.BLOCKED)
                if expected_status is not None and cur_status != TaskStatus(expected_status):
                    raise TaskQueueError(f'unexpected task status {cur_status.value} (task {task_id})')
                if new_status not in _TRANSITIONS.get(cur_status, set()):
                    raise TaskQueueError(
                        f"illegal transition {cur_status.value} → {new_status.value} (task {task_id})"
                    )
                if (decided_by == 'consent'
                        or (type(decision) is str and
                            (decision.startswith('auto-consent-') or
                             decision.startswith('consent-')))):
                    raise TaskQueueError('consent decision requires private queue authority')
                if self._consent_marked_locked(row) and (
                    (cur_status == TaskStatus.APPROVED and new_status == TaskStatus.RUNNING)
                    or (cur_status == TaskStatus.RUNNING and new_status == TaskStatus.APPROVED)
                    or new_status in {TaskStatus.BLOCKED, TaskStatus.DEFERRED}
                    or decided_by is not None or decision is not None or record_human
                ):
                    raise TaskQueueError('consent transition requires private queue authority')
                if (self._consent_marked_locked(row)
                        and cur_status == TaskStatus.RUNNING
                        and new_status == TaskStatus.DONE):
                    claim = self._consent_claims.get(task_id)
                    bound = self._conn.execute(
                        'SELECT state FROM task_consent_proofs WHERE task_id=?', (task_id,)
                    ).fetchone()
                    if (bound is None or bound['state'] != 'dispatching' or claim is None
                            or not self._consent_claim_current_locked(task_id, claim, lambda: True)):
                        raise TaskQueueError('consent execution has not dispatched')
                if (new_status == TaskStatus.APPROVED and decision in {'accept', 'edit'}
                        and self._current_smart_denial_locked(task)):
                    raise TaskQueueError('smart denial requires exact owner-once reply')
                if (cur_status == TaskStatus.APPROVED and new_status == TaskStatus.RUNNING
                        and task.decided_by == 'owner_once' and task.decision == 'owner-once'):
                    raise TaskQueueError('owner-once execution requires private claim')
                now = instant.isoformat(timespec='microseconds')
                sets = ["status=?", "updated_at=?"]
                params: list = [new_status.value, now]
                if decided_by is not None:
                    sets.append("decided_by=?")
                    params.append(decided_by)
                if decision is not None:
                    sets.append("decision=?")
                    params.append(decision)
                if result is not None:
                    sets.append("result=?")
                    params.append(json.dumps(result, ensure_ascii=False))
                if record_human:
                    metadata = self._human_decision_record(decision, decided_by, reason, now,
                                                           previous=row['human_decision'])
                    sets.append("human_decision=?")
                    params.append(json.dumps(metadata, ensure_ascii=False))
                params.append(task_id)
                # Column names are a fixed list; all values stay parameterized.
                self._conn.execute(
                    f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params,  # nosec B608
                )
                group_id = self._withdraw_task_group_locked(task_id)
                self._record_promotion_effect_locked(group_id, task_id)
                updated = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if new_status == TaskStatus.BLOCKED and decided_by == 'policy' and decision == 'needs-approval':
                    self._finalize_chat_approval_locked(_row_to_task(updated))
                if record_human and new_status == TaskStatus.APPROVED and decision in {'accept', 'edit'}:
                    self._reset_chat_guardian_denials_locked(task)
                self._conn.commit()
                if new_status in {TaskStatus.DONE, TaskStatus.FAILED}:
                    self._consent_claims.pop(task_id, None)
                return _row_to_task(updated), group_id
            except TaskApprovalExpired:
                raise  # expiry already committed; never roll it back
            except Exception:
                self._conn.rollback()
                raise

    def attach_human_reason(self, task_id: int, reason: str | None, *,
                            expected_decision: dict) -> Task | None:
        """Fill one exact Telegram rejection's missing reason, metadata only.

        The caller owns owner/chat/window verification; this CAS binds that
        window to a persisted unique decision and never reopens the task.
        """
        normalized = normalize_reason(reason)
        if normalized is None or not isinstance(expected_decision, dict):
            return None
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                task = _row_to_task(row) if row else None
                metadata = task.human_decision if task else None
                if (task is None or task.status != TaskStatus.REJECTED.value
                        or not isinstance(metadata, dict) or metadata != expected_decision
                        or metadata.get("action") != "reject" or metadata.get("by") != "telegram"
                        or metadata.get("reason") is not None):
                    self._conn.rollback()
                    return None
                changed = {**metadata, "reason": normalized}
                self._conn.execute("UPDATE tasks SET human_decision=? WHERE id=?",
                                   (json.dumps(changed, ensure_ascii=False), task_id))
                updated = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                self._conn.commit()
                return _row_to_task(updated)
            except Exception:
                self._conn.rollback()
                raise

    def _task_group_binding_locked(self, row: sqlite3.Row) -> dict | None:
        """Compare authority categories; each member keeps its independent receipt."""
        binding = {'mode': self.mediation_mode, 'policy_revision': self.mediation_policy_revision,
                   'binding': 'registration_only', 'scope': None}
        if self._row_requires_mediation_locked(row):
            try:
                if self.mediation_mode != 'enforce':
                    return None
                receipt, expected, digest = self._row_receipt_and_expectation(row)
                if (receipt.policy_revision != self.mediation_policy_revision
                        or row['mediation_task_sha256'] != digest
                        or not self._scope_allowed(expected.scope)
                        or not verify_receipt(self._mediation_signer, receipt, expected=expected,
                                              now_ms=self._mediation_clock_ms())):
                    return None
                binding.update(binding='independent_mediated_receipt', scope=receipt.scope,
                               verdict=receipt.verdict, tier=receipt.tier,
                               effective_tier=receipt.effective_tier,
                               reason_sha256=receipt.reason_sha256)
            except Exception:
                return None
        elif row['kernel_intake_id'] or row['kernel_intake_evidence']:
            return None  # no proven common authority context for this separate intake seam
        return binding

    def _pending_group_members_locked(self, group_id: str) -> list[sqlite3.Row]:
        members = self._conn.execute(
            "SELECT tasks.*, g.fingerprint AS group_fingerprint, g.member_sha256 AS group_member_sha256, "
            "g.snapshot AS group_snapshot, g.binding_sha256 AS group_binding_sha256 "
            "FROM tasks JOIN task_approval_groups g ON g.task_id=tasks.id "
            "WHERE g.group_id=? AND tasks.status='blocked' ORDER BY tasks.id LIMIT 65", (group_id,),
        ).fetchall()
        if len(members) > 64:
            return []
        for row in members:
            binding = self._task_group_binding_locked(row)
            binding_digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest() if binding else None
            if (row['group_member_sha256'] != self._approval_snapshot_digest_locked(_row_to_task(row))
                    or not binding_digest or row['group_binding_sha256'] != binding_digest
                    or row['group_fingerprint'] != members[0]['group_fingerprint']
                    or row['group_snapshot'] != members[0]['group_snapshot']):
                return []
        return members

    def _withdraw_task_group_locked(self, task_id: int) -> str | None:
        membership = self._conn.execute(
            'SELECT group_id FROM task_approval_groups WHERE task_id=?', (task_id,),
        ).fetchone()
        if membership is not None:
            self._conn.execute('DELETE FROM task_approval_groups WHERE task_id=?', (task_id,))
            self._conn.execute('UPDATE task_approval_groups SET snapshot=? WHERE group_id=?',
                               (uuid.uuid4().hex, membership['group_id']))
            return membership['group_id']
        return None

    def register_pending_group(self, task_id: int, *, context, policy: dict) -> dict | None:
        """Attach verified registration/producer metadata; this never changes the task."""
        from .approval_grouping import current_model_producer, model_group_semantics
        from .approval_judge import action_is_tainted
        from .inbox import OwnerTaskRegistrationContext
        owner_context = type(context) is OwnerTaskRegistrationContext
        if owner_context:
            try:
                checked = OwnerTaskRegistrationContext.from_request(json.loads(context.request_json))
                if checked is None or checked.request_json != context.request_json:
                    return None
            except (TypeError, ValueError, RecursionError):
                return None
        elif context is None or context is not current_model_producer():
            return None
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                if row is None or row['status'] != 'blocked':
                    self._conn.rollback()
                    return None
                binding = self._task_group_binding_locked(row)
                member = self._approval_snapshot_digest_locked(_row_to_task(row))
                if binding is None or member is None:
                    self._conn.rollback()
                    return None
                task = _row_to_task(row)
                producer = ({'request': json.loads(context.request_json), 'principal': 'owner',
                             'surface': 'http_task_registration'} if owner_context
                            else model_group_semantics(context, task))
                if producer is None:
                    self._conn.rollback()
                    return None
                semantics = {**producer, 'policy': policy,
                             'namespace': self._group_namespace, 'authority': binding,
                             'task': {key: getattr(task, key) for key in (
                                 'agent', 'kind', 'title', 'payload', 'origin', 'risk_tier',
                                 'autonomy_level', 'attention_mode',
                             )}, 'tainted': action_is_tainted({'args': task.payload, 'origin': task.origin})}
                encoded = json.dumps(semantics, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')
                if len(encoded) > 131_072:
                    self._conn.rollback()
                    return None
                fingerprint = hashlib.sha256(encoded).hexdigest()
                binding_digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
                candidates = self._conn.execute(
                    'SELECT DISTINCT group_id FROM task_approval_groups WHERE fingerprint=? LIMIT 64',
                    (fingerprint,),
                ).fetchall()
                group_id = uuid.uuid4().hex
                for candidate in candidates:
                    members = self._pending_group_members_locked(candidate['group_id'])
                    if 0 < len(members) < 64:
                        group_id = candidate['group_id']
                        break
                snapshot = uuid.uuid4().hex
                self._conn.execute('UPDATE task_approval_groups SET snapshot=? WHERE group_id=?',
                                   (snapshot, group_id))
                self._conn.execute(
                    'INSERT INTO task_approval_groups(task_id,group_id,fingerprint,member_sha256,snapshot,binding_sha256) '
                    'VALUES (?,?,?,?,?,?)', (task_id, group_id, fingerprint, member, snapshot, binding_digest),
                )
                self._conn.commit()
            except (TypeError, ValueError, UnicodeError):
                self._conn.rollback()
                return None
            except Exception:
                self._conn.rollback()
                raise
        return self.pending_group(task_id)

    def _group_projection_locked(self, group_id: str) -> dict | None:
        members = self._pending_group_members_locked(group_id)
        if len(members) < 2:
            return None
        return {'id': group_id, 'leader_id': members[0]['id'], 'count': len(members),
                'member_ids': [row['id'] for row in members], 'snapshot': members[0]['group_snapshot']}

    def pending_groups(self) -> list[dict]:
        with self._lock:
            identifiers = self._conn.execute(
                "SELECT DISTINCT g.group_id FROM task_approval_groups g JOIN tasks ON tasks.id=g.task_id "
                "WHERE tasks.status='blocked' ORDER BY tasks.id LIMIT 1000"
            ).fetchall()
            groups = [group for row in identifiers
                      if (group := self._group_projection_locked(row['group_id'])) is not None]
            groups.sort(key=lambda group: group['leader_id'])
            return groups

    def pending_group(self, task_id: int) -> dict | None:
        with self._lock:
            membership = self._conn.execute(
                'SELECT group_id FROM task_approval_groups WHERE task_id=?', (task_id,),
            ).fetchone()
            group = self._group_projection_locked(membership['group_id']) if membership else None
            return group if group and task_id in group['member_ids'] else None

    def pending_group_leader(self, group_id: str) -> Task | None:
        """Next valid member, including a singleton left after once settlement."""
        with self._lock:
            members = self._pending_group_members_locked(group_id)
            return _row_to_task(members[0]) if members else None

    def reject_pending_group(self, group_id: str, *, snapshot: str, member_ids: list[int],
                             decided_by: str = 'admin', reason: str | None = None) -> list[Task] | None:
        """One SQLite transaction rejects exactly the current immutable membership."""
        normalized = normalize_reason(reason)
        if (not isinstance(member_ids, list) or not 2 <= len(member_ids) <= 64
                or any(type(task_id) is not int or task_id < 1 for task_id in member_ids)):
            return None
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                instant = _approval_now()
                # Resolve membership from the stored group, never submitted IDs.
                members = self._conn.execute(
                    "SELECT tasks.* FROM tasks JOIN task_approval_groups g ON g.task_id=tasks.id "
                    "WHERE g.group_id=? AND tasks.status='blocked' ORDER BY tasks.id LIMIT 65", (group_id,),
                ).fetchall()
                if len(members) > 64:
                    self._conn.rollback()
                    return None
                effects = []
                corrupt = False
                for row in members:
                    try:
                        effect = self._expire_approval_locked(row, instant)
                    except TaskQueueError:
                        corrupt = True
                        continue
                    if effect is not None:
                        effects.append(effect)
                if effects:
                    batch = self._expiry_batch_locked(effects)
                    self._conn.commit()
                    raise TaskApprovalExpired(batch)
                if corrupt:
                    self._conn.rollback()
                    return None
                group = self._group_projection_locked(group_id)
                if group is None or group['snapshot'] != snapshot or group['member_ids'] != member_ids:
                    self._conn.rollback()
                    return None
                now = instant.isoformat(timespec='microseconds')
                previous_decisions = {row['id']: row['human_decision'] for row in members}
                for task_id in member_ids:
                    metadata = self._human_decision_record('reject', decided_by, normalized, now,
                                                           previous=previous_decisions[task_id])
                    self._conn.execute(
                        "UPDATE tasks SET status='rejected', decided_by=?, decision='reject', "
                        'human_decision=?, updated_at=? WHERE id=?',
                        (decided_by, json.dumps(metadata, ensure_ascii=False), now, task_id),
                    )
                    self._withdraw_task_group_locked(task_id)
                result = [_row_to_task(self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())
                          for task_id in member_ids]
                self._conn.commit()
                return result
            except TaskApprovalExpired:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def update_payload(self, task_id: int, payload: dict) -> None:
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                if row is not None and self._consent_marked_locked(row):
                    raise TaskQueueError('consent task cannot be edited')
                instant = _approval_now()
                if row is not None:
                    self._raise_due_approval_locked(row, instant)
                self._conn.execute(
                    'UPDATE tasks SET payload=?, updated_at=? WHERE id=?',
                    (json.dumps(payload, ensure_ascii=False), instant.isoformat(timespec='microseconds'), task_id),
                )
                self._conn.execute(
                    'INSERT INTO approval_judgement_revisions (task_id, revision) VALUES (?, 1) '
                    'ON CONFLICT(task_id) DO UPDATE SET revision=revision+1', (task_id,),
                )
                self._withdraw_task_group_locked(task_id)
                self._conn.commit()
            except TaskApprovalExpired:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def update_payload_policy(
        self, task_id: int, payload: dict, *, risk_tier: int, autonomy_level: str,
        decided_by: str | None = None,
        human_reason: str | None | object = _HUMAN_REASON_UNSET, approve: bool = False,
    ) -> Task:
        task, _group_id = self.update_payload_policy_with_group(
            task_id, payload, risk_tier=risk_tier, autonomy_level=autonomy_level,
            decided_by=decided_by, human_reason=human_reason, approve=approve,
        )
        return task

    def update_payload_policy_with_group(
        self,
        task_id: int,
        payload: dict,
        *,
        risk_tier: int,
        autonomy_level: str,
        decided_by: str | None = None,
        human_reason: str | None | object = _HUMAN_REASON_UNSET,
        approve: bool = False,
    ) -> tuple[Task, str | None]:
        """Edit atomically and capture the withdrawn private group for promotion."""
        record_human = human_reason is not _HUMAN_REASON_UNSET
        reason = normalize_reason(human_reason) if record_human else None
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                task = _row_to_task(row) if row else None
                if task is None:
                    raise TaskQueueError(f"task {task_id} not found")
                if self._consent_marked_locked(row) or decided_by == 'consent':
                    raise TaskQueueError('consent task cannot be edited')
                instant = _approval_now()
                self._raise_due_approval_locked(row, instant)
                if (record_human or approve) and self._current_smart_denial_locked(task):
                    raise TaskQueueError('smart denial requires exact owner-once reply')
                if (record_human or approve) and TaskStatus.APPROVED not in _TRANSITIONS.get(
                    TaskStatus(task.status), set(),
                ):
                    raise TaskQueueError(f"task {task_id} cannot accept an edit from {task.status}")
                now = instant.isoformat(timespec='microseconds')
                sets = ["payload=?", "risk_tier=?", "autonomy_level=?", "updated_at=?"]
                values = [json.dumps(payload, ensure_ascii=False), int(risk_tier), autonomy_level, now]
                if record_human:
                    metadata = self._human_decision_record("edit", decided_by, reason, now,
                                                           previous=row['human_decision'])
                    sets.append("human_decision=?")
                    values.append(json.dumps(metadata, ensure_ascii=False))
                if approve:
                    sets.extend(["status=?", "decided_by=?", "decision=?"])
                    values.extend([TaskStatus.APPROVED.value, decided_by, "edit"])
                values.append(task_id)
                self._conn.execute(
                    f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", values,  # nosec B608
                )
                self._conn.execute(
                    "INSERT INTO approval_judgement_revisions (task_id, revision) VALUES (?, 1) "
                    "ON CONFLICT(task_id) DO UPDATE SET revision=revision+1", (task_id,),
                )
                group_id = self._withdraw_task_group_locked(task_id)
                self._record_promotion_effect_locked(group_id, task_id)
                updated = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if record_human and approve:
                    self._reset_chat_guardian_denials_locked(task)
                self._conn.commit()
                return _row_to_task(updated), group_id
            except TaskApprovalExpired:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def increment_attempts(self, task_id: int) -> int:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET attempts = attempts + 1, updated_at=? WHERE id=?",
                (_now(), task_id),
            )
            self._conn.commit()
        return self.get(task_id).attempts

    def mark_pushed(self, task_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET pushed=1, updated_at=? WHERE id=?", (_now(), task_id)
            )
            self._conn.commit()

    def record_capability_outcome(self, capability_id: str, *, success: bool) -> None:
        """Durably add one real terminal execution outcome for a capability."""
        capability_id = str(capability_id or "").strip()
        if not capability_id:
            return
        succeeded, failed = (1, 0) if success else (0, 1)
        now = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO capability_outcomes
                       (capability_id, successes, failures, last_outcome_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(capability_id) DO UPDATE SET
                       successes = successes + excluded.successes,
                       failures = failures + excluded.failures,
                       last_outcome_at = excluded.last_outcome_at""",
                (capability_id, succeeded, failed, now),
            )
            self._conn.commit()

    # Chat origin metadata is observational, outside every execution/receipt field.
    def _associate_chat_approval_locked(self, task_id: int, task_birth: str) -> None:
        producer = current_tool_approval()
        if producer is None:
            return
        context = producer.turn
        per_turn = self._conn.execute('SELECT COUNT(*) FROM chat_approval_tasks WHERE origin_id=?',
                                      (context.turn_id,)).fetchone()[0]
        per_consumer = self._conn.execute('''SELECT COUNT(*) FROM chat_approval_tasks t
            JOIN chat_approval_origins o ON o.origin_id=t.origin_id
            WHERE o.session_id=? AND o.session_instance=? AND o.principal_key=?''',
            (context.session_id, context.session_instance, context.principal_key)).fetchone()[0]
        if per_turn >= MAX_PER_TURN or per_consumer >= MAX_PER_CONSUMER:
            logger.warning('chat approval observation capacity reached; task retained')
            return
        self._conn.execute('INSERT OR IGNORE INTO chat_approval_origins VALUES(?,?,?,?,?)',
                           (context.turn_id, context.session_id, context.session_instance,
                            context.principal_key, _now()))
        self._conn.execute('INSERT INTO chat_approval_tasks(task_id,origin_id,tool,task_birth) VALUES(?,?,?,?)',
                           (task_id, context.turn_id, producer.tool, task_birth))

    def _chat_intent_locked(self, task: Task) -> str:
        fields = ('id', 'agent', 'kind', 'title', 'payload', 'risk_tier', 'autonomy_level',
                  'attention_mode', 'origin', 'created_at', 'mediation_enqueue_id',
                  'mediation_enqueue_revision', 'mediation_scope', 'mediation_policy_revision',
                  'mediation_task_sha256', 'mediation_receipt', 'kernel_intake_id', 'kernel_intake_evidence')
        value = {name: getattr(task, name) for name in fields}
        revision = self._conn.execute('SELECT revision FROM approval_judgement_revisions WHERE task_id=?',
                                      (task.id,)).fetchone()
        value['edit_revision'] = revision[0] if revision else 0
        value['queue_binding'] = [self.mediation_mode, self._mediation_policy_revision]
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _finalize_chat_approval_locked(self, task: Task) -> None:
        producer = current_tool_approval()
        if producer is None:
            return
        try:
            digest = self._chat_intent_locked(task)
        except (TypeError, ValueError):
            logger.warning('chat approval intent unavailable; task retained')
            return
        self._conn.execute('''UPDATE chat_approval_tasks SET ready=1,intent_sha256=?
            WHERE task_id=? AND origin_id=? AND task_birth=? AND ready=0''',
            (digest, task.id, producer.turn.turn_id, task.created_at))

    @staticmethod
    def _chat_context(context) -> bool:
        return isinstance(context, ApprovalTurnContext) and context.live()

    def _chat_denial_consumer_locked(self, task: Task) -> sqlite3.Row | None:
        """Return only the server-created, ready association for this task birth."""
        row = self._conn.execute('''SELECT t.*, o.session_id, o.session_instance, o.principal_key
            FROM chat_approval_tasks t JOIN chat_approval_origins o ON o.origin_id=t.origin_id
            WHERE t.task_id=? AND t.ready=1 AND t.task_birth=?''',
            (task.id, task.created_at)).fetchone()
        return row if (row is not None and row['tool'] == 'terminal_run'
                       and isinstance(row['intent_sha256'], str)
                       and _SHA256_HEX.fullmatch(row['intent_sha256']) is not None) else None

    def _record_chat_guardian_denial_locked(self, task: Task, snapshot_sha256: str) -> None:
        """Append one exact event and increment its consumer in the caller's CAS."""
        consumer = self._chat_denial_consumer_locked(task)
        if consumer is None:
            return
        key = (consumer['session_id'], consumer['session_instance'], consumer['principal_key'])
        prior = self._conn.execute('''SELECT consecutive_denials,epoch
            FROM chat_guardian_denial_tallies
            WHERE session_id=? AND session_instance=? AND principal_key=?''', key).fetchone()
        if (prior is not None and type(prior['consecutive_denials']) is int
                and 1 <= prior['consecutive_denials'] <= _GUARDIAN_DENIAL_LIMIT
                and isinstance(prior['epoch'], str)
                and _GUARDIAN_EPOCH_HEX.fullmatch(prior['epoch']) is not None):
            count = min(_GUARDIAN_DENIAL_LIMIT, prior['consecutive_denials'] + 1)
            epoch = prior['epoch']
        else:
            count, epoch = 1, uuid.uuid4().hex
        now = _now()
        sequence = self._conn.execute('''SELECT COALESCE(MAX(last_sequence),0)+1
            FROM chat_guardian_denial_tallies''').fetchone()[0]
        self._conn.execute('''INSERT INTO chat_guardian_denial_tallies
            (session_id,session_instance,principal_key,consecutive_denials,epoch,updated_at,last_sequence)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(session_id,session_instance,principal_key)
            DO UPDATE SET consecutive_denials=excluded.consecutive_denials,
                          epoch=excluded.epoch,updated_at=excluded.updated_at,
                          last_sequence=excluded.last_sequence''',
            (*key, count, epoch, now, sequence))
        changed = self._conn.execute('''UPDATE chat_approval_tasks
            SET denial_snapshot_sha256=?,denial_count=?,denial_epoch=?,denial_sequence=?
            WHERE task_id=? AND origin_id=? AND ready=1 AND task_birth=?''',
            (snapshot_sha256, count, epoch, sequence, task.id, consumer['origin_id'], task.created_at))
        if changed.rowcount != 1:
            raise TaskQueueError('guardian denial association changed')
        # Keep only the 256 most recently denied consumer keys. Eviction never
        # removes a task or its historical event; an evicted event cannot warn.
        self._conn.execute('''DELETE FROM chat_guardian_denial_tallies WHERE rowid IN
            (SELECT rowid FROM chat_guardian_denial_tallies
             ORDER BY last_sequence DESC,rowid DESC LIMIT -1 OFFSET ?)''',
            (_GUARDIAN_CONSUMER_LIMIT,))

    def _reset_chat_guardian_denials_locked(self, task: Task) -> None:
        """Reset only this task's original consumer within the approval transaction."""
        consumer = self._chat_denial_consumer_locked(task)
        if consumer is not None:
            self._conn.execute('''DELETE FROM chat_guardian_denial_tallies
                WHERE session_id=? AND session_instance=? AND principal_key=?''',
                (consumer['session_id'], consumer['session_instance'], consumer['principal_key']))

    def _chat_guardian_denial_locked(self, task: Task, association: sqlite3.Row) -> dict | None:
        """Project one exact original DENY, including its settled outcome."""
        if association['ready'] != 1 or association['task_birth'] != task.created_at:
            return None
        snapshot, count, epoch, sequence = (
            association['denial_snapshot_sha256'], association['denial_count'],
            association['denial_epoch'], association['denial_sequence'],
        )
        if (type(snapshot) is not str or _SHA256_HEX.fullmatch(snapshot) is None
                or type(count) is not int or not 1 <= count <= _GUARDIAN_DENIAL_LIMIT
                or type(epoch) is not str or _GUARDIAN_EPOCH_HEX.fullmatch(epoch) is None
                or type(sequence) is not int or sequence <= 0):
            return None
        row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task.id,)).fetchone()
        if task.status == TaskStatus.BLOCKED.value:
            if (not approval_is_pending(task) or task.decided_by != 'policy'
                    or task.decision != 'needs-approval' or task.human_decision is not None):
                return None
        elif task.status == TaskStatus.REJECTED.value:
            if self._smart_terminal_denial_locked(task.id, snapshot) is None:
                bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                           (task.id,)).fetchone()
                if (self._owner_once_withdrawn_approval_locked(row, bound) is None
                        or bound['denial_snapshot_sha256'] != snapshot
                        or bound['origin_id'] != association['origin_id']
                        or bound['intent_sha256'] != association['intent_sha256']):
                    return None
        elif task.status in {'approved', 'running', 'done'} and task.decided_by == 'owner_once':
            bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                       (task.id,)).fetchone()
            if (self._owner_once_approval_locked(row, bound, allow_done=True) is None
                    or bound['denial_snapshot_sha256'] != snapshot
                    or bound['origin_id'] != association['origin_id']
                    or bound['intent_sha256'] != association['intent_sha256']):
                return None
        else:
            return None
        original = replace(task, status=TaskStatus.BLOCKED.value,
                           decided_by='policy', decision='needs-approval',
                           mediation_execution_id=None, human_decision=None)
        if self._approval_snapshot_digest_locked(original) != snapshot:
            return None
        opinion = self._conn.execute('''SELECT snapshot_sha256,annotation,receipt,signature
            FROM task_smart_approvals WHERE task_id=? AND snapshot_sha256=?''',
            (task.id, snapshot)).fetchone()
        if opinion is None or self._unsigned_smart_hold_verdict(opinion) != 'deny':
            return None
        consumer = self._chat_denial_consumer_locked(task)
        if consumer is None:
            return None
        tally = self._conn.execute('''SELECT consecutive_denials,epoch
            FROM chat_guardian_denial_tallies
            WHERE session_id=? AND session_instance=? AND principal_key=?''',
            (consumer['session_id'], consumer['session_instance'], consumer['principal_key'])).fetchone()
        threshold = _guardian_denial_threshold()
        breaker = bool(
            threshold and count >= threshold and tally is not None
            and tally['epoch'] == epoch and type(tally['consecutive_denials']) is int
            and count <= tally['consecutive_denials'] <= _GUARDIAN_DENIAL_LIMIT
        )
        return {'decision': 'deny', 'consecutive_denials': count, 'breaker': breaker}

    def _chat_observation_locked(self, association: sqlite3.Row) -> dict:
        digest = association['intent_sha256']
        if (not isinstance(digest, str) or len(digest) != 64
                or any(ch not in '0123456789abcdef' for ch in digest)
                or not isinstance(association['tool'], str) or not association['tool']
                or len(association['tool']) > 128):
            raise ValueError('invalid chat approval binding metadata')
        raw = self._conn.execute('SELECT * FROM tasks WHERE id=?', (association['task_id'],)).fetchone()
        task = _row_to_task(raw) if raw is not None else None
        # AUTOINCREMENT prevents ordinary ID reuse. Birth check also fails closed
        # for an externally restored/substituted row with the same integer ID.
        if task is not None and task.created_at != association['task_birth']:
            task = None
        states = {'proposed': 'waiting', 'blocked': 'waiting', 'deferred': 'waiting',
                  'approved': 'approved_not_executed', 'running': 'running', 'done': 'completed',
                  'failed': 'execution_failed', 'rejected': 'rejected', 'quarantined': 'quarantined',
                  'expired': 'expired_unanswered'}
        item = {'task_id': association['task_id'], 'originating_turn_id': association['origin_id'],
                'tool': association['tool'], 'intent': 'original' if task is not None
                and self._chat_intent_locked(task) == digest else 'changed',
                'state': task.status if task is not None else 'lost',
                'outcome': states[task.status] if task is not None else 'lost'}
        if task is not None:
            deadline = normalize_approval_deadline(task.approval_deadline_at)
            expired_at = normalize_approval_deadline(task.expired_at)
            if deadline is not None:
                item['approval_deadline_at'] = deadline
            if expired_at is not None:
                item['expired_at'] = expired_at
            guardian = self._chat_guardian_denial_locked(task, association)
            if guardian is not None:
                item['guardian'] = guardian
        if task is not None and task.status != 'expired' and task.human_decision is not None:
            metadata = task.human_decision
            if (not isinstance(metadata.get('id'), str) or len(metadata['id']) != 32
                    or metadata.get('action') not in {'accept', 'edit', 'reject', 'defer', 'once'}
                    or not isinstance(metadata.get('by'), str) or not metadata['by']
                    or len(metadata['by']) > 256 or not isinstance(metadata.get('at'), str)
                    or len(metadata['at']) > 64):
                raise ValueError('invalid human decision metadata')
            if metadata['action'] == 'once':
                bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                           (task.id,)).fetchone()
                if (self._owner_once_approval_locked(raw, bound, allow_done=True) is None
                        and self._owner_once_withdrawn_approval_locked(raw, bound) is None):
                    raise ValueError('unbound owner-once decision metadata')
            reason = normalize_reason(metadata.get('reason'))
            item['decision'] = {'id': metadata['id'], 'action': metadata['action'],
                                'by': metadata['by'], **({'human_reason': reason} if reason else {})}
        else:
            metadata = None
        encoded = json.dumps([item, metadata], sort_keys=True, separators=(',', ':'), allow_nan=False)
        item['revision'] = hashlib.sha256(encoded.encode()).hexdigest()
        return item

    def _chat_rows_locked(self, context: ApprovalTurnContext, *, include_current: bool = False):
        params = (context.session_id, context.session_instance, context.principal_key)
        if include_current:
            return self._conn.execute('''SELECT t.* FROM chat_approval_tasks t
                JOIN chat_approval_origins o ON o.origin_id=t.origin_id
                WHERE o.session_id=? AND o.session_instance=? AND o.principal_key=?
                AND t.ready=1 ORDER BY t.task_id LIMIT 256''', params).fetchall()
        return self._conn.execute('''SELECT t.* FROM chat_approval_tasks t
            JOIN chat_approval_origins o ON o.origin_id=t.origin_id
            WHERE o.session_id=? AND o.session_instance=? AND o.principal_key=?
            AND t.origin_id!=? AND t.ready=1 ORDER BY t.task_id LIMIT 256''',
            (*params, context.turn_id)).fetchall()

    def chat_invocation_outcome(self, context, task_id: int) -> dict | None:
        """Read one ready association from this live turn without acknowledging it."""
        if not self._chat_context(context) or type(task_id) is not int or task_id <= 0:
            return None
        with self._lock:
            try:
                self._conn.execute('BEGIN')
                row = self._conn.execute('''SELECT t.* FROM chat_approval_tasks t
                    JOIN chat_approval_origins o ON o.origin_id=t.origin_id
                    WHERE t.task_id=? AND t.origin_id=? AND t.ready=1
                    AND o.session_id=? AND o.session_instance=? AND o.principal_key=?''',
                    (task_id, context.turn_id, context.session_id,
                     context.session_instance, context.principal_key)).fetchone()
                item = self._chat_observation_locked(row) if row is not None else None
                acknowledged = row['acknowledged_revision'] if row is not None else None
                self._conn.commit()
                if (item is None or item['revision'] == acknowledged
                        or not self._chat_context(context)):
                    return None
                included = render_chat_outcomes([item])[1]
                return included[0] if included and self._chat_context(context) else None
            except Exception:
                if self._conn is not None:
                    self._conn.rollback()
                logger.warning('chat invocation observation unavailable; no outcome inferred')
                return None

    def chat_outcome_snapshot(self, context, *, limit: int = 8, max_bytes: int = 4096) -> list[dict]:
        if not self._chat_context(context):
            return []
        self.prune_chat_outcomes()
        with self._lock:
            try:
                self._conn.execute('BEGIN')
                observations = []
                breakers = []
                for row in self._chat_rows_locked(context):
                    try:
                        item = self._chat_observation_locked(row)
                    except (TypeError, ValueError, KeyError):
                        logger.warning('chat approval binding unreadable; observation skipped')
                        continue
                    if item['revision'] != row['acknowledged_revision']:
                        observations.append(item)
                        if item.get('guardian', {}).get('breaker') is True:
                            breakers.append((row['denial_sequence'], row['task_id'], item))
                self._conn.commit()
                if not self._chat_context(context):
                    return []
                if breakers:
                    latest = max(breakers, key=lambda entry: (entry[0], entry[1]))[2]
                    observations = [latest, *(item for item in observations if item is not latest)]
                return render_chat_outcomes(observations[:max(0, min(8, limit))], max_bytes=max_bytes)[1]
            except Exception:
                if self._conn is not None:
                    self._conn.rollback()
                logger.warning('chat approval observation unavailable; no outcome inferred')
                return []

    def ack_chat_outcomes(self, context, observations: list[dict]) -> int:
        if not self._chat_context(context):
            return 0
        expected = {item.get('task_id'): item.get('revision') for item in observations[:8]
                    if isinstance(item, dict) and type(item.get('task_id')) is int
                    and isinstance(item.get('revision'), str)}
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                count = 0
                for row in self._chat_rows_locked(context, include_current=True):
                    try:
                        item = self._chat_observation_locked(row)
                    except (TypeError, ValueError, KeyError):
                        logger.warning('chat approval binding unreadable; acknowledgement skipped')
                        continue
                    if expected.get(row['task_id']) != item['revision']:
                        continue
                    self._conn.execute('''UPDATE chat_approval_tasks SET acknowledged_revision=?,acknowledged_at=?
                        WHERE task_id=?''', (item['revision'], _now(), row['task_id']))
                    count += 1
                if not self._chat_context(context):
                    self._conn.rollback()
                    return 0
                self._conn.commit()
                return count
            except Exception:
                if self._conn is not None:
                    self._conn.rollback()
                logger.warning('chat approval acknowledgement unavailable; revision retained')
                return 0

    def chat_outcomes_for_backup(self, session_id: str, *, session_instance: str | None = None) -> dict:
        with self._lock:
            clause = 'session_id=?' + (' AND session_instance=?' if session_instance is not None else '')
            params = (session_id, session_instance) if session_instance is not None else (session_id,)
            origins = self._conn.execute(f'SELECT * FROM chat_approval_origins WHERE {clause}', params).fetchall()  # nosec B608
            tasks = self._conn.execute(f'''SELECT t.* FROM chat_approval_tasks t
                JOIN chat_approval_origins o ON o.origin_id=t.origin_id WHERE {clause}''', params).fetchall()  # nosec B608
            if session_instance is None:
                tallies = self._conn.execute('''SELECT * FROM chat_guardian_denial_tallies
                    WHERE session_id=? ORDER BY last_sequence DESC LIMIT ?''',
                    (session_id, _GUARDIAN_CONSUMER_LIMIT)).fetchall()
            else:
                tallies = self._conn.execute('''SELECT * FROM chat_guardian_denial_tallies
                    WHERE session_id=? AND session_instance=?
                    ORDER BY last_sequence DESC LIMIT ?''',
                    (session_id, session_instance, _GUARDIAN_CONSUMER_LIMIT)).fetchall()
            backup = {'origins': [dict(row) for row in origins], 'tasks': [dict(row) for row in tasks]}
            if tallies:
                backup['guardian_denials'] = [dict(row) for row in tallies]
            return backup

    def purge_chat_outcomes(self, session_id: str, session_instance: str | None = None) -> int:
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                clause = 'session_id=?' + (' AND session_instance=?' if session_instance is not None else '')
                params = (session_id, session_instance) if session_instance is not None else (session_id,)
                if session_instance is None:
                    self._conn.execute('DELETE FROM task_owner_once WHERE session_id=?',
                                       (session_id,))
                else:
                    self._conn.execute('''DELETE FROM task_owner_once
                        WHERE session_id=? AND session_instance=?''',
                        (session_id, session_instance))
                self._conn.execute('''DELETE FROM task_consent_sources WHERE task_id IN (
                    SELECT t.task_id FROM chat_approval_tasks t
                    JOIN chat_approval_origins o ON o.origin_id=t.origin_id
                    WHERE o.session_id=? AND (? IS NULL OR o.session_instance=?))''',
                    (session_id, session_instance, session_instance))
                count = self._conn.execute(f'''DELETE FROM chat_approval_tasks WHERE origin_id IN
                    (SELECT origin_id FROM chat_approval_origins WHERE {clause})''', params).rowcount  # nosec B608
                self._conn.execute(f'DELETE FROM chat_approval_origins WHERE {clause}', params)  # nosec B608
                if session_instance is None:
                    self._conn.execute('''DELETE FROM chat_guardian_denial_tallies
                        WHERE session_id=?''', (session_id,))
                else:
                    self._conn.execute('''DELETE FROM chat_guardian_denial_tallies
                        WHERE session_id=? AND session_instance=?''',
                        (session_id, session_instance))
                self._prune_owner_once_claims_locked()
                self._conn.commit()
                return count
            except Exception:
                self._conn.rollback()
                raise

    def prune_chat_outcomes(self, *, limit: int = 128) -> int:
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=TERMINAL_RETENTION_DAYS)).isoformat()
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                batch = max(0, min(128, limit))
                self._conn.execute('INSERT OR IGNORE INTO chat_approval_retention VALUES(1,0)')
                cursor = self._conn.execute('SELECT last_task_id FROM chat_approval_retention WHERE id=1').fetchone()[0]
                rows = self._conn.execute('''SELECT * FROM chat_approval_tasks
                    WHERE acknowledged_at < ? AND task_id>? ORDER BY task_id LIMIT ?''',
                    (cutoff, cursor, batch)).fetchall()
                count = 0
                for row in rows:
                    try:
                        item = self._chat_observation_locked(row)
                    except (TypeError, ValueError, KeyError):
                        logger.warning('chat approval binding unreadable; retention skipped')
                        continue
                    if item['state'] not in {'done', 'failed', 'rejected', 'quarantined', 'expired', 'lost'}:
                        continue
                    if item['revision'] == row['acknowledged_revision']:
                        self._conn.execute('DELETE FROM task_consent_sources WHERE task_id=?', (row['task_id'],))
                        self._conn.execute('DELETE FROM chat_approval_tasks WHERE task_id=?', (row['task_id'],))
                        count += 1
                next_cursor = rows[-1]['task_id'] if rows and len(rows) == batch else 0
                self._conn.execute('UPDATE chat_approval_retention SET last_task_id=? WHERE id=1', (next_cursor,))
                self._conn.execute('''DELETE FROM chat_approval_origins WHERE NOT EXISTS
                    (SELECT 1 FROM chat_approval_tasks t WHERE t.origin_id=chat_approval_origins.origin_id)''')
                self._conn.execute('''DELETE FROM task_owner_once WHERE task_id IN (
                    SELECT p.task_id FROM task_owner_once p
                    WHERE NOT EXISTS (SELECT 1 FROM chat_approval_tasks c
                                      WHERE c.task_id=p.task_id AND c.origin_id=p.origin_id)
                    ORDER BY p.task_id LIMIT ?)''', (batch,))
                self._conn.execute('''DELETE FROM task_consent_sources WHERE task_id IN (
                    SELECT s.task_id FROM task_consent_sources s WHERE NOT EXISTS (
                        SELECT 1 FROM chat_approval_tasks c WHERE c.task_id=s.task_id)
                    ORDER BY s.task_id LIMIT ?)''', (batch,))
                self._conn.execute('''DELETE FROM chat_guardian_denial_tallies
                    WHERE updated_at < ? OR NOT EXISTS (
                        SELECT 1 FROM chat_approval_origins o
                        WHERE o.session_id=chat_guardian_denial_tallies.session_id
                          AND o.session_instance=chat_guardian_denial_tallies.session_instance
                          AND o.principal_key=chat_guardian_denial_tallies.principal_key)''',
                    (cutoff,))
                self._prune_owner_once_claims_locked()
                self._conn.commit()
                return count
            except Exception:
                if self._conn is not None:
                    self._conn.rollback()
                logger.warning('chat approval retention unavailable; metadata retained')
                return 0

    # ── reads ─────────────────────────────────────────────────────
    def _capture_consent_source(self, task_id: int, *, policy: dict) -> bool:
        from .consent_sources import capture_locked
        with self._lock:
            return capture_locked(self, task_id, policy=policy)

    def _consent_source(self, task_id: int) -> dict | None:
        from .consent_sources import read_locked
        with self._lock:
            return read_locked(self, task_id)

    def bind_consent_resolver(self, resolve: Callable[[Task, dict], ConsentDescriptor | None]) -> None:
        """Bind the server's current producer/policy/target classifier."""
        if not callable(resolve):
            raise ValueError('consent resolver must be callable')
        with self._lock:
            self._consent_resolver = resolve

    def _resolve_consent_descriptor(self, task: Task, source: dict) -> ConsentDescriptor | None:
        try:
            if self._consent_ledger is None or not callable(self._consent_resolver):
                return None
            descriptor = self._consent_resolver(task, source)
            producer = source['producer']
            if (type(descriptor) is not ConsentDescriptor
                    or not _valid_context(descriptor.context)
                    or type(descriptor.categories) is not tuple
                    or self._consent_ledger._requested(descriptor.categories) != descriptor.categories
                    or type(descriptor.registration_epoch) is not str
                    or descriptor.registration_epoch != producer['registration_epoch']
                    or descriptor.context.registration_key != producer['registration_key']
                    or descriptor.context.principal != producer['principal']
                    or descriptor.context.session_id != producer['session_id']
                    or descriptor.context.session_instance != producer['session_instance']):
                return None
            return descriptor
        except Exception:
            return None

    @staticmethod
    def _consent_descriptor_data(descriptor: ConsentDescriptor) -> dict:
        return {'context': asdict(descriptor.context),
                'categories': [asdict(item) for item in descriptor.categories],
                'registration_epoch': descriptor.registration_epoch}

    @staticmethod
    def _consent_marker_row(row: sqlite3.Row) -> bool:
        return (type(row['decision']) is str
                and (row['decision'].startswith('auto-consent-')
                     or row['decision'].startswith('consent-')))

    def _consent_marked_locked(self, row: sqlite3.Row) -> bool:
        return (self._consent_marker_row(row) or self._conn.execute(
            'SELECT 1 FROM task_consent_proofs WHERE task_id=?', (row['id'],)
        ).fetchone() is not None)

    def _consent_intake_locked(self, row: sqlite3.Row) -> bool:
        """Verify this task's own QA4 evidence without broadening grouping."""
        if bool(row['kernel_intake_id']) != bool(row['kernel_intake_evidence']):
            return False
        if not row['kernel_intake_id']:
            return self.mediation_mode == 'enforce'
        try:
            evidence = json.loads(row['kernel_intake_evidence'])
            return (type(evidence) is dict
                    and evidence.get('intake_id') == row['kernel_intake_id']
                    and verify_intake_evidence(
                        self._mediation_signer, evidence,
                        agent=row['agent'], kind=row['kind'], title=row['title'],
                        origin=row['origin'], payload=json.loads(row['payload']),
                        tier=None, task_tier=int(row['risk_tier']),
                        now_ms=self._clock_ms(), task_id=int(row['id']),
                    ))
        except Exception:
            return False

    def consent_task_marker(self, task_id: int) -> bool:
        if type(task_id) is not int or task_id <= 0:
            return False
        with self._lock:
            try:
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                return row is not None and self._consent_marked_locked(row)
            except Exception:
                return True  # An unreadable marker cannot permit ordinary fallback.

    def _consent_offer_locked(self, task_id: int):
        from .consent_sources import current_locked, group_key
        if self._consent_ledger is None or type(task_id) is not int or task_id <= 0:
            return None
        if self._consent_ledger._verified_head_locked() is None:
            return None
        leader = self._conn.execute('''SELECT tasks.*, s.group_key AS consent_group_key
            FROM tasks JOIN task_consent_sources s ON s.task_id=tasks.id
            WHERE tasks.id=?''', (task_id,)).fetchone()
        if leader is None:
            return None
        leader_source = current_locked(self, task_id, pending_only=True)
        fingerprint = group_key(self, _row_to_task(leader), leader_source)
        if fingerprint is None:
            return None
        if leader['consent_group_key'] is None:
            # Pending v2 source captured before the private index existed may
            # retain its singleton offer; it never borrows another task's key.
            rows = [leader]
        elif leader['consent_group_key'] == fingerprint:
            rows = self._conn.execute('''SELECT tasks.* FROM tasks
                JOIN task_consent_sources s ON s.task_id=tasks.id
                WHERE s.group_key=? AND tasks.status='blocked'
                ORDER BY tasks.id LIMIT 65''', (fingerprint,)).fetchall()
        else:
            return None
        if not rows or len(rows) > 64 or task_id not in {row['id'] for row in rows}:
            return None
        first = None
        members = []
        group_bindings = []
        for row in rows:
            task = _row_to_task(row)
            source = current_locked(self, task.id, pending_only=True)
            if (source is None or source['version'] != 2 or row['status'] != 'blocked'
                    or self._consent_marked_locked(row)
                    or not self._consent_intake_locked(row)
                    or (self.mediation_mode == 'off' and self._row_has_mediation_provenance(row))
                    or (self.mediation_mode == 'enforce' and self._consent_b7_locked(row) is None)):
                return None
            descriptor = self._resolve_consent_descriptor(task, source)
            if descriptor is None or (first is not None and descriptor != first):
                return None
            if group_key(self, task, source) != fingerprint:
                return None
            first = descriptor
            members.append((row, source, descriptor))
            membership = self._conn.execute('''SELECT group_id,snapshot
                FROM task_approval_groups WHERE task_id=?''', (task.id,)).fetchone()
            group_bindings.append([task.id, membership['group_id'], membership['snapshot']]
                                  if membership else [task.id, None, None])
        group_ids = tuple(dict.fromkeys(binding[1] for binding in group_bindings
                                       if binding[1] is not None))
        revision = canonical_digest({
            'purpose': 'h487-consent-offer', 'group_key': fingerprint,
            'group_bindings': group_bindings,
            'members': [[row['id'], source['snapshot'],
                         self._chat_intent_locked(_row_to_task(row))]
                        for row, source, _ in members],
            'descriptor': self._consent_descriptor_data(first),
        })
        return ConsentOffer(task_id, revision, tuple(row['id'] for row in rows),
                            first.categories), members, group_ids

    def pending_consent_offer(self, task_id: int) -> ConsentOffer | None:
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                result = self._consent_offer_locked(task_id)
                self._conn.rollback()
                return result[0] if result else None
            except Exception:
                self._conn.rollback()
                return None

    def _consent_proof_insert_locked(self, row: sqlite3.Row, source: dict,
                                     descriptor: ConsentDescriptor, witness: dict,
                                     *, marker: str, decision_id: str,
                                     human_id: str | None,
                                     decider_principal: str | None = None) -> bool:
        task = _row_to_task(row)
        proof = {
            'purpose': 'h487-consent-task-proof',
            'version': 2 if decider_principal is not None else 1,
            'namespace': self._group_namespace, 'task_id': task.id,
            'birth': task.created_at, 'source_sha256': canonical_digest(source),
            'intent_sha256': self._chat_intent_locked(task),
            'descriptor': self._consent_descriptor_data(descriptor), 'witness': witness,
            'marker': marker, 'decision_id': decision_id, 'human_id': human_id,
        }
        if decider_principal is not None:
            proof['decider_principal'] = decider_principal
        payload = canonical_json(proof)
        signature = self._mediation_signer.sign(payload)
        if signature is None:
            return False
        self._conn.execute(
            'INSERT INTO task_consent_proofs(task_id,payload,signature,state) VALUES(?,?,?,?)',
            (task.id, payload, signature, 'approved'),
        )
        return True

    def _consent_actor_current(self, actor: OwnerConsentActor,
                               descriptor: ConsentDescriptor) -> bool:
        try:
            if (type(actor) is not OwnerConsentActor or actor.label not in {'admin', 'owner'}
                    or actor.decided_by not in {'admin', 'telegram'}
                    or (actor.label, actor.decided_by) not in {
                        ('admin', 'admin'), ('owner', 'telegram')}):
                return False
            if actor.decided_by == 'admin':
                return (actor.authority is None and actor.principal_key is None
                        and actor.live() is True)
            from .consent_authority import telegram_actor_current, valid_telegram_principal
            if actor.authority is not None:
                return telegram_actor_current(actor)
            # Existing same-origin server integrations remain valid, but a
            # forged web principal cannot impersonate a Telegram callback.
            return (valid_telegram_principal(actor.principal_key)
                    and actor.principal_key == descriptor.context.principal
                    and actor.live() is True)
        except Exception:
            return False

    def decide_reusable_consent(self, task_id: int, revision: str, *, choice: str,
                                actor: OwnerConsentActor, reason: str | None = None
                                ) -> ConsentDecisionResult | None:
        if (choice not in {'session', 'always', 'deny'} or type(revision) is not str
                or not revision or type(task_id) is not int):
            return None
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                offered = self._consent_offer_locked(task_id)
                if offered is None or offered[0].revision != revision:
                    self._conn.rollback()
                    return None
                _offer, members, group_ids = offered
                descriptor = members[0][2]
                if not self._consent_actor_current(actor, descriptor):
                    self._conn.rollback()
                    return None
                decider_principal = (actor.principal_key if actor.authority is not None
                                     else None)
                normalized = normalize_reason(reason)
                now = _now()
                decision_id = uuid.uuid4().hex
                if choice != 'deny':
                    if not self._consent_ledger.grant(
                        descriptor.context, descriptor.categories, choice=choice,
                        decision_id=decision_id, decided_by=actor.label,
                        decider_principal=decider_principal,
                    ):
                        self._conn.rollback()
                        return None
                    witness = self._consent_ledger.current_witness(
                        descriptor.context, descriptor.categories, decision_id=decision_id,
                    )
                    if witness is None:
                        self._conn.rollback()
                        return None
                else:
                    witness = None
                for row, source, desc in members:
                    if not self._consent_actor_current(actor, desc):
                        self._conn.rollback()
                        return None
                    human = {'id': uuid.uuid4().hex, 'action': choice,
                             'reason': normalized, 'by': actor.decided_by,
                             'at': now, 'first_at': now}
                    if decider_principal is not None:
                        human['principal_key'] = decider_principal
                    marker = f'consent-{choice}'
                    if choice != 'deny' and not self._consent_proof_insert_locked(
                        row, source, desc, witness, marker=marker,
                        decision_id=decision_id, human_id=human['id'],
                        decider_principal=decider_principal,
                    ):
                        self._conn.rollback()
                        return None
                    changed = self._conn.execute(
                        '''UPDATE tasks SET status=?,decided_by=?,decision=?,human_decision=?,updated_at=?
                           WHERE id=? AND status='blocked' AND decided_by='policy'
                           AND decision='needs-approval' ''',
                        ('rejected' if choice == 'deny' else 'approved', actor.decided_by,
                         marker, json.dumps(human, ensure_ascii=False), now, row['id']),
                    )
                    if changed.rowcount != 1:
                        self._conn.rollback()
                        return None
                    self._withdraw_task_group_locked(row['id'])
                tasks = tuple(_row_to_task(self._conn.execute(
                    'SELECT * FROM tasks WHERE id=?', (row['id'],)
                ).fetchone()) for row, _, _ in members)
                self._conn.commit()
                return ConsentDecisionResult(tasks, group_ids)
            except Exception:
                self._conn.rollback()
                return None

    def approve_with_current_consent(self, task_id: int) -> bool:
        from .consent_sources import current_locked
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                source = current_locked(self, task_id, pending_only=True)
                if (row is None or source is None or source['version'] != 2
                        or self._consent_marked_locked(row)
                        or not self._consent_intake_locked(row)
                        or (self.mediation_mode == 'off' and self._row_has_mediation_provenance(row))
                        or (self.mediation_mode == 'enforce' and self._consent_b7_locked(row) is None)):
                    self._conn.rollback()
                    return False
                descriptor = self._resolve_consent_descriptor(_row_to_task(row), source)
                witness = (self._consent_ledger.current_witness(
                    descriptor.context, descriptor.categories,
                ) if descriptor is not None else None)
                if witness is None:
                    self._conn.rollback()
                    return False
                marker = ('auto-consent-always' if all(item['scope'] == 'always'
                          for item in witness.values()) else 'auto-consent-session')
                decision_id = canonical_digest(witness)
                if not self._consent_proof_insert_locked(
                    row, source, descriptor, witness, marker=marker,
                    decision_id=decision_id, human_id=None,
                ):
                    self._conn.rollback()
                    return False
                updated = self._conn.execute(
                    '''UPDATE tasks SET status='approved',decided_by='consent',decision=?,
                       human_decision=NULL,updated_at=? WHERE id=? AND status='blocked'
                       AND decided_by='policy' AND decision='needs-approval' ''',
                    (marker, _now(), task_id),
                )
                if updated.rowcount != 1:
                    self._conn.rollback()
                    return False
                group_id = self._withdraw_task_group_locked(task_id)
                self._record_promotion_effect_locked(group_id, task_id)
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                return False

    def _consent_proof_locked(self, row: sqlite3.Row) -> tuple[sqlite3.Row, dict] | None:
        from .consent_sources import current_locked
        if self._consent_ledger is None or not self._consent_marked_locked(row):
            return None
        bound = self._conn.execute(
            'SELECT * FROM task_consent_proofs WHERE task_id=?', (row['id'],)
        ).fetchone()
        if bound is None or not isinstance(bound['payload'], bytes):
            return None
        payload = bound['payload']
        if not self._mediation_signer.verify(payload, bound['signature']):
            return None
        proof = json.loads(payload)
        fields = {'purpose', 'version', 'namespace', 'task_id', 'birth',
                  'source_sha256', 'intent_sha256', 'descriptor',
                  'witness', 'marker', 'decision_id', 'human_id'}
        if (type(proof) is not dict or canonical_json(proof) != payload
                or type(proof.get('version')) is not int
                or proof['version'] not in {1, 2}
                or set(proof) != (fields | ({'decider_principal'} if proof['version'] == 2 else set()))
                or proof['purpose'] != 'h487-consent-task-proof'
                or proof['namespace'] != self._group_namespace
                or proof['task_id'] != row['id'] or proof['birth'] != row['created_at']
                or proof['marker'] != row['decision']
                or proof['intent_sha256'] != self._chat_intent_locked(_row_to_task(row))):
            return None
        if proof['marker'].startswith('auto-consent-'):
            if (proof['version'] != 1 or row['decided_by'] != 'consent'
                    or row['human_decision'] is not None or proof['human_id'] is not None):
                return None
        elif proof['marker'] in {'consent-session', 'consent-always'}:
            human = json.loads(row['human_decision']) if row['human_decision'] else None
            if (row['decided_by'] not in {'admin', 'telegram'} or type(human) is not dict
                    or human.get('id') != proof['human_id']
                    or human.get('action') != proof['marker'].removeprefix('consent-')
                    or human.get('by') != row['decided_by']):
                return None
            if proof['version'] == 2:
                from .consent_authority import valid_telegram_principal
                if (row['decided_by'] != 'telegram'
                        or not valid_telegram_principal(proof['decider_principal'])
                        or human.get('principal_key') != proof['decider_principal']):
                    return None
            elif 'principal_key' in human:
                return None
        else:
            return None
        source = current_locked(self, row['id'], pending_only=False)
        if (source is None or source['version'] != 2
                or canonical_digest(source) != proof['source_sha256']
                or not self._consent_intake_locked(row)):
            return None
        descriptor = self._resolve_consent_descriptor(_row_to_task(row), source)
        if descriptor is None or self._consent_descriptor_data(descriptor) != proof['descriptor']:
            return None
        if not self._consent_ledger.witness_current(
            descriptor.context, descriptor.categories, proof['witness'],
        ):
            return None
        if (proof['version'] == 2 and not self._consent_ledger.attributed_decision_current(
                descriptor.context, descriptor.categories,
                decision_id=proof['decision_id'],
                decider_principal=proof['decider_principal'],
                choice=proof['marker'].removeprefix('consent-'))):
            return None
        return bound, proof

    def _consent_b7_locked(self, row: sqlite3.Row, *, execution_id: str | None = None):
        if self.mediation_mode == 'off':
            return (None, None, None) if not self._row_has_mediation_provenance(row) else None
        if self.mediation_mode != 'enforce' or self._classification(row['kind']) is not True:
            return None
        snapshot = self._validated_mediation_snapshot_locked()
        if snapshot is None:
            return None
        receipt, expectation, digest = self._row_receipt_and_expectation(row)
        receipt_digest = canonical_digest(receipt.to_dict())
        authorized = self._conn.execute('''SELECT COUNT(*) FROM task_mediation_events
            WHERE task_id=? AND enqueue_id=? AND outcome='authorized_enqueue'
            AND receipt_id=? AND receipt_sha256=?''',
            (row['id'], expectation.enqueue_id, receipt.receipt_id, receipt_digest)).fetchone()[0]
        if (authorized != 1 or digest != row['mediation_task_sha256']
                or int(row['risk_tier']) != receipt.effective_tier
                or not self._scope_allowed(expectation.scope)
                or expectation.policy_revision != self._mediation_policy_revision
                or not self._event_chain_valid_locked()
                or not verify_receipt(self._mediation_signer, receipt, expected=expectation,
                                      now_ms=self._clock_ms())):
            return None
        if execution_id is None:
            if row['mediation_execution_id'] is not None:
                return None
        else:
            governed = self._conn.execute('''SELECT COUNT(*) FROM task_mediation_events
                WHERE task_id=? AND enqueue_id=? AND outcome='governed' AND execution_id=?
                AND receipt_id=? AND receipt_sha256=?''',
                (row['id'], expectation.enqueue_id, execution_id,
                 receipt.receipt_id, receipt_digest)).fetchone()[0]
            if row['mediation_execution_id'] != execution_id or governed != 1:
                return None
        return snapshot[0], receipt, expectation

    def claim_consent(self, task_id: int, *, execution_id: str,
                      live_check: Callable[[], bool]) -> ConsentClaim | None:
        if (type(task_id) is not int or task_id <= 0 or type(execution_id) is not str
                or not execution_id or len(execution_id) > 128 or not callable(live_check)):
            return None
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                if (row is None or row['status'] != 'approved'
                        or live_check() is not True
                        or self._consent_proof_locked(row) is None):
                    self._conn.rollback()
                    return None
                b7 = self._consent_b7_locked(row)
                if b7 is None:
                    self._conn.rollback()
                    return None
                nonce = uuid.uuid4().hex
                claim_body = canonical_json({
                    'purpose': 'h487-consent-claim', 'version': 1,
                    'task_id': task_id, 'execution_id': execution_id,
                    'nonce': nonce,
                    'proof_sha256': hashlib.sha256(self._conn.execute(
                        'SELECT payload FROM task_consent_proofs WHERE task_id=?',
                        (task_id,),
                    ).fetchone()[0]).hexdigest(),
                })
                claim_signature = self._mediation_signer.sign(claim_body)
                if claim_signature is None:
                    self._conn.rollback()
                    return None
                changed = self._conn.execute('''UPDATE tasks SET status='running',
                    mediation_execution_id=?,updated_at=? WHERE id=? AND status='approved'
                    AND mediation_execution_id IS NULL''',
                    (execution_id if self.mediation_mode == 'enforce' else None,
                     _now(), task_id))
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return None
                changed = self._conn.execute('''UPDATE task_consent_proofs
                    SET claim_payload=?,claim_signature=?,state='claimed'
                    WHERE task_id=? AND state='approved' ''',
                    (claim_body, claim_signature, task_id))
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return None
                if self.mediation_mode == 'enforce':
                    self._append_mediation_event_locked(
                        outcome='governed', task_id=task_id,
                        enqueue_id=b7[2].enqueue_id, receipt=b7[1],
                        execution_id=execution_id, verified_state=b7[0],
                    )
                self._conn.commit()
                claim = ConsentClaim(task_id, nonce, execution_id, self._consent_queue_key)
                self._consent_claims[task_id] = claim
                return claim
            except Exception:
                self._conn.rollback()
                return None

    def _consent_claim_current_locked(self, task_id: int, claim: ConsentClaim,
                                      live_check: Callable[[], bool]) -> bool:
        if (type(claim) is not ConsentClaim or claim.task_id != task_id
                or claim._queue_key is not self._consent_queue_key
                or self._consent_claims.get(task_id) is not claim
                or not callable(live_check) or live_check() is not True):
            return False
        row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if row is None or row['status'] != 'running':
            return False
        found = self._consent_proof_locked(row)
        if found is None:
            return False
        bound, _proof = found
        claim_payload = bound['claim_payload']
        if (bound['state'] not in {'claimed', 'dispatching'}
                or not isinstance(claim_payload, bytes)
                or not self._mediation_signer.verify(claim_payload, bound['claim_signature'])):
            return False
        data = json.loads(claim_payload)
        if (type(data) is not dict or canonical_json(data) != claim_payload
                or data != {'purpose': 'h487-consent-claim', 'version': 1,
                            'task_id': task_id, 'execution_id': claim.execution_id,
                            'nonce': claim.nonce,
                            'proof_sha256': hashlib.sha256(bound['payload']).hexdigest()}):
            return False
        return self._consent_b7_locked(row, execution_id=claim.execution_id) is not None

    def verify_consent_execution(self, task_id: int, claim: ConsentClaim, *,
                                 live_check: Callable[[], bool]) -> bool:
        with self._lock:
            try:
                self._conn.execute('BEGIN')
                valid = self._consent_claim_current_locked(task_id, claim, live_check)
                self._conn.rollback()
                return valid
            except Exception:
                self._conn.rollback()
                return False

    def consent_dispatch_current(self, task_id: int, claim: ConsentClaim, *,
                                 live_check: Callable[[], bool]) -> bool:
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                if not self._consent_claim_current_locked(task_id, claim, live_check):
                    self._conn.rollback()
                    return False
                changed = self._conn.execute('''UPDATE task_consent_proofs
                    SET state='dispatching' WHERE task_id=? AND state='claimed' ''',
                    (task_id,))
                self._conn.commit()
                return changed.rowcount == 1
            except Exception:
                self._conn.rollback()
                return False

    def consent_execution_dispatched(self, task_id: int, claim: ConsentClaim, *,
                                     live_check: Callable[[], bool]) -> bool:
        """Read-only proof that this exact live claim spent its dispatch slot."""
        with self._lock:
            try:
                self._conn.execute('BEGIN')
                valid = self._consent_claim_current_locked(task_id, claim, live_check)
                bound = self._conn.execute(
                    'SELECT state FROM task_consent_proofs WHERE task_id=?', (task_id,)
                ).fetchone() if valid else None
                self._conn.rollback()
                return bound is not None and bound['state'] == 'dispatching'
            except Exception:
                self._conn.rollback()
                return False

    def verify_consent_terminal_result(self, task_id: int) -> bool:
        """Read the completed durable proof after the worker releases its claim.

        This attests to the queue's one-use dispatch and DONE transition; the
        caller separately checks the positive physical result it expected.
        """
        if type(task_id) is not int or task_id <= 0:
            return False
        with self._lock:
            if self._conn.in_transaction:
                return False
            started = False
            try:
                self._conn.execute('BEGIN')
                started = True
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                if (row is None or row['status'] != 'done' or row['attempts'] != 1
                        or row['kind'] != 'toolrpc.terminal_run'):
                    return False
                found = self._consent_proof_locked(row)
                if found is None:
                    return False
                bound, _proof = found
                claim_payload = bound['claim_payload']
                if (bound['state'] != 'dispatching'
                        or not isinstance(claim_payload, bytes)
                        or not self._mediation_signer.verify(
                            claim_payload, bound['claim_signature'])):
                    return False
                claim = json.loads(claim_payload)
                if (type(claim) is not dict or canonical_json(claim) != claim_payload
                        or set(claim) != {'purpose', 'version', 'task_id',
                                          'execution_id', 'nonce', 'proof_sha256'}
                        or claim['purpose'] != 'h487-consent-claim'
                        or type(claim['version']) is not int or claim['version'] != 1
                        or claim['task_id'] != task_id
                        or type(claim['execution_id']) is not str
                        or not 1 <= len(claim['execution_id']) <= 128
                        or type(claim['nonce']) is not str
                        or uuid.UUID(hex=claim['nonce']).hex != claim['nonce']
                        or uuid.UUID(hex=claim['nonce']).version != 4
                        or claim['proof_sha256'] != hashlib.sha256(bound['payload']).hexdigest()):
                    return False
                if self._consent_b7_locked(
                    row, execution_id=(claim['execution_id']
                                       if self.mediation_mode == 'enforce' else None),
                ) is None:
                    return False
                result = json.loads(row['result']) if row['result'] else None
                return (type(result) is dict and result.get('status') not in
                        {'refused', 'failed', 'noop'})
            except Exception:
                return False
            finally:
                if started:
                    self._conn.rollback()

    def approval_snapshot_digest(self, task: Task) -> str | None:
        """Bind an opinion to action bytes and a separate advisory edit revision."""
        with self._lock:
            return self._approval_snapshot_digest_locked(task)

    def _approval_snapshot_digest_locked(self, task: Task) -> str | None:
        # Push bookkeeping changes updated_at, but must not invalidate an opinion.
        # A separate counter revokes even an edit that preserves the same payload.
        revision = self._conn.execute(
            "SELECT revision FROM approval_judgement_revisions WHERE task_id=?", (task.id,),
        ).fetchone()
        execution = TaskQueue.execution_fingerprint(task)
        if execution is None:
            return None
        try:
            encoded = json.dumps({
                "execution": execution,
                "kernel_intake_id": task.kernel_intake_id,
                "kernel_intake_evidence": task.kernel_intake_evidence,
                "advisory_revision": revision["revision"] if revision else 0,
            }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return hashlib.sha256(encoded).hexdigest()
        except (TypeError, ValueError):
            return None

    def approval_judgement(self, task_id: int, snapshot_sha256: str) -> dict | None:
        """Read only a still-current BLOCKED row's opinion, never a stale one."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if (row is None or row["status"] != TaskStatus.BLOCKED.value
                    or not approval_is_pending(_row_to_task(row))
                    or self._approval_snapshot_digest_locked(_row_to_task(row)) != snapshot_sha256):
                return None
            # A smart denial/escalation remains a blocked owner decision. Surface
            # that exact snapshot's non-advisory annotation before older risk
            # advice, so restart scans do not re-dispatch the same operation.
            opinion = self._conn.execute(
                "SELECT annotation FROM task_smart_approvals WHERE task_id=? AND snapshot_sha256=?",
                (task_id, snapshot_sha256),
            ).fetchone()
            if opinion is None:
                opinion = self._conn.execute(
                    "SELECT annotation FROM approval_judgements WHERE task_id=? AND snapshot_sha256=?",
                    (task_id, snapshot_sha256),
                ).fetchone()
        return json.loads(opinion["annotation"]) if opinion else None

    def store_approval_judgement(self, task_id: int, snapshot_sha256: str,
                                annotation: dict) -> dict | None:
        """Atomically compare persisted action/status and store its first opinion.

        BEGIN IMMEDIATE protects the comparison even against another queue connection.
        This method never updates the tasks table, receipts or mediation event chain.
        """
        encoded = json.dumps(annotation, ensure_ascii=False, allow_nan=False)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if (row is None or row["status"] != TaskStatus.BLOCKED.value
                    or not approval_is_pending(_row_to_task(row))
                        or self._approval_snapshot_digest_locked(_row_to_task(row)) != snapshot_sha256):
                    self._conn.rollback()
                    return None
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO approval_judgements (task_id, snapshot_sha256, annotation) "
                    "VALUES (?, ?, ?)", (task_id, snapshot_sha256, encoded),
                )
                self._conn.commit()
                return json.loads(encoded) if cursor.rowcount == 1 else None
            except Exception:
                self._conn.rollback()
                raise

    def _smart_terminal_mediation_valid_locked(self, row: sqlite3.Row, *,
                                                allow_done: bool = False) -> bool:
        """Keep a smart verdict behind any existing task mediation boundary."""
        if bool(row["kernel_intake_id"]) != bool(row["kernel_intake_evidence"]):
            return False
        if row["kernel_intake_id"]:
            try:
                evidence = json.loads(row["kernel_intake_evidence"])
                if (
                    not isinstance(evidence, dict)
                    or evidence.get("intake_id") != row["kernel_intake_id"]
                    or not verify_intake_evidence(
                        self._mediation_signer, evidence,
                        agent=row["agent"], kind=row["kind"], title=row["title"],
                        origin=row["origin"], payload=json.loads(row["payload"]),
                        tier=None, task_tier=int(row["risk_tier"]),
                        now_ms=self._clock_ms(), task_id=int(row["id"]),
                    )
                ):
                    return False
            except Exception:
                return False
        if self.mediation_mode == "off":
            return not self._row_has_mediation_provenance(row)
        if self.mediation_mode != "enforce" or self._classification(row["kind"]) is not True:
            return False
        if self._validated_mediation_snapshot_locked() is None:
            return False
        try:
            receipt, expected, task_sha256 = self._row_receipt_and_expectation(row)
            authorized = self._conn.execute(
                """SELECT COUNT(*) AS count FROM task_mediation_events
                   WHERE task_id=? AND enqueue_id=? AND outcome='authorized_enqueue'
                     AND receipt_id=? AND receipt_sha256=?""",
                (row["id"], expected.enqueue_id, receipt.receipt_id,
                 canonical_digest(receipt.to_dict())),
            ).fetchone()
            if row["status"] == TaskStatus.RUNNING.value or (
                allow_done and row["status"] == TaskStatus.DONE.value
            ):
                execution_id = row["mediation_execution_id"]
                governed = self._conn.execute(
                    """SELECT COUNT(*) AS count FROM task_mediation_events
                       WHERE task_id=? AND enqueue_id=? AND outcome='governed'
                         AND execution_id=? AND receipt_id=? AND receipt_sha256=?""",
                    (row["id"], expected.enqueue_id, execution_id,
                     receipt.receipt_id, canonical_digest(receipt.to_dict())),
                ).fetchone()
                if not execution_id or int(governed["count"]) != 1:
                    return False
            elif row["mediation_execution_id"] is not None:
                return False
            return (
                int(authorized["count"]) == 1
                and int(row["risk_tier"]) == receipt.effective_tier
                and self._scope_allowed(expected.scope)
                and expected.policy_revision == self._mediation_policy_revision
                and task_sha256 == row["mediation_task_sha256"]
                and verify_receipt(
                    self._mediation_signer, receipt, expected=expected, now_ms=self._clock_ms(),
                )
            )
        except Exception:
            return False

    @staticmethod
    def _unsigned_smart_hold_verdict(prior: sqlite3.Row) -> str | None:
        """Validate one canonical unsigned machine hold before any projection."""
        try:
            previous = prior["snapshot_sha256"]
            if (
                type(previous) is not str or _SHA256_HEX.fullmatch(previous) is None
                or prior["receipt"] is not None or prior["signature"] is not None
                or type(prior["annotation"]) is not str
            ):
                return None
            annotation = json.loads(prior["annotation"])
            valid = (
                type(annotation) is dict
                and set(annotation) == {
                    "decision", "advisory", "judge", "policy_revision", "judge_revision", "at",
                }
                and annotation["decision"] in {"deny", "escalate"}
                and annotation["advisory"] is False
                and type(annotation["judge"]) is dict
                and type(annotation["policy_revision"]) is str
                and _SHA256_HEX.fullmatch(annotation["policy_revision"]) is not None
                and type(annotation["judge_revision"]) is str
                and _SHA256_HEX.fullmatch(annotation["judge_revision"]) is not None
                and type(annotation["at"]) in {int, float}
                and math.isfinite(annotation["at"])
                and canonical_json(annotation).decode("utf-8") == prior["annotation"]
            )
            return annotation["decision"] if valid else None
        except Exception:
            return None

    @staticmethod
    def _supersedable_smart_hold(prior: sqlite3.Row, next_snapshot: str) -> bool:
        """Only an intact unsigned hold may yield to a new exact task revision."""
        return (prior["snapshot_sha256"] != next_snapshot
                and TaskQueue._unsigned_smart_hold_verdict(prior) in {"deny", "escalate"})

    def _current_smart_denial_locked(self, task: Task) -> bool:
        if (task.status != TaskStatus.BLOCKED.value or not approval_is_pending(task)
                or task.decided_by != 'policy' or task.decision != 'needs-approval'
                or task.human_decision is not None or _smart_terminal_args(task) is None):
            return False
        prior = self._conn.execute(
            'SELECT * FROM task_smart_approvals WHERE task_id=?', (task.id,),
        ).fetchone()
        return (prior is not None and self._unsigned_smart_hold_verdict(prior) == 'deny'
                and prior['snapshot_sha256'] == self._approval_snapshot_digest_locked(task))

    def store_smart_terminal_judgement(
        self,
        task_id: int,
        snapshot_sha256: str,
        result: SmartApprovalResult,
        *,
        check: Callable[[], bool],
    ) -> tuple[dict | None, str | None]:
        """CAS one guardian verdict onto an exact pending terminal task.

        The caller's check must read only trusted live configuration, never this
        queue. Model output cannot choose the task transition, actor or receipt.
        """
        try:
            if (type(task_id) is not int or task_id <= 0 or type(snapshot_sha256) is not str
                    or _SHA256_HEX.fullmatch(snapshot_sha256) is None or not callable(check)
                    or type(result) is not SmartApprovalResult):
                return None, None
            verdict = result.verdict
            if verdict not in {"approve", "deny", "escalate"}:
                return None, None
            policy_revision = result.policy_revision
            judge_revision = result.judge_revision
            judge = result.judge
            at = result.at
            annotation = result.annotation()
            if (
                type(policy_revision) is not str or _SHA256_HEX.fullmatch(policy_revision) is None
                or type(judge_revision) is not str or _SHA256_HEX.fullmatch(judge_revision) is None
                or type(judge) is not dict
                or type(at) not in {int, float} or not math.isfinite(at)
                or type(annotation) is not dict
                or set(annotation) != {"decision", "advisory", "judge", "policy_revision", "judge_revision", "at"}
                or annotation != {
                    "decision": verdict, "advisory": False, "judge": judge,
                    "policy_revision": policy_revision, "judge_revision": judge_revision, "at": at,
                }
            ):
                return None, None
            annotation_json = canonical_json(annotation).decode("utf-8")
            # The result dataclass is frozen, but its identity mapping is not.
            # Seal one detached value before the live configuration check runs.
            judge = json.loads(annotation_json)["judge"]
        except Exception:
            return None, None

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                task = _row_to_task(row) if row else None
                prior = self._conn.execute(
                    "SELECT * FROM task_smart_approvals WHERE task_id=?", (task_id,),
                ).fetchone()
                args = _smart_terminal_args(task) if task else None
                if (
                    task is None or task.status != TaskStatus.BLOCKED.value
                    or not approval_is_pending(task)
                    or task.decided_by != "policy" or task.decision != "needs-approval"
                    or task.human_decision is not None
                    or args is None
                    or (prior is not None and not self._supersedable_smart_hold(prior, snapshot_sha256))
                    or self._approval_snapshot_digest_locked(task) != snapshot_sha256
                    or not self._smart_terminal_mediation_valid_locked(row)
                    or check() is not True
                ):
                    self._conn.rollback()
                    return None, None

                receipt_json = signature = None
                if verdict == "approve":
                    approved = replace(
                        task, status=TaskStatus.APPROVED.value,
                        decided_by="smart_approval", decision="smart-approve",
                    )
                    approved_sha256 = self.execution_fingerprint(approved)
                    if approved_sha256 is None:
                        self._conn.rollback()
                        return None, None
                    receipt = {
                        "schema": 1,
                        "purpose": _SMART_TERMINAL_PURPOSE,
                        "task_id": task_id,
                        "preapproval_sha256": snapshot_sha256,
                        "approved_execution_sha256": approved_sha256,
                        "policy_revision": policy_revision,
                        "judge_revision": judge_revision,
                        "judge": judge,
                        "at": at,
                        "nonce": str(uuid.uuid4()),
                        "command_target_sha256": canonical_digest(args),
                    }
                    receipt_bytes = canonical_json(receipt)
                    signature = self._mediation_signer.sign(receipt_bytes)
                    if signature is None:
                        self._conn.rollback()
                        return None, None
                    receipt_json = receipt_bytes.decode("utf-8")

                if prior is None:
                    self._conn.execute(
                        """INSERT INTO task_smart_approvals
                           (task_id, snapshot_sha256, annotation, receipt, signature)
                           VALUES (?, ?, ?, ?, ?)""",
                        (task_id, snapshot_sha256, annotation_json, receipt_json, signature),
                    )
                else:
                    changed = self._conn.execute(
                        """UPDATE task_smart_approvals
                           SET snapshot_sha256=?, annotation=?, receipt=?, signature=?
                           WHERE task_id=? AND snapshot_sha256=?
                             AND receipt IS NULL AND signature IS NULL""",
                        (snapshot_sha256, annotation_json, receipt_json, signature,
                         task_id, prior["snapshot_sha256"]),
                    )
                    if changed.rowcount != 1:
                        self._conn.rollback()
                        return None, None
                group_id = None
                if verdict == "approve":
                    self._conn.execute(
                        """UPDATE tasks SET status='approved', decided_by='smart_approval',
                           decision='smart-approve', updated_at=? WHERE id=? AND status='blocked'""",
                        (_now(), task_id),
                    )
                    group_id = self._withdraw_task_group_locked(task_id)
                    self._record_promotion_effect_locked(group_id, task_id)
                    self._reset_chat_guardian_denials_locked(task)
                elif verdict == "deny":
                    self._record_chat_guardian_denial_locked(task, snapshot_sha256)
                self._conn.commit()
                return json.loads(annotation_json), group_id
            except Exception:
                self._conn.rollback()
                return None, None

    def _smart_terminal_receipt_locked(self, row: sqlite3.Row | None, *,
                                       allow_done: bool = False) -> dict | None:
        """Verify the original approval, including a completed mediated row."""
        try:
            task = _row_to_task(row) if row else None
            allowed = {"approved", "running", "done"} if allow_done else {"approved", "running"}
            if (task is None or task.status not in allowed
                    or task.decided_by != "smart_approval" or task.decision != "smart-approve"
                    or task.human_decision is not None or _smart_terminal_args(task) is None
                    or not self._smart_terminal_mediation_valid_locked(row, allow_done=allow_done)):
                return None
            stored = self._conn.execute(
                "SELECT * FROM task_smart_approvals WHERE task_id=?", (task.id,),
            ).fetchone()
            if stored is None or not stored["receipt"] or not stored["signature"]:
                return None
            receipt = json.loads(stored["receipt"])
            if type(receipt) is not dict or set(receipt) != {
                "schema", "purpose", "task_id", "preapproval_sha256",
                "approved_execution_sha256", "policy_revision", "judge_revision",
                "judge", "at", "nonce", "command_target_sha256",
            }:
                return None
            approval_phase = replace(task, mediation_execution_id=None)
            expected_sha = self.execution_fingerprint(approval_phase)
            if (
                type(receipt["schema"]) is not int or receipt["schema"] != 1
                or receipt["purpose"] != _SMART_TERMINAL_PURPOSE
                or type(receipt["task_id"]) is not int or receipt["task_id"] != task.id
                or type(receipt["preapproval_sha256"]) is not str
                or receipt["preapproval_sha256"] != stored["snapshot_sha256"]
                or _SHA256_HEX.fullmatch(receipt["preapproval_sha256"]) is None
                or receipt["approved_execution_sha256"] != expected_sha
                or receipt["command_target_sha256"] != canonical_digest(_smart_terminal_args(task))
                or type(receipt["policy_revision"]) is not str
                or _SHA256_HEX.fullmatch(receipt["policy_revision"]) is None
                or type(receipt["judge_revision"]) is not str
                or _SHA256_HEX.fullmatch(receipt["judge_revision"]) is None
                or type(receipt["judge"]) is not dict
                or type(receipt["at"]) not in {int, float} or not math.isfinite(receipt["at"])
                or str(uuid.UUID(receipt["nonce"])) != receipt["nonce"]
            ):
                return None
            receipt_bytes = canonical_json(receipt)
            return (json.loads(receipt_bytes) if self._mediation_signer.verify(
                receipt_bytes, stored["signature"],
            ) else None)
        except Exception:
            return None

    def verify_smart_terminal_approval(
        self, task_id: int, *, check: Callable[[dict], bool],
    ) -> bool:
        """Verify machine authority from the live row and sealed receipt only."""
        if type(task_id) is not int or task_id <= 0 or not callable(check):
            return False
        with self._lock:
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                receipt = self._smart_terminal_receipt_locked(row)
                return receipt is not None and check(receipt) is True
            except Exception:
                return False

    @staticmethod
    def _smart_result_body(result: dict) -> dict:
        """Reserve the completion proof key for the worker, never the executor."""
        return {key: value for key, value in result.items() if key != "_smart_execution"}

    def issue_smart_terminal_result(self, task: Task, result: dict) -> dict:
        """Seal an actual RUNNING smart terminal result before the worker stores DONE.

        This is evidence of completion, not an execution permit. Failure to seal
        leaves the operation result intact but cannot prove successful execution.
        """
        if type(result) is not dict:
            return result
        body = self._smart_result_body(result)
        if (type(task) is not Task or task.status != TaskStatus.RUNNING.value
                or type(task.id) is not int or task.id <= 0
                or task.attempts <= 0
                or body.get("status") != "ok"
                or type(body.get("result")) is not dict
                or body["result"].get("ok") is not True):
            return body
        with self._lock:
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task.id,)).fetchone()
                persisted = _row_to_task(row) if row else None
                receipt = self._smart_terminal_receipt_locked(row)
                if (persisted is None or persisted.status != TaskStatus.RUNNING.value
                        or receipt is None or persisted.created_at != task.created_at
                        or self.execution_fingerprint(persisted) != self.execution_fingerprint(task)):
                    return body
                # The proof itself is small and bounded even if stdout is not.
                # Reject non-JSON values rather than certify a different result.
                result_sha256 = hashlib.sha256(json.dumps(
                    body, ensure_ascii=False, allow_nan=False,
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                proof = {
                    "schema": 1,
                    "purpose": _SMART_EXECUTION_PURPOSE,
                    "task_id": task.id,
                    "task_birth": task.created_at,
                    "running_execution_sha256": self.execution_fingerprint(task),
                    "kernel_intake_sha256": canonical_digest({
                        "id": task.kernel_intake_id,
                        "evidence": task.kernel_intake_evidence,
                    }),
                    "approval_receipt_sha256": canonical_digest(receipt),
                    "result_sha256": result_sha256,
                    "nonce": uuid.uuid4().hex,
                }
                signature = self._mediation_signer.sign(canonical_json(proof))
                if signature is None:
                    return body
                return {**body, "_smart_execution": {**proof, "signature": signature}}
            except Exception:
                return body

    def verify_smart_terminal_result(self, task_id: int) -> bool:
        """Check durable DONE bytes against one worker-sealed result receipt."""
        if type(task_id) is not int or task_id <= 0:
            return False
        with self._lock:
            try:
                row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                task = _row_to_task(row) if row else None
                receipt = self._smart_terminal_receipt_locked(row, allow_done=True)
                if (task is None or task.status != TaskStatus.DONE.value
                        or receipt is None or type(task.result) is not dict):
                    return False
                proof = task.result.get("_smart_execution")
                if type(proof) is not dict or set(proof) != {
                    "schema", "purpose", "task_id", "task_birth",
                    "running_execution_sha256", "kernel_intake_sha256",
                    "approval_receipt_sha256", "result_sha256", "nonce", "signature",
                }:
                    return False
                body = self._smart_result_body(task.result)
                if (body.get("status") != "ok" or type(body.get("result")) is not dict
                        or body["result"].get("ok") is not True):
                    return False
                result_sha256 = hashlib.sha256(json.dumps(
                    body, ensure_ascii=False, allow_nan=False,
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                if (
                    type(proof["schema"]) is not int or proof["schema"] != 1
                    or proof["purpose"] != _SMART_EXECUTION_PURPOSE
                    or type(proof["task_id"]) is not int or proof["task_id"] != task_id
                    or proof["task_birth"] != task.created_at
                    or proof["running_execution_sha256"] != self.execution_fingerprint(task)
                    or proof["kernel_intake_sha256"] != canonical_digest({
                        "id": task.kernel_intake_id,
                        "evidence": task.kernel_intake_evidence,
                    })
                    or proof["approval_receipt_sha256"] != canonical_digest(receipt)
                    or proof["result_sha256"] != result_sha256
                    or type(proof["nonce"]) is not str
                    or uuid.UUID(hex=proof["nonce"]).hex != proof["nonce"]
                    or uuid.UUID(hex=proof["nonce"]).version != 4
                ):
                    return False
                signature = proof["signature"]
                core = {key: value for key, value in proof.items() if key != "signature"}
                return self._mediation_signer.verify(canonical_json(core), signature)
            except Exception:
                return False

    @staticmethod
    def _owner_once_nonce(value: object) -> bool:
        try:
            return (type(value) is str and len(value) == 32
                    and uuid.UUID(hex=value).hex == value
                    and uuid.UUID(hex=value).version == 4)
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _owner_once_check(check: Callable[[], bool]) -> bool:
        try:
            return callable(check) and check() is True
        except Exception:
            return False

    def _prune_owner_once_claims_locked(self) -> None:
        now = _approval_now()
        for task_id, claim in tuple(self._owner_once_claims.items()):
            bound = self._conn.execute('SELECT state,deadline_at FROM task_owner_once WHERE task_id=?',
                                       (task_id,)).fetchone()
            try:
                expired = bound is None or datetime.fromisoformat(bound['deadline_at']) <= now
            except (TypeError, ValueError):
                expired = True
            if (expired or bound['state'] == 'revoked' or not claim._turn.live()):
                self._owner_once_claims.pop(task_id, None)

    def _owner_once_denial_locked(self, row: sqlite3.Row | None,
                                  snapshot_sha256: str) -> tuple[Task, sqlite3.Row] | None:
        task = _row_to_task(row) if row else None
        if (task is None or type(snapshot_sha256) is not str
                or _SHA256_HEX.fullmatch(snapshot_sha256) is None
                or not self._current_smart_denial_locked(task)
                or self._approval_snapshot_digest_locked(task) != snapshot_sha256
                or not self._smart_terminal_mediation_valid_locked(row)):
            return None
        denial = self._conn.execute(
            'SELECT * FROM task_smart_approvals WHERE task_id=?', (task.id,),
        ).fetchone()
        if denial is None or denial['snapshot_sha256'] != snapshot_sha256:
            return None
        return task, denial

    def offer_owner_once(self, task_id: int, snapshot_sha256: str, *, turn,
                         live_check: Callable[[], bool], timeout: float = 120) -> OwnerOnceOffer | None:
        """Offer one exact current DENY to its live interactive origin."""
        from agents.core.approval_outcomes import current_approval_turn

        if (type(task_id) is not int or task_id <= 0 or type(timeout) not in {int, float}
                or not math.isfinite(timeout) or not 0 < timeout <= 120
                or not isinstance(turn, ApprovalTurnContext)
                or current_approval_turn() is not turn or not turn.live()):
            return None
        try:
            principal = json.loads(turn.principal_key)
            if (type(principal) is not list or len(principal) != 3
                    or principal[0] != 'telegram' or any(
                        type(part) is not str or not part for part in principal[1:]
                    ) or re.fullmatch(r'[1-9][0-9]*', principal[1]) is None
                    or int(principal[1]) > 0xffffffffff
                    or re.fullmatch(r'-?[1-9][0-9]*', principal[2]) is None
                    or abs(int(principal[2])) > 0x7fffffffffffffff):
                return None
        except (TypeError, ValueError):
            return None
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                self._prune_owner_once_claims_locked()
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                current = self._owner_once_denial_locked(row, snapshot_sha256)
                if current is None or self.mediation_mode == 'hold' or not self._owner_once_check(live_check):
                    self._conn.rollback()
                    return None
                task, denial = current
                origin = self._chat_denial_consumer_locked(task)
                if origin is None or self._chat_intent_locked(task) != origin['intent_sha256']:
                    self._conn.rollback()
                    return None
                if (origin['origin_id'] != turn.turn_id or origin['session_id'] != turn.session_id
                        or origin['session_instance'] != turn.session_instance
                        or origin['principal_key'] != turn.principal_key):
                    self._conn.rollback()
                    return None
                if self._conn.execute('SELECT 1 FROM task_owner_once WHERE task_id=?',
                                      (task_id,)).fetchone() is not None:
                    self._conn.rollback()
                    return None
                now = _approval_now()
                active = self._conn.execute('''SELECT COUNT(*) FROM task_owner_once
                    WHERE state IN ('offered','accepted','claimed','dispatching')
                      AND deadline_at>?''', (now.isoformat(timespec='microseconds'),)).fetchone()[0]
                if active >= _OWNER_ONCE_LIMIT or len(self._owner_once_claims) >= _OWNER_ONCE_LIMIT:
                    self._conn.rollback()
                    return None
                deadline = now + timedelta(seconds=timeout)
                if task.approval_deadline_at is not None:
                    deadline = min(deadline, datetime.fromisoformat(
                        normalize_approval_deadline(task.approval_deadline_at)))
                if deadline <= now:
                    self._conn.rollback()
                    return None
                nonce = uuid.uuid4().hex
                stamp = deadline.isoformat(timespec='microseconds')
                self._conn.execute('''INSERT INTO task_owner_once (
                    task_id,task_birth,denial_snapshot_sha256,denial_annotation_sha256,
                    origin_id,session_id,session_instance,principal_key,intent_sha256,
                    offer_nonce_sha256,deadline_at,state
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'offered')''',
                    (task_id, task.created_at, snapshot_sha256,
                     hashlib.sha256(denial['annotation'].encode()).hexdigest(),
                     origin['origin_id'], origin['session_id'], origin['session_instance'],
                     origin['principal_key'], origin['intent_sha256'],
                     hashlib.sha256(nonce.encode()).hexdigest(), stamp))
                self._conn.commit()
                return OwnerOnceOffer(task_id, nonce, stamp, turn, self._owner_once_key)
            except Exception:
                self._conn.rollback()
                return None

    def _owner_once_offer_locked(self, offer: OwnerOnceOffer) -> sqlite3.Row | None:
        if (type(offer) is not OwnerOnceOffer or offer._queue_key is not self._owner_once_key
                or not self._owner_once_nonce(offer.nonce) or not offer._turn.live()):
            return None
        row = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                 (offer.task_id,)).fetchone()
        if (row is None or row['state'] != 'offered'
                or row['offer_nonce_sha256'] != hashlib.sha256(offer.nonce.encode()).hexdigest()
                or row['deadline_at'] != offer.deadline_at
                or datetime.fromisoformat(row['deadline_at']) <= _approval_now()):
            return None
        return row

    def mark_owner_once_delivered(self, offer: OwnerOnceOffer, *, chat_id: int,
                                  user_id: int, message_id: int, generation: str,
                                  live_check: Callable[[], bool]) -> bool:
        """Bind a Telegram-confirmed prompt before any answer is acceptable."""
        if (type(chat_id) is not int or chat_id == 0 or type(user_id) is not int
                or not 0 < user_id <= 0xffffffffff or type(message_id) is not int
                or message_id <= 0 or not self._owner_once_nonce(generation)):
            return False
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                bound = self._owner_once_offer_locked(offer)
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?',
                                         (offer.task_id,)).fetchone() if bound else None
                current = self._owner_once_denial_locked(row, bound['denial_snapshot_sha256']) if bound else None
                principal = json.loads(bound['principal_key']) if bound else None
                if (bound is None or current is None or bound['message_id'] is not None
                        or principal != ['telegram', str(user_id), str(chat_id)]
                        or not self._owner_once_check(live_check)):
                    self._conn.rollback()
                    return False
                changed = self._conn.execute('''UPDATE task_owner_once
                    SET chat_id=?,user_id=?,message_id=?,generation=?
                    WHERE task_id=? AND state='offered' AND message_id IS NULL''',
                    (chat_id, user_id, message_id, generation, offer.task_id))
                self._conn.commit()
                return changed.rowcount == 1
            except Exception:
                self._conn.rollback()
                return False

    def reject_smart_terminal_denial(self, task_id: int, snapshot_sha256: str, *,
                                     check: Callable[[], bool],
                                     reason: str = 'guardian-denied') -> bool:
        """Settle only the original still-current unsigned machine DENY."""
        if (type(task_id) is not int or task_id <= 0 or type(reason) is not str
                or not reason or len(reason) > 128):
            return False
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                current = self._owner_once_denial_locked(row, snapshot_sha256)
                offer = self._conn.execute('SELECT state FROM task_owner_once WHERE task_id=?',
                                           (task_id,)).fetchone()
                if (current is None or (offer is not None and offer['state'] != 'offered')
                        or not self._owner_once_check(check)):
                    self._conn.rollback()
                    return False
                if offer is not None:
                    self._conn.execute("UPDATE task_owner_once SET state='revoked' WHERE task_id=?",
                                       (task_id,))
                changed = self._conn.execute('''UPDATE tasks SET status='rejected',
                    decided_by='smart_approval',decision='smart-deny',updated_at=?
                    WHERE id=? AND status='blocked' AND decided_by='policy'
                    AND decision='needs-approval' ''', (_now(), task_id))
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return False
                self._withdraw_task_group_locked(task_id)
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                return False

    def smart_terminal_denial(self, task_id: int, snapshot_sha256: str) -> dict | None:
        """Observe one canonical exact DENY after a machine refusal settles it.

        This is evidence for the originating answer, never an execution receipt.
        """
        if (type(task_id) is not int or task_id <= 0 or type(snapshot_sha256) is not str
                or _SHA256_HEX.fullmatch(snapshot_sha256) is None):
            return None
        with self._lock:
            return self._smart_terminal_denial_locked(task_id, snapshot_sha256)

    def _smart_terminal_denial_locked(self, task_id: int,
                                      snapshot_sha256: str) -> dict | None:
        try:
            row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            task = _row_to_task(row) if row else None
            if task is None:
                return None
            if task.status == 'blocked':
                if self._owner_once_denial_locked(row, snapshot_sha256) is None:
                    return None
            elif (task.status == 'rejected' and _smart_terminal_args(task) is not None
                  and self._smart_terminal_mediation_valid_locked(row)):
                machine = (task.decided_by == 'smart_approval'
                           and task.decision == 'smart-deny'
                           and task.human_decision is None)
                owner = (task.decided_by == 'owner_once'
                         and task.decision == 'owner-deny'
                         and type(task.human_decision) is dict)
                if not machine and not owner:
                    return None
                if owner:
                    human = task.human_decision
                    bound = self._conn.execute(
                        'SELECT * FROM task_owner_once WHERE task_id=?', (task_id,),
                    ).fetchone()
                    if (bound is None or bound['state'] != 'revoked'
                            or bound['task_birth'] != task.created_at
                            or bound['denial_snapshot_sha256'] != snapshot_sha256
                            or bound['owner_decision_id'] != human.get('id')
                            or not self._owner_once_nonce(human.get('id'))
                            or set(human) != {'id', 'action', 'reason', 'by', 'at', 'first_at'}
                            or human['action'] != 'reject' or human['by'] != 'owner_once'
                            or human['reason'] is not None
                            or type(human['at']) is not str
                            or human['at'] != human['first_at']
                            or bound['message_id'] is None
                            or bound['approval_receipt'] is not None
                            or bound['signature'] is not None):
                        return None
                phase = replace(task, status='blocked', decided_by='policy',
                                decision='needs-approval', human_decision=None)
                if self._approval_snapshot_digest_locked(phase) != snapshot_sha256:
                    return None
            else:
                return None
            denial = self._conn.execute('SELECT * FROM task_smart_approvals WHERE task_id=?',
                                        (task_id,)).fetchone()
            if (denial is None or denial['snapshot_sha256'] != snapshot_sha256
                    or self._unsigned_smart_hold_verdict(denial) != 'deny'):
                return None
            if (task.status == 'rejected' and task.decided_by == 'owner_once'
                    and bound['denial_annotation_sha256']
                    != hashlib.sha256(denial['annotation'].encode()).hexdigest()):
                return None
            return json.loads(denial['annotation'])
        except Exception:
            return None

    @staticmethod
    def _owner_once_owner_valid(owner: OwnerOnceOwner, bound: sqlite3.Row) -> bool:
        if (type(owner) is not OwnerOnceOwner or owner.channel != 'telegram'
                or type(owner.principal_key) is not str
                or owner.principal_key != bound['principal_key']
                or type(owner.chat_id) is not int or owner.chat_id == 0
                or type(owner.user_id) is not int or not 0 < owner.user_id <= 0xffffffffff
                or type(owner.message_id) is not int or owner.message_id <= 0
                or not TaskQueue._owner_once_nonce(owner.generation)
                or owner.chat_id != bound['chat_id'] or owner.user_id != bound['user_id']
                or owner.message_id != bound['message_id']
                or owner.generation != bound['generation']):
            return False
        try:
            return json.loads(owner.principal_key) == [
                'telegram', str(owner.user_id), str(owner.chat_id),
            ]
        except (TypeError, ValueError):
            return False

    def _owner_once_receipt_body_locked(self, task: Task, bound: sqlite3.Row | dict,
                                        decision_id: str) -> dict | None:
        """Build one exact approval body; caller signs it or compares stored bytes."""
        try:
            args = _smart_terminal_args(task)
            if (args is None or task.created_at != bound['task_birth']
                    or task.decided_by != 'owner_once' or task.decision != 'owner-once'
                    or not self._owner_once_nonce(decision_id)):
                return None
            phase = replace(task, status=TaskStatus.BLOCKED.value,
                            decided_by='policy', decision='needs-approval',
                            mediation_execution_id=None, human_decision=None)
            if self._approval_snapshot_digest_locked(phase) != bound['denial_snapshot_sha256']:
                return None
            denial = self._conn.execute('SELECT * FROM task_smart_approvals WHERE task_id=?',
                                        (task.id,)).fetchone()
            origin = self._chat_denial_consumer_locked(task)
            if (denial is None or self._unsigned_smart_hold_verdict(denial) != 'deny'
                    or denial['snapshot_sha256'] != bound['denial_snapshot_sha256']
                    or hashlib.sha256(denial['annotation'].encode()).hexdigest()
                    != bound['denial_annotation_sha256']
                    or origin is None or origin['origin_id'] != bound['origin_id']
                    or origin['session_id'] != bound['session_id']
                    or origin['session_instance'] != bound['session_instance']
                    or origin['principal_key'] != bound['principal_key']
                    or origin['intent_sha256'] != bound['intent_sha256']
                    or self._chat_intent_locked(task) != bound['intent_sha256']):
                return None
            approved = replace(task, status=TaskStatus.APPROVED.value,
                               mediation_execution_id=None)
            fingerprint = self.execution_fingerprint(approved)
            if fingerprint is None:
                return None
            if bound['generation'] is None or bound['message_id'] is None:
                return None
            return {
                'schema': 1, 'purpose': _OWNER_ONCE_PURPOSE,
                'task_id': task.id, 'task_birth': task.created_at,
                'denial_snapshot_sha256': bound['denial_snapshot_sha256'],
                'denial_annotation_sha256': bound['denial_annotation_sha256'],
                'origin_id': bound['origin_id'], 'session_id': bound['session_id'],
                'session_instance': bound['session_instance'],
                'principal_key': bound['principal_key'],
                'intent_sha256': bound['intent_sha256'],
                'offer_nonce_sha256': bound['offer_nonce_sha256'],
                'deadline_at': bound['deadline_at'],
                'owner_decision_id': decision_id, 'owner_channel': 'telegram',
                'owner_chat_id': bound['chat_id'], 'owner_user_id': bound['user_id'],
                'owner_message_id': bound['message_id'],
                'owner_generation': bound['generation'],
                'command_target_sha256': canonical_digest(args),
                'kernel_intake_sha256': canonical_digest({
                    'id': task.kernel_intake_id, 'evidence': task.kernel_intake_evidence,
                }),
                'mediation_receipt_sha256': (
                    canonical_digest(task.mediation_receipt)
                    if task.mediation_receipt is not None else None
                ),
                'mediation_policy_revision': task.mediation_policy_revision,
                'approved_execution_sha256': fingerprint,
            }
        except Exception:
            return None

    def _owner_once_approval_locked(self, row: sqlite3.Row | None,
                                    bound: sqlite3.Row | None,
                                    *, allow_done: bool = False) -> dict | None:
        try:
            task = _row_to_task(row) if row else None
            statuses = {'approved', 'running', 'done'} if allow_done else {'approved', 'running'}
            if (task is None or bound is None or task.status not in statuses
                    or bound['state'] not in {'accepted', 'claimed', 'dispatching'}
                    or task.human_decision is None
                    or task.human_decision.get('id') != bound['owner_decision_id']
                    or task.human_decision.get('action') != 'once'
                    or task.human_decision.get('by') != 'owner_once'
                    or not self._smart_terminal_mediation_valid_locked(row, allow_done=allow_done)
                    or type(bound['approval_receipt']) is not str
                    or type(bound['signature']) is not str):
                return None
            receipt = json.loads(bound['approval_receipt'])
            expected = self._owner_once_receipt_body_locked(task, bound,
                                                            bound['owner_decision_id'])
            if (type(receipt) is not dict or expected is None or receipt != expected
                    or canonical_json(receipt).decode() != bound['approval_receipt']
                    or not self._mediation_signer.verify(canonical_json(receipt),
                                                         bound['signature'])):
                return None
            if task.status in {'running', 'done'}:
                if bound['state'] not in {'claimed', 'dispatching'}:
                    return None
                if (self.mediation_mode == 'enforce'
                        and bound['mediation_execution_id'] != task.mediation_execution_id):
                    return None
            return receipt
        except Exception:
            return None

    def _owner_once_withdrawn_approval_locked(self, row: sqlite3.Row | None,
                                              bound: sqlite3.Row | None) -> dict | None:
        """Read a signed acceptance withdrawn before dispatch, never execution authority."""
        try:
            task = _row_to_task(row) if row else None
            if (task is None or bound is None or task.status != 'rejected'
                    or task.decided_by != 'owner_once' or task.decision != 'owner-once'
                    or type(task.human_decision) is not dict
                    or set(task.human_decision)
                    != {'id', 'action', 'reason', 'by', 'at', 'first_at'}
                    or task.human_decision.get('action') != 'once'
                    or task.human_decision.get('by') != 'owner_once'
                    or not self._owner_once_nonce(task.human_decision.get('id'))
                    or task.human_decision.get('reason') is not None
                    or type(task.human_decision.get('at')) is not str
                    or task.human_decision['at'] != task.human_decision['first_at']
                    or bound['state'] != 'revoked'
                    or bound['owner_decision_id'] != task.human_decision['id']
                    or bound['claimed_at'] is not None or bound['dispatch_at'] is not None
                    or bound['mediation_execution_id'] is not None
                    or task.mediation_execution_id is not None
                    or not self._smart_terminal_mediation_valid_locked(row)
                    or type(bound['approval_receipt']) is not str
                    or type(bound['signature']) is not str):
                return None
            receipt = json.loads(bound['approval_receipt'])
            approved = replace(task, status='approved')
            expected = self._owner_once_receipt_body_locked(
                approved, bound, bound['owner_decision_id'])
            if (type(receipt) is not dict or expected is None or receipt != expected
                    or canonical_json(receipt).decode() != bound['approval_receipt']
                    or not self._mediation_signer.verify(canonical_json(receipt),
                                                         bound['signature'])):
                return None
            return receipt
        except Exception:
            return None

    def decide_owner_once(self, offer: OwnerOnceOffer, nonce: str, choice: str, *,
                          authenticated_owner: OwnerOnceOwner,
                          live_check: Callable[[], bool]) -> OwnerOnceClaim | None:
        """CAS a delivered owner's exact once/deny answer, without scope grants."""
        if (choice not in {'once', 'deny'} or type(choice) is not str
                or type(offer) is not OwnerOnceOffer or nonce != offer.nonce):
            return None
        if choice == 'deny':
            self.reject_owner_once(offer, nonce, authenticated_owner=authenticated_owner,
                                   live_check=live_check)
            return None
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                bound = self._owner_once_offer_locked(offer)
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?',
                                         (offer.task_id,)).fetchone() if bound else None
                current = self._owner_once_denial_locked(row, bound['denial_snapshot_sha256']) if bound else None
                if (bound is None or current is None or bound['message_id'] is None
                        or not self._owner_once_owner_valid(authenticated_owner, bound)
                        or not self._owner_once_check(live_check)):
                    self._conn.rollback()
                    return None
                task, _denial = current
                decision_id = uuid.uuid4().hex
                at = _now()
                human = {'id': decision_id, 'action': 'once', 'by': 'owner_once',
                         'at': at, 'first_at': at, 'reason': None}
                approved = replace(task, status='approved', decided_by='owner_once',
                                   decision='owner-once', human_decision=human)
                receipt = self._owner_once_receipt_body_locked(approved, bound, decision_id)
                if receipt is None:
                    self._conn.rollback()
                    return None
                encoded = canonical_json(receipt)
                signature = self._mediation_signer.sign(encoded)
                if signature is None:
                    self._conn.rollback()
                    return None
                changed = self._conn.execute('''UPDATE tasks SET status='approved',
                    decided_by='owner_once',decision='owner-once',human_decision=?,updated_at=?
                    WHERE id=? AND status='blocked' AND decided_by='policy'
                    AND decision='needs-approval' ''',
                    (json.dumps(human, ensure_ascii=False), at, task.id))
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return None
                self._conn.execute('''UPDATE task_owner_once SET state='accepted',
                    owner_decision_id=?,approval_receipt=?,signature=?
                    WHERE task_id=? AND state='offered' ''',
                    (decision_id, encoded.decode(), signature, task.id))
                group_id = self._withdraw_task_group_locked(task.id)
                self._record_promotion_effect_locked(group_id, task.id)
                self._conn.commit()
                claim = OwnerOnceClaim(task.id, nonce, decision_id, offer._turn,
                                       authenticated_owner, self._owner_once_key)
                self._owner_once_claims[task.id] = claim
                return claim
            except Exception:
                self._conn.rollback()
                return None

    def reject_owner_once(self, offer: OwnerOnceOffer, nonce: str, *,
                          authenticated_owner: OwnerOnceOwner,
                          live_check: Callable[[], bool]) -> bool:
        """Return true only when an exact delivered owner's rejection commits."""
        if (type(offer) is not OwnerOnceOffer or type(nonce) is not str
                or nonce != offer.nonce):
            return False
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                bound = self._owner_once_offer_locked(offer)
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?',
                                         (offer.task_id,)).fetchone() if bound else None
                current = self._owner_once_denial_locked(
                    row, bound['denial_snapshot_sha256']) if bound else None
                if (bound is None or current is None or bound['message_id'] is None
                        or not self._owner_once_owner_valid(authenticated_owner, bound)
                        or not self._owner_once_check(live_check)):
                    self._conn.rollback()
                    return False
                task, _denial = current
                at = _now()
                human = self._human_decision_record('reject', 'owner_once', None, at)
                changed = self._conn.execute('''UPDATE tasks SET status='rejected',
                    decided_by='owner_once',decision='owner-deny',human_decision=?,updated_at=?
                    WHERE id=? AND status='blocked' AND decided_by='policy'
                    AND decision='needs-approval' ''',
                    (json.dumps(human, ensure_ascii=False), at, task.id))
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return False
                changed = self._conn.execute('''UPDATE task_owner_once SET state='revoked',
                    owner_decision_id=? WHERE task_id=? AND state='offered' ''',
                    (human['id'], task.id))
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return False
                self._withdraw_task_group_locked(task.id)
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                return False

    def _owner_once_claim_live_locked(self, claim: OwnerOnceClaim,
                                      bound: sqlite3.Row) -> bool:
        return (
            type(claim) is OwnerOnceClaim
            and claim._queue_key is self._owner_once_key
            and self._owner_once_claims.get(claim.task_id) is claim
            and claim._turn.live()
            and self._owner_once_nonce(claim.nonce)
            and hashlib.sha256(claim.nonce.encode()).hexdigest() == bound['offer_nonce_sha256']
            and claim.decision_id == bound['owner_decision_id']
            and claim._turn.turn_id == bound['origin_id']
            and claim._turn.session_id == bound['session_id']
            and claim._turn.session_instance == bound['session_instance']
            and claim._turn.principal_key == bound['principal_key']
            and self._owner_once_owner_valid(claim._owner, bound)
            and datetime.fromisoformat(bound['deadline_at']) > _approval_now()
        )

    def revoke_owner_once(self, offer: OwnerOnceOffer, reason: str = 'withdrawn') -> bool:
        """Invalidate an undispached offer/claim before a late reply or send."""
        if (type(offer) is not OwnerOnceOffer or offer._queue_key is not self._owner_once_key
                or type(reason) is not str or not reason or len(reason) > 128):
            return False
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                           (offer.task_id,)).fetchone()
                if (bound is None or bound['state'] not in {'offered', 'accepted', 'claimed'}
                        or bound['offer_nonce_sha256'] != hashlib.sha256(
                            offer.nonce.encode()).hexdigest()):
                    self._conn.rollback()
                    return False
                changed = self._conn.execute("""UPDATE task_owner_once SET state='revoked'
                    WHERE task_id=? AND state IN ('offered','accepted','claimed')""",
                    (offer.task_id,))
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return False
                task_row = self._conn.execute('SELECT * FROM tasks WHERE id=?',
                                              (offer.task_id,)).fetchone()
                if bound['state'] in {'offered', 'accepted'}:
                    exact = (self._owner_once_denial_locked(
                        task_row, bound['denial_snapshot_sha256']) is not None
                        if bound['state'] == 'offered'
                        else self._owner_once_approval_locked(task_row, bound) is not None)
                    if exact:
                        if bound['state'] == 'offered':
                            self._conn.execute("""UPDATE tasks SET status='rejected',
                                decided_by='smart_approval',decision='smart-deny',updated_at=?
                                WHERE id=? AND status='blocked'""", (_now(), offer.task_id))
                        else:
                            self._conn.execute("""UPDATE tasks SET status='rejected',updated_at=?
                                WHERE id=? AND status='approved'""", (_now(), offer.task_id))
                        self._withdraw_task_group_locked(offer.task_id)
                self._conn.commit()
                self._owner_once_claims.pop(offer.task_id, None)
                return True
            except Exception:
                self._conn.rollback()
                return False

    def claim_owner_once(self, task_id: int, claim: OwnerOnceClaim, *, execution_id: str,
                         live_check: Callable[[], bool]) -> Task | None:
        """Claim one signed owner reply; B7 validation and event stay atomic."""
        if (type(task_id) is not int or task_id <= 0 or type(execution_id) is not str
                or not execution_id or len(execution_id) > 128
                or type(claim) is not OwnerOnceClaim or claim.task_id != task_id
                or self.mediation_mode not in {'off', 'enforce'}):
            return None
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                           (task_id,)).fetchone()
                receipt = self._owner_once_approval_locked(row, bound)
                if (row is None or bound is None or bound['state'] != 'accepted'
                        or row['status'] != 'approved' or receipt is None
                        or not self._owner_once_claim_live_locked(claim, bound)
                        or not self._owner_once_check(live_check)):
                    self._conn.rollback()
                    return None
                verified_state = mediation_receipt = expectation = None
                if self.mediation_mode == 'enforce':
                    snapshot = self._validated_mediation_snapshot_locked()
                    if snapshot is None or self._classification(row['kind']) is not True:
                        self._conn.rollback()
                        return None
                    verified_state = snapshot[0]
                    mediation_receipt, expectation, current_sha256 = self._row_receipt_and_expectation(row)
                    authorized = self._conn.execute('''SELECT 1 FROM task_mediation_events
                        WHERE task_id=? AND enqueue_id=? AND outcome='authorized_enqueue'
                        LIMIT 1''', (task_id, expectation.enqueue_id)).fetchone()
                    if not (
                        row['mediation_execution_id'] is None
                        and int(row['risk_tier']) == mediation_receipt.effective_tier
                        and self._scope_allowed(expectation.scope)
                        and expectation.policy_revision == self._mediation_policy_revision
                        and authorized is not None
                        and current_sha256 == row['mediation_task_sha256']
                        and self._event_chain_valid_locked()
                        and verify_receipt(self._mediation_signer, mediation_receipt,
                                           expected=expectation, now_ms=self._clock_ms())
                    ):
                        self._conn.rollback()
                        return None
                elif self._row_has_mediation_provenance(row):
                    self._conn.rollback()
                    return None
                changed = self._conn.execute('''UPDATE tasks SET status='running',
                    mediation_execution_id=?,updated_at=?
                    WHERE id=? AND status='approved' AND mediation_execution_id IS NULL''',
                    (execution_id if self.mediation_mode == 'enforce' else None,
                     _now(), task_id))
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return None
                self._conn.execute('''UPDATE task_owner_once SET state='claimed',
                    mediation_execution_id=?,claimed_at=?
                    WHERE task_id=? AND state='accepted' ''',
                    (execution_id, _now(), task_id))
                if self.mediation_mode == 'enforce':
                    self._append_mediation_event_locked(
                        outcome='governed', task_id=task_id,
                        enqueue_id=expectation.enqueue_id, receipt=mediation_receipt,
                        execution_id=execution_id, verified_state=verified_state,
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                return None
        return self.get(task_id)

    def owner_once_dispatch_current(self, task_id: int, claim: OwnerOnceClaim, *,
                                    live_check: Callable[[], bool]) -> bool:
        """Consume the only physical-dispatch opportunity for this claim."""
        if type(task_id) is not int or task_id <= 0 or type(claim) is not OwnerOnceClaim:
            return False
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                           (task_id,)).fetchone()
                if (bound is None or bound['state'] != 'claimed' or row is None
                        or row['status'] != 'running'
                        or self._owner_once_approval_locked(row, bound) is None
                        or not self._owner_once_claim_live_locked(claim, bound)
                        or not self._owner_once_check(live_check)):
                    self._conn.rollback()
                    return False
                changed = self._conn.execute('''UPDATE task_owner_once
                    SET state='dispatching',dispatch_at=?
                    WHERE task_id=? AND state='claimed' ''', (_now(), task_id))
                self._conn.commit()
                return changed.rowcount == 1
            except Exception:
                self._conn.rollback()
                return False

    def verify_owner_once_terminal_approval(self, task_id: int, *,
                                            check: Callable[[dict], bool]) -> bool:
        """Verify a live signed owner claim before kernel or terminal authority."""
        if type(task_id) is not int or task_id <= 0 or not callable(check):
            return False
        with self._lock:
            try:
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                           (task_id,)).fetchone()
                receipt = self._owner_once_approval_locked(row, bound)
                claim = self._owner_once_claims.get(task_id)
                return (receipt is not None and claim is not None
                        and self._owner_once_claim_live_locked(claim, bound)
                        and check(receipt) is True)
            except Exception:
                return False

    @staticmethod
    def _owner_once_result_body(result: dict) -> dict:
        return {key: value for key, value in result.items()
                if key != '_owner_once_execution'}

    def issue_owner_once_terminal_result(self, task: Task, result: dict) -> dict:
        """Sign only one real dispatched successful RUNNING owner operation."""
        if type(result) is not dict:
            return result
        body = self._owner_once_result_body(result)
        if (type(task) is not Task or task.status != 'running'
                or task.attempts <= 0 or body.get('status') != 'ok'
                or type(body.get('result')) is not dict
                or body['result'].get('ok') is not True):
            return body
        with self._lock:
            try:
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task.id,)).fetchone()
                bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                           (task.id,)).fetchone()
                persisted = _row_to_task(row) if row else None
                receipt = self._owner_once_approval_locked(row, bound)
                if (persisted is None or persisted.status != 'running'
                        or bound is None or bound['state'] != 'dispatching'
                        or bound['dispatch_at'] is None or receipt is None
                        or persisted.created_at != task.created_at
                        or self.execution_fingerprint(persisted) != self.execution_fingerprint(task)):
                    return body
                result_sha256 = hashlib.sha256(json.dumps(
                    body, ensure_ascii=False, allow_nan=False, sort_keys=True,
                    separators=(',', ':'),
                ).encode()).hexdigest()
                proof = {
                    'schema': 1, 'purpose': _OWNER_ONCE_EXECUTION_PURPOSE,
                    'task_id': task.id, 'task_birth': task.created_at,
                    'running_execution_sha256': self.execution_fingerprint(task),
                    'claim_execution_id': bound['mediation_execution_id'],
                    'kernel_intake_sha256': canonical_digest({
                        'id': task.kernel_intake_id, 'evidence': task.kernel_intake_evidence,
                    }),
                    'approval_receipt_sha256': canonical_digest(receipt),
                    'result_sha256': result_sha256, 'nonce': uuid.uuid4().hex,
                }
                signature = self._mediation_signer.sign(canonical_json(proof))
                if signature is None:
                    return body
                return {**body, '_owner_once_execution': {**proof, 'signature': signature}}
            except Exception:
                return body

    def verify_owner_once_terminal_result(self, task_id: int) -> bool:
        """Verify historical DONE evidence after the live turn has closed."""
        if type(task_id) is not int or task_id <= 0:
            return False
        with self._lock:
            try:
                row = self._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                bound = self._conn.execute('SELECT * FROM task_owner_once WHERE task_id=?',
                                           (task_id,)).fetchone()
                task = _row_to_task(row) if row else None
                receipt = self._owner_once_approval_locked(row, bound, allow_done=True)
                if (task is None or task.status != 'done' or bound is None
                        or bound['state'] != 'dispatching' or bound['dispatch_at'] is None
                        or receipt is None or type(task.result) is not dict):
                    return False
                proof = task.result.get('_owner_once_execution')
                if type(proof) is not dict or set(proof) != {
                    'schema', 'purpose', 'task_id', 'task_birth',
                    'running_execution_sha256', 'claim_execution_id',
                    'kernel_intake_sha256', 'approval_receipt_sha256',
                    'result_sha256', 'nonce', 'signature',
                }:
                    return False
                body = self._owner_once_result_body(task.result)
                if (body.get('status') != 'ok' or type(body.get('result')) is not dict
                        or body['result'].get('ok') is not True):
                    return False
                result_sha256 = hashlib.sha256(json.dumps(
                    body, ensure_ascii=False, allow_nan=False, sort_keys=True,
                    separators=(',', ':'),
                ).encode()).hexdigest()
                if (type(proof['schema']) is not int or proof['schema'] != 1
                        or proof['purpose'] != _OWNER_ONCE_EXECUTION_PURPOSE
                        or type(proof['task_id']) is not int or proof['task_id'] != task_id
                        or proof['task_birth'] != task.created_at
                        or proof['running_execution_sha256'] != self.execution_fingerprint(task)
                        or proof['claim_execution_id'] != bound['mediation_execution_id']
                        or proof['kernel_intake_sha256'] != canonical_digest({
                            'id': task.kernel_intake_id, 'evidence': task.kernel_intake_evidence,
                        })
                        or proof['approval_receipt_sha256'] != canonical_digest(receipt)
                        or proof['result_sha256'] != result_sha256
                        or not self._owner_once_nonce(proof['nonce'])):
                    return False
                core = {key: value for key, value in proof.items() if key != 'signature'}
                return self._mediation_signer.verify(canonical_json(core), proof['signature'])
            except Exception:
                return False

    def get(self, task_id: int) -> Optional[Task]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list(
        self, status: Optional[str] = None, origin: Optional[str] = None, limit: int = 100
    ) -> list[Task]:
        clauses, params = [], []
        if status:
            clauses.append("status=?")
            params.append(status)
        if origin:
            clauses.append("origin=?")
            params.append(origin)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                # `where` contains only the fixed status/origin clauses above.
                f"SELECT * FROM tasks {where} ORDER BY id DESC LIMIT ?",  # nosec B608
                params,
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def reap_stuck_running(self, ttl_seconds: float, *, now: Optional[float] = None) -> list[Task]:
        """Fail tasks stranded in RUNNING past ``ttl_seconds`` (crash mid-task).

        A worker crash between the RUNNING transition and the terminal one
        strands the task: ``runnable()`` selects APPROVED only, so nothing ever
        picks it back up. ``updated_at`` is stamped by the RUNNING transition
        (and again by ``increment_attempts`` moments later), so it is the
        run-start marker. In-process hangs are already bounded by the executor's
        wall-time budget — this reaper exists for dead processes.
        """
        ts = float(now) if now is not None else time.time()
        cutoff = datetime.fromtimestamp(
            ts - max(0.0, float(ttl_seconds)), tz=timezone.utc
        ).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status='running' AND updated_at < ? ORDER BY id ASC",
                (cutoff,),
            ).fetchall()
        reaped: list[Task] = []
        for task in (_row_to_task(r) for r in rows):
            reaped.append(
                self.transition(
                    task.id,
                    TaskStatus.FAILED,
                    result={
                        "error": "stuck_running_ttl",
                        "ttl_seconds": float(ttl_seconds),
                        "stuck_since": task.updated_at,
                    },
                )
            )
        return reaped

    def runnable(self, limit: int = 10, max_tier: Optional[int] = None, *,
                 task_id: int | None = None) -> list[Task]:
        """Approved tasks that have not exhausted their retry budget.

        `max_tier` (optional) caps the risk tier — the night shift passes 1 to
        batch only reversible/read-only work.
        """
        if task_id is not None and (type(task_id) is not int or task_id <= 0):
            raise ValueError("task_id must be a positive integer")
        # An owner-once approval is inert without its private named claim.
        clause = ("status='approved' AND attempts < ? AND "
                  "COALESCE(decided_by,'')!='owner_once' AND COALESCE(decision,'')!='owner-once'")
        params: list = [MAX_ATTEMPTS]
        if max_tier is not None:
            clause += " AND risk_tier <= ?"
            params.append(int(max_tier))
        if task_id is not None:
            clause += " AND id=?"
            params.append(task_id)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                # `clause` contains only fixed retry/tier predicates.
                f"SELECT * FROM tasks WHERE {clause} ORDER BY id ASC LIMIT ?",  # nosec B608
                params,
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def pending_decisions(self, only_unpushed: bool = False, limit: int = 100,
                          kind: Optional[str] = None) -> list[Task]:
        # O26-P0.7 (F3): a 'proposed' task also awaits a human decision
        # (PROPOSED -> APPROVED is a legal apply_decision transition) — before
        # this, broker-originated proposals never appeared in the decision
        # inbox (Telegram or HUD), only in the raw task list.
        # H262 review round 2 (N7): ``kind`` filters in SQL, so the waiting tasks of one
        # kind are found however many decisions of other kinds wait before them.
        clause = "status IN ('blocked','proposed')"
        params: list = []
        if only_unpushed:
            clause += " AND pushed=0"
        if kind is not None:
            clause += " AND kind=?"
            params.append(kind)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                # `clause` is built only from the fixed predicates above; values are bound.
                f"SELECT * FROM tasks WHERE {clause} ORDER BY id ASC LIMIT ?",  # nosec B608
                params,
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def capability_outcome_stats(self, capability_id: str) -> dict:
        capability_id = str(capability_id or "").strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM capability_outcomes WHERE capability_id=?",
                (capability_id,),
            ).fetchone()
        return _outcome_stats(capability_id, row)

    def all_capability_outcome_stats(self) -> dict[str, dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM capability_outcomes ORDER BY capability_id"
            ).fetchall()
        return {row["capability_id"]: _outcome_stats(row["capability_id"], row) for row in rows}


# ── helpers ───────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    """95% Wilson lower bound; small samples never look more certain than they are."""
    if total <= 0:
        return 0.0
    rate = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = rate + z2 / (2.0 * total)
    margin = z * math.sqrt((rate * (1.0 - rate) / total) + z2 / (4.0 * total * total))
    return max(0.0, min(1.0, (centre - margin) / denominator))


def _outcome_stats(capability_id: str, row) -> dict:
    successes = int(row["successes"]) if row is not None else 0
    failures = int(row["failures"]) if row is not None else 0
    total = successes + failures
    return {
        "capability_id": capability_id,
        "successes": successes,
        "failures": failures,
        "total": total,
        "success_rate": round(successes / total, 6) if total else 0.0,
        "confidence": round(_wilson_lower_bound(successes, total), 6),
        "last_outcome_at": row["last_outcome_at"] if row is not None else None,
    }


def _row_to_task(row: sqlite3.Row) -> Task:
    receipt = None
    if row["mediation_receipt"]:
        try:
            receipt = json.loads(row["mediation_receipt"])
        except (TypeError, ValueError, json.JSONDecodeError):
            receipt = None
    intake_evidence = None
    if row["kernel_intake_evidence"]:
        try:
            intake_evidence = json.loads(row["kernel_intake_evidence"])
        except (TypeError, ValueError, json.JSONDecodeError):
            intake_evidence = None
    human_decision = None
    if row["human_decision"]:
        try:
            metadata = json.loads(row["human_decision"])
            if isinstance(metadata, dict):
                human_decision = metadata
        except (TypeError, ValueError):
            pass
    return Task(
        id=row["id"],
        agent=row["agent"],
        kind=row["kind"],
        title=row["title"],
        payload=json.loads(row["payload"] or "{}"),
        risk_tier=row["risk_tier"],
        status=row["status"],
        autonomy_level=row["autonomy_level"],
        attention_mode=row["attention_mode"],
        origin=row["origin"],
        attempts=row["attempts"],
        result=json.loads(row["result"]) if row["result"] else None,
        decided_by=row["decided_by"],
        decision=row["decision"],
        pushed=row["pushed"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        mediation_enqueue_id=row["mediation_enqueue_id"],
        mediation_enqueue_revision=row["mediation_enqueue_revision"],
        mediation_scope=row["mediation_scope"],
        mediation_policy_revision=row["mediation_policy_revision"],
        mediation_receipt=receipt,
        mediation_task_sha256=row["mediation_task_sha256"],
        mediation_execution_id=row["mediation_execution_id"],
        kernel_intake_id=row["kernel_intake_id"],
        kernel_intake_evidence=intake_evidence,
        human_decision=human_decision,
        approval_deadline_at=row["approval_deadline_at"],
        expired_at=row["expired_at"],
    )


def _intake_evidence_columns(
    evidence: KernelIntakeEvidence | Mapping[str, object] | None,
) -> tuple[str | None, str | None]:
    if evidence is None:
        return None, None
    sealed = evidence if isinstance(evidence, KernelIntakeEvidence) else KernelIntakeEvidence.from_dict(evidence)
    return sealed.intake_id, json.dumps(
        sealed.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
