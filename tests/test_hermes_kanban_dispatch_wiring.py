"""The approved Kanban controller is reachable only through governed app seams."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import Task
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.commands import Principal
from agents.core.kanban.dispatcher import KanbanDispatcher
from agents.core.routers import autonomy as autonomy_router
from agents.core.routers._deps import admin_guard
from agents.core.settings_db import DEFAULTS


def queue_task():
    return Task(
        id=17,
        agent="builder",
        kind=KanbanDispatcher.KIND,
        title="synthetic card",
        payload={"task_id": "t_1", "submission_id": "s_1"},
        risk_tier=2,
        status="running",
        autonomy_level="ask",
        origin="generated",
        attempts=0,
        result=None,
        decided_by="owner",
        decision="accept",
        pushed=1,
        created_at="2026-10-04T00:00:00Z",
        updated_at="2026-10-04T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_executor_registers_cached_controller_under_existing_execution_guard(monkeypatch):
    from tests.test_web_tools_wiring import _coordinator

    coordinator = _coordinator({})
    allow = False
    guarded = []

    def guard(task):
        guarded.append(task.id)
        return allow

    coordinator._orch.autonomy.execution_allowed = guard
    controller = coordinator.kanban_dispatcher()
    invoked = []

    async def execute(task):
        invoked.append(task.id)
        return {"status": "ok", "task_id": task.id}

    monkeypatch.setattr(controller, "execute", execute)
    executor = coordinator.build_executor()
    assert coordinator.kanban_dispatcher() is controller
    assert executor.execution_guard is guard
    assert executor.handles(KanbanDispatcher.KIND)
    assert (await executor.execute(queue_task()))["status"] == "refused"
    assert invoked == []
    allow = True
    assert await executor.execute(queue_task()) == {"status": "ok", "task_id": 17}
    assert guarded == [17, 17]
    assert invoked == [17]


def route_orchestrator():
    orch = SimpleNamespace(get_setting=lambda key, default=None: default)
    orch._autonomy = AutonomyCoordinator(orch)
    return orch


@pytest.mark.asyncio
async def test_admin_route_uses_cached_controller_and_bounds_request(monkeypatch):
    from agents import web

    orch = route_orchestrator()
    monkeypatch.setattr(autonomy_router, "get_orch", lambda: orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "synthetic-admin")

    class TokenStore:
        def verify(self, token):
            return None

        def env_revoked(self, scope):
            return False

        def list_tokens(self):
            return []

    monkeypatch.setattr(web, "get_token_store", lambda: TokenStore())
    monkeypatch.delitem(web.app.dependency_overrides, admin_guard, raising=False)
    controller = orch._autonomy.kanban_dispatcher()
    calls = []

    async def request(principal, *, board, limit):
        calls.append((principal, board, limit))
        return {"ok": True, "status": "queued", "queued": []}

    monkeypatch.setattr(controller, "request", request)
    client = TestClient(web.app)
    url = "/api/autonomy/kanban/dispatch"
    assert client.post(url, json={"board": "default", "limit": 2}).status_code == 401
    response = client.post(
        url, headers={"X-Admin-Token": "synthetic-admin"}, json={"board": "research", "limit": 2}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert calls == [(Principal(channel="web", admin=True), "research", 2)]
    assert orch._autonomy.kanban_dispatcher() is controller
    for body in (
        {"board": "../escape", "limit": 2},
        {"board": "default", "limit": 17},
        {"board": "default", "limit": True},
        {"board": "default", "limit": 1, "extra": "no"},
    ):
        assert (
            client.post(url, headers={"X-Admin-Token": "synthetic-admin"}, json=body).status_code
            == 422
        )
    assert len(calls) == 1


def test_disabled_governed_runtime_gives_meaningful_route_refusal(monkeypatch):
    from agents import web

    orch = route_orchestrator()
    monkeypatch.setattr(autonomy_router, "get_orch", lambda: orch)
    monkeypatch.setitem(web.app.dependency_overrides, admin_guard, lambda: None)
    response = TestClient(web.app).post("/api/autonomy/kanban/dispatch", json={})
    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "status": "refused",
        "reason": "governed_worker_unavailable",
        "queued": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["disabled", "enabled", "unavailable"])
async def test_coordinator_loop_intakes_only_when_flags_enabled_and_keeps_normal_tick(
    monkeypatch,
    state,
):
    from agents.core import estop

    events = []

    async def normal_tick(**kwargs):
        events.append("normal")

    enabled = state == "enabled"
    configured = state != "disabled"
    settings = {
        "llm.kanban": configured,
        "llm.kanban_dispatch": configured,
        "llm.tool_loop_enabled": configured,
        "system.error_backlog_sync_enabled": False,
    }

    def get_setting(key, default=None):
        if state == "unavailable" and key == "llm.kanban_dispatch":
            raise RuntimeError("settings temporarily unavailable")
        return settings.get(key, default)

    orch = SimpleNamespace(
        get_setting=get_setting,
        autonomy=SimpleNamespace(policy=AutonomyPolicy(), budget=None, tick=normal_tick),
        observer=None,
        event_watcher=None,
        reflector=None,
        curator=None,
        cognition=None,
        ingestion_watcher=None,
    )
    coordinator = AutonomyCoordinator(orch)

    async def dispatch_tick():
        events.append("dispatch")
        return {"ok": True, "status": "queued", "queued": []}

    if enabled:
        monkeypatch.setattr(coordinator.kanban_dispatcher(), "tick", dispatch_tick)

    async def no_drain():
        return None

    monkeypatch.setattr(coordinator, "_drain_workflow_pending", no_drain)
    monkeypatch.setattr(
        coordinator,
        "_record_cycle",
        lambda **kwargs: events.append("record-ok" if kwargs["ok"] else "record-failed"),
    )
    monkeypatch.setattr(estop, "check_paused", lambda *args: False)
    sleeps = 0

    async def one_cycle(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", one_cycle)
    with pytest.raises(asyncio.CancelledError):
        await coordinator.loop()
    assert events == (["normal", "dispatch", "record-ok"] if enabled else ["normal", "record-ok"])
    if not enabled:
        assert coordinator._kanban_dispatcher is None


def test_dispatch_settings_are_default_off_with_separate_total_and_agent_caps():
    llm = {row["key"]: row for row in DEFAULTS if row["category"] == "llm"}
    assert llm["kanban"]["value"] is False
    assert "separate" in llm["kanban"]["label"].lower()
    assert llm["kanban_dispatch"]["value"] is False
    assert llm["kanban_max_workers"]["value"] == 2
    assert llm["kanban_max_workers_per_agent"]["value"] == 1
