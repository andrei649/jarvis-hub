"""Risk-ordered implementation selection for the Nerva computer operator.

The router deliberately selects but never executes. Callers must pass the returned
implementation id to its already-governed API, terminal, structured UI, or visual
surface. This preserves the Action Kernel and approval boundaries of those systems.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

READY_STATES = frozenset({"wired", "verified", "ga"})


class OperatorRoute(StrEnum):
    API = "api"
    CLI = "cli"
    STRUCTURED_UI = "structured_ui"
    VISUAL = "visual"


_ROUTE_RANK = {
    OperatorRoute.API: 0,
    OperatorRoute.CLI: 1,
    OperatorRoute.STRUCTURED_UI: 2,
    OperatorRoute.VISUAL: 3,
}


@dataclass(frozen=True)
class OperatorImplementation:
    """Trusted registration metadata for one governed implementation path."""

    id: str
    route: OperatorRoute
    capability_id: str
    matcher: Callable[[str, dict], bool]
    availability: Callable[[], bool] = lambda: True
    priority: int = 100

    def __post_init__(self) -> None:
        if not str(self.id).strip():
            raise ValueError("implementation id is required")
        if not isinstance(self.route, OperatorRoute):
            raise ValueError("route must be an OperatorRoute")
        if not str(self.capability_id).strip():
            raise ValueError("capability_id is required")
        if not callable(self.matcher) or not callable(self.availability):
            raise ValueError("matcher and availability must be callable")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("priority must be a non-negative integer")


@dataclass(frozen=True)
class OperatorDecision:
    selected_id: str | None
    route: OperatorRoute | None
    capability_id: str | None
    risk: str | None
    reason: str
    considered: list[dict]


class ActionHierarchyRouter:
    """Choose API → CLI → structured UI → visual, with readiness and audit proof."""

    def __init__(
        self,
        registry_provider: Callable[[], Iterable[Any]],
        *,
        audit_sink: Callable[[dict], None] | None = None,
        audit_limit: int = 1_000,
        max_goal_chars: int = 4_000,
    ) -> None:
        if not callable(registry_provider):
            raise ValueError("registry_provider must be callable")
        if type(audit_limit) is not int or audit_limit <= 0:
            raise ValueError("audit_limit must be a positive integer")
        if type(max_goal_chars) is not int or max_goal_chars <= 0:
            raise ValueError("max_goal_chars must be a positive integer")
        self._registry_provider = registry_provider
        self._audit_sink = audit_sink
        self._audit_limit = audit_limit
        self._max_goal_chars = max_goal_chars
        self._implementations: dict[str, OperatorImplementation] = {}
        self._lock = threading.RLock()
        self.audit_log: list[dict] = []
        self._audit_sequence = 0

    def register(self, implementation: OperatorImplementation) -> None:
        if not isinstance(implementation, OperatorImplementation):
            raise ValueError("implementation must be OperatorImplementation")
        with self._lock:
            if implementation.id in self._implementations:
                raise ValueError(f"duplicate implementation id: {implementation.id}")
            self._implementations[implementation.id] = implementation

    def plan(
        self,
        goal: str,
        *,
        params: dict | None = None,
        allow_visual_fallback: bool = False,
    ) -> OperatorDecision:
        normalized_goal = str(goal or "").strip()
        if not normalized_goal:
            raise ValueError("goal is required")
        if len(normalized_goal) > self._max_goal_chars:
            raise ValueError(f"goal exceeds {self._max_goal_chars} characters")
        parameters = dict(params or {})

        with self._lock:
            implementations = sorted(
                self._implementations.values(),
                key=lambda item: (_ROUTE_RANK[item.route], item.priority, item.id),
            )

        try:
            records = self._registry_records()
        except Exception:
            decision = OperatorDecision(
                selected_id=None,
                route=None,
                capability_id=None,
                risk=None,
                reason="capability_registry_unavailable",
                considered=[],
            )
            self._audit(normalized_goal, allow_visual_fallback, decision)
            return decision

        considered: list[dict] = []
        eligible: list[tuple[OperatorImplementation, str]] = []
        for implementation in implementations:
            entry = {
                "id": implementation.id,
                "route": implementation.route.value,
                "capability_id": implementation.capability_id,
                "reason": "",
            }
            if (
                implementation.route is OperatorRoute.VISUAL
                and not allow_visual_fallback
            ):
                entry["reason"] = "visual_fallback_not_allowed"
                considered.append(entry)
                continue

            record = records.get(implementation.capability_id)
            if record is None:
                entry["reason"] = "capability_missing"
                considered.append(entry)
                continue
            state = str(self._field(record, "state", "seam")).lower()
            if state not in READY_STATES:
                entry["reason"] = f"capability_not_ready:{state}"
                considered.append(entry)
                continue
            try:
                if not bool(implementation.availability()):
                    entry["reason"] = "unavailable"
                    considered.append(entry)
                    continue
            except Exception:
                entry["reason"] = "availability_failed"
                considered.append(entry)
                continue
            try:
                if not bool(implementation.matcher(normalized_goal, parameters)):
                    entry["reason"] = "goal_not_matched"
                    considered.append(entry)
                    continue
            except Exception:
                entry["reason"] = "matcher_failed"
                considered.append(entry)
                continue

            risk = str(self._field(record, "risk", "sensitive"))
            eligible.append((implementation, risk))
            considered.append(entry)

        selected = eligible[0] if eligible else None
        selected_id = selected[0].id if selected else None
        for entry in considered:
            if entry["id"] == selected_id:
                entry["reason"] = "selected"
            elif not entry["reason"]:
                entry["reason"] = "higher_risk_or_priority_alternative"

        decision = OperatorDecision(
            selected_id=selected_id,
            route=selected[0].route if selected else None,
            capability_id=selected[0].capability_id if selected else None,
            risk=selected[1] if selected else None,
            reason="selected" if selected else "no_eligible_implementation",
            considered=considered,
        )
        self._audit(normalized_goal, allow_visual_fallback, decision)
        return decision

    def _registry_records(self) -> dict[str, Any]:
        records: dict[str, Any] = {}
        duplicates: set[str] = set()
        for record in self._registry_provider() or []:
            capability_id = str(self._field(record, "id", "")).strip()
            if not capability_id:
                continue
            if capability_id in records:
                duplicates.add(capability_id)
                continue
            records[capability_id] = record
        for capability_id in duplicates:
            records.pop(capability_id, None)
        return records

    @staticmethod
    def _field(record: Any, name: str, default: Any) -> Any:
        if isinstance(record, dict):
            return record.get(name, default)
        return getattr(record, name, default)

    def _audit(
        self,
        goal: str,
        allow_visual_fallback: bool,
        decision: OperatorDecision,
    ) -> None:
        event = {
            "goal_sha256": hashlib.sha256(goal.encode("utf-8")).hexdigest(),
            "goal_chars": len(goal),
            "allow_visual_fallback": bool(allow_visual_fallback),
            "selected_id": decision.selected_id,
            "route": decision.route.value if decision.route else None,
            "capability_id": decision.capability_id,
            "reason": decision.reason,
            "considered": [
                {"id": item["id"], "route": item["route"], "reason": item["reason"]}
                for item in decision.considered
            ],
            "external_audit": "not_configured",
        }
        if self._audit_sink is not None:
            try:
                self._audit_sink(dict(event))
                event["external_audit"] = "ok"
            except Exception:
                event["external_audit"] = "failed"

        with self._lock:
            self._audit_sequence += 1
            event["sequence"] = self._audit_sequence
            self.audit_log.append(event)
            if len(self.audit_log) > self._audit_limit:
                del self.audit_log[:-self._audit_limit]
