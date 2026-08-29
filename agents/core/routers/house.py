"""House Brain API (H30.5) — bounded state and governed proposals only.

The router never calls Home Assistant services directly.  Read state comes from
the strict-local adapter; mutations are durable proposals handled by
``HouseActuator`` and the autonomy worker.  Security-device confirmation is an
admin-only ceremony bound to an already-persisted task.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.paths import data_path
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

from ..house import (
    HOUSE_SECURITY_KIND,
    ConfirmationError,
    HomeAssistantAdapter,
    HomeAssistantServiceDriver,
    HouseActuator,
    HouseGraph,
    HousePresenceIngestor,
    PresenceInference,
    PrivateHouseStore,
    PrivateStoreError,
    StrongConfirmationStore,
    register_house_handlers,
)

router = APIRouter(tags=["house"])
logger = logging.getLogger(__name__)

_PSEUDONYM = re.compile(r"occ-[0-9a-f]{32}")
_STATE_LIMIT = 500
_runtime = None
_build_lock = threading.Lock()


@dataclass
class HouseRuntime:
    adapter: HomeAssistantAdapter
    graph: HouseGraph
    private_store: PrivateHouseStore | None
    actuator: object
    queue: object | None
    private_status: str
    confirmation_status: str
    orch_id: int = 0
    # GAP-9: the production presence writer (None = feature off/store down).
    presence_ingestor: HousePresenceIngestor | None = None


class _StrictBody(BaseModel):
    model_config = {"extra": "forbid"}


class LightControlBody(_StrictBody):
    entity_id: str = Field(..., min_length=3, max_length=128, pattern=r"^light\.[A-Za-z0-9_.-]+$")
    state: Literal["on", "off"]
    brightness_pct: int | None = Field(None, ge=1, le=100)


class ClimateControlBody(_StrictBody):
    entity_id: str = Field(
        ..., min_length=3, max_length=128, pattern=r"^climate\.[A-Za-z0-9_.-]+$"
    )
    action: Literal["set_temperature", "set_mode"]
    value: float | str


class SecurityControlBody(_StrictBody):
    entity_id: str = Field(
        ...,
        min_length=3,
        max_length=128,
        pattern=r"^(lock|alarm_control_panel|cover)\.[A-Za-z0-9_.-]+$",
    )
    action: Literal["lock", "unlock", "arm_home", "arm_away", "disarm", "open", "close"]


class ConfirmationBody(_StrictBody):
    challenge_token: str = Field(..., min_length=16, max_length=256)


class _UnavailableActuator:
    def __init__(self, reason: str = "house_actuation_unavailable") -> None:
        self._reason = reason

    def _result(self) -> dict:
        return {"ok": False, "queued": False, "reason": self._reason}

    async def request_light(self, *_args, **_kwargs) -> dict:
        return self._result()

    async def request_climate(self, *_args, **_kwargs) -> dict:
        return self._result()

    async def request_security(self, *_args, **_kwargs) -> dict:
        return self._result()

    def mint_confirmation(self, _task):
        raise ConfirmationError("strong confirmation is unavailable")

    def confirm(self, _token, _task):
        raise ConfirmationError("strong confirmation is unavailable")


def _settings(orch) -> dict:
    getter = getattr(orch, "get_setting", None)
    if not callable(getter):
        return {}
    keys = (
        "house.enabled",
        "house.ha_enabled",
        "house.ha_url",
        "house.ha_token_ref",
        "house.ha_allowed_hosts",
        "house.presence_enabled",
    )
    return {key: getter(key, None) for key in keys}


def _presence_enabled(settings: dict) -> bool:
    """Default-off presence writer flag (env wins over settings, house-style)."""
    import os

    if "JARVIS_HOUSE_PRESENCE" in os.environ:
        return os.environ["JARVIS_HOUSE_PRESENCE"].strip().lower() in {"1", "true", "yes", "on"}
    return settings.get("house.presence_enabled") is True


def _build_runtime(orch) -> HouseRuntime:
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.memory.graph import InMemoryGraph

    secret_broker = getattr(orch, "secret_broker", None) if orch is not None else None
    adapter = HomeAssistantAdapter(
        settings=_settings(orch),
        secret_broker=secret_broker,
    )
    generic_graph = getattr(getattr(orch, "memory", None), "graph", None)
    graph = HouseGraph(generic_graph or InMemoryGraph())
    queue = getattr(orch, "autonomy_queue", None) if orch is not None else None
    if not adapter.config.enabled or not adapter.config.ha_enabled:
        return HouseRuntime(
            adapter=adapter,
            graph=graph,
            private_store=None,
            actuator=_UnavailableActuator("house_brain_disabled"),
            queue=queue,
            private_status="disabled",
            confirmation_status="unavailable",
        )

    try:
        private_store = PrivateHouseStore(secret_broker=secret_broker)
        private_status = "live"
    except (PrivateStoreError, OSError):
        private_store = None
        private_status = "unavailable"

    # GAP-9: the production presence writer. Shares the SAME store instance as
    # _presence_view (a second store on the same path would be invisible to
    # the router's cached one). Default-off; None keeps prior behavior.
    presence_ingestor = None
    if private_store is not None and _presence_enabled(_settings(orch)):
        try:
            presence_ingestor = HousePresenceIngestor(PresenceInference(private_store))
        except ValueError:
            logger.warning("House presence writer unavailable", exc_info=True)

    try:
        confirmations = StrongConfirmationStore(
            data_path("house", "confirmations.db"),
            secret_broker=secret_broker,
        )
        confirmation_status = "live"
    except (ConfirmationError, OSError):
        confirmations = None
        confirmation_status = "unavailable"

    worker = getattr(orch, "autonomy", None) if orch is not None else None
    enqueue = getattr(worker, "govern_enqueue", None)
    intake_authorizer = getattr(worker, "kernel_gate", None)
    outcomes = getattr(queue, "capability_outcome_stats", None)
    try:
        actuator = HouseActuator(
            state_reader=adapter,
            driver=HomeAssistantServiceDriver(adapter=adapter),
            authorizer=make_action_kernel(orch) if orch is not None else None,
            intake_authorizer=intake_authorizer if callable(intake_authorizer) else None,
            enqueue=enqueue if callable(enqueue) else None,
            outcome_provider=outcomes if callable(outcomes) else None,
            confirmation_store=confirmations,
        )
    except Exception:
        logger.warning("House actuation storage is unavailable", exc_info=True)
        actuator = _UnavailableActuator()
        confirmation_status = "unavailable"
    executor = getattr(orch, "task_executor", None) if orch is not None else None
    if executor is not None and isinstance(actuator, HouseActuator):
        register_house_handlers(executor, actuator)
    return HouseRuntime(
        adapter=adapter,
        graph=graph,
        private_store=private_store,
        actuator=actuator,
        queue=queue,
        private_status=private_status,
        confirmation_status=confirmation_status,
        orch_id=id(orch) if orch is not None else 0,
        presence_ingestor=presence_ingestor,
    )


async def _get_runtime() -> HouseRuntime:
    global _runtime
    orch = get_orch()
    orch_id = id(orch) if orch is not None else 0
    current = _runtime
    if current is not None and current.orch_id == orch_id:
        return current

    # Runtime construction blocks (DNS-validated adapter config, encrypted
    # store reads, sqlite DDL); build it off the loop, under a lock so
    # concurrent first requests still construct the runtime exactly once.
    def _build() -> HouseRuntime:
        global _runtime
        with _build_lock:
            built = _runtime
            if built is None or built.orch_id != orch_id:
                built = _build_runtime(orch)
                _runtime = built
            return built

    return await asyncio.to_thread(_build)


def _apply_presence_fact(occupants: dict[str, dict], fact: object) -> None:
    if not isinstance(fact, dict):
        return
    subject = fact.get("subject_id")
    predicate = fact.get("predicate")
    value = fact.get("object")
    if not isinstance(subject, str) or _PSEUDONYM.fullmatch(subject) is None:
        return
    if predicate not in {"presence_status", "present_in", "privacy_context"}:
        return
    if not isinstance(value, str) or len(value) > 128:
        return
    item = occupants.setdefault(
        subject,
        {
            "occupant_id": subject,
            "status": "unknown",
            "privacy": "household",
            "confidence": 1.0,
            "fresh": True,
        },
    )
    if predicate == "presence_status" and value in {"present", "vacant"}:
        item["status"] = value
    elif predicate == "present_in":
        item["room_id"] = value
    elif predicate == "privacy_context":
        item["privacy"] = value
    confidence = fact.get("confidence", 0.0)
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        item["confidence"] = min(item["confidence"], max(0.0, min(float(confidence), 1.0)))
    item["fresh"] = item["fresh"] and fact.get("fresh") is True


def _presence_view(store: PrivateHouseStore | None) -> list[dict]:
    if store is None:
        return []
    facts = store.query(limit=_STATE_LIMIT)
    occupants: dict[str, dict] = {}
    for fact in facts[:_STATE_LIMIT]:
        _apply_presence_fact(occupants, fact)

    visible = []
    for occupant_id in sorted(occupants)[:_STATE_LIMIT]:
        item = occupants[occupant_id]
        if item["privacy"].lower() == "private":
            item.pop("room_id", None)
        visible.append(item)
    return visible


def _action_response(result: dict, *, security: bool = False) -> dict:
    if not isinstance(result, dict):
        result = {"ok": False, "reason": "invalid_house_response"}
    reason = str(result.get("reason") or "")[:256]
    if reason == "house_brain_disabled":
        status = "disabled"
    elif not result.get("ok"):
        status = "denied"
    elif result.get("queued"):
        status = "queued"
    else:
        status = "unverified"
        reason = reason or "governed_queue_unavailable"
    payload = {
        "enabled": status != "disabled",
        "status": status,
        "reason": reason or ("strong_confirmation_required" if security else "approval_required"),
        "strong_confirmation_required": bool(
            security or result.get("strong_confirmation_required")
        ),
    }
    task_id = result.get("task_id")
    if isinstance(task_id, int) and not isinstance(task_id, bool) and task_id > 0:
        payload["task_id"] = task_id
    return payload


async def _security_task(runtime: HouseRuntime, task_id: int):
    if runtime.confirmation_status != "live" or runtime.queue is None:
        return None, nocache_json(
            {
                "enabled": True,
                "status": "unavailable",
                "reason": "strong_confirmation_unavailable",
            },
            status_code=503,
        )
    try:
        # TaskQueue.get is a blocking sqlite read; keep it off the event loop.
        task = await asyncio.to_thread(runtime.queue.get, task_id)
    except Exception:
        task = None
    if task is None:
        return None, nocache_json(
            {"enabled": True, "status": "not_found", "reason": "task_not_found"},
            status_code=404,
        )
    if getattr(task, "kind", "") != HOUSE_SECURITY_KIND:
        return None, nocache_json(
            {"enabled": True, "status": "denied", "reason": "task_not_security_control"},
            status_code=409,
        )
    if getattr(task, "status", "") not in {"proposed", "approved"}:
        return None, nocache_json(
            {"enabled": True, "status": "denied", "reason": "task_not_confirmable"},
            status_code=409,
        )
    return task, None


@router.get("/api/house/state", dependencies=[Depends(user_guard)])
async def house_state():
    runtime = await _get_runtime()
    try:
        snapshot = await runtime.adapter.snapshot()
    except Exception:
        logger.warning("House state adapter failed", exc_info=True)
        return nocache_json(
            {
                "enabled": True,
                "status": "degraded",
                "reason": "house_state_unavailable",
                "observed_at": 0.0,
                "confidence": 0.0,
                "freshness_seconds": None,
                "rooms": [],
                "devices": [],
                "presence": [],
                "presence_status": (
                    "unavailable"
                    if getattr(runtime, "presence_ingestor", None) is not None
                    else "off"
                ),
                "privacy_status": runtime.private_status,
            }
        )
    status = snapshot.status
    reason = snapshot.reason

    # GAP-9: run the production presence writer before the presence view is
    # read, so the view reflects this very snapshot. Store writes are
    # blocking (encrypted file store) — keep them off the loop. The writer's
    # own status is reported separately from the array so an empty list
    # means "no occupants detected", never "the feature was never built".
    ingestor = getattr(runtime, "presence_ingestor", None)
    if ingestor is None:
        presence_status = "off"
    elif snapshot.status != "live":
        presence_status = "unavailable"
    else:
        try:
            await asyncio.to_thread(ingestor.ingest, snapshot)
            presence_status = "live"
        except Exception:
            logger.warning("House presence ingest failed", exc_info=True)
            presence_status = "degraded"
    state = {
        "status": status,
        "observed_at": snapshot.observed_at,
        "confidence": 0.0,
        "freshness_seconds": None,
        "rooms": [],
        "devices": [],
    }
    if snapshot.status == "live":
        projection = runtime.graph.project_snapshot(snapshot)
        state = runtime.graph.query_state(limit=_STATE_LIMIT)
        if projection.get("status") == "degraded":
            status = "degraded"
            reason = str(projection.get("reason") or "graph_projection_failed")[:256]
    privacy_status = runtime.private_status
    try:
        presence = _presence_view(runtime.private_store)
    except Exception:
        logger.warning("Private house state read failed", exc_info=True)
        presence = []
        privacy_status = "degraded"
    return nocache_json(
        {
            "enabled": snapshot.enabled,
            "status": status,
            "reason": reason,
            "observed_at": state.get("observed_at", snapshot.observed_at),
            "confidence": state.get("confidence", 0.0),
            "freshness_seconds": state.get("freshness_seconds"),
            "rooms": list(state.get("rooms") or [])[:_STATE_LIMIT],
            "devices": list(state.get("devices") or [])[:_STATE_LIMIT],
            "presence": presence,
            "presence_status": presence_status,
            "privacy_status": privacy_status,
        }
    )


@router.post("/api/house/control/light", dependencies=[Depends(user_guard)])
async def house_control_light(body: LightControlBody):
    try:
        result = await (await _get_runtime()).actuator.request_light(
            body.entity_id,
            state=body.state,
            brightness_pct=body.brightness_pct,
            agent="jarvis",
        )
    except ValueError:
        return nocache_json(
            {"enabled": True, "status": "denied", "reason": "invalid_light_control"},
            status_code=422,
        )
    return nocache_json(_action_response(result))


@router.post("/api/house/control/climate", dependencies=[Depends(user_guard)])
async def house_control_climate(body: ClimateControlBody):
    try:
        result = await (await _get_runtime()).actuator.request_climate(
            body.entity_id,
            action=body.action,
            value=body.value,
            agent="jarvis",
        )
    except ValueError:
        return nocache_json(
            {"enabled": True, "status": "denied", "reason": "invalid_climate_control"},
            status_code=422,
        )
    return nocache_json(_action_response(result))


@router.post("/api/house/control/security", dependencies=[Depends(user_guard)])
async def house_control_security(body: SecurityControlBody):
    try:
        result = await (await _get_runtime()).actuator.request_security(
            body.entity_id,
            action=body.action,
            agent="jarvis",
        )
    except ValueError:
        return nocache_json(
            {"enabled": True, "status": "denied", "reason": "invalid_security_control"},
            status_code=422,
        )
    return nocache_json(_action_response(result, security=True))


@router.post(
    "/api/house/security/{task_id}/challenge",
    dependencies=[Depends(admin_guard)],
)
async def house_security_challenge(task_id: int):
    runtime = await _get_runtime()
    task, error = await _security_task(runtime, task_id)
    if error is not None:
        return error
    try:
        # Challenge minting writes to the confirmation sqlite store.
        result = await runtime.actuator.mint_confirmation_async(task)
    except (ConfirmationError, ValueError):
        return nocache_json(
            {"enabled": True, "status": "denied", "reason": "challenge_refused"},
            status_code=409,
        )
    return nocache_json({"enabled": True, **result})


@router.post(
    "/api/house/security/{task_id}/confirm",
    dependencies=[Depends(admin_guard)],
)
async def house_security_confirm(task_id: int, body: ConfirmationBody):
    runtime = await _get_runtime()
    task, error = await _security_task(runtime, task_id)
    if error is not None:
        return error
    try:
        # Confirmation consumes a row in the confirmation sqlite store.
        result = await runtime.actuator.confirm_async(body.challenge_token, task)
    except (ConfirmationError, ValueError):
        return nocache_json(
            {"enabled": True, "status": "denied", "reason": "confirmation_refused"},
            status_code=409,
        )
    return nocache_json({"enabled": True, **result})
