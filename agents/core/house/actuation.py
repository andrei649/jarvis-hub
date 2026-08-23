"""Governed Home Assistant control with verification and recovery."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from agents.core.autonomy.dry_run import preview_task
from agents.core.capability_actions import CapabilityActionAPI, PerformContext
from agents.core.paths import data_path

from .confirmation import ConfirmationError, StrongConfirmationStore
from .contracts import HouseEntity, HouseSnapshot

HOUSE_CONTROL_KIND = "house.control"
HOUSE_SECURITY_KIND = "house.security_control"
HOUSE_RECOVERY_KIND = "house.recovery"
_CONTROL_CAPABILITY = f"action:{HOUSE_CONTROL_KIND}"
_SECURITY_CAPABILITY = f"action:{HOUSE_SECURITY_KIND}"
_RECOVERY_CAPABILITY = f"action:{HOUSE_RECOVERY_KIND}"
_MAX_STATE_AGE = 30.0
_EARNED_SAMPLES = 20
_EARNED_CONFIDENCE = 0.80
_COMMON_KEYS = frozenset(
    {
        "version",
        "control",
        "entity_id",
        "action",
        "risk_tier",
        "reversible",
        "signal_quality",
    }
)
_SECURITY_ACTIONS = {
    "lock": frozenset({"lock", "unlock"}),
    "alarm_control_panel": frozenset({"arm_home", "arm_away", "disarm"}),
    "cover": frozenset({"open", "close"}),
}
_SECURITY_STATES = {
    "lock": "locked",
    "unlock": "unlocked",
    "arm_home": "armed_home",
    "arm_away": "armed_away",
    "disarm": "disarmed",
    "open": "open",
    "close": "closed",
}


class HouseActuationError(RuntimeError):
    """A durable house task failed and must not be settled as successful."""


def _text(value: object, *, label: str, limit: int = 128) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    result = value.strip()
    if len(result) > limit:
        raise ValueError(f"{label} exceeds its size limit")
    return result


def _number(value: object, *, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{label} is outside its bounds")
    return result


def _entity_domain(entity_id: str) -> str:
    entity = _text(entity_id, label="entity_id")
    if "." not in entity:
        raise ValueError("entity_id is invalid")
    return entity.split(".", 1)[0]


def _canonical_light(entity_id: str, state: str, brightness_pct=None) -> dict:
    if _entity_domain(entity_id) != "light":
        raise ValueError("entity_id must be a light")
    action = _text(state, label="state", limit=16).lower()
    if action not in {"on", "off"}:
        raise ValueError("light state is invalid")
    payload = {
        "version": 1,
        "control": "light",
        "entity_id": entity_id,
        "action": action,
        "risk_tier": 1,
        "reversible": True,
        "signal_quality": 1.0,
    }
    if brightness_pct is not None:
        if action != "on":
            raise ValueError("brightness requires light state on")
        brightness = _number(brightness_pct, label="brightness_pct", minimum=1, maximum=100)
        if not brightness.is_integer():
            raise ValueError("brightness_pct must be an integer")
        payload["brightness_pct"] = int(brightness)
    return payload


def _canonical_climate(entity_id: str, action: str, value: object) -> dict:
    if _entity_domain(entity_id) != "climate":
        raise ValueError("entity_id must be climate")
    action = _text(action, label="action", limit=32).lower()
    if action == "set_temperature":
        clean_value: object = _number(value, label="temperature", minimum=10.0, maximum=30.0)
    elif action == "set_mode":
        clean_value = _text(value, label="hvac_mode", limit=16).lower()
        if clean_value not in {"off", "heat", "cool", "auto", "dry", "fan_only"}:
            raise ValueError("hvac_mode is invalid")
    else:
        raise ValueError("climate action is invalid")
    return {
        "version": 1,
        "control": "climate",
        "entity_id": entity_id,
        "action": action,
        "value": clean_value,
        "risk_tier": 1,
        "reversible": True,
        "signal_quality": 1.0,
    }


def _canonical_security(entity_id: str, action: str) -> dict:
    domain = _entity_domain(entity_id)
    action = _text(action, label="action", limit=32).lower()
    if domain not in _SECURITY_ACTIONS or action not in _SECURITY_ACTIONS[domain]:
        raise ValueError("security entity/action is invalid")
    return {
        "version": 1,
        "control": "security",
        "entity_id": entity_id,
        "action": action,
        "risk_tier": 3,
        "reversible": False,
        "signal_quality": 1.0,
    }


def _canonical_task(kind: str, payload: object) -> dict:
    if not isinstance(payload, Mapping):
        raise ValueError("invalid_payload")
    raw = dict(payload)
    control = raw.get("control")
    allowed = set(_COMMON_KEYS)
    if control == "light":
        if "brightness_pct" in raw:
            allowed.add("brightness_pct")
        clean = _canonical_light(
            raw.get("entity_id", ""), raw.get("action", ""), raw.get("brightness_pct")
        )
        expected_kind = HOUSE_CONTROL_KIND
    elif control == "climate":
        allowed.add("value")
        clean = _canonical_climate(
            raw.get("entity_id", ""), raw.get("action", ""), raw.get("value")
        )
        expected_kind = HOUSE_CONTROL_KIND
    elif control == "security":
        clean = _canonical_security(raw.get("entity_id", ""), raw.get("action", ""))
        expected_kind = HOUSE_SECURITY_KIND
    else:
        raise ValueError("invalid_payload")
    if kind != expected_kind or set(raw) != allowed or _payload_hash(raw) != _payload_hash(clean):
        raise ValueError("invalid_payload")
    return clean


def _intended_state(payload: Mapping) -> str:
    if payload["control"] == "light":
        return str(payload["action"])
    if payload["control"] == "climate":
        return str(payload["value"])
    return _SECURITY_STATES[str(payload["action"])]


def _payload_hash(payload: Mapping) -> str:
    import hashlib

    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class _ExecutionLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with closing(sqlite3.connect(str(self.path))) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS house_executions (
                    task_id INTEGER PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT
                )
                """
            )

    def lookup(self, task_id: int, digest: str) -> tuple[str, dict | None]:
        with self._lock, closing(sqlite3.connect(str(self.path))) as connection, connection:
            row = connection.execute(
                "SELECT payload_hash, status, result FROM house_executions WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return "new", None
        if row[0] != digest:
            return "conflict", None
        if row[1] == "done" and row[2]:
            return "cached", json.loads(row[2])
        return "running", None

    def begin(self, task_id: int, digest: str) -> bool:
        with self._lock, closing(sqlite3.connect(str(self.path))) as connection, connection:
            changed = connection.execute(
                "INSERT OR IGNORE INTO house_executions (task_id, payload_hash, status) "
                "VALUES (?, ?, 'running')",
                (task_id, digest),
            ).rowcount
        return changed == 1

    def finish(self, task_id: int, result: dict) -> None:
        with self._lock, closing(sqlite3.connect(str(self.path))) as connection, connection:
            connection.execute(
                "UPDATE house_executions SET status='done', result=? WHERE task_id=?",
                (json.dumps(result, sort_keys=True, separators=(",", ":")), task_id),
            )

    def abort(self, task_id: int) -> None:
        with self._lock, closing(sqlite3.connect(str(self.path))) as connection, connection:
            connection.execute(
                "DELETE FROM house_executions WHERE task_id=? AND status='running'",
                (task_id,),
            )


class HomeAssistantServiceDriver:
    """Narrow HA service mapper; arbitrary domains/services are unrepresentable."""

    def __init__(self, *, service_call: Callable | None = None, adapter=None) -> None:
        if service_call is None and adapter is None:
            raise ValueError("service_call or adapter is required")
        self._service_call = service_call
        self._adapter = adapter

    @staticmethod
    def _service(command: Mapping) -> tuple[str, str, dict]:
        if not all(key in command for key in ("control", "entity_id", "action")):
            raise ValueError("command is not allowlisted")
        control = command.get("control")
        entity_id = _text(command.get("entity_id"), label="entity_id")
        action = _text(command.get("action"), label="action", limit=32)
        domain = _entity_domain(entity_id)
        data = {"entity_id": entity_id}
        if control == "light" and domain == "light" and action in {"on", "off"}:
            service = "turn_on" if action == "on" else "turn_off"
            if command.get("brightness_pct") is not None:
                brightness = _number(
                    command["brightness_pct"],
                    label="brightness_pct",
                    minimum=1,
                    maximum=100,
                )
                if not brightness.is_integer():
                    raise ValueError("command brightness must be an integer")
                data["brightness_pct"] = int(brightness)
            return domain, service, data
        if control == "climate" and domain == "climate":
            if action == "set_temperature":
                data["temperature"] = _number(
                    command.get("value"), label="temperature", minimum=10, maximum=30
                )
                return domain, "set_temperature", data
            if action == "set_mode":
                mode = _text(command.get("value"), label="hvac_mode", limit=16)
                if mode not in {"off", "heat", "cool", "auto", "dry", "fan_only"}:
                    raise ValueError("command hvac_mode is not allowlisted")
                data["hvac_mode"] = mode
                return domain, "set_hvac_mode", data
        if control == "security" and action in _SECURITY_ACTIONS.get(domain, ()):
            service = {
                "arm_home": "alarm_arm_home",
                "arm_away": "alarm_arm_away",
                "disarm": "alarm_disarm",
                "open": "open_cover",
                "close": "close_cover",
            }.get(action, action)
            return domain, service, data
        raise ValueError("command is not allowlisted")

    async def _adapter_service_call(self, domain: str, service: str, data: dict) -> dict:
        adapter = self._adapter
        origin, pinned_ip, host, _port = await asyncio.to_thread(adapter._runtime_endpoint)
        parsed = urlparse(origin)
        ip_host = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
        explicit_port = f":{parsed.port}" if parsed.port else ""
        pinned_origin = urlunparse((parsed.scheme, f"{ip_host}{explicit_port}", "", "", "", ""))
        host_header = f"{host}:{parsed.port}" if parsed.port else host
        response = await adapter._rest.request(
            "POST",
            f"{pinned_origin}/api/services/{domain}/{service}",
            headers={
                "Authorization": f"Bearer {adapter._token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Host": host_header,
            },
            json=data,
            timeout=5.0,
            follow_redirects=False,
            extensions={"sni_hostname": host},
        )
        status = int(getattr(response, "status_code", 0))
        final_host = (urlparse(str(getattr(response, "url", ""))).hostname or "").lower()
        if status != 200 or (final_host and final_host != pinned_ip.lower()):
            return {"ok": False, "transport_status": status, "reason": "ha_service_failed"}
        return {"ok": True, "transport_status": status}

    async def apply(self, command: Mapping) -> dict:
        if not isinstance(command, Mapping):
            raise ValueError("command must be a mapping")
        domain, service, data = self._service(command)
        caller = self._service_call or self._adapter_service_call
        result = caller(domain, service, data)
        if inspect.isawaitable(result):
            result = await result
        return dict(result) if isinstance(result, Mapping) else {"ok": False}


class HouseActuator:
    def __init__(
        self,
        *,
        state_reader,
        driver,
        authorizer=None,
        enqueue=None,
        outcome_provider=None,
        confirmation_store: StrongConfirmationStore | None = None,
        ledger_path: str | Path | None = None,
        clock=None,
    ) -> None:
        self._state_reader = state_reader
        self._driver = driver
        self._enqueue = enqueue
        self._outcomes = outcome_provider
        self._confirmations = confirmation_store
        self._clock = clock or time.time
        self._ledger = _ExecutionLedger(ledger_path or data_path("house", "actuation.db"))
        self._actions = CapabilityActionAPI(authorizer=authorizer)
        for capability in (
            _CONTROL_CAPABILITY,
            _SECURITY_CAPABILITY,
            _RECOVERY_CAPABILITY,
        ):
            self._actions.register(capability, self._apply)

    async def _apply(self, payload: dict, _context: PerformContext) -> dict:
        return await self._driver.apply(payload)

    async def _snapshot_entity(self, entity_id: str) -> tuple[HouseSnapshot, HouseEntity | None]:
        snapshot = await self._state_reader.snapshot()
        if not isinstance(snapshot, HouseSnapshot):
            raise RuntimeError("invalid house snapshot")
        entity = next((item for item in snapshot.entities if item.entity_id == entity_id), None)
        return snapshot, entity

    def _precondition_reason(self, snapshot: HouseSnapshot, entity: HouseEntity | None) -> str:
        if snapshot.status != "live":
            return "house_state_not_live"
        if entity is None:
            return "target_not_found"
        now = float(self._clock())
        if entity.updated_at > now + 5 or now - entity.updated_at > _MAX_STATE_AGE:
            return "house_state_stale"
        return ""

    async def _request(self, kind: str, payload: dict, *, agent: str) -> dict:
        try:
            snapshot, entity = await self._snapshot_entity(payload["entity_id"])
        except Exception:
            return {"ok": False, "queued": False, "reason": "house_state_unavailable"}
        reason = self._precondition_reason(snapshot, entity)
        if reason:
            return {"ok": False, "queued": False, "reason": reason}
        security = kind == HOUSE_SECURITY_KIND
        autonomy_level = "ask"
        if not security and callable(self._outcomes):
            try:
                stats = self._outcomes(_CONTROL_CAPABILITY)
                if (
                    isinstance(stats, Mapping)
                    and int(stats.get("total", 0)) >= _EARNED_SAMPLES
                    and float(stats.get("confidence", 0)) >= _EARNED_CONFIDENCE
                ):
                    autonomy_level = "act"
            except (TypeError, ValueError):
                autonomy_level = "ask"
        title = f"{payload['control']} {payload['action']} → {payload['entity_id']}"
        preview = preview_task(
            {
                "kind": kind,
                "title": title,
                "risk_tier": payload["risk_tier"],
                "payload": {**payload, "target": payload["entity_id"]},
            },
            # The house pipeline sets its own approval floor (ask until earned);
            # the preview must describe that reality, not the generic tier math.
            autonomy_level=autonomy_level,
        )
        base = {
            "ok": True,
            "kind": kind,
            "title": title,
            "payload": payload,
            "preview": preview,
            "autonomy_level": autonomy_level,
            "strong_confirmation_required": security,
        }
        if self._enqueue is None:
            return {**base, "queued": False}
        # Governed intake ends in a sync sqlite write (TaskQueue.enqueue) and is
        # awaited straight from device-facing routes — offload it so the event
        # loop never blocks on disk I/O. Same callable, same arguments, same id.
        task_id = await asyncio.to_thread(
            self._enqueue,
            agent,
            kind,
            title,
            payload=payload,
            risk_tier=payload["risk_tier"],
            autonomy_level="ask" if security else autonomy_level,
            origin="generated",
        )
        return {**base, "queued": True, "task_id": int(task_id)}

    async def request_light(
        self,
        entity_id: str,
        *,
        state: str,
        brightness_pct=None,
        agent: str = "jarvis",
    ) -> dict:
        payload = _canonical_light(entity_id, state, brightness_pct)
        return await self._request(HOUSE_CONTROL_KIND, payload, agent=agent)

    async def request_climate(
        self, entity_id: str, *, action: str, value: object, agent: str = "jarvis"
    ) -> dict:
        payload = _canonical_climate(entity_id, action, value)
        return await self._request(HOUSE_CONTROL_KIND, payload, agent=agent)

    async def request_security(self, entity_id: str, *, action: str, agent: str = "jarvis") -> dict:
        payload = _canonical_security(entity_id, action)
        return await self._request(HOUSE_SECURITY_KIND, payload, agent=agent)

    @staticmethod
    def _task_binding(task, payload: Mapping) -> dict:
        return {
            "task_id": int(task.id),
            "capability": HOUSE_SECURITY_KIND,
            "target": payload["entity_id"],
            "intended_state": _intended_state(payload),
        }

    def mint_confirmation(self, task, *, ttl_seconds: float = 120.0) -> dict:
        if self._confirmations is None:
            raise ConfirmationError("strong confirmation is unavailable")
        payload = _canonical_task(getattr(task, "kind", ""), getattr(task, "payload", None))
        if task.kind != HOUSE_SECURITY_KIND:
            raise ConfirmationError("task does not require strong confirmation")
        return self._confirmations.mint(
            **self._task_binding(task, payload), ttl_seconds=ttl_seconds
        )

    def confirm(self, token: str, task) -> dict:
        if self._confirmations is None:
            raise ConfirmationError("strong confirmation is unavailable")
        payload = _canonical_task(getattr(task, "kind", ""), getattr(task, "payload", None))
        return self._confirmations.confirm(token, **self._task_binding(task, payload))

    @staticmethod
    def _entity(snapshot: HouseSnapshot, entity_id: str) -> HouseEntity | None:
        return next((item for item in snapshot.entities if item.entity_id == entity_id), None)

    @staticmethod
    def _verified(entity: HouseEntity | None, payload: Mapping) -> bool:
        if entity is None:
            return False
        if payload["control"] == "light":
            if entity.state != payload["action"]:
                return False
            if "brightness_pct" in payload:
                attrs = dict(entity.attributes)
                if attrs.get("brightness_pct") == str(payload["brightness_pct"]):
                    return True
                try:
                    actual_pct = round(float(attrs["brightness"]) * 100 / 255)
                    return abs(actual_pct - int(payload["brightness_pct"])) <= 2
                except (KeyError, TypeError, ValueError):
                    return False
            return True
        if payload["control"] == "climate":
            if payload["action"] == "set_mode":
                return entity.state == str(payload["value"])
            try:
                return (
                    abs(float(dict(entity.attributes).get("temperature")) - float(payload["value"]))
                    <= 0.1
                )
            except (TypeError, ValueError):
                return False
        return entity.state == _intended_state(payload)

    @staticmethod
    def _restore(pre: HouseEntity, payload: Mapping) -> dict | None:
        if payload["control"] == "light":
            restore = _canonical_light(pre.entity_id, pre.state)
            attrs = dict(pre.attributes)
            brightness = attrs.get("brightness_pct")
            if brightness is None and attrs.get("brightness") is not None:
                brightness = round(float(attrs["brightness"]) * 100 / 255)
            if pre.state == "on" and brightness is not None:
                restore["brightness_pct"] = int(float(brightness))
            return restore
        if payload["control"] == "climate":
            if payload["action"] == "set_temperature":
                temperature = dict(pre.attributes).get("temperature")
                if temperature is None:
                    return None
                return _canonical_climate(pre.entity_id, "set_temperature", float(temperature))
            return _canonical_climate(pre.entity_id, "set_mode", pre.state)
        reverse = {
            "locked": "lock",
            "unlocked": "unlock",
            "armed_home": "arm_home",
            "armed_away": "arm_away",
            "disarmed": "disarm",
            "open": "open",
            "closed": "close",
        }.get(pre.state)
        return _canonical_security(pre.entity_id, reverse) if reverse else None

    async def _rollback(
        self, task, pre: HouseEntity, current: HouseEntity | None, payload: dict
    ) -> dict:
        try:
            restore = self._restore(pre, payload)
        except ValueError:
            # Pre-actuation state wasn't a canonical value (e.g. 'unavailable') —
            # report the same 'unavailable' shape rather than letting the restore
            # raise and silently vanish (execute_task then marks it manual).
            return {"status": "unavailable", "reason": "restore_state_unavailable"}
        if restore is None:
            return {"status": "unavailable", "reason": "restore_state_unavailable"}
        if self._verified(current, restore):
            return {"status": "not_needed"}
        result = await self._actions.perform(
            _RECOVERY_CAPABILITY,
            restore,
            PerformContext(
                agent=getattr(task, "agent", "jarvis"),
                title=f"recover {pre.entity_id}",
                capability_name=HOUSE_RECOVERY_KIND,
                scope=f"house:{pre.entity_id}",
            ),
        )
        if result.status != "completed":
            return {"status": "failed", "reason": "kernel_denied"}
        try:
            verified_snapshot = await self._state_reader.snapshot()
        except Exception:
            return {"status": "failed", "reason": "recovery_verification_unavailable"}
        if self._verified(self._entity(verified_snapshot, pre.entity_id), restore):
            return {"status": "verified"}
        return {"status": "failed", "reason": "recovery_verification_failed"}

    async def execute_task(self, task) -> dict:
        try:
            task_id = int(task.id)
            kind = str(task.kind)
            payload = _canonical_task(kind, getattr(task, "payload", None))
        except (AttributeError, TypeError, ValueError):
            return {"status": "failed", "reason": "invalid_payload", "verified": False}
        digest = _payload_hash(payload)
        # Ledger ops are sync sqlite round-trips (lookup/begin/finish/abort);
        # execute_task runs on the loop via the autonomy executor, so offload.
        ledger_state, cached = await asyncio.to_thread(self._ledger.lookup, task_id, digest)
        if ledger_state == "cached":
            return cached or {"status": "failed", "reason": "cached_result_missing"}
        if ledger_state == "conflict":
            return {"status": "failed", "reason": "task_payload_changed", "verified": False}
        if ledger_state == "running":
            return {"status": "failed", "reason": "execution_in_progress", "verified": False}

        try:
            snapshot, pre = await self._snapshot_entity(payload["entity_id"])
        except Exception:
            return {"status": "failed", "reason": "house_state_unavailable", "verified": False}
        reason = self._precondition_reason(snapshot, pre)
        if reason:
            return {"status": "failed", "reason": reason, "verified": False}
        if kind == HOUSE_SECURITY_KIND and (
            self._confirmations is None
            or not await asyncio.to_thread(
                self._confirmations.consume, **self._task_binding(task, payload)
            )
        ):
            return {
                "status": "failed",
                "reason": "strong_confirmation_required",
                "verified": False,
            }
        if not await asyncio.to_thread(self._ledger.begin, task_id, digest):
            return {"status": "failed", "reason": "execution_in_progress", "verified": False}

        capability = _SECURITY_CAPABILITY if kind == HOUSE_SECURITY_KIND else _CONTROL_CAPABILITY
        perform = await self._actions.perform(
            capability,
            payload,
            PerformContext(
                agent=getattr(task, "agent", "jarvis"),
                title=f"execute {payload['entity_id']}",
                capability_name=kind,
                scope=f"house:{payload['entity_id']}",
            ),
        )
        if perform.status in {"disabled", "refused", "queued"}:
            result = {
                "status": "failed",
                "reason": "kernel_denied",
                "verified": False,
                "manual_recovery_required": False,
            }
            await asyncio.to_thread(self._ledger.abort, task_id)
            return result

        try:
            post = await self._state_reader.snapshot()
            current = self._entity(post, payload["entity_id"])
        except Exception:
            post = None
            current = None
        if post is not None and post.status == "live" and self._verified(current, payload):
            result = {
                "status": "verified",
                "reason": "state_verified",
                "verified": True,
                "manual_recovery_required": False,
            }
            await asyncio.to_thread(self._ledger.finish, task_id, result)
            return result

        rollback = await self._rollback(task, pre, current, payload)
        manual = rollback["status"] not in {"verified", "not_needed"}
        result = {
            "status": "failed",
            "reason": "verification_failed",
            "verified": False,
            "rollback": rollback,
            "manual_recovery_required": manual,
        }
        await asyncio.to_thread(self._ledger.finish, task_id, result)
        return result


def register_house_handlers(executor, actuator: HouseActuator):
    async def _execute(task):
        result = await actuator.execute_task(task)
        if result.get("status") == "failed":
            raise HouseActuationError(str(result.get("reason") or "house actuation failed"))
        return result

    executor.register(HOUSE_CONTROL_KIND, _execute)
    executor.register(HOUSE_SECURITY_KIND, _execute)
    return executor
