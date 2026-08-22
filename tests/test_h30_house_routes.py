"""H30.5 — bounded House Brain API and owner confirmation surface."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.core.autonomy.queue import Task
from agents.core.house.contracts import HouseArea, HouseEntity, HouseSnapshot
from agents.core.routers import house as house_routes


class _Adapter:
    def __init__(self, snapshot: HouseSnapshot):
        self.value = snapshot

    async def snapshot(self) -> HouseSnapshot:
        return self.value


class _Graph:
    def __init__(self, state=None):
        self.state = state or {
            "status": "empty",
            "observed_at": 0.0,
            "confidence": 0.0,
            "freshness_seconds": None,
            "rooms": [],
            "devices": [],
        }
        self.projected = []

    def project_snapshot(self, snapshot):
        self.projected.append(snapshot)
        return {"status": "projected"}

    def query_state(self, *, limit=500):
        assert limit == 500
        return self.state


class _PrivateStore:
    def __init__(self, facts):
        self.facts = facts

    def query(self, *, limit=500):
        assert limit == 500
        return self.facts


class _Actuator:
    def __init__(self):
        self.calls = []

    async def request_light(self, entity_id, *, state, brightness_pct=None, agent="jarvis"):
        self.calls.append(("light", entity_id, state, brightness_pct, agent))
        return {"ok": True, "queued": True, "task_id": 11, "reason": "approval_required"}

    async def request_climate(self, entity_id, *, action, value, agent="jarvis"):
        self.calls.append(("climate", entity_id, action, value, agent))
        return {"ok": False, "queued": False, "reason": "house_state_stale"}

    async def request_security(self, entity_id, *, action, agent="jarvis"):
        self.calls.append(("security", entity_id, action, agent))
        return {
            "ok": True,
            "queued": True,
            "task_id": 77,
            "strong_confirmation_required": True,
        }

    def mint_confirmation(self, task):
        self.calls.append(("mint", task.id, task.kind, dict(task.payload)))
        return {
            "status": "challenge_minted",
            "task_id": task.id,
            "token": "server-minted-token",
            "target": task.payload["entity_id"],
            "intended_state": "unlocked",
            "expires_at": 999.0,
        }

    def confirm(self, token, task):
        self.calls.append(("confirm", token, task.id, task.kind, dict(task.payload)))
        return {"status": "confirmed", "confirmation_id": 9, "receipt": "receipt-token"}


@dataclass
class _Runtime:
    adapter: object
    graph: object
    private_store: object | None
    actuator: object
    queue: object | None = None
    private_status: str = "live"
    confirmation_status: str = "live"


def _snapshot(*, enabled=True, status="live", reason=""):
    return HouseSnapshot(
        enabled=enabled,
        status=status,
        observed_at=100.0,
        reason=reason,
        areas=(HouseArea("kitchen", "Kitchen"),) if status == "live" else (),
        entities=(
            HouseEntity(
                "light.kitchen",
                "light",
                "Kitchen light",
                "on",
                area_id="kitchen",
                updated_at=100.0,
            ),
        )
        if status == "live"
        else (),
    )


def _task(task_id=77, kind="house.security_control", entity_id="lock.front"):
    return Task(
        id=task_id,
        agent="jarvis",
        kind=kind,
        title="security unlock",
        payload={
            "version": 1,
            "control": "security",
            "entity_id": entity_id,
            "action": "unlock",
            "risk_tier": 3,
            "reversible": False,
            "signal_quality": 1.0,
        },
        risk_tier=3,
        status="proposed",
        autonomy_level="ask",
        origin="generated",
        attempts=0,
        result=None,
        decided_by=None,
        decision=None,
        pushed=0,
        created_at="2026-07-13T00:00:00Z",
        updated_at="2026-07-13T00:00:00Z",
    )


@pytest.fixture
def client(monkeypatch):
    from agents import web
    from agents.core.routers._deps import admin_guard, user_guard

    web.app.dependency_overrides[user_guard] = lambda: None
    web.app.dependency_overrides[admin_guard] = lambda: None
    runtime = _Runtime(_Adapter(_snapshot()), _Graph(), None, _Actuator())

    # The router's runtime accessor is async; handlers await it.
    async def _runtime_override():
        return runtime

    monkeypatch.setattr(house_routes, "_get_runtime", _runtime_override)
    try:
        yield TestClient(web.app), runtime
    finally:
        web.app.dependency_overrides.pop(user_guard, None)
        web.app.dependency_overrides.pop(admin_guard, None)


@pytest.mark.parametrize(
    ("snapshot", "expected_status", "expected_reason"),
    [
        (_snapshot(enabled=False, status="disabled", reason="house_brain_disabled"), "disabled", "house_brain_disabled"),
        (_snapshot(status="degraded", reason="rest_unavailable"), "degraded", "rest_unavailable"),
        (_snapshot(status="live"), "live", ""),
    ],
)
def test_house_state_reports_disabled_degraded_and_live_honestly(
    client, snapshot, expected_status, expected_reason
):
    http, runtime = client
    runtime.adapter.value = snapshot

    response = http.get("/api/house/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is snapshot.enabled
    assert payload["status"] == expected_status
    assert payload["reason"] == expected_reason
    assert "no-store" in response.headers.get("cache-control", "")
    assert len(runtime.graph.projected) == (1 if snapshot.status == "live" else 0)


def test_house_state_is_bounded_and_filters_private_identity_and_room(client):
    http, runtime = client
    occupant_private = "occ-" + "a" * 32
    occupant_shared = "occ-" + "b" * 32
    rooms = [
        {"room_id": f"room-{i}", "name": f"Room {i}", "observed_at": 100.0}
        for i in range(700)
    ]
    devices = [
        {
            "entity_id": f"light.device_{i}",
            "domain": "light",
            "state": "on",
            "room_id": f"room-{i}",
            "observed_at": 100.0,
        }
        for i in range(700)
    ]
    runtime.graph.state = {
        "status": "live",
        "observed_at": 100.0,
        "confidence": 1.0,
        "freshness_seconds": 1.0,
        "rooms": rooms,
        "devices": devices,
    }
    runtime.private_store = _PrivateStore(
        [
            {"subject_id": occupant_private, "predicate": "presence_status", "object": "present", "confidence": 0.9, "fresh": True},
            {"subject_id": occupant_private, "predicate": "present_in", "object": "bedroom", "confidence": 0.9, "fresh": True},
            {"subject_id": occupant_private, "predicate": "privacy_context", "object": "private", "confidence": 1.0, "fresh": True},
            {"subject_id": occupant_private, "predicate": "identity_link", "object": "Alice Example", "confidence": 1.0, "fresh": True},
            {"subject_id": occupant_shared, "predicate": "presence_status", "object": "present", "confidence": 0.8, "fresh": True},
            {"subject_id": occupant_shared, "predicate": "present_in", "object": "kitchen", "confidence": 0.8, "fresh": True},
            {"subject_id": "raw-person-name", "predicate": "present_in", "object": "office", "confidence": 1.0, "fresh": True},
        ]
    )

    payload = http.get("/api/house/state").json()

    assert len(payload["rooms"]) == 500
    assert len(payload["devices"]) == 500
    assert payload["presence"] == [
        {
            "occupant_id": occupant_private,
            "status": "present",
            "privacy": "private",
            "confidence": 0.9,
            "fresh": True,
        },
        {
            "occupant_id": occupant_shared,
            "status": "present",
            "room_id": "kitchen",
            "privacy": "household",
            "confidence": 0.8,
            "fresh": True,
        },
    ]
    rendered = str(payload)
    assert "Alice Example" not in rendered
    assert "raw-person-name" not in rendered
    assert "bedroom" not in rendered


def test_house_state_degrades_honestly_when_the_adapter_raises(client):
    http, runtime = client

    async def _broken_snapshot():
        raise RuntimeError("credential and host detail must not escape")

    runtime.adapter.snapshot = _broken_snapshot

    response = http.get("/api/house/state")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "status": "degraded",
        "reason": "house_state_unavailable",
        "observed_at": 0.0,
        "confidence": 0.0,
        "freshness_seconds": None,
        "rooms": [],
        "devices": [],
        "presence": [],
        "privacy_status": runtime.private_status,
    }


def test_house_state_marks_private_store_read_failures_degraded(client):
    http, runtime = client

    class _BrokenPrivateStore:
        def query(self, *, limit=500):
            raise RuntimeError("private path and key detail must not escape")

    runtime.private_store = _BrokenPrivateStore()
    runtime.private_status = "live"

    payload = http.get("/api/house/state").json()

    assert payload["status"] == "live"
    assert payload["presence"] == []
    assert payload["privacy_status"] == "degraded"
    assert "private path" not in str(payload)


def test_narrow_control_routes_preserve_governance_outcomes(client):
    http, runtime = client

    light = http.post(
        "/api/house/control/light",
        json={"entity_id": "light.kitchen", "state": "on", "brightness_pct": 45},
    )
    climate = http.post(
        "/api/house/control/climate",
        json={"entity_id": "climate.living", "action": "set_temperature", "value": 21.5},
    )
    security = http.post(
        "/api/house/control/security",
        json={"entity_id": "lock.front", "action": "unlock"},
    )

    assert light.json() == {
        "enabled": True,
        "status": "queued",
        "reason": "approval_required",
        "task_id": 11,
        "strong_confirmation_required": False,
    }
    assert climate.json() == {
        "enabled": True,
        "status": "denied",
        "reason": "house_state_stale",
        "strong_confirmation_required": False,
    }
    assert security.json() == {
        "enabled": True,
        "status": "queued",
        "reason": "strong_confirmation_required",
        "task_id": 77,
        "strong_confirmation_required": True,
    }
    assert [call[0] for call in runtime.actuator.calls] == ["light", "climate", "security"]


def test_control_routes_reject_extra_fields_and_invalid_targets(client):
    http, runtime = client

    smuggled = http.post(
        "/api/house/control/light",
        json={"entity_id": "light.kitchen", "state": "on", "service": "unlock"},
    )
    invalid = http.post(
        "/api/house/control/security",
        json={"entity_id": "light.kitchen", "action": "unlock"},
    )

    assert smuggled.status_code == 422
    assert invalid.status_code == 422
    assert runtime.actuator.calls == []


def test_admin_challenge_is_minted_only_from_the_exact_durable_security_task(client):
    http, runtime = client
    task = _task()
    runtime.queue = SimpleNamespace(get=lambda task_id: task if task_id == 77 else None)

    response = http.post(
        "/api/house/security/77/challenge",
        json={"entity_id": "lock.other", "action": "lock"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "challenge_minted"
    assert payload["task_id"] == 77
    assert payload["target"] == "lock.front"
    assert runtime.actuator.calls[-1] == ("mint", 77, "house.security_control", task.payload)


def test_admin_confirmation_accepts_only_the_server_challenge_token(client):
    http, runtime = client
    task = _task()
    runtime.queue = SimpleNamespace(get=lambda task_id: task if task_id == 77 else None)

    confirmed = http.post(
        "/api/house/security/77/confirm",
        json={"challenge_token": "server-minted-token"},
    )
    smuggled = http.post(
        "/api/house/security/77/confirm",
        json={"challenge_token": "server-minted-token", "entity_id": "lock.other"},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert smuggled.status_code == 422
    assert runtime.actuator.calls == [
        ("confirm", "server-minted-token", 77, "house.security_control", task.payload)
    ]


@pytest.mark.parametrize(
    ("task", "expected"),
    [(None, 404), (_task(kind="house.control", entity_id="light.kitchen"), 409)],
)
def test_confirmation_refuses_missing_or_non_security_tasks(client, task, expected):
    http, runtime = client
    runtime.queue = SimpleNamespace(get=lambda _task_id: task)

    assert http.post("/api/house/security/77/challenge").status_code == expected
    assert runtime.actuator.calls == []


def test_confirmation_refuses_terminal_security_tasks(client):
    http, runtime = client
    task = _task()
    task.status = "completed"
    runtime.queue = SimpleNamespace(get=lambda _task_id: task)

    response = http.post("/api/house/security/77/challenge")

    assert response.status_code == 409
    assert response.json()["reason"] == "task_not_confirmable"
    assert runtime.actuator.calls == []


@pytest.mark.asyncio
async def test_runtime_keeps_reads_available_when_local_actuation_storage_fails(monkeypatch):
    class _EnabledAdapter:
        config = SimpleNamespace(enabled=True, ha_enabled=True)

        def __init__(self, *_args, **_kwargs):
            pass

    class _BrokenConfirmation:
        def __init__(self, *_args, **_kwargs):
            raise OSError("disk unavailable")

    class _BrokenActuator:
        def __init__(self, *_args, **_kwargs):
            raise OSError("disk unavailable")

    monkeypatch.setattr(house_routes, "StrongConfirmationStore", _BrokenConfirmation)
    monkeypatch.setattr(house_routes, "HouseActuator", _BrokenActuator)
    monkeypatch.setattr(house_routes, "HomeAssistantAdapter", _EnabledAdapter)

    runtime = house_routes._build_runtime(None)
    result = await runtime.actuator.request_light("light.kitchen", state="on")

    assert runtime.confirmation_status == "unavailable"
    assert result == {"ok": False, "queued": False, "reason": "house_actuation_unavailable"}


@pytest.mark.asyncio
async def test_default_off_runtime_constructs_no_private_or_actuation_storage(monkeypatch):
    class _DisabledAdapter:
        config = SimpleNamespace(enabled=False, ha_enabled=False)

        def __init__(self, *_args, **_kwargs):
            pass

    def _must_not_construct(*_args, **_kwargs):
        raise AssertionError("default-off runtime must not construct storage")

    monkeypatch.setattr(house_routes, "HomeAssistantAdapter", _DisabledAdapter)
    monkeypatch.setattr(house_routes, "PrivateHouseStore", _must_not_construct)
    monkeypatch.setattr(house_routes, "StrongConfirmationStore", _must_not_construct)
    monkeypatch.setattr(house_routes, "HouseActuator", _must_not_construct)

    runtime = house_routes._build_runtime(None)
    result = await runtime.actuator.request_security("lock.front", action="unlock")

    assert runtime.private_status == "disabled"
    assert result == {"ok": False, "queued": False, "reason": "house_brain_disabled"}
    assert house_routes._action_response(result, security=True) == {
        "enabled": False,
        "status": "disabled",
        "reason": "house_brain_disabled",
        "strong_confirmation_required": True,
    }


def test_confirmation_is_honestly_unavailable_without_queue_or_secret_store(client):
    http, runtime = client
    runtime.queue = None
    runtime.confirmation_status = "unavailable"

    response = http.post("/api/house/security/77/challenge")

    assert response.status_code == 503
    assert response.json() == {
        "enabled": True,
        "status": "unavailable",
        "reason": "strong_confirmation_unavailable",
    }
