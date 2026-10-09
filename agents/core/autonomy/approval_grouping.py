"""Private equality rules for verified HTTP/model registrations, never consent."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .approval_judge import action_is_tainted


@dataclass(frozen=True)
class OwnerRegistrationContext:
    """Internal marker produced after the existing HTTP owner identity check.

    There is deliberately no caller-supplied principal, session or grant field.
    Direct queue/browser requests never receive this marker automatically.
    """


_AUTHORITY_KEYS = frozenset({
    'principal', 'principal_id', 'session', 'session_id', 'session_key',
    'policy', 'policy_revision', 'scope', 'binding', 'approval_binding',
    'authority', 'context', 'task_id', 'grouping_context', 'coalescing_context', '_grouping',
})


def _valid_json(value, depth=0) -> bool:
    if depth > 20:
        return False
    if isinstance(value, dict):
        return all(isinstance(key, str) and key not in _AUTHORITY_KEYS
                   and _valid_json(child, depth + 1) for key, child in value.items())
    if isinstance(value, list):
        return all(_valid_json(child, depth + 1) for child in value)
    return value is None or type(value) in {str, int, float, bool}


def registration_fingerprint(action: Mapping, context: OwnerRegistrationContext | None,
                             namespace: str) -> str | None:
    """Fail closed on unknown authority or noncanonical request semantics.

    The full request participates, including fields the legacy public item does
    not retain. Taint is checked independently of whether a judge is configured.
    This digest and queue namespace are private and never become public tokens.
    """
    if type(context) is not OwnerRegistrationContext or not isinstance(action, dict):
        return None
    try:
        if (not _valid_json(action) or not isinstance(action.get('tool'), str)
                or not action['tool'].strip() or not isinstance(action.get('args', {}), dict)
                or not isinstance(action.get('agent', ''), str)
                or not isinstance(action.get('summary', ''), str)
                or type(action.get('risk_tier', 2)) is not int):
            return None
        encoded = json.dumps({
            'request': action, 'tainted': action_is_tainted(action),
            'context': {'principal': 'owner', 'surface': 'http_actions_registration',
                        'binding': 'registration_only', 'namespace': namespace},
        }, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(encoded) > 65_536:
            return None
        return hashlib.sha256(encoded).hexdigest()
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return None


def member_snapshot(item: Mapping) -> str | None:
    """Bind private group membership to immutable stored card bytes, excluding opinions."""
    try:
        immutable = {key: item.get(key) for key in (
            'id', 'tool', 'args', 'agent', 'task_id', 'summary', 'preview', 'created_at', 'tainted',
        )}
        encoded = json.dumps(immutable, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        return hashlib.sha256(encoded).hexdigest()
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return None


# This scope is minted only by the registered generic ToolRPC enqueue branch.
# It is observational provenance, never an owner registration or a grant.
@dataclass(frozen=True)
class _ModelProducer:
    producer: object = field(repr=False)
    actor: str
    tool: str
    args_json: str = field(repr=False)
    epoch: str = field(repr=False)
    registration_is_live: object = field(repr=False)
    task: object = field(repr=False)
    thread: int
    lifetime: list = field(repr=False)
    registration_key: str | None = field(default=None, repr=False)
    registration_key_is_live: object = field(default=None, repr=False)


_MODEL_PRODUCER = ContextVar('model_approval_grouping', default=None)


def _calling_task():
    import asyncio
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


@contextmanager
def model_request_scope(*, actor, tool, args, epoch, registration_is_live,
                        registration_key=None, registration_key_is_live=None):
    """Private synchronous producer lifetime; descendants cannot borrow it."""
    import threading

    from agents.core.approval_outcomes import current_tool_approval
    producer = current_tool_approval()
    context = None
    try:
        if (producer is not None and producer.tool == tool and isinstance(actor, str)
                and 0 < len(actor) <= 128 and isinstance(args, dict) and _valid_json(args)
                and isinstance(epoch, str) and len(epoch) == 32
                and callable(registration_is_live) and registration_is_live() is True):
            encoded = json.dumps(args, sort_keys=True, ensure_ascii=False,
                                 separators=(',', ':'), allow_nan=False)
            if len(encoded.encode('utf-8')) <= 65_536:
                key = None
                verifier = None
                if (isinstance(registration_key, str) and len(registration_key) == 64
                        and all(char in '0123456789abcdef' for char in registration_key)
                        and callable(registration_key_is_live)):
                    try:
                        if registration_key_is_live(registration_key) is True:
                            key = registration_key
                            verifier = registration_key_is_live
                    except Exception:
                        key = verifier = None  # Consent failure preserves legacy grouping.
                context = _ModelProducer(producer, actor, tool, encoded, epoch,
                    registration_is_live, _calling_task(), threading.get_ident(), [True],
                    key, verifier)
    except Exception:
        context = None  # Failed provenance leaves an independent approval request.
    token = _MODEL_PRODUCER.set(context)
    try:
        yield
    finally:
        if context is not None:
            context.lifetime[0] = False
        _MODEL_PRODUCER.reset(token)


def current_model_producer():
    import threading

    from agents.core.approval_outcomes import current_tool_approval
    context = _MODEL_PRODUCER.get()
    try:
        return context if (type(context) is _ModelProducer and context.lifetime[0]
            and context.producer is current_tool_approval() and context.task is _calling_task()
            and context.thread == threading.get_ident()
            and context.registration_is_live() is True) else None
    except Exception:
        return None


def model_group_semantics(context, task):
    """Verify finalized stored intent against the exact registered producer."""
    if context is None or context is not current_model_producer():
        return None
    try:
        payload = task.payload
        if (task.agent != context.actor or task.kind != f'toolrpc.{context.tool}'
                or not isinstance(payload, dict) or payload.get('tool') != context.tool
                or payload.get('target') != context.tool or not _valid_json(payload)
                or not isinstance(payload.get('args'), dict)
                or json.dumps(payload['args'], sort_keys=True, ensure_ascii=False,
                    separators=(',', ':'), allow_nan=False) != context.args_json):
            return None
        turn = context.producer.turn
        return {'request': {'tool': context.tool, 'args': json.loads(context.args_json)},
                'principal': turn.principal_key, 'surface': 'generic_model_toolrpc',
                'session_id': turn.session_id, 'session_instance': turn.session_instance,
                'registration_epoch': context.epoch}
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None


def model_consent_semantics(context, task):
    """Export registrar provenance only for the exact verified live producer."""
    semantics = model_group_semantics(context, task)
    if semantics is None or not isinstance(context.registration_key, str):
        return None
    try:
        # Call arguments are model-controlled. A claimed provenance field cannot
        # ride alongside the registrar-owned key, even when the rest matches.
        def claimed(value, depth=0):
            if depth > 20:
                return True
            if isinstance(value, dict):
                return any(key in {'registration_key', '_consent_registration_key',
                                   'consent_revision'} or claimed(child, depth + 1)
                           for key, child in value.items())
            if isinstance(value, list):
                return any(claimed(child, depth + 1) for child in value)
            return False

        if claimed(task.payload):
            return None
        if (not callable(context.registration_key_is_live)
                or context.registration_key_is_live(context.registration_key) is not True):
            return None
    except Exception:
        return None
    return {**semantics, 'registration_key': context.registration_key}
