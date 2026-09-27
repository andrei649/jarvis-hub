"""Advisory opinions on real, persisted Decision Inbox tasks, never authority."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.approval_judge import ApprovalJudge, JudgeStatus
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.tool_rpc import ToolRPCServer


class Backend:
    def __init__(self, gate=None):
        from agents.core.llm.providers import get_profile

        self.profile = get_profile("lm-studio")
        self.base_url = "http://localhost:1234"
        from agents.core.llm.egress import llm_async_client

        self.client = llm_async_client("lm-studio", base_url=self.base_url, trust_env=False,
                                       transport=httpx.MockTransport(lambda request: pytest.fail("unexpected fixture I/O")))
        self.gate = gate
        self.calls = []
        self.active = self.maximum = 0

    async def generate(self, model, prompt, **kwargs):
        self.calls.append(prompt)
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            if self.gate:
                await self.gate.wait()
            return '{"risk":99,"why":"Check the destination before approving"}'
        finally:
            self.active -= 1

    async def aclose(self):
        pass


@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    yield queue
    queue.close()


def judge(monkeypatch, backend):
    for name in ('PROVIDER', 'BASE_URL', 'ALLOW_REMOTE', 'KEY'):
        monkeypatch.delenv('JARVIS_ROLE_APPROVAL_JUDGE_' + name, raising=False)
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_MODEL', 'task-judge')
    return ApprovalJudge(backend_factory=lambda status: backend,
                         settings=lambda category, key, default=None: default)


def bind(q, configured_judge):
    worker = AutonomyWorker(q)
    worker.attach_approval_judge(configured_judge, loop=asyncio.get_running_loop())
    return worker, worker.approval_judge


async def drain(adapter):
    await asyncio.sleep(0)
    while adapter._judge_tasks:
        await asyncio.gather(*list(adapter._judge_tasks))
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_toolrpc_creates_one_card_and_opinion_without_executing(q, monkeypatch):
    backend = Backend(asyncio.Event())
    worker, adapter = bind(q, judge(monkeypatch, backend))
    executed = []
    server = ToolRPCServer(enqueue=worker.govern_enqueue)
    server.register_tool('write_report', lambda args: executed.append(args), gated=True)
    answer = await server.handle({'tool': 'write_report', 'args': {'path': 'report.md'}}, actor='jarvis')
    task = q.get(answer['task_id'])
    before = task.to_dict()
    fingerprint = q.execution_fingerprint(task)
    assert answer['reason'] == 'approval_required'
    assert task.status == 'blocked' and len(q.list()) == 1
    assert adapter.project(task)['judge_pending'] is True
    backend.gate.set()
    await drain(adapter)
    assert q.get(task.id).to_dict() == before
    assert q.execution_fingerprint(q.get(task.id)) == fingerprint
    assert adapter.project(task)['judge']['score'] == 99
    assert 'judge_pending' not in adapter.project(task)
    assert executed == []
    await worker.apply_decision(task.id, 'accept')
    assert q.get(task.id).status == 'approved'  # high risk is advisory


@pytest.mark.asyncio
async def test_opinion_persists_outside_task_schema_and_pending_does_not(q, monkeypatch):
    worker, adapter = bind(q, judge(monkeypatch, Backend()))
    task = await worker.submit('jarvis', 'delete_file', 'Delete', {'path': 'old'}, attention_mode='none')
    await drain(adapter)
    reopened = TaskQueue(q.db_path).initialize()
    try:
        other_worker, other_adapter = bind(reopened, judge(monkeypatch, Backend()))
        assert other_adapter.project(reopened.get(task.id))['judge']['score'] == 99
        assert 'judge_pending' not in other_adapter.project(reopened.get(task.id))
        assert 'judge' not in reopened.get(task.id).to_dict()
        assert other_worker.approval_judge is other_adapter
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_thread_intake_uses_hub_loop_and_detached_payload(q, monkeypatch):
    backend = Backend(asyncio.Event())
    worker, adapter = bind(q, judge(monkeypatch, backend))
    payload = {'nested': {'text': 'original'}}
    task_id = await asyncio.to_thread(worker.govern_enqueue, 'jarvis', 'delete_file', 'Delete', payload)
    payload['nested']['text'] = 'changed after enqueue'
    backend.gate.set()
    await drain(adapter)
    assert q.get(task_id).status == 'blocked'
    assert 'original' in backend.calls[0] and 'changed after enqueue' not in backend.calls[0]
    assert adapter.project(q.get(task_id))['judge']['score'] == 99


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['accept', 'reject', 'defer', 'edit', 'revoke'])
async def test_result_is_discarded_after_pending_state_or_snapshot_changes(q, monkeypatch, change):
    backend = Backend(asyncio.Event())
    worker, adapter = bind(q, judge(monkeypatch, backend))
    task = await worker.submit('jarvis', 'delete_file', 'Delete', {'path': 'old'}, attention_mode='none')
    for _ in range(20):
        if backend.calls:
            break
        await asyncio.sleep(0)
    assert len(backend.calls) == 1
    if change == 'edit':
        q.update_payload(task.id, {'path': 'new'})
    elif change == 'revoke':
        monkeypatch.delenv('JARVIS_ROLE_APPROVAL_JUDGE_MODEL')
    else:
        await worker.apply_decision(task.id, change)
    backend.gate.set()
    await drain(adapter)
    assert 'judge' not in adapter.project(q.get(task.id))
    assert 'judge_pending' not in adapter.project(q.get(task.id))


@pytest.mark.asyncio
async def test_edited_blocked_task_gets_new_opinion_and_old_one_is_hidden(q, monkeypatch):
    backend = Backend()
    worker, adapter = bind(q, judge(monkeypatch, backend))
    task = await worker.submit('jarvis', 'delete_file', 'Delete', {'path': 'old'}, attention_mode='none')
    await drain(adapter)
    backend.gate = asyncio.Event()
    edited = await worker.apply_decision(task.id, 'edit', payload={'path': 'new'})
    assert edited.status == 'blocked'
    assert 'judge' not in adapter.project(edited)
    assert adapter.project(edited)['judge_pending'] is True
    backend.gate.set()
    await drain(adapter)
    assert len(backend.calls) == 2 and 'new' in backend.calls[-1]
    assert adapter.project(edited)['judge']['score'] == 99


@pytest.mark.asyncio
async def test_waiting_slot_rechecks_revocation_before_egress(q, monkeypatch):
    backend = Backend(asyncio.Event())
    worker, adapter = bind(q, judge(monkeypatch, backend))
    tasks = [await worker.submit('jarvis', 'delete_file', str(i), attention_mode='none') for i in range(3)]
    for _ in range(20):
        if len(backend.calls) == 2:
            break
        await asyncio.sleep(0)
    assert len(backend.calls) == 2
    monkeypatch.delenv('JARVIS_ROLE_APPROVAL_JUDGE_MODEL')
    backend.gate.set()
    await drain(adapter)
    assert len(backend.calls) == 2
    assert all('judge' not in adapter.project(q.get(t.id)) for t in tasks)


@pytest.mark.asyncio
async def test_restart_backlog_is_bounded_and_never_executes(q, monkeypatch):
    worker = AutonomyWorker(q)
    for i in range(40):
        await worker.submit('jarvis', 'delete_file', str(i), attention_mode='none')
    backend = Backend(asyncio.Event())
    worker, adapter = bind(q, judge(monkeypatch, backend))
    adapter.resume_pending()
    assert len(adapter.judge_status_public()['judging']) == 32
    backend.gate.set()
    await drain(adapter)
    assert len(backend.calls) == 32 and backend.maximum <= 2
    assert all(t.status == 'blocked' for t in q.list())


@pytest.mark.asyncio
async def test_task_and_action_adapters_share_one_capacity(q, monkeypatch):
    from agents.core.autonomy.action_approvals import ActionApprovalQueue
    from agents.core.autonomy.advisory_judgements import JudgementCapacity

    backend = Backend(asyncio.Event())
    shared_judge = judge(monkeypatch, backend)
    pool = JudgementCapacity()
    worker = AutonomyWorker(q)
    worker.attach_approval_judge(shared_judge, loop=asyncio.get_running_loop(), capacity=pool)
    actions = ActionApprovalQueue()
    actions.attach_judge(shared_judge, capacity=pool)
    for i in range(20):
        await worker.submit('jarvis', 'delete_file', str(i), attention_mode='none')
        actions.request({'tool': 'delete_file', 'agent': 'jarvis', 'args': {'path': str(i)}})
    backend.gate.set()
    await drain(worker.approval_judge)
    await drain(actions)
    assert len(backend.calls) == 32 and backend.maximum <= 2
    # Finished work must release the shared reservation, allowing both stores
    # to judge fresh cards after the initial capacity has been fully consumed.
    fresh_task = await worker.submit('jarvis', 'delete_file', 'Fresh task', attention_mode='none')
    fresh_action = actions.request({'tool': 'delete_file', 'agent': 'jarvis',
                                    'args': {'path': 'fresh-action'}})
    await drain(worker.approval_judge)
    await drain(actions)
    assert len(backend.calls) == 34
    assert worker.approval_judge.project(q.get(fresh_task.id))['judge']['score'] == 99
    assert actions.get(fresh_action['id'])['judge']['score'] == 99


@pytest.mark.asyncio
async def test_task_routes_project_opinions_and_off_shape_is_preserved(q, monkeypatch):
    from agents.core.routers import autonomy

    worker = AutonomyWorker(q)
    monkeypatch.setattr(autonomy, 'get_orch', lambda: SimpleNamespace(autonomy_queue=q, autonomy=worker))
    task = await worker.submit('jarvis', 'delete_file', 'Delete', attention_mode='none')
    original = json.loads((await autonomy.autonomy_list('blocked', None, 100)).body)
    assert 'judge' not in original and 'judge' not in original['tasks'][0]
    worker.attach_approval_judge(judge(monkeypatch, Backend()), loop=asyncio.get_running_loop())
    worker.approval_judge.resume_pending()
    await drain(worker.approval_judge)
    result = json.loads((await autonomy.autonomy_list('blocked', None, 100)).body)
    approvals = json.loads((await autonomy.autonomy_approvals()).body)
    assert result['judge']['configured'] is True and result['judge']['timeout'] > 0
    assert result['tasks'][0]['judge']['score'] == 99
    assert approvals['pending'][0]['judge']['score'] == 99
    assert q.get(task.id).status == 'blocked'


@pytest.mark.asyncio
async def test_timeout_failure_clears_pending_and_keeps_task_decidable(q):
    class SlowJudge:
        def status(self):
            return JudgeStatus(True, '', timeout=0.01, local=True)

        def wants(self, snapshot, status):
            return True

        async def score(self, snapshot, status):
            await asyncio.Event().wait()

    worker, adapter = bind(q, SlowJudge())
    task = await worker.submit('jarvis', 'delete_file', 'Delete', attention_mode='none')
    await drain(adapter)
    assert 'judge_pending' not in adapter.project(task)
    assert 'judge' not in adapter.project(task)
    await worker.apply_decision(task.id, 'reject')
    assert q.get(task.id).status == 'rejected'


def test_store_compares_persisted_snapshot_and_never_overwrites_first_opinion(q):
    task_id = q.enqueue('jarvis', 'delete_file', 'Delete', payload={'path': 'old'})
    task = q.transition(task_id, TaskStatus.BLOCKED)
    assert hasattr(q, 'approval_snapshot_digest'), 'TaskQueue lacks isolated advisory snapshot persistence'
    digest = q.approval_snapshot_digest(task)
    annotation = {'score': 99, 'rationale': 'Review this', 'judge': {'model': 'j'}}
    before = task.to_dict()
    assert q.store_approval_judgement(task_id, digest, annotation) == annotation
    assert q.store_approval_judgement(task_id, digest, {'score': 0}) is None
    assert q.get(task_id).to_dict() == before
    q.update_payload(task_id, {'path': 'new'})
    assert q.approval_judgement(task_id, digest) is None
    assert q.store_approval_judgement(task_id, digest, annotation) is None


@pytest.mark.asyncio
async def test_telegram_delivery_does_not_invalidate_action_opinion(q, monkeypatch):
    backend = Backend(asyncio.Event())
    worker, adapter = bind(q, judge(monkeypatch, backend))

    async def notifier(task):
        return True

    worker.notifier = notifier
    task = await worker.submit('jarvis', 'delete_file', 'Delete')
    assert q.get(task.id).pushed == 1
    backend.gate.set()
    await drain(adapter)
    assert adapter.project(q.get(task.id))['judge']['score'] == 99


@pytest.mark.asyncio
async def test_identical_payload_edit_revokes_old_inflight_snapshot(q, monkeypatch):
    backend = Backend(asyncio.Event())
    worker, adapter = bind(q, judge(monkeypatch, backend))
    task = await worker.submit('jarvis', 'delete_file', 'Delete', {'path': 'same'}, attention_mode='none')
    for _ in range(20):
        if backend.calls:
            break
        await asyncio.sleep(0)
    old_key = next(iter(adapter._judging))
    q.update_payload(task.id, {'path': 'same'})
    assert adapter._pending_snapshot(old_key) is None
    backend.gate.set()
    await drain(adapter)
    assert 'judge' not in adapter.project(q.get(task.id))


@pytest.mark.asyncio
async def test_mediated_task_opinion_preserves_receipt_chain_and_execution(q, monkeypatch, tmp_path):
    import hashlib
    import hmac

    from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
    from agents.core.kernel import Decision, Verdict
    from agents.core.kernel.binding import MediationKernelBridge

    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    signer = DetachedHMACSigner(lambda raw: hmac.new(b'task-judge-owner-key', raw, hashlib.sha256).hexdigest())
    head = [None]

    def cas(expected, replacement):
        if head[0] != expected:
            return False
        head[0] = replacement
        return True

    mediated = TaskQueue(str(tmp_path / 'mediated.db'), mediation_mode='enforce',
                         mediation_signer=signer,
                         mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
                         mediation_classifier=lambda kind: True, mediation_scope='global').initialize()
    calls = []

    def kernel(action):
        calls.append(action)
        return Decision(Verdict.QUEUE, tier=3, reason='owner decides')

    executed = []

    async def executor(task):
        executed.append(task.payload['path'])
        return {'ok': True}

    worker = AutonomyWorker(mediated, kernel=MediationKernelBridge(kernel),
                            mediation_signer=signer, executor=executor)
    worker.attach_approval_judge(judge(monkeypatch, Backend()), loop=asyncio.get_running_loop())
    try:
        task = await worker.submit('jarvis', 'filesystem.write', 'Write report',
                                   {'path': 'report.md'}, attention_mode='none')
        before = task.to_dict()
        events = mediated.mediation_events()
        fingerprint = mediated.execution_fingerprint(task)
        await drain(worker.approval_judge)
        assert worker.approval_judge.project(task)['judge']['score'] == 99
        assert mediated.get(task.id).to_dict() == before
        assert mediated.execution_fingerprint(mediated.get(task.id)) == fingerprint
        assert mediated.mediation_events() == events and len(calls) == 1
        assert mediated.verified_mediation_stats()['valid'] is True
        assert executed == []
        await worker.apply_decision(task.id, 'accept')
        result = await worker.tick()
        assert result['done'] == 1 and executed == ['report.md']
    finally:
        mediated.close()


@pytest.mark.asyncio
async def test_task_adapter_keeps_deep_taint_from_remote_judge(q, monkeypatch):
    backend = Backend()
    configured = judge(monkeypatch, backend)
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER', 'openai-compatible')
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL', 'https://judge.example/v1')
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE', '1')
    worker, adapter = bind(q, configured)
    assert configured.status().configured and not configured.status().local
    task = await worker.submit('pepper', 'delete_file', 'Delete',
                               {'args': {'child': {'tainted': True, 'text': 'private'}}},
                               attention_mode='none')
    await drain(adapter)
    assert backend.calls == [] and 'judge' not in adapter.project(task)


@pytest.mark.asyncio
async def test_task_adapter_clears_inherited_job_selection(q, monkeypatch):
    from agents.core.llm import job_selection

    backend = Backend()
    worker, adapter = bind(q, judge(monkeypatch, backend))
    marker = job_selection._selection.set(object())
    try:
        task = await worker.submit('jarvis', 'delete_file', 'Delete', attention_mode='none')
        await drain(adapter)
        assert adapter.project(task)['judge']['score'] == 99
    finally:
        job_selection._selection.reset(marker)


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['unknown', 'edit'])
async def test_failed_decision_keeps_pending_opinion_on_unchanged_blocked_task(q, monkeypatch, action):
    from agents.core.autonomy.queue import TaskQueueError

    backend = Backend(asyncio.Event())
    worker, adapter = bind(q, judge(monkeypatch, backend))
    task = await worker.submit('jarvis', 'delete_file', 'Delete', attention_mode='none')
    if action == 'edit':
        q.mediation_mode = 'enforce'
        monkeypatch.setattr(q, 'classify_mediation', lambda kind: True)
    with pytest.raises(TaskQueueError):
        await worker.apply_decision(task.id, action, payload={'path': 'new'})
    assert q.get(task.id).status == 'blocked'
    assert adapter.project(q.get(task.id))['judge_pending'] is True
    backend.gate.set()
    await drain(adapter)
    assert adapter.project(q.get(task.id))['judge']['score'] == 99
