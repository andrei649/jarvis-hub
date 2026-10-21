"""irreversible.py — the approval queue's irreversible tier for owner writes (H262).

Critic note 28 asked for one helper every row can reuse when a write must never happen
on a single click because what follows it cannot be undone (retention deleting owner
data for good, later a session purge or a memory forget):

* :func:`register` — a kind and the async function that applies an approved task of it.
  The kinds that ship are declared in :data:`BUILTIN_KINDS` by module path and imported
  only when used, so their modules (``retention``) stay free of the autonomy package.
* :func:`enqueue` — the owner's request as a tier-3 task, ``autonomy_level="ask"``, so it
  lands BLOCKED in the decision inbox with its ``preview`` on the card. It never falls
  back to doing the write: no autonomy worker, or a queue that refuses the task, is a
  ``{"refused": reason}`` the caller reports (and writes nothing).
* :func:`execute` — the executor handler. It applies a task only when a *human* decided
  accept or edit on it (the ``permission_ledger.apply_grant`` rule): a machine decider
  such as ``policy`` is refused, and so is any other decision.

``settings.voice_command`` has an exact kernel registration and can enter the
``enforce`` queue with signed evidence; its tier-three human floor remains.
``settings.retention`` is still unregistered and strict intake refuses it.
``hold`` refuses classified intake too. No settings wildcard is registered.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

logger = logging.getLogger("jarvis.autonomy.irreversible")

#: ``RiskTier.IRREVERSIBLE_OR_MONEY``: the policy always asks.
RISK_TIER = 3
#: Deciders that are not a person (the ``permission_ledger`` / ``goal_contract`` set).
MACHINE_DECIDERS = frozenset({"policy", "system", "kernel", "auto", "worker", "scheduler", ""})
#: The decisions that approve a task.
HUMAN_DECISIONS = frozenset({"accept", "approve", "edit"})

Apply = Callable[[Any, Any], Awaitable[dict]]
#: The shipped kinds: kind → (module, apply function), imported on first use.
BUILTIN_KINDS: dict[str, tuple[str, str]] = {
    "settings.retention": ("agents.core.retention", "apply_approved"),   # H262
    "settings.voice_command": ("agents.core.voice.command_settings", "apply_approved"),   # H613
    "backup.restore": ("agents.core.backup", "apply_approved"),   # H010: staged, then the hub restarts
}
_APPLY: dict[str, Apply] = {}
#: Kinds some processes must leave for another one: kind → (module, function), the
#: function answering ``task`` with a reason to leave it APPROVED here, or None.
BUILTIN_HOLDS: dict[str, tuple[str, str]] = {
    "backup.restore": ("agents.core.backup", "restore_held_here"),   # H010 review r6
}


def register(kind: str, apply_fn: Apply) -> None:
    """Make ``kind`` an irreversible kind applied by ``apply_fn(task, orch)``."""
    _APPLY[kind] = apply_fn


def kinds() -> tuple[str, ...]:
    """Every kind (the executor wires each one to :func:`execute`)."""
    return tuple(sorted(set(_APPLY) | set(BUILTIN_KINDS)))


def _apply_for(kind: str) -> Apply | None:
    if kind not in _APPLY and kind in BUILTIN_KINDS:
        module, name = BUILTIN_KINDS[kind]
        _APPLY[kind] = getattr(importlib.import_module(module), name)
    return _APPLY.get(kind)


def enqueue(orch: Any, kind: str, *, title: str, payload: dict, preview: dict) -> dict:
    """Queue the owner's request for a human decision: ``{"pending": task id}``, or
    ``{"refused": reason}`` (``unknown_kind``, ``approval_queue_unavailable``,
    ``approval_queue_refused``) — never a write."""
    if kind not in kinds():
        return {"refused": "unknown_kind"}
    worker = getattr(orch, "autonomy", None) if orch is not None else None
    govern = getattr(worker, "govern_enqueue", None)
    if not callable(govern):
        return {"refused": "approval_queue_unavailable"}
    try:
        task_id = govern(
            agent="owner", kind=kind, title=title,
            payload={**payload, "risk_tier": RISK_TIER, "reversible": False, "preview": preview},
            risk_tier=RISK_TIER, autonomy_level="ask", origin="manual",
        )
    except Exception as exc:  # noqa: BLE001 — TaskQueueError (mediation), a store error: never write
        logger.warning("the approval queue refused a %s request (%s)", kind, type(exc).__name__)
        return {"refused": "approval_queue_refused"}
    return {"pending": int(task_id)}


#: How many waiting tasks of one kind :func:`pending` returns at most.
PENDING_MAX = 1000


def pending(orch: Any, kind: str) -> list[Any]:
    """The tasks of ``kind`` waiting for a human decision, oldest first; none when there is
    no queue to ask (H262 review: the settings route never queues a second identical card,
    and the state route names the waiting one). The queue is asked for that kind only
    (review round 2, N7), so other kinds waiting in any number never hide one."""
    worker = getattr(orch, "autonomy", None) if orch is not None else None
    lister = getattr(getattr(worker, "queue", None), "pending_decisions", None)
    if not callable(lister):
        return []
    try:
        try:
            found = lister(kind=kind, limit=PENDING_MAX)
        except TypeError:                     # a queue without the kind filter: every page
            found = lister(limit=10**9)
        return [task for task in found if getattr(task, "kind", None) == kind]
    except Exception:  # noqa: BLE001 — a queue that cannot answer holds nothing we can merge
        logger.warning("the approval queue could not list the waiting %s tasks", kind, exc_info=True)
        return []


def held_here(task: Any) -> str | None:
    """Why this process's worker must not claim ``task`` (it stays APPROVED for a worker
    in another process), or None. H010 review r6: an accepted ``backup.restore`` is left
    for the hub, the one process that can restart itself to apply it."""
    hold = BUILTIN_HOLDS.get(str(getattr(task, "kind", "") or ""))
    if hold is None:
        return None
    try:
        reason = getattr(importlib.import_module(hold[0]), hold[1])(task)
    except Exception:  # noqa: BLE001 — a broken probe never strands the task: the apply rechecks
        logger.warning("could not tell whether %s belongs to another process", hold[0], exc_info=True)
        return None
    return str(reason) if reason else None


async def execute(task: Any, *, orch: Any) -> dict:
    """Apply an approved task of a registered kind — only on a human's accept or edit."""
    kind = str(getattr(task, "kind", "") or "")
    apply = _apply_for(kind)
    if apply is None:
        return {"status": "refused", "reason": "unknown_kind"}
    decided_by = str(getattr(task, "decided_by", "") or "").strip().lower()
    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decided_by in MACHINE_DECIDERS:
        return {"status": "refused", "reason": "human_decision_required"}
    if decision not in HUMAN_DECISIONS:
        return {"status": "refused", "reason": "decision_not_approval"}
    if not isinstance(getattr(task, "payload", None), Mapping):
        return {"status": "refused", "reason": "payload_required"}
    try:
        return await apply(task, orch)
    except Exception:
        logger.exception("applying the approved %s task failed", kind)
        return {"status": "failed", "reason": "apply_failed"}


__all__ = ["HUMAN_DECISIONS", "MACHINE_DECIDERS", "RISK_TIER", "enqueue", "execute", "held_here", "kinds", "pending", "register"]
