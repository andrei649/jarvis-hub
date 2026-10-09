"""Consent-specific pending followers from the registered terminal producer."""

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.autonomy.terminal_consent_categories import terminal_consent_categories
from agents.core.commands import Principal
from tests.test_h487_consent_runtime_integration import ask, consent_runtime  # noqa: F401


@pytest.mark.asyncio
async def test_identical_real_terminal_requests_share_one_exact_owner_choice(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    second = await ask(runtime)
    assert first.id != second.id
    assert first.status == second.status == 'blocked'
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None and offer.member_ids == (first.id, second.id)
    assert runtime.q.pending_consent_offer(second.id).member_ids == offer.member_ids
    if runtime.mode == 'off':
        assert first.kernel_intake_id != second.kernel_intake_id
    else:
        assert first.mediation_receipt['receipt_id'] != second.mediation_receipt['receipt_id']
    result = await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='session',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    assert result is not None and tuple(task.id for task in result.tasks) == offer.member_ids
    assert all(runtime.q.get(task_id).status == 'approved' for task_id in offer.member_ids)


async def _telegram_ask(runtime):
    turn = open_approval_turn(
        session_id='owner-chat', session_instance='instance',
        principal=Principal(channel='telegram', admin=True, sender='second-owner', chat='chat'),
        session_is_live=lambda *_: True,
    )
    token = bind_approval_turn(turn)
    try:
        reply = await runtime.orch.tool_rpc.handle(
            {'tool': 'terminal_run', 'args': {
                'target': 'local-host', 'command': 'git reset --hard',
            }}, actor='jarvis',
        )
        return runtime.q.get(reply['task_id'])
    finally:
        close_approval_turn(turn, token)


@pytest.mark.asyncio
async def test_different_command_and_principal_stay_outside_real_offer(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    changed_command = await ask(runtime, command='git reset --hard HEAD')
    changed_principal = await _telegram_ask(runtime)
    assert terminal_consent_categories('git reset --hard') == terminal_consent_categories(
        'git reset --hard HEAD')
    assert all(task.status == 'blocked' for task in (first, changed_command, changed_principal))
    assert runtime.q.pending_consent_offer(first.id).member_ids == (first.id,)
    assert runtime.q.pending_consent_offer(changed_command.id).member_ids == (changed_command.id,)
    assert runtime.q.pending_consent_offer(changed_principal.id).member_ids == (changed_principal.id,)


@pytest.mark.asyncio
async def test_current_policy_change_cannot_collect_old_pending_request(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    original = runtime.worker.policy.daily_ceiling
    runtime.worker.policy.daily_ceiling = original + 1
    second = await ask(runtime)
    assert second.status == 'blocked'
    assert runtime.q.pending_consent_offer(first.id) is None
    assert runtime.q.pending_consent_offer(second.id).member_ids == (second.id,)
    runtime.worker.policy.daily_ceiling = original
    assert runtime.q.pending_consent_offer(first.id).member_ids == (first.id,)
    assert runtime.q.pending_consent_offer(second.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['edit', 'expiry'])
async def test_stale_or_expired_real_follower_refuses_entire_old_choice(consent_runtime, change):
    runtime = consent_runtime
    first = await ask(runtime)
    second = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None and offer.member_ids == (first.id, second.id)
    if change == 'edit':
        runtime.q.update_payload(second.id, second.payload)
    else:
        runtime.q._conn.execute(
            'UPDATE tasks SET approval_deadline_at=? WHERE id=?',
            ('2000-01-01T00:00:00+00:00', second.id),
        )
        runtime.q._conn.commit()
        assert any(task.id == second.id for task in runtime.q.expire_pending_approvals().tasks)
    result = await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='always',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    assert result is None
    assert runtime.q.get(first.id).status == 'blocked'
    assert runtime.q.get(second.id).status == ('blocked' if change == 'edit' else 'expired')


@pytest.mark.asyncio
@pytest.mark.parametrize('consent_runtime', ['off'], indirect=True)
async def test_real_pending_consent_group_refuses_more_than_64_members(consent_runtime):
    runtime = consent_runtime
    task_ids = [(await ask(runtime)).id for _ in range(64)]
    assert runtime.q.pending_consent_offer(task_ids[0]).member_ids == tuple(task_ids)
    task_ids.append((await ask(runtime)).id)
    assert len(set(task_ids)) == 65
    assert runtime.q.pending_consent_offer(task_ids[0]) is None
    assert all(runtime.q.get(task_id).status == 'blocked' for task_id in task_ids)
