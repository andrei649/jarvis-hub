"""Bounded deterministic evaluation engine for H33 declarative monitors."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from .contracts import AmbientDecision, AmbientEvent, MonitorDefinition, MonitorPredicate
from .policy import LadderContext, LadderPolicy
from .registry import MonitorRegistry
from .store import AmbientStore, AmbientStoreError


def _value(event: AmbientEvent, field: str):
    if field == "source":
        return event.source
    if field == "schema":
        return event.schema
    if field == "subject_id":
        return event.subject_id
    if field == "age_seconds":
        return event.observed_at - event.occurred_at
    if field.startswith("attributes."):
        return event.attribute(field.split(".", 1)[1])
    return None


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compare(predicate: MonitorPredicate, event: AmbientEvent, prior_hashes: dict[str, str]) -> bool:
    actual = _value(event, predicate.field)
    operator = predicate.operator
    if operator == "changed":
        current = _fingerprint(actual)
        previous = prior_hashes.get(predicate.field)
        return previous is not None and current != previous
    if operator == "age":
        return event.observed_at - event.occurred_at >= predicate.expected
    if operator == "eq":
        return actual == predicate.expected
    if operator == "ne":
        return actual != predicate.expected
    if operator == "in":
        return actual in predicate.expected
    if actual is None or isinstance(actual, bool) or isinstance(predicate.expected, bool):
        return False
    try:
        if operator == "lt":
            return actual < predicate.expected
        if operator == "lte":
            return actual <= predicate.expected
        if operator == "gt":
            return actual > predicate.expected
        if operator == "gte":
            return actual >= predicate.expected
    except TypeError:
        return False
    return False


def _field_hashes(event: AmbientEvent) -> dict[str, str]:
    values = {
        "source": event.source,
        "schema": event.schema,
        "subject_id": event.subject_id,
        "age_seconds": event.observed_at - event.occurred_at,
    }
    values.update({f"attributes.{key}": value for key, value in event.attributes})
    return {key: _fingerprint(value) for key, value in values.items()}


class AmbientEngine:
    """Evaluate sanitized facts only; this layer can never execute an action."""

    def __init__(
        self,
        *,
        store: AmbientStore,
        registry: MonitorRegistry,
        enabled: bool,
        per_source_queue: int = 256,
        global_queue: int = 2_048,
        work_per_tick: int = 100,
        ladder_policy: LadderPolicy | None = None,
        quiet_hours: Callable[[float], bool] | None = None,
        silent_context: Callable[[MonitorDefinition], dict[str, object]] | None = None,
        decision_sink: Callable[
            [AmbientDecision, AmbientEvent, MonitorDefinition], object
        ]
        | None = None,
    ) -> None:
        if not isinstance(store, AmbientStore) or not isinstance(registry, MonitorRegistry):
            raise ValueError("ambient store and registry are required")
        if not isinstance(enabled, bool):
            raise ValueError("ambient enabled flag must be boolean")
        for value, maximum, label in (
            (per_source_queue, 256, "per-source queue"),
            (global_queue, 2_048, "global queue"),
            (work_per_tick, 100, "work per tick"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"ambient {label} is invalid")
        self._store = store
        self._registry = registry
        self.enabled = enabled
        self._per_source = per_source_queue
        self._global = global_queue
        self._work = work_per_tick
        self._policy = ladder_policy or LadderPolicy()
        self._quiet_hours = quiet_hours or (lambda _timestamp: False)
        self._silent_context = silent_context
        self._decision_sink = decision_sink
        if not callable(self._quiet_hours):
            raise ValueError("ambient quiet-hours provider must be callable")
        if silent_context is not None and not callable(silent_context):
            raise ValueError("ambient silent-action provider must be callable")
        if decision_sink is not None and not callable(decision_sink):
            raise ValueError("ambient decision sink must be callable")
        self._queues: dict[str, deque[AmbientEvent]] = defaultdict(deque)
        self._critical_backpressure: dict[str, int] = defaultdict(int)
        self._dropped: dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()

    def submit(self, event: AmbientEvent) -> dict[str, object]:
        with self._lock:
            return self._submit(event)

    def _submit(self, event: AmbientEvent) -> dict[str, object]:
        if not isinstance(event, AmbientEvent):
            raise ValueError("ambient engine input must be AmbientEvent")
        if not self.enabled:
            return {"status": "disabled", "reason": "ambient_disabled"}
        if self._store.health()["status"] != "ready":
            return {"status": "degraded", "reason": "ambient_store_unavailable"}
        try:
            if not self._store.claim_event(event):
                return {"status": "duplicate", "reason": "source_event_duplicate"}
        except AmbientStoreError:
            return {"status": "degraded", "reason": "ambient_store_unavailable"}

        queue = self._queues[event.source]
        total = sum(len(items) for items in self._queues.values())
        if len(queue) >= self._per_source or total >= self._global:
            if event.critical:
                try:
                    self._store.add_pending(event)
                except AmbientStoreError:
                    return {"status": "degraded", "reason": "critical_backpressure_failed"}
                self._critical_backpressure[event.source] += 1
                self._update_source_health(event.source, status="degraded", error="queue_full")
                return {"status": "backpressured", "reason": "critical_transition_held"}
            self._dropped[event.source] += 1
            self._update_source_health(event.source, status="degraded", error="queue_full")
            return {"status": "dropped", "reason": "queue_full"}
        queue.append(event)
        self._update_source_health(event.source, status="live", event_time=event.observed_at)
        return {"status": "queued", "queue_depth": total + 1}

    def process_tick(self) -> list[AmbientDecision]:
        with self._lock:
            return self._process_tick()

    def _process_tick(self) -> list[AmbientDecision]:
        if not self.enabled or self._store.health()["status"] != "ready":
            return []
        decisions: list[AmbientDecision] = []
        work = 0
        for source in sorted(self._queues):
            queue = self._queues[source]
            while queue and work < self._work:
                event = queue.popleft()
                decisions.extend(self._evaluate_event(event))
                work += 1
            if not queue:
                self._queues.pop(source, None)
            if work >= self._work:
                break
        if work < self._work:
            for row_id, event in self._store.pending(limit=self._work - work):
                decisions.extend(self._evaluate_event(event))
                self._store.delete_pending(row_id)
                work += 1
        for source in set(self._critical_backpressure) | set(self._queues):
            self._update_source_health(source, status="live")
        return decisions

    def _evaluate_event(self, event: AmbientEvent) -> list[AmbientDecision]:
        decisions: list[AmbientDecision] = []
        for definition in self._registry.list():
            if (
                not definition.enabled
                or definition.source != event.source
                or definition.schema != event.schema
                or (definition.subject_id and definition.subject_id != event.subject_id)
            ):
                continue
            state = self._store.monitor_state(definition.monitor_id)
            last_event = state.get("last_event_at")
            if last_event is not None and event.observed_at < float(last_event):
                continue
            decision = self._transition(definition, event, state)
            state["field_hashes"] = _field_hashes(event)
            state["last_event_at"] = event.observed_at
            self._store.save_monitor_state(definition.monitor_id, state)
            if decision is not None:
                self._store.append_decision(decision)
                decisions.append(decision)
                if self._decision_sink is not None:
                    try:
                        self._decision_sink(decision, event, definition)
                    except Exception:
                        self._update_source_health(
                            event.source, status="degraded", error="proposal_failed"
                        )
        self._update_source_health(event.source, status="live", event_time=event.observed_at)
        return decisions

    def _transition(
        self,
        definition: MonitorDefinition,
        event: AmbientEvent,
        state: dict[str, Any],
    ) -> AmbientDecision | None:
        prior_hashes = dict(state.get("field_hashes") or {})
        desired = all(_compare(item, event, prior_hashes) for item in definition.predicates)
        matched = bool(state.get("matched"))
        pending = state.get("pending_since")
        last_emit = state.get("last_emit")
        transition = ""
        reason = ""
        if matched:
            clear = (
                all(_compare(item, event, prior_hashes) for item in definition.clear_predicates)
                if definition.clear_predicates
                else not desired
            )
            if clear:
                state["matched"] = False
                state["pending_since"] = None
                transition = "recovery"
                reason = "predicate_cleared"
        elif desired:
            effective_hold = max(definition.debounce_seconds, definition.hold_seconds)
            if pending is None:
                pending = event.observed_at
                state["pending_since"] = pending
            hold_ready = event.observed_at - float(pending) >= effective_hold
            cooldown_ready = (
                last_emit is None
                or event.observed_at - float(last_emit) >= definition.cooldown_seconds
            )
            if hold_ready and cooldown_ready:
                state["matched"] = True
                state["pending_since"] = None
                state["last_emit"] = event.observed_at
                transition = "alert"
                reason = "predicate_matched"
        else:
            state["pending_since"] = None
        if not transition:
            return None
        material = (
            f"{definition.definition_hash}:{event.fingerprint}:{transition}:"
            f"{event.consent_generation}"
        )
        decision_id = f"decision-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"
        requested_rung = (
            definition.alert_rung if transition == "alert" else definition.recovery_rung
        )
        confidence = event.attribute("confidence", 1.0)
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            confidence = 0.0
        silent = self._silent_context(definition) if self._silent_context is not None else {}
        if not isinstance(silent, dict):
            silent = {}
        ladder = self._policy.decide(
            LadderContext(
                requested_rung=requested_rung,
                confidence=float(confidence),
                tainted=event.tainted,
                critical=event.critical,
                quiet_hours=bool(self._quiet_hours(event.observed_at)),
                capability_id=str(silent.get("capability_id") or ""),
                silent_eligible=silent.get("silent_eligible") is True,
                rollbackable=silent.get("rollbackable") is True,
                postcondition_bound=silent.get("postcondition_bound") is True,
            )
        )
        return AmbientDecision(
            decision_id=decision_id,
            monitor_id=definition.monitor_id,
            monitor_version=definition.version,
            monitor_hash=definition.definition_hash,
            event_fingerprint=event.fingerprint,
            transition=transition,
            matched=transition == "alert",
            reason=reason,
            decided_at=event.observed_at,
            consent_generation=event.consent_generation,
            rung=ladder.rung.value,
            attention_mode=ladder.attention_mode,
            policy_reason=ladder.reason,
        )

    def _update_source_health(
        self,
        source: str,
        *,
        status: str,
        event_time: float | None = None,
        error: str = "",
    ) -> None:
        try:
            self._store.update_source_health(
                source,
                status=status,
                last_event_at=event_time,
                last_error=error,
                queued=len(self._queues.get(source, ())),
                critical_backpressure=self._critical_backpressure[source],
            )
        except AmbientStoreError:
            return

    def health(self) -> dict[str, object]:
        queue_depth = sum(len(items) for items in self._queues.values())
        try:
            sources = self._store.source_health()
        except AmbientStoreError:
            sources = {}
        for source, dropped in self._dropped.items():
            sources.setdefault(source, {})["dropped"] = dropped
        status = "disabled" if not self.enabled else self._store.health()["status"]
        return {
            "enabled": self.enabled,
            "status": status,
            "queue_depth": queue_depth,
            "queue_capacity": self._global,
            "pending_critical": self._store.pending_count() if status == "ready" else 0,
            "sources": sources,
        }


__all__ = ["AmbientEngine"]
