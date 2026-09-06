"""first_action.py — how long from install to the first action the owner accepted.

NERVA_VISION S8 and GAP-0 both come down to one number: **time to first governed
action**. It is the adoption metric, and it is the one most easily flattered, so
each definition below is chosen against a specific way of flattering it.

* **The clock starts at install, not at first launch.** Someone who installed on
  Monday and opened it on Friday took five days. Starting at launch would report
  ninety seconds and describe nothing about the product's actual friction.
* **"First governed action" means one the owner ACCEPTED**, not one Nerva
  proposed. A product that proposes quickly and gets rejected has activated
  nobody; counting proposals would reward volume over usefulness.
* **A machine decision does not count.** An action auto-approved by policy is not
  the owner choosing to trust the product with something. The same
  ``MACHINE_DECIDERS`` rule as the permission ledger and the goal contract, spelled
  the same way on purpose.
* **The first is the first.** Activation is recorded once and then immutable; a
  later, faster action does not improve the number. Re-installing produces a new
  install id and therefore a new, honest clock.
* **Never-activated is reported as never-activated**, with how long it has been —
  not as a missing field, and never as zero. "Nobody has activated yet, and it has
  been three days" is the finding; a blank is the same fact with the urgency
  removed.

Nothing here is a funnel: the wizard's own steps live in the onboarding surface.
This records one moment and refuses to embellish it.

Persistence: a small JSON file at ``data_path('activation.json')`` — one record,
written once, never rewritten. It survives restarts because the number it holds
would otherwise reset every time the process did, which would make it useless
exactly where it matters most.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.activation")

SCHEMA = "nerva.activation.v1"
_DEFAULT_FILE = "activation.json"

# Same rule, same words, as permission_ledger and goal_contract: an action decided
# by one of these had no human behind it.
MACHINE_DECIDERS = frozenset({"policy", "system", "kernel", "auto", "worker", "scheduler", ""})
HUMAN_DECISIONS = frozenset({"accept", "approve", "edit"})

# The buckets the roadmap talks in. Reported alongside the raw seconds so a
# conversation about "under ten minutes" does not need a calculator, and so the
# raw number is always still there for anyone who wants it.
BANDS = (
    (600.0, "under_10_minutes"),
    (3_600.0, "under_an_hour"),
    (86_400.0, "under_a_day"),
    (604_800.0, "under_a_week"),
)


def _epoch(value: Any, fallback: float) -> float:
    """A timestamp from a record, tolerating a legitimate 0.0.

    Deliberately not ``float(value or fallback)``: epoch 0 is a real instant, and
    an ``or`` there silently discards it — which reads as "no install recorded"
    for any clock that genuinely started at zero, and makes every elapsed time
    computed from it wrong.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return float(fallback)


def _band(seconds: float) -> str:
    for limit, name in BANDS:
        if seconds < limit:
            return name
    return "over_a_week"


def store_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else data_path(_DEFAULT_FILE)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(stored, Mapping) or stored.get("schema") != SCHEMA:
        return None
    return dict(stored)


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def mark_installed(
    path: str | Path | None = None, *, now: float | None = None
) -> dict[str, Any]:
    """Start the clock. Idempotent — a second call never restarts it.

    Called from the bootstrap and, defensively, at first boot: an install that
    somehow reached first launch without a start time gets one now, which reports
    a *shorter* elapsed time than the truth. That direction is the honest one to
    fail in — it never invents friction that did not happen — and the record says
    ``inferred_at_boot`` so a reader knows the start was reconstructed.
    """
    target = store_path(path)
    existing = _read(target)
    if existing is not None:
        return existing
    moment = time.time() if now is None else float(now)
    record = {
        "schema": SCHEMA,
        "install_id": uuid.uuid4().hex[:16],
        "installed_at": moment,
        "inferred_at_boot": False,
        "activated": None,
    }
    _write(target, record)
    logger.info("activation clock started: install %s", record["install_id"])
    return record


