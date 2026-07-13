"""H33.6 owner transparency and bounded monitor administration API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field

from agents.core.ambient.contracts import MonitorDefinition, MonitorPredicate
from agents.core.ambient.runtime import AmbientRuntime, get_ambient_runtime
from agents.core.ambient.store import AmbientStoreError
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["ambient"])
_RUNGS = ("ignore", "remember", "monitor", "act_silently", "ask", "interrupt")
_MAX_MONITORS = 200


class PredicateBody(BaseModel):
    model_config = {"extra": "forbid"}

    field: str = Field(..., min_length=1, max_length=96)
    operator: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "changed", "age"]
    expected: Any = None


class MonitorBody(BaseModel):
    model_config = {"extra": "forbid", "populate_by_name": True}

    monitor_id: str = Field(
        ..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )
    version: int = Field(..., ge=1)
    source: Literal["house", "camera", "digital"]
    schema_name: str = Field(
        ...,
        alias="schema",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    predicates: list[PredicateBody] = Field(..., min_length=1, max_length=20)
    clear_predicates: list[PredicateBody] = Field(default_factory=list, max_length=20)
    subject_id: str = Field(
        "", max_length=128, pattern=r"^(?:|[A-Za-z0-9][A-Za-z0-9._:-]{0,127})$"
    )
    debounce_seconds: float = Field(0, ge=0, le=604_800)
    hold_seconds: float = Field(0, ge=0, le=604_800)
    cooldown_seconds: float = Field(0, ge=0, le=604_800)
    enabled: bool = True
    alert_rung: Literal[
        "ignore", "remember", "monitor", "act_silently", "ask", "interrupt"
    ] = "monitor"
    recovery_rung: Literal[
        "ignore", "remember", "monitor", "act_silently", "ask", "interrupt"
    ] = "monitor"

    def definition(self) -> MonitorDefinition:
        values = self.model_dump(by_alias=True)
        values["predicates"] = tuple(
            MonitorPredicate(**item) for item in values["predicates"]
        )
        values["clear_predicates"] = tuple(
            MonitorPredicate(**item) for item in values["clear_predicates"]
        )
        return MonitorDefinition(**values)


_MonitorId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
]


def _get_runtime() -> AmbientRuntime:
    return get_ambient_runtime(get_orch())


def _attention(runtime: AmbientRuntime) -> dict[str, Any]:
    ledger = runtime.attention_ledger
    try:
        status = ledger.status() if ledger is not None else {}
    except Exception:
        status = {}
    return {
        "status": str(status.get("status") or "degraded"),
        "reason": (
            str(status.get("reason", ""))
            if status
            else "attention_ledger_unavailable"
        ),
        "limit": max(0, int(status.get("limit") or 0)),
        "used": max(0, int(status.get("used") or 0)),
        "remaining": max(0, int(status.get("remaining") or 0)),
    }


def _decision(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "monitor_id": str(row.get("monitor_id") or "")[:128],
        "transition": str(row.get("transition") or "")[:16],
        "rung": str(row.get("rung") or "monitor")[:16],
        "attention_mode": str(row.get("attention_mode") or "none")[:16],
        "policy_reason": str(row.get("policy_reason") or "")[:64],
        "decided_at": float(row.get("decided_at") or 0),
    }


def _snapshot(runtime: AmbientRuntime) -> dict[str, Any]:
    attention = _attention(runtime)
    base = {
        "enabled": bool(runtime.enabled),
        "status": runtime.status,
        "reason": runtime.reason,
        "monitors": [],
        "sources": [],
        "last_decision": None,
        "rung_counts": dict.fromkeys(_RUNGS, 0),
        "decision_samples": 0,
        "attention": attention,
        "privacy": {"events": "redacted", "subjects": "redacted"},
    }
    if not runtime.enabled or runtime.store is None or runtime.registry is None:
        return base
    health = runtime.store.health()
    if health["status"] != "ready":
        return {**base, "status": "degraded", "reason": str(health["reason"])}
    definitions = list(runtime.registry.list())[:_MAX_MONITORS]
    decisions = runtime.store.recent_decisions(limit=1_000)
    latest_by_monitor: dict[str, dict[str, Any]] = {}
    rung_counts = dict.fromkeys(_RUNGS, 0)
    for item in decisions:
        monitor_id = str(item.get("monitor_id") or "")
        latest_by_monitor.setdefault(monitor_id, item)
        rung = str(item.get("rung") or "")
        if rung in rung_counts:
            rung_counts[rung] += 1
    states = runtime.store.monitor_states([item.monitor_id for item in definitions])
    monitors = []
    for definition in definitions:
        state = states[definition.monitor_id]
        last = _decision(latest_by_monitor.get(definition.monitor_id))
        monitors.append(
            {
                "monitor_id": definition.monitor_id,
                "version": definition.version,
                "source": definition.source,
                "schema": definition.schema,
                "enabled": definition.enabled,
                "alert_rung": definition.alert_rung,
                "recovery_rung": definition.recovery_rung,
                "state": "alert" if state["matched"] else (
                    "clear" if state["last_event_at"] is not None else "waiting"
                ),
                "last_event_at": state["last_event_at"],
                "last_decision": last,
            }
        )
    source_health = runtime.store.source_health()
    sources = []
    for source in sorted({item.source for item in definitions} | set(source_health)):
        item = source_health.get(source, {})
        sources.append(
            {
                "source": source,
                "status": str(item.get("status") or "waiting")[:16],
                "last_event_at": item.get("last_event_at"),
                "reason": str(item.get("last_error") or "")[:64],
                "queued": max(0, int(item.get("queued") or 0)),
                "critical_backpressure": max(
                    0, int(item.get("critical_backpressure") or 0)
                ),
            }
        )
    return {
        **base,
        "status": "live" if monitors else "empty",
        "reason": "",
        "monitors": monitors,
        "sources": sources,
        "last_decision": _decision(decisions[0]) if decisions else None,
        "rung_counts": rung_counts,
        "decision_samples": len(decisions),
    }


@router.get("/api/ambient/monitors", dependencies=[Depends(user_guard)])
async def ambient_monitors():
    return nocache_json(_snapshot(_get_runtime()))


def _mutation_refused(reason: str):
    return nocache_json({"status": "refused", "reason": reason}, status_code=409)


@router.post("/api/ambient/monitors", dependencies=[Depends(admin_guard)])
async def ambient_monitor_create(body: MonitorBody):
    runtime = _get_runtime()
    if not runtime.enabled or runtime.registry is None:
        return _mutation_refused(runtime.reason or "ambient_disabled")
    try:
        result = runtime.registry.create(body.definition(), actor="owner.api")
    except (AmbientStoreError, ValueError):
        return _mutation_refused("monitor_create_refused")
    return nocache_json(
        {key: result[key] for key in ("status", "monitor_id", "version")},
        status_code=201,
    )


@router.put(
    "/api/ambient/monitors/{monitor_id}", dependencies=[Depends(admin_guard)]
)
async def ambient_monitor_update(monitor_id: _MonitorId, body: MonitorBody):
    if monitor_id != body.monitor_id:
        return _mutation_refused("monitor_id_mismatch")
    runtime = _get_runtime()
    if not runtime.enabled or runtime.registry is None:
        return _mutation_refused(runtime.reason or "ambient_disabled")
    try:
        result = runtime.registry.update(body.definition(), actor="owner.api")
    except (AmbientStoreError, ValueError):
        return _mutation_refused("monitor_update_refused")
    return nocache_json(
        {key: result[key] for key in ("status", "monitor_id", "version")}
    )


@router.delete(
    "/api/ambient/monitors/{monitor_id}", dependencies=[Depends(admin_guard)]
)
async def ambient_monitor_delete(monitor_id: _MonitorId):
    runtime = _get_runtime()
    if not runtime.enabled or runtime.registry is None:
        return _mutation_refused(runtime.reason or "ambient_disabled")
    try:
        result = runtime.registry.delete(monitor_id, actor="owner.api")
    except (AmbientStoreError, ValueError):
        return _mutation_refused("monitor_delete_refused")
    return nocache_json(
        {"status": result["status"], "monitor_id": result["monitor_id"]}
    )


__all__ = ["MonitorBody", "PredicateBody", "ambient_monitors", "router"]
