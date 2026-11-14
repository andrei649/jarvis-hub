"""Owner progress reads compose with real SQLite cards and updater files."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.core import hub_update_apply
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.commands import CommandContext, Principal
from agents.core.update_commands import update_command


@pytest.fixture
def progress_rig(tmp_path, monkeypatch):
    state = tmp_path / 'update'
    state.mkdir()
    monkeypatch.setattr(hub_update_apply, 'state_dir', lambda: state)
    queue = TaskQueue(str(tmp_path / 'queue.db')).initialize()
    orch = SimpleNamespace(autonomy=SimpleNamespace(queue=queue), autonomy_queue=queue)
    ctx = CommandContext(orch, Principal(channel='telegram', admin=True), 'update', 'status')
    for name in ('request_apply', 'apply_approved', 'status', 'plan'):
        monkeypatch.setattr(hub_update_apply, name,
                            lambda *a, **kw: pytest.fail('status reached updater effect/probe'))
    try:
        yield queue, state, ctx
    finally:
        queue.close()


def finish(queue, task_id):
    for status in (TaskStatus.APPROVED, TaskStatus.RUNNING, TaskStatus.DONE):
        queue.transition(task_id, status)


@pytest.mark.asyncio
async def test_completed_card_needs_its_own_terminal_receipt(progress_rig):
    queue, state, ctx = progress_rig
    card = queue.enqueue('owner', 'hub.update', 'Private title', {'secret': 'do not print'})
    finish(queue, card)
    before = queue._conn.total_changes
    reply = await update_command(ctx)
    assert 'unavailable' in reply.lower()
    record = {'kind': 'update', 'task_id': card, 'phase': 'verified', 'result': 'verified',
              'log': ['secret-bearer-token'], 'reason': '/private/path'}
    (state / 'receipts.jsonl').write_text(json.dumps(record) + '\n')
    reply = await update_command(ctx)
    assert 'verified' in reply.lower()
    assert str(card) in reply
    assert 'secret' not in reply and '/private' not in reply
    assert queue._conn.total_changes == before


@pytest.mark.asyncio
async def test_new_card_does_not_inherit_old_success(progress_rig):
    queue, state, ctx = progress_rig
    old = queue.enqueue('owner', 'hub.update', 'First', {})
    finish(queue, old)
    (state / 'receipts.jsonl').write_text(json.dumps({
        'kind': 'update', 'task_id': old, 'phase': 'verified', 'result': 'verified'}) + '\n')
    new = queue.enqueue('owner', 'hub.update', 'Second', {})
    reply = await update_command(ctx)
    assert str(new) in reply and 'approval' in reply.lower()
    assert 'verified' not in reply.lower()
    assert queue.get(new).status == TaskStatus.PROPOSED


@pytest.mark.asyncio
async def test_invalid_current_state_cannot_reveal_old_success(progress_rig):
    queue, state, ctx = progress_rig
    card = queue.enqueue('owner', 'hub.update', 'First', {})
    finish(queue, card)
    (state / 'receipts.jsonl').write_text(json.dumps({
        'kind': 'update', 'task_id': card, 'phase': 'verified', 'result': 'verified'}) + '\n')
    (state / 'current.json').write_text('{incomplete')
    reply = await update_command(ctx)
    assert 'unavailable' in reply.lower()
    assert 'verified' not in reply.lower()
