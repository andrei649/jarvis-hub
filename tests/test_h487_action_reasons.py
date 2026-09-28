"""H487: trusted action decision text and durable terminal unanswered expiry."""
import asyncio
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.cli.nerva import Context, main
from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.autonomy.approval_judge import JudgeStatus
from agents.core.browser_agent import GovernedBrowser
from agents.core.routers import actions


@pytest.mark.parametrize('approved', [True, False])
def test_reason_is_normalised_persisted_and_audited_only_for_winner(tmp_path, approved):
    path = tmp_path / 'actions.json'
    q = ActionApprovalQueue(path)
    rows = []
    q.attach_audit(SimpleNamespace(record=lambda **row: rows.append(row)))
    item = q.request({'tool': 'delete_file', 'human_reason': 'forged'})
    assert 'human_reason' not in item
    first = q.decide(item['id'], approved, by='owner', reason='  wait\nfor\u200bbackup  ')
    assert first['human_reason'] == 'wait for backup'
    assert q.decide(item['id'], not approved, by='other', reason='overwrite') == first
    assert ActionApprovalQueue(path).get(item['id'])['human_reason'] == 'wait for backup'
    assert len(rows) == 1
    assert rows[0]['metadata']['human_reason'] == 'wait for backup'
    assert rows[0]['metadata']['by'] == 'owner'


@pytest.mark.parametrize('reason', [None, '', ' \n\u200b '])
def test_empty_reason_preserves_legacy_shape(reason):
    q = ActionApprovalQueue()
    item = q.request({'tool': 'delete_file'})
    assert 'human_reason' not in q.decide(item['id'], False, reason=reason)


@pytest.mark.parametrize('reason', [False, 12, [], {}, 'x' * 281])
def test_invalid_reason_cannot_decide_or_write(tmp_path, reason):
    path = tmp_path / 'actions.json'
    q = ActionApprovalQueue(path)
    item = q.request({'tool': 'delete_file'})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        q.decide(item['id'], False, reason=reason)
    assert path.read_bytes() == before and q.get(item['id'])['status'] == 'pending'


async def test_timeout_expires_durably_wakes_all_waiters_and_refuses_late_approval(tmp_path):
    path = tmp_path / 'actions.json'
    q = ActionApprovalQueue(path)
    item = q.request({'tool': 'delete_file'})
    waiting = asyncio.create_task(q.await_decision(item['id']))
    assert await q.await_decision(item['id'], timeout=0.01) == 'expired'
    assert await asyncio.wait_for(waiting, 0.2) == 'expired'
    stored = ActionApprovalQueue(path).get(item['id'])
    assert stored['status'] == 'expired' and stored['expired_at'] > 0
    assert q.stats()['expired'] == 1 and not q.list('pending')
    before = path.read_bytes()
    assert q.decide(item['id'], True, reason='too late')['status'] == 'expired'
    assert path.read_bytes() == before and 'human_reason' not in q.get(item['id'])


async def test_decision_winning_timeout_race_retains_its_reason(monkeypatch):
    q = ActionApprovalQueue()
    item = q.request({'tool': 'delete_file'})

    async def deadline_race(awaitable, timeout=None):
        awaitable.close()
        q.decide(item['id'], True, reason='reviewed')
        raise TimeoutError

    monkeypatch.setattr(asyncio, 'wait_for', deadline_race)
    assert await q.await_decision(item['id'], timeout=0.01) == 'approved'
    assert q.get(item['id'])['human_reason'] == 'reviewed'
    assert q.stats()['expired'] == 0