def infer_install_at_boot(
    path: str | Path | None = None, *, now: float | None = None
) -> dict[str, Any]:
    """Start the clock at boot when the bootstrap did not. Marks it as inferred."""
    target = store_path(path)
    existing = _read(target)
    if existing is not None:
        return existing
    record = mark_installed(target, now=now)
    record["inferred_at_boot"] = True
    _write(target, record)
    return record


def record_first_action(
    task: Any,
    path: str | Path | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Record the first owner-accepted governed action, once.

    Returns the activation record when this call is the one that recorded it, and
    ``None`` otherwise — including when the task does not qualify. Callers can wire
    this into every decision without checking anything first: the rules live here,
    so there is one place to read them and no chance of two callers disagreeing.
    """
    decided_by = str(getattr(task, "decided_by", "") or "").strip().lower()
    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decided_by in MACHINE_DECIDERS or decision not in HUMAN_DECISIONS:
        # Auto-approved by policy is not the owner choosing to trust the product.
        return None

    target = store_path(path)
    record = _read(target)
    if record is None:
        # No install record at all. Rather than dropping the activation, start the
        # clock now and mark it inferred — the elapsed time will read as ~0, which
        # is visibly wrong in the honest direction and is flagged as inferred.
        record = infer_install_at_boot(target, now=now)
    if record.get("activated"):
        return None  # the first is the first

    moment = time.time() if now is None else float(now)
    elapsed = max(0.0, moment - _epoch(record.get("installed_at"), moment))
    record["activated"] = {
        "at": moment,
        "seconds": elapsed,
        "band": _band(elapsed),
        "task_id": getattr(task, "id", None),
        "task_kind": str(getattr(task, "kind", "") or "")[:64],
        "decided_by": decided_by[:64],
        "decision": decision,
    }
    _write(target, record)
    logger.info(
        "activation: first governed action accepted after %.1fs (%s)",
        elapsed, record["activated"]["band"],
    )
    return record


def activation_state(
    path: str | Path | None = None, *, now: float | None = None
) -> dict[str, Any]:
    """The metric, in the shape the north-star and the HUD read.

    Never-activated is a *reported state* carrying how long it has been, not an
    absent field: "nobody has activated, and it has been three days" is the
    finding, and a blank is that same fact with the urgency taken out.
    """
    moment = time.time() if now is None else float(now)
    record = _read(store_path(path))
    if record is None:
        return {
            "schema": SCHEMA,
            "installed": False,
            "activated": False,
            # Not zero seconds: nothing has been measured, which is different from
            # having measured an instant activation.
            "seconds": None,
            "band": None,
            "reason": "no install record — the activation clock has not started",
        }
    installed_at = _epoch(record.get("installed_at"), moment)
    activated = record.get("activated")
    if not activated:
        waiting = max(0.0, moment - installed_at)
        return {
            "schema": SCHEMA,
            "installed": True,
            "install_id": record.get("install_id"),
            "installed_at": installed_at,
            "inferred_start": bool(record.get("inferred_at_boot")),
            "activated": False,
            "seconds": None,
            "band": None,
            "waiting_seconds": waiting,
            "waiting_band": _band(waiting),
            "reason": "no owner-accepted governed action yet",
        }
    return {
        "schema": SCHEMA,
        "installed": True,
        "install_id": record.get("install_id"),
        "installed_at": installed_at,
        "inferred_start": bool(record.get("inferred_at_boot")),
        "activated": True,
        "seconds": _epoch(activated.get("seconds"), 0.0),
        "band": activated.get("band"),
        "activated_at": activated.get("at"),
        "task_kind": activated.get("task_kind"),
        "decision": activation_decision(activated),
    }


def activation_decision(activated: Mapping[str, Any]) -> str:
    """"accepted by owner" — who and how, in one readable phrase."""
    who = str(activated.get("decided_by") or "").strip() or "someone"
    how = str(activated.get("decision") or "").strip() or "decided"
    return f"{how} by {who}"


__all__ = [
    "BANDS",
    "HUMAN_DECISIONS",
    "MACHINE_DECIDERS",
    "SCHEMA",
    "activation_decision",
    "activation_state",
    "infer_install_at_boot",
    "mark_installed",
    "record_first_action",
    "store_path",
]
