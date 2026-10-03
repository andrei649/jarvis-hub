"""Private signed enqueue provenance. A source is never an execution grant."""
from __future__ import annotations

import hashlib
import json

from .approval_grouping import current_model_producer, model_consent_semantics
from .approval_judge import action_is_tainted
from .mediation import MAX_CANONICAL_BYTES, canonical_json

_PURPOSE = 'nerva.pending-consent-source'
_FIELDS = frozenset({'purpose', 'version', 'namespace', 'task_id', 'task_birth',
                     'snapshot', 'deadline', 'association', 'producer', 'policy'})
_FIELDS_V2 = _FIELDS | {'descriptor'}


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS task_consent_sources (
        task_id INTEGER PRIMARY KEY, source TEXT NOT NULL, signature TEXT NOT NULL,
        group_key TEXT
    )''')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(task_consent_sources)')}
    if 'group_key' not in columns:
        conn.execute('ALTER TABLE task_consent_sources ADD COLUMN group_key TEXT')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_task_consent_group_key '
                 'ON task_consent_sources(group_key, task_id)')


def group_key(queue, task, source):
    """Index only equal signed producer, policy, descriptor and task semantics."""
    if type(source) is not dict or source.get('version') != 2:
        return None
    try:
        encoded = canonical_json({
            'purpose': 'h487-pending-consent-followers', 'version': 1,
            'namespace': queue._group_namespace,
            'producer': source['producer'], 'policy': source['policy'],
            'descriptor': source['descriptor'],
            'task': {name: getattr(task, name) for name in (
                'agent', 'kind', 'title', 'payload', 'risk_tier',
                'autonomy_level', 'attention_mode', 'origin',
                'approval_deadline_at',
            )},
        })
        return hashlib.sha256(encoded).hexdigest()
    except Exception:
        return None


def _pending(queue, task_id):
    # Late import avoids a queue/module initialization cycle. Caller owns lock.
    from .queue import _row_to_task, approval_is_pending

    row = queue._conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    task = _row_to_task(row) if row else None
    if (task is None or task.status != 'blocked' or task.decided_by != 'policy'
            or task.decision != 'needs-approval' or task.human_decision is not None
            or not approval_is_pending(task)
            or action_is_tainted({'args': task.payload, 'origin': task.origin})):
        return None
    snapshot = queue._approval_snapshot_digest_locked(task)
    if (snapshot is None
            or queue._smart_terminal_denial_locked(task_id, snapshot) is not None):
        return None
    return task, snapshot


def _association(queue, task):
    row = queue._conn.execute('''SELECT t.origin_id,t.tool,t.task_birth,t.ready,
        t.intent_sha256,o.session_id,o.session_instance,o.principal_key
        FROM chat_approval_tasks t JOIN chat_approval_origins o ON o.origin_id=t.origin_id
        WHERE t.task_id=? AND t.ready=1 AND t.task_birth=?''',
        (task.id, task.created_at)).fetchone()
    if row is None or row['intent_sha256'] != queue._chat_intent_locked(task):
        return None
    return dict(row)


def capture_locked(queue, task_id, *, policy):
    """Capture only during the exact live registrar/owner-turn enqueue scope.

    Own the transaction or refuse; never commit or roll back a caller's work.
    All failures leave the already persisted ordinary approval untouched.
    """
    conn = queue._conn
    if conn is None or conn.in_transaction:
        return False
    started = False
    try:
        conn.execute('BEGIN IMMEDIATE')
        started = True
        pending = _pending(queue, task_id)
        if pending is None or type(policy) is not dict:
            return False
        task, snapshot = pending
        context = current_model_producer()
        producer = model_consent_semantics(context, task)
        association = _association(queue, task)
        if (producer is None or association is None
                or association['origin_id'] != context.producer.turn.turn_id
                or association['tool'] != producer['request']['tool']
                or association['principal_key'] != producer['principal']
                or association['session_id'] != producer['session_id']
                or association['session_instance'] != producer['session_instance']):
            return False
        source = {'purpose': _PURPOSE, 'version': 1, 'namespace': queue._group_namespace,
                  'task_id': task.id, 'task_birth': task.created_at, 'snapshot': snapshot,
                  'deadline': task.approval_deadline_at, 'association': association,
                  'producer': producer, 'policy': policy}
        descriptor = queue._resolve_consent_descriptor(task, source)
        if descriptor is not None and queue._consent_ledger is not None:
            source['version'] = 2
            source['descriptor'] = queue._consent_descriptor_data(descriptor)
        encoded = canonical_json(source)
        signature = queue._mediation_signer.sign(encoded)
        if signature is None:
            return False
        fingerprint = group_key(queue, task, source)
        if source['version'] == 2 and fingerprint is None:
            return False
        # Never repair/re-sign altered provenance or replace its original origin.
        changed = conn.execute('''INSERT OR IGNORE INTO task_consent_sources
            (task_id,source,signature,group_key) VALUES(?,?,?,?)''',
            (task.id, encoded.decode('utf-8'), signature, fingerprint))
        conn.commit()
        started = False
        return changed.rowcount == 1
    except Exception:
        return False
    finally:
        if started:
            conn.rollback()


def current_locked(queue, task_id, *, pending_only=False):
    """Validate signed origin and immutable intent in the caller's transaction.

    Consent consumers use this after a task is approved/running. The old read
    wrapper below remains pending-only and never conveys execution authority.
    """
    conn = queue._conn
    if conn is None or not conn.in_transaction:
        return None
    try:
        row = conn.execute('SELECT * FROM task_consent_sources WHERE task_id=?',
                           (task_id,)).fetchone()
        if row is None or type(row['source']) is not str:
            return None
        encoded = row['source'].encode('utf-8')
        if not encoded or len(encoded) > MAX_CANONICAL_BYTES:
            return None
        source = json.loads(encoded)
        version = source.get('version') if type(source) is dict else None
        if (type(source) is not dict or source.keys() != (_FIELDS_V2 if version == 2 else _FIELDS)
                or canonical_json(source) != encoded
                or not queue._mediation_signer.verify(encoded, row['signature'])
                or source['purpose'] != _PURPOSE or type(source['version']) is not int
                or source['version'] not in {1, 2} or source['namespace'] != queue._group_namespace
                or type(source['task_id']) is not int or source['task_id'] != task_id):
            return None
        from .queue import _row_to_task
        task_row = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        task = _row_to_task(task_row) if task_row else None
        if task is None or (pending_only and _pending(queue, task_id) is None):
            return None
        if (source['task_birth'] != task.created_at
                or source['deadline'] != task.approval_deadline_at
                or source['association'] != _association(queue, task)
                or (pending_only and source['snapshot'] != queue._approval_snapshot_digest_locked(task))):
            return None
        if version == 2:
            descriptor = queue._resolve_consent_descriptor(task, source)
            if descriptor is None or queue._consent_descriptor_data(descriptor) != source['descriptor']:
                return None
            fingerprint = group_key(queue, task, source)
            if fingerprint is None or (row['group_key'] is not None and row['group_key'] != fingerprint):
                return None
        elif row['group_key'] is not None:
            return None
        return source
    except Exception:
        return None


def read_locked(queue, task_id):
    """Legacy pending-only source read; no permission or status change."""
    conn = queue._conn
    if conn is None or conn.in_transaction:
        return None
    try:
        conn.execute('BEGIN')
        return current_locked(queue, task_id, pending_only=True)
    finally:
        conn.rollback()
