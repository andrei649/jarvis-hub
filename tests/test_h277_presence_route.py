"""H277: an explicit, local-only production consumer for presence explanation."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.core import settings_db
from agents.core.house import HousePresenceIngestor, PresenceInference
from agents.core.house.contracts import HouseSnapshot
from agents.core.llm import data_handling as dh
from agents.core.llm.egress import llm_async_client
from agents.core.llm.providers import get_profile
from agents.core.routers import house as house_routes
from tests.test_h30_presence import _evidence, _store


@pytest.fixture
def presence_client(tmp_path, monkeypatch):
    from agents import web
    from agents.core.routers._deps import user_guard

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-presence-route")
    store = _store(tmp_path)
    engine = PresenceInference(store, clock=lambda: 1_000.0, private_rooms=("bedroom",))
    engine.infer("Alice Example", [
        _evidence("bluetooth", room="bedroom", confidence=0.9),
        _evidence("motion", room="bedroom", occupant="", confidence=0.9),
    ])
    requests = []

    async def generate(model, prompt, **kwargs):
        requests.append((model, json.loads(prompt), kwargs))
        return "Evidence supports presence; the room is private."

    client = llm_async_client(
        "lm-studio", base_url="http://127.0.0.1:1234", trust_env=False,
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected model HTTP request")),
    )
    backend = SimpleNamespace(
        profile=get_profile("lm-studio"), base_url="http://127.0.0.1:1234",
        client=client, generate=generate,
    )
    llm_router = SimpleNamespace(
        local_backend=backend, active_model="synthetic-presence",
        _backend=backend, _local_model="synthetic-presence",
    )

    async def snapshot():
        return HouseSnapshot(enabled=True, status="live", observed_at=1_000.0)

    runtime = SimpleNamespace(
        adapter=SimpleNamespace(snapshot=snapshot), private_store=store,
        presence_ingestor=HousePresenceIngestor(engine),
    )

    async def get_runtime():
        return runtime

    monkeypatch.setattr(house_routes, "_get_runtime", get_runtime)
    monkeypatch.setattr(house_routes, "get_orch", lambda: SimpleNamespace(llm_router=llm_router))
    web.app.dependency_overrides[user_guard] = lambda: None
    try:
        yield TestClient(web.app), runtime, backend, requests, store.pseudonym_for("Alice Example")
    finally:
        web.app.dependency_overrides.pop(user_guard, None)
        asyncio.run(client.aclose())


def test_explicit_presence_explanation_uses_private_decision_and_never_identity(presence_client):
    http, runtime, _backend, requests, occupant_id = presence_client

    result = http.post("/api/house/presence/explain", json={"occupant_id": occupant_id})

    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "explained"
    assert body["decision"]["status"] == "present"
    assert body["decision"]["privacy_context"] == "private"
    assert body["decision"]["room_id"] == ""
    assert body["explanation"] == "Evidence supports presence; the room is private."
    assert len(requests) == 1
    assert requests[0][1]["room_id"] == ""
    assert "Alice Example" not in str(body) + str(requests)
    assert "bedroom" not in str(body) + str(requests)
    assert "no-store" in result.headers.get("cache-control", "")


def test_presence_explanation_refuses_off_unknown_and_nonlocal(presence_client):
    http, runtime, backend, requests, occupant_id = presence_client

    runtime.presence_ingestor = None
    assert http.post("/api/house/presence/explain", json={"occupant_id": occupant_id}).status_code == 409
    runtime.presence_ingestor = HousePresenceIngestor(
        PresenceInference(runtime.private_store, clock=lambda: 1_000.0)
    )
    assert http.post("/api/house/presence/explain", json={"occupant_id": "occ-" + "0" * 32}).status_code == 404
    backend.base_url = "https://synthetic.invalid/v1"
    refused = http.post("/api/house/presence/explain", json={"occupant_id": occupant_id})
    assert refused.status_code == 503
    assert requests == []


def test_presence_explanation_refuses_stale_snapshot_and_degraded_answer(presence_client):
    http, runtime, backend, requests, occupant_id = presence_client

    async def degraded_snapshot():
        return HouseSnapshot(enabled=True, status="degraded", observed_at=1_000.0)

    runtime.adapter.snapshot = degraded_snapshot
    unavailable = http.post("/api/house/presence/explain", json={"occupant_id": occupant_id})
    assert unavailable.status_code == 503
    assert requests == []

    async def live_snapshot():
        return HouseSnapshot(enabled=True, status="live", observed_at=1_000.0)

    runtime.adapter.snapshot = live_snapshot

    async def degraded_answer(model, prompt, **kwargs):
        requests.append(prompt)
        return "⚠️ local backend unavailable"

    backend.generate = degraded_answer
    degraded = http.post("/api/house/presence/explain", json={"occupant_id": occupant_id})
    assert degraded.status_code == 503
    assert degraded.json()["reason"] == "explanation_failed"


def test_state_read_never_calls_explainer(presence_client):
    http, runtime, _backend, requests, _occupant_id = presence_client
    runtime.graph = SimpleNamespace(
        project_snapshot=lambda snapshot: {"status": "projected"},
        query_state=lambda **kwargs: {"rooms": [], "devices": []},
    )
    runtime.private_status = "live"
    payload = http.get("/api/house/state").json()
    assert payload["presence"]
    assert requests == []