async def test_expiry_clears_pending_and_drops_late_judge(tmp_path):
    release, entered = asyncio.Event(), asyncio.Event()

    class Judge:
        def status(self):
            return JudgeStatus(True, local=True, timeout=1)

        def wants(self, snapshot, status):
            return True

        async def score(self, snapshot, status):
            entered.set()
            await release.wait()
            return {'score': 1, 'rationale': 'late'}

    q = ActionApprovalQueue(tmp_path / 'actions.json')
    q.attach_judge(Judge())
    item = q.request({'tool': 'delete_file'})
    await asyncio.wait_for(entered.wait(), 0.2)
    assert item['judge_pending'] is True
    assert await q.await_decision(item['id'], timeout=0.01) == 'expired'
    assert 'judge_pending' not in q.get(item['id'])
    before = (tmp_path / 'actions.json').read_bytes()
    release.set()
    await asyncio.gather(*list(q._judge_tasks))
    assert (tmp_path / 'actions.json').read_bytes() == before
    assert 'judge' not in q.get(item['id'])


@pytest.fixture
def action_api(monkeypatch):
    q = ActionApprovalQueue()
    app = FastAPI()
    app.include_router(actions.router)
    app.dependency_overrides[actions.admin_guard] = lambda: None
    monkeypatch.setattr(actions, 'require_component', lambda *args: (SimpleNamespace(), q, None))
    return app, q


@pytest.mark.parametrize('body', [[], 'bad', {'approved': 'false'}, {'approved': 1}, {'approved': False, 'reason': False}, {'approved': False, 'reason': {}}, {'approved': False, 'reason': 'x' * 281}])
async def test_api_invalid_body_leaves_card_pending(action_api, body):
    app, q = action_api
    item = q.request({'tool': 'delete_file'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        reply = await client.post(f"/api/actions/{item['id']}/decide", json=body)
    assert reply.status_code == 400
    assert q.get(item['id'])['status'] == 'pending'


async def test_api_propagates_reason(action_api):
    app, q = action_api
    item = q.request({'tool': 'delete_file'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        reply = await client.post(f"/api/actions/{item['id']}/decide", json={'approved': False, 'reason': ' missing backup '})
    assert reply.status_code == 200
    assert reply.json()['action']['human_reason'] == 'missing backup'


@pytest.mark.parametrize('decision', ['reject', 'accept'])
def test_cli_sends_normalised_optional_reason(decision):
    calls = []
    hub = SimpleNamespace(post=lambda path, body: calls.append((path, body)) or {'task': {'status': 'blocked'}})
    context = Context(environ={}, out=io.StringIO(), err=io.StringIO(), inp=io.StringIO(), client_factory=lambda env: hub)
    assert main(['approvals', decision, '3', '--reason', ' wait\nfor backup '], context=context) == 0
    assert calls == [('/autonomy/tasks/3/decision', {'action': decision, 'reason': 'wait for backup'})]


@pytest.mark.parametrize('approved', [True, False])
async def test_browser_keeps_human_reason_separate_from_machine_outcome(approved):
    q = ActionApprovalQueue()
    calls = []

    async def click(**kwargs):
        calls.append(kwargs)
        return 'clicked'

    browser = GovernedBrowser(driver=SimpleNamespace(click=click), approvals=q, approval_timeout=1)
    run = asyncio.create_task(browser.run_step({'action': 'click', 'selector': '#buy'}))
    await asyncio.sleep(0)
    item = q.list('pending')[0]
    q.decide(item['id'], approved, reason='owner reviewed destination')
    result = await run
    assert result['human_reason'] == 'owner reviewed destination'
    assert result['status'] == ('done' if approved else 'denied')
    if not approved:
        assert result['reason'] == 'rejected' and calls == []
    else:
        assert result['result'] == 'clicked' and len(calls) == 1


async def test_browser_reports_terminal_unanswered_expiry():
    q = ActionApprovalQueue()
    browser = GovernedBrowser(approvals=q, approval_timeout=0.01)
    result = await browser.run_step({'action': 'click', 'selector': '#buy'})
    assert result['status'] == 'denied' and result['reason'] == 'expired_unanswered'
    assert q.get(result['approval_id'])['status'] == 'expired'
