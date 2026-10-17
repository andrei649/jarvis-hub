"""The approval effect registry (spec §5 "effects_api.py").

An approval is a request to perform one consequential *effect* — email a report,
publish a document company-wide — after a named person agrees. The approvals engine
(S4) knows nothing about those domains: each domain module registers an
:class:`EffectSpec` at import time with a ``validate`` (runs at request time and again
before execution, raising :class:`WorkspaceError`) and an async ``execute`` (opens its
own connections, returns a JSON-able result). ``decider_rule`` says who may decide:
``"department"`` — an approver of that department or an admin; ``"admin"`` — admins only.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agents.core.workspace import notifications
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.identity import WorkspaceUser

logger = logging.getLogger("nerva.workspace.effects_api")

DECIDER_RULES = ("department", "admin")


@dataclass
class ValidatedRequest:
    """What ``validate`` returns: the scope, a human summary and the clean payload."""

    department_id: int | None
    summary: str
    payload: dict


@dataclass
class EffectSpec:
    """One registered approval kind."""

    kind: str
    validate: Callable[[sqlite3.Connection, WorkspaceUser, dict], ValidatedRequest]
    execute: Callable[[dict, WorkspaceUser, WorkspaceUser], Awaitable[dict]]
    decider_rule: str = "department"


_REGISTRY: dict[str, EffectSpec] = {}


def register_effect(spec: EffectSpec) -> None:
    """Register (or replace) the spec for ``spec.kind``."""
    if spec.decider_rule not in DECIDER_RULES:
        raise ValueError(f"decider_rule must be one of {DECIDER_RULES}, got {spec.decider_rule!r}")
    if not spec.kind or not isinstance(spec.kind, str):
        raise ValueError("an effect needs a non-empty kind")
    if spec.kind in _REGISTRY:
        logger.info("approval effect %s re-registered", spec.kind)
    _REGISTRY[spec.kind] = spec


def get_effect(kind: str) -> EffectSpec:
    """The spec for *kind*, or ``400 unknown_kind``."""
    spec = _REGISTRY.get(kind)
    if spec is None:
        raise WorkspaceError("unknown_kind", "this kind of approval does not exist", 400,
                             kind=kind)
    return spec


def kinds() -> list[str]:
    """Registered kinds, sorted."""
    return sorted(_REGISTRY)


def eligible_decider_ids(conn: sqlite3.Connection, spec: EffectSpec, department_id: int | None,
                         *, exclude: int | None = None) -> list[int]:
    """Who may decide an approval of *spec* scoped to *department_id* (minus *exclude*).

    A ``department`` rule without a department (company-wide scope) falls back to the
    admins, the only people allowed to act company-wide.
    """
    if spec.decider_rule == "admin" or department_id is None:
        return notifications.admins(conn, exclude=exclude)
    return notifications.department_approvers(conn, department_id, exclude=exclude)


def can_decide(user: WorkspaceUser, spec: EffectSpec, department_id: int | None,
               requester_id: int) -> bool:
    """Whether *user* may decide such an approval (never their own request)."""
    if user.id == requester_id or user.status != "active":
        return False
    if spec.decider_rule == "admin" or department_id is None:
        return user.is_admin
    return user.can_approve_in(department_id)
