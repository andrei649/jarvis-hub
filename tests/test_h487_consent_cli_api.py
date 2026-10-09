"""CLI list and exact choices use the existing authenticated owner routes."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.core.routers import _deps
from agents.core.routers import autonomy as routes
from agents.core.routers._deps import admin_guard
from tests.test_h487_consent_runtime_integration import ask, consent_runtime  # noqa: F401


def _app(runtime, monkeypatch):
    monkeypatch.setattr(routes, 'get_orch', lambda: runtime.orch)
    monkeypatch.setattr(_deps, '_web', lambda: SimpleNamespace(
        _admin_credential_ok=lambda supplied: supplied == 'synthetic-cli-owner',
        _admin_configured=lambda: True,
    ))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[admin_guard] = lambda: None
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'always', 'deny'])
async def test_cli_listing_and_choice_share_one_exact_owner_offer(consent_runtime, monkeypatch, choice):
    runtime = consent_runtime
    task = await ask(runtime)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(runtime, monkeypatch)),
                                 base_url='http://test') as client:
        listed = (await client.get('/autonomy/approvals')).json()
        row = next(t for t in listed['pending'] if t['id'] == task.id)
        offer = row['consent_offer']
        assert offer['count'] == 1 and offer['choices'] == ['session', 'always', 'deny']
        assert all(set(category) == {'description', 'permanent'} for category in offer['categories'])
        assert set(offer) == {'revision', 'count', 'choices', 'categories'}
        response = await client.post(f'/autonomy/tasks/{task.id}/consent',
            headers={'X-Admin-Token': 'synthetic-cli-owner'},
            json={'choice': choice, 'revision': offer['revision'], 'reason': 'synthetic CLI reason'})
        assert response.status_code == 200 and response.json()['ok'] is True
        row = runtime.q.get(task.id)
        assert row.status == ('rejected' if choice == 'deny' else 'approved')
        assert row.human_decision['action'] == choice
        assert row.human_decision['reason'] == 'synthetic CLI reason'
        assert row.decided_by == 'admin'


@pytest.mark.asyncio
async def test_cli_copied_revision_refuses_changed_followers(consent_runtime, monkeypatch):
    runtime = consent_runtime
    first = await ask(runtime)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(runtime, monkeypatch)),
                                 base_url='http://test') as client:
        old = (await client.get('/autonomy/approvals')).json()['pending'][0]['consent_offer']
        second = await ask(runtime)
        response = await client.post(f'/autonomy/tasks/{first.id}/consent',
            headers={'X-Admin-Token': 'synthetic-cli-owner'},
            json={'choice': 'always', 'revision': old['revision']})
        assert response.status_code == 409
        assert all(runtime.q.get(t.id).status == 'blocked' for t in (first, second))
        fresh = (await client.get('/autonomy/approvals')).json()['pending'][0]['consent_offer']
        assert fresh['count'] == 2 and fresh['revision'] != old['revision']


def test_malformed_private_offer_projection_does_not_invent_cli_authority():
    queue = SimpleNamespace(pending_consent_offer=lambda _task: object())
    assert routes._consent_projection(queue, SimpleNamespace(id=1)) == {}
