"""Best-effort, non-authoritative observations of a guardian's native request."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from ..extensions.events import EXTENSION_EVENTS, prepare_smart_event_fields
from .smart_approvals import SmartApprovalResult, terminal_args

logger = logging.getLogger("jarvis.autonomy.smart_observers")


@dataclass(slots=True)
class SmartObservation:
    """Mutable across wait_for's child task; no unredacted operation text retained."""

    task_id: int
    snapshot_sha256: str
    identity: str
    request_id: str
    requested: bool = False
    dispatched: bool = False
    decided: bool = False
    excerpts: dict[str, str] | None = None


_DISABLED = object()
_CURRENT: ContextVar[SmartObservation | object | None] = ContextVar("smart_observation", default=None)


def _identity(snapshot: Mapping) -> str | None:
    """Bind one observation to the immutable copied queued request, not model text."""
    try:
        if terminal_args(snapshot) is None:
            return None
        data = {key: snapshot[key] for key in (
            "id", "task_id", "snapshot_sha256", "tool", "agent", "summary", "args",
        )}
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
    except (KeyError, TypeError, ValueError, UnicodeError):
        return None


def _new(snapshot: Mapping) -> SmartObservation | None:
    identity = _identity(snapshot)
    if identity is None:
        return None
    task_id = snapshot.get("task_id")
    digest = snapshot.get("snapshot_sha256")
    if type(task_id) is not int or type(digest) is not str:
        return None
    return SmartObservation(task_id, digest, identity, uuid.uuid4().hex)


@contextmanager
def judgement_scope(snapshot: Mapping):
    """Create a fresh mutable holder shared with dispatch's wait_for child task."""
    try:
        observation = _new(snapshot)
    except Exception:  # noqa: BLE001 — entropy or preparation failure skips observation
        logger.debug("smart observation identity unavailable")
        observation = None
    token = _CURRENT.set(observation if observation is not None else _DISABLED)
    try:
        yield observation
    finally:
        _CURRENT.reset(token)


@contextmanager
def score_scope(snapshot: Mapping):
    """Direct score gets a temporary holder; runner score reuses its holder."""
    existing = _CURRENT.get()
    if existing is _DISABLED:
        yield None  # A failed parent preparation disables its child observation too.
    elif existing is not None:
        yield existing
    else:
        with judgement_scope(snapshot) as observation:
            yield observation


def requested(snapshot: Mapping) -> None:
    """Observe one validated physical send attempt without affecting the request."""
    try:
        observation = _CURRENT.get()
        if type(observation) is not SmartObservation:
            return
        if observation.requested or _identity(snapshot) != observation.identity:
            return
        observation.requested = True  # Native retries cannot emit a second request.
        args = terminal_args(snapshot)
        if args is None or type(snapshot.get("summary")) is not str:
            return
        raw = {"request_id": observation.request_id, "surface": "smart",
               "command": args["command"], "description": snapshot["summary"]}
        clean = prepare_smart_event_fields("approval.smart.requested", raw)
        # Reuse only an already-redacted bounded excerpt for the decided event.
        observation.excerpts = {key: clean[key][:200] for key in ("command", "description")}
        report = EXTENSION_EVENTS.emit("approval.smart.requested", **clean)
        observation.dispatched = report is not None
    except Exception:  # noqa: BLE001 — observers never decide whether a request proceeds
        logger.debug("smart request observation skipped")


def decided_after_store(observation: SmartObservation | None, owner, snapshot: Mapping,
                        annotation, stored) -> None:
    """Pair a committed task CAS with its own observed send attempt."""
    try:
        from .task_approval_judge import TaskApprovalJudge

        if (observation is None or not observation.dispatched or observation.decided
                or type(owner) is not TaskApprovalJudge
                or type(annotation) is not SmartApprovalResult
                or annotation.verdict not in {"approve", "deny"}
                or type(stored) is not dict or stored.get("advisory") is not False
                or stored.get("decision") != annotation.verdict
                or stored != annotation.annotation()
                or snapshot.get("task_id") != observation.task_id
                or snapshot.get("snapshot_sha256") != observation.snapshot_sha256
                or _identity(snapshot) != observation.identity
                or observation.excerpts is None):
            return
        observation.decided = True
        EXTENSION_EVENTS.emit(
            "approval.smart.decided", request_id=observation.request_id, surface="smart",
            **observation.excerpts,
            choice="smart_approve" if annotation.verdict == "approve" else "smart_deny",
            decided_by="aux_llm",
        )
    except Exception:  # noqa: BLE001 — neither CAS nor promotion depends on observers
        logger.debug("smart decision observation skipped")
