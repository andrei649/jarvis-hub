"""Real producer and signed-evidence checks for Telegram owner consent."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
from dataclasses import replace

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.consent_authority import (
    make_telegram_consent_actor,
    telegram_actor_current,
)
from agents.core.autonomy.consent_ledger import ConsentCategory, ConsentContext, ConsentLedger
from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.autonomy.mediation import DetachedHMACSigner, canonical_json
from agents.core.commands import Principal
from tests.test_h487_consent_runtime_integration import _Process, ask, consent_runtime  # noqa: F401


def _key(user_id=42, chat_id=-500):
    return json.dumps(['telegram', str(user_id), str(chat_id)], separators=(',', ':'))


async def _telegram_ask(runtime, *, user_id=42, chat_id=-500):
    turn = open_approval_turn(
        session_id='owner-telegram', session_instance='telegram-instance',
        principal=Principal(channel='telegram', sender=str(user_id), chat=str(chat_id), admin=True),
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


@pytest.mark.parametrize('user_id,chat_id', [
    (True, -500), (42, False), (0, -500), (-1, -500), (42, 0),
    ('42', -500), (42, '-500'),
])
def test_factory_rejects_non_event_ids(user_id, chat_id):
    assert make_telegram_consent_actor(
        user_id=user_id, chat_id=chat_id, current=lambda: True,
    ) is None


def test_issued_actor_binds_event_key_callback_and_current_state():
    current = [True]
    actor = make_telegram_consent_actor(
        user_id=42, chat_id=-500, current=lambda: current[0],
    )
    assert actor is not None and actor.live()
    assert telegram_actor_current(actor)
    assert not telegram_actor_current(replace(actor, principal_key='["web-owner"]'))
    assert not telegram_actor_current(replace(actor, live=lambda: True))
    assert not telegram_actor_current(replace(actor, authority=object()))
    current[0] = False
    assert not telegram_actor_current(actor)


@pytest.mark.asyncio
async def test_real_web_origin_can_be_decided_by_actual_telegram_owner(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None
    source = runtime.q._consent_source(first.id)
    original = source['descriptor']['context']
    assert original['principal'] == '["web-owner"]'
    actor = make_telegram_consent_actor(
        user_id=42, chat_id=-500, current=lambda: True,
    )
    assert actor is not None and actor.principal_key == _key()
    result = await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='always', actor=actor,
    )
    assert result is not None
    decided = runtime.q.get(first.id)
    assert decided.status == 'approved' and decided.decided_by == 'telegram'
    assert decided.human_decision['action'] == 'always'
    assert decided.human_decision['by'] == 'telegram'
    assert decided.human_decision['principal_key'] == _key()

    ledger_row = runtime.q._conn.execute(
        'SELECT payload FROM h487_consent_decisions',
    ).fetchone()
    ledger_decision = json.loads(ledger_row[0])
    assert ledger_decision['version'] == 2
    assert ledger_decision['decider_principal'] == _key()
    assert ledger_decision['context'] == original
    grant = json.loads(runtime.q._conn.execute(
        'SELECT payload FROM h487_consent_grants',
    ).fetchone()[0])
    assert grant['version'] == 2 and grant['decider_principal'] == _key()
    assert grant['identity']['principal'] == '["web-owner"]'
    proof = json.loads(runtime.q._conn.execute(
        'SELECT payload FROM task_consent_proofs WHERE task_id=?', (first.id,),
    ).fetchone()[0])
    assert proof['version'] == 2 and proof['decider_principal'] == _key()
    assert proof['descriptor']['context'] == original

    later_web = await ask(runtime, session='later-web', instance='later-instance')
    assert later_web.status == 'approved' and later_web.decided_by == 'consent'
    later_telegram = await _telegram_ask(runtime)
    assert later_telegram.status == 'blocked'


@pytest.mark.asyncio
@pytest.mark.parametrize('issued', [False, True])
async def test_same_telegram_origin_preserves_legacy_and_attributed_modes(consent_runtime, issued):
    runtime = consent_runtime
    first = await _telegram_ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None
    source = runtime.q._consent_source(first.id)
    descriptor = runtime.q._consent_resolver(first, source)
    actor = (make_telegram_consent_actor(user_id=42, chat_id=-500, current=lambda: True)
             if issued else OwnerConsentActor('owner', 'telegram', lambda: True, _key()))
    assert runtime.q.decide_reusable_consent(first.id, offer.revision,
                                            choice='session', actor=actor)
    decided = runtime.q.get(first.id)
    decision = json.loads(runtime.q._conn.execute(
        'SELECT payload FROM h487_consent_decisions',
    ).fetchone()[0])
    proof = json.loads(runtime.q._conn.execute(
        'SELECT payload FROM task_consent_proofs WHERE task_id=?', (first.id,),
    ).fetchone()[0])
    assert decision['context']['principal'] == _key()
    assert decision['version'] == proof['version'] == (2 if issued else 1)
    assert ('principal_key' in decided.human_decision) is issued
    assert runtime.q._consent_ledger.lookup(descriptor.context, descriptor.categories)


@pytest.mark.asyncio
async def test_legacy_telegram_actor_cannot_claim_web_source_identity(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None
    forged = OwnerConsentActor('owner', 'telegram', lambda: True, principal_key='["web-owner"]')
    assert runtime.q.decide_reusable_consent(
        first.id, offer.revision, choice='session', actor=forged,
    ) is None
    assert runtime.q.get(first.id).status == 'blocked'


@pytest.mark.asyncio
async def test_issued_actor_rechecks_current_for_each_follower(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    second = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None and offer.member_ids == (first.id, second.id)
    calls = [0]

    def current():
        calls[0] += 1
        return calls[0] <= 1

    actor = make_telegram_consent_actor(user_id=42, chat_id=-500, current=current)
    assert runtime.q.decide_reusable_consent(
        first.id, offer.revision, choice='session', actor=actor,
    ) is None
    assert calls[0] >= 2
    assert all(runtime.q.get(task_id).status == 'blocked' for task_id in offer.member_ids)
    assert runtime.q._conn.execute('SELECT COUNT(*) FROM h487_consent_decisions').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_attributed_proof_rejects_changed_human_or_signed_decider(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    actor = make_telegram_consent_actor(user_id=42, chat_id=-500, current=lambda: True)
    assert runtime.q.decide_reusable_consent(first.id, offer.revision, choice='session', actor=actor)
    row = runtime.q._conn.execute(
        'SELECT payload FROM task_consent_proofs WHERE task_id=?', (first.id,),
    ).fetchone()
    proof = json.loads(row[0])
    assert proof['version'] == 2
    task = runtime.q.get(first.id)
    human = dict(task.human_decision, principal_key=_key(99, -500))
    runtime.q._conn.execute('UPDATE tasks SET human_decision=? WHERE id=?',
                            (json.dumps(human), first.id))
    runtime.q._conn.commit()
    assert runtime.q.claim_consent(first.id, execution_id='fake', live_check=lambda: True) is None
    runtime.q._conn.execute('UPDATE tasks SET human_decision=? WHERE id=?',
                            (json.dumps(task.human_decision), first.id))
    proof['decider_principal'] = _key(99, -500)
    payload = canonical_json(proof)
    runtime.q._conn.execute(
        'UPDATE task_consent_proofs SET payload=?, signature=? WHERE task_id=?',
        (payload, runtime.q._mediation_signer.sign(payload), first.id),
    )
    runtime.q._conn.commit()
    assert runtime.q.claim_consent(first.id, execution_id='fake', live_check=lambda: True) is None


def test_ledger_v2_rejects_unsupported_signed_versions_and_preserves_v1(tmp_path):
    conn = sqlite3.connect(tmp_path / 'ledger.db')
    signer = DetachedHMACSigner(
        lambda body: hmac.new(b'test-attributed', body, hashlib.sha256).hexdigest(),
    )
    category = ConsentCategory('terminal.run')
    context = ConsentContext('["web-owner"]', 'generic_model_toolrpc', 's', 'i', 'r', 'p', 't')
    ledger = ConsentLedger(conn, signer, categories=(category,))
    ledger.initialize()
    assert ledger.grant(context, (category,), choice='always',
                        decision_id='legacy', decided_by='admin')
    assert ledger.lookup(context, (category,))
    assert not ledger.grant(context, (category,), choice='always',
                            decision_id='claimed-web', decided_by='owner',
                            decider_principal='["web-owner"]')
    assert not ledger.grant(context, (category,), choice='always',
                            decision_id='admin-with-sender', decided_by='admin',
                            decider_principal=_key())
    assert ledger.grant(context, (category,), choice='always',
                        decision_id='attributed', decided_by='owner',
                        decider_principal=_key())
    assert ledger.lookup(context, (category,))
    for table, decision_id in [('h487_consent_decisions', 'attributed'),
                               ('h487_consent_grants', 'attributed')]:
        row = conn.execute(
            f'SELECT rowid,payload FROM {table} WHERE decision_id=?', (decision_id,),
        ).fetchone()
        original = row[1]
        changed = json.loads(original)
        changed['version'] = 3
        payload = canonical_json(changed)
        conn.execute(f'UPDATE {table} SET payload=?,signature=? WHERE rowid=?',
                     (payload, signer.sign(payload), row[0]))
        assert not ledger.lookup(context, (category,))
        conn.execute(f'UPDATE {table} SET payload=?,signature=? WHERE rowid=?',
                     (original, signer.sign(original), row[0]))
        assert ledger.lookup(context, (category,))
    conn.close()


@pytest.mark.asyncio
async def test_readonly_terminal_completion_requires_real_dispatch_evidence(consent_runtime, monkeypatch):
    runtime = consent_runtime
    effects = []

    async def spawn(*args, **kwargs):
        effects.append((args, kwargs['cwd']))
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    first = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    actor = make_telegram_consent_actor(user_id=42, chat_id=-500, current=lambda: True)
    assert runtime.q.decide_reusable_consent(first.id, offer.revision, choice='session', actor=actor)
    assert not runtime.q.verify_consent_terminal_result(first.id)
    assert (await runtime.worker.tick(task_id=first.id))['done'] == 1
    assert effects == [(('git', 'reset', '--hard'), str(runtime.root))]
    assert runtime.q.verify_consent_terminal_result(first.id)
    runtime.q._conn.execute(
        'UPDATE task_consent_proofs SET claim_signature=? WHERE task_id=?',
        ('bad', first.id),
    )
    runtime.q._conn.commit()
    assert not runtime.q.verify_consent_terminal_result(first.id)


@pytest.mark.asyncio
async def test_manufactured_done_marker_is_not_a_terminal_result(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    runtime.q._conn.execute(
        "UPDATE tasks SET status='done', attempts=1, decision='consent-session', "
        "decided_by='telegram', result=? WHERE id=?",
        (json.dumps({'status': 'done'}), first.id),
    )
    runtime.q._conn.commit()
    assert not runtime.q.verify_consent_terminal_result(first.id)
