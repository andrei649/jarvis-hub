"""Reusable consent must enter through an authenticated owner route."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agents.core.routers import autonomy
from agents.core.routers._deps import admin_guard

router = autonomy.router


def test_guest_cannot_choose_reusable_consent():
    app = FastAPI()
    app.include_router(router)

    def denied():
        raise HTTPException(status_code=401)

    app.dependency_overrides[admin_guard] = denied
    with TestClient(app) as client:
        response = client.post(
            "/autonomy/tasks/1/consent",
            json={"choice": "session", "revision": "a" * 64},
        )
    assert response.status_code == 401


@pytest.mark.parametrize("extra", [
    {"decided_by": "owner"}, {"principal_key": "owner"},
    {"payload": {"command": "changed"}}, {"choice": "once"},
    {"revision": "a"}, {"reason": "x" * 281},
])
def test_consent_route_refuses_client_authority_and_invalid_choice(extra, monkeypatch):
    monkeypatch.setattr(autonomy, "get_orch", lambda: None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[admin_guard] = lambda: None
    with TestClient(app) as client:
        response = client.post(
            "/autonomy/tasks/1/consent",
            json={"choice": "session", "revision": "a" * 64, **extra},
        )
    assert response.status_code == 422


def test_consent_route_without_runtime_grants_nothing(monkeypatch):
    monkeypatch.setattr(autonomy, "get_orch", lambda: None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[admin_guard] = lambda: None
    with TestClient(app) as client:
        response = client.post(
            "/autonomy/tasks/1/consent",
            json={"choice": "always", "revision": "a" * 64},
        )
    assert response.status_code == 503


def test_forged_consent_marker_cannot_enter_executor_with_mediation_off(tmp_path):
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker

    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    try:
        task_id = queue.enqueue(agent='jarvis', kind='toolrpc.terminal_run',
                                title='synthetic request', payload={'args': {'command': 'ls'}})
        queue._conn.execute(
            "UPDATE tasks SET status='running', decided_by='consent', "
            "decision='auto-consent-always' WHERE id=?", (task_id,),
        )
        queue._conn.commit()
        assert not AutonomyWorker(queue).execution_allowed(queue.get(task_id))
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_tick_holds_invalid_consent_instead_of_using_ordinary_claim(tmp_path):
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker

    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    try:
        task_id = queue.enqueue(agent='jarvis', kind='toolrpc.terminal_run',
                                title='synthetic request', payload={'args': {'command': 'ls'}})
        queue._conn.execute(
            "UPDATE tasks SET status='approved', decided_by='consent', "
            "decision='auto-consent-always' WHERE id=?", (task_id,),
        )
        queue._conn.commit()
        summary = await AutonomyWorker(queue).tick(task_id=task_id)
        assert summary['ran'] == 0 and summary['held'] == 1
        assert queue.get(task_id).status == 'approved'
    finally:
        queue.close()
