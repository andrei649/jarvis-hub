from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.core.ambient.contracts import AmbientEvent, EventProvenance
from agents.core.ambient.policy import AttentionLedger
from agents.core.ambient.runtime import AmbientRuntime, build_ambient_runtime
from agents.core.routers import ambient as ambient_routes


class _Orch:
    def __init__(self, values, attention_ledger=None):
        self.values = values
        self.attention_ledger = attention_ledger

    def get_setting(self, name, default=None):
        return self.values.get(name, default)


@pytest.fixture
def client(monkeypatch, tmp_path):
    from agents import web
    from agents.core.routers._deps import admin_guard, user_guard

    attention = AttentionLedger(
        tmp_path / "attention.db", timezone_name="Europe/Bucharest", per_day=4
    )
    runtime = build_ambient_runtime(
        _Orch(
            {
                "ambient.enabled": True,
                "ambient.generation": 3,
                "general.timezone": "Europe/Bucharest",
            },
            attention,
        ),
        root=tmp_path / "ambient",
    )
    box = {"runtime": runtime}
    monkeypatch.setattr(ambient_routes, "_get_runtime", lambda: box["runtime"])
    web.app.dependency_overrides[user_guard] = lambda: None
    web.app.dependency_overrides[admin_guard] = lambda: None
    try:
        yield TestClient(web.app), box, attention
    finally:
        web.app.dependency_overrides.pop(user_guard, None)
        web.app.dependency_overrides.pop(admin_guard, None)
        runtime.close()
        attention.close()


def _monitor(version=1):
    return {
        "monitor_id": "monitor.front.private",
        "version": version,
        "source": "camera",
        "schema": "camera.event.v1",
        "subject_id": "resident.alice.private",
        "predicates": [
            {"field": "attributes.label", "operator": "eq", "expected": "person"}
        ],
        "clear_predicates": [],
        "debounce_seconds": 0,
        "hold_seconds": 0,
        "cooldown_seconds": 0,
        "enabled": True,
        "alert_rung": "interrupt",
        "recovery_rung": "monitor",
    }


def test_transparency_reports_disabled_empty_degraded_and_live(client):
    http, box, attention = client
    empty = http.get("/api/ambient/monitors")
    assert empty.status_code == 200
    assert empty.json()["status"] == "empty"
    assert empty.json()["monitors"] == []
    assert empty.json()["attention"] == {
        "status": "ready",
        "reason": "",
        "limit": 4,
        "used": 0,
        "remaining": 4,
    }
    assert "no-store" in empty.headers.get("cache-control", "")

    box["runtime"] = AmbientRuntime(
        False,
        "disabled",
        "ambient_disabled",
        attention_ledger=attention,
    )
    disabled = http.get("/api/ambient/monitors").json()
    assert (disabled["enabled"], disabled["status"], disabled["reason"]) == (
        False,
        "disabled",
        "ambient_disabled",
    )

    box["runtime"] = AmbientRuntime(
        False,
        "degraded",
        "store_corrupt",
        attention_ledger=attention,
    )
    degraded = http.get("/api/ambient/monitors").json()
    assert degraded["status"] == "degraded"
    assert degraded["reason"] == "store_corrupt"


def test_admin_mutations_are_versioned_and_public_projection_is_private(client):
    http, box, _attention = client
    created = http.post("/api/ambient/monitors", json=_monitor())
    assert created.status_code == 201
    assert created.json() == {
        "status": "created",
        "monitor_id": "monitor.front.private",
        "version": 1,
    }

    event = AmbientEvent(
        source="camera",
        schema="camera.event.v1",
        source_event_id="private-event-id",
        subject_id="resident.alice.private",
        occurred_at=1_000,
        observed_at=1_001,
        dedupe_key="camera:private-event-id",
        provenance=EventProvenance(adapter="camera.feed", version=1),
        attributes=(("label", "person"), ("confidence", 0.99)),
        privacy="private",
        consent_generation=9,
        critical=True,
    )
    assert box["runtime"].engine.submit(event)["status"] == "queued"
    box["runtime"].engine.process_tick()

    response = http.get("/api/ambient/monitors")
    payload = response.json()
    assert payload["status"] == "live"
    assert payload["rung_counts"]["interrupt"] == 1
    assert payload["last_decision"] == {
        "monitor_id": "monitor.front.private",
        "transition": "alert",
        "rung": "interrupt",
        "attention_mode": "interrupt",
        "policy_reason": "policy_selected",
        "decided_at": 1001.0,
    }
    assert payload["monitors"][0]["last_decision"] == payload["last_decision"]
    assert payload["sources"] == [
        {
            "source": "camera",
            "status": "live",
            "last_event_at": 1001.0,
            "reason": "",
            "queued": 0,
            "critical_backpressure": 0,
        }
    ]
    serialized = json.dumps(payload).lower()
    for secret in (
        "resident.alice.private",
        "private-event-id",
        "confidence",
        "event_fingerprint",
        "monitor_hash",
        "predicates",
        "subject_id",
        "0.99",
    ):
        assert secret not in serialized

    updated = http.put(
        "/api/ambient/monitors/monitor.front.private", json=_monitor(version=2)
    )
    assert updated.json()["status"] == "updated"
    assert updated.json()["version"] == 2
    assert http.delete("/api/ambient/monitors/monitor.front.private").json() == {
        "status": "deleted",
        "monitor_id": "monitor.front.private",
    }
    assert http.get("/api/ambient/monitors").json()["status"] == "empty"


@pytest.mark.parametrize("method", ["post", "put"])
def test_monitor_mutation_rejects_extra_or_mismatched_fields(client, method):
    http, _box, _attention = client
    body = {**_monitor(), "raw_event": {"private": True}}
    path = "/api/ambient/monitors"
    if method == "put":
        path += "/another.monitor"

    response = getattr(http, method)(path, json=body)

    assert response.status_code == 422


def test_ambient_route_guards_are_user_read_admin_write():
    from agents import web
    from tests.test_route_auth_matrix import _runtime_guards

    guards = _runtime_guards()
    assert guards["GET /api/ambient/monitors"] == "user"
    assert guards["POST /api/ambient/monitors"] == "admin"
    assert guards["PUT /api/ambient/monitors/{monitor_id}"] == "admin"
    assert guards["DELETE /api/ambient/monitors/{monitor_id}"] == "admin"
    assert web.app is not None


def test_ambient_settings_are_seeded_default_off():
    from agents.core.settings_db import DEFAULTS

    values = {
        (item["category"], item["key"]): item["value"]
        for item in DEFAULTS
        if item["category"] == "ambient"
    }
    assert values == {
        ("ambient", "enabled"): False,
        ("ambient", "generation"): 1,
        ("ambient", "quiet_hours_start"): 22,
        ("ambient", "quiet_hours_end"): 7,
    }
