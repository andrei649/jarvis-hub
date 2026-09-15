"""Job tool choices restrict real offers and intake without granting approval."""
import asyncio
from types import SimpleNamespace

import pytest

from agents.core import job_toolsets as scope
from agents.core.autonomy.jobs import validate_action, validate_options


@pytest.mark.parametrize('value', ['basic', True, {}, ['unknown'], ['basic', 'basic'], [None], ['basic'] * 20])
def test_invalid_selection(value):
    with pytest.raises(ValueError):
        validate_options({'enabled_toolsets': value})


def test_schema_semantics_and_action_boundary():
    for value in (None, [], ['basic']):
        assert validate_options({'enabled_toolsets': value})['enabled_toolsets'] == value
        assert validate_action({'type': 'ask', 'prompt': 'hello'}, {'enabled_toolsets': value}) == []
        assert validate_action({'type': 'remind', 'message': 'hello'}, {'enabled_toolsets': value})
    with pytest.raises(ValueError):
        validate_options({'enabled_toolsets': [], 'script': 'a.py', 'no_agent': True}, check_scripts=False)


def test_resolution_requires_every_registered_member():
    server = SimpleNamespace(tools=lambda: [{'name': 'echo'}])
    with pytest.raises(ValueError, match='unavailable'):
        scope.resolve(['basic'], server)
    assert scope.resolve([], None) == frozenset()
    assert scope.resolve(None, None) is None


@pytest.mark.asyncio
async def test_concurrent_intersections_and_default_compatibility():
    async def one(name):
        with scope.toolset_scope(frozenset([name])):
            await asyncio.sleep(0)
            assert scope.allows(name)
            assert not scope.allows('other')
            with scope.toolset_scope(None):
                assert scope.allows(name)
            with scope.toolset_scope(frozenset(['other'])):
                assert not scope.allows(name)
                assert not scope.allows('other')
    await asyncio.gather(one('echo'), one('time'))
    assert scope.allows('anything')


@pytest.mark.asyncio
async def test_nested_null_cannot_shed_parent_revocation():
    entered, resume = asyncio.Event(), asyncio.Event()
    async def child():
        with scope.toolset_scope(None):
            entered.set()
            await resume.wait()
            assert not scope.allows('echo')
            with pytest.raises(ValueError, match='expired'), scope.toolset_scope(None):
                pass
    with scope.toolset_scope(frozenset(['echo'])):
        task = asyncio.create_task(child())
        await entered.wait()
    resume.set()
    await task


@pytest.mark.asyncio
async def test_unmanaged_late_child_unchanged():
    resume = asyncio.Event()
    async def child():
        await resume.wait()
        assert scope.allows('echo')
    with scope.toolset_scope(None):
        task = asyncio.create_task(child())
    resume.set()
    await task

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.autonomy.jobs import JobRunner, JobStore
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer
from tests.test_agent_runtime_v2 import _ScriptedBackend


def server_fixture():
    server = ToolRPCServer()
    calls = []
    async def handle(args):
        calls.append(args)
        return args
    for name in ('echo', 'time', 'execute_code'):
        server.register_tool(name, handle)
    return server, calls


@pytest.mark.asyncio
async def test_intake_refuses_before_preflight_and_handler():
    server, calls = server_fixture()
    server._tools['execute_code']['preflight'] = lambda args: pytest.fail('preflight reached')
    with scope.toolset_scope(frozenset(['echo'])):
        refused = await server.handle({'tool': 'execute_code', 'args': {}})
        assert refused['reason'] == 'job_toolset_not_allowed'
        assert (await server.handle({'tool': 'echo', 'args': {'value': 'ok'}}))['ok']
    assert calls == [{'value': 'ok'}]


@pytest.mark.asyncio
async def test_actual_runtime_filters_without_optional_profile_and_blocks_hallucination():
    server, calls = server_fixture()
    backend = _ScriptedBackend([
        ToolTurn(tool_calls=(ToolCall(id='a', name='execute_code', raw_arguments='{}', arguments={}),)),
        ToolTurn(content='done'),
    ])
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    with scope.toolset_scope(frozenset(['echo'])):
        assert await runtime.run(agent_id='jarvis', backend=backend, model='m', prompt='hi') == 'done'
    assert [row.name for row in backend.calls[0]['tools']] == ['echo']
    assert not calls
    with scope.toolset_scope(frozenset()):
        assert not runtime.can_run(backend, 'jarvis')
        assert not runtime.can_run(backend)


@pytest.mark.asyncio
async def test_runner_create_edit_restart_and_live_registration(tmp_path):
    server, calls = server_fixture()
    seen = []
    async def process(*args, **kwargs):
        seen.append(scope.allows('execute_code'))
        assert scope.allows('echo')
        return 'answer'
    store = JobStore(tmp_path / 'jobs.db')
    runner = JobRunner(store, orch=SimpleNamespace(process=process, tool_rpc=server), scheduler=lambda: None)
    try:
        with pytest.raises(ValueError, match='unavailable'):
            runner.create(name='bad', schedule_text='0 9 * * *', action={'type':'ask','prompt':'hi'}, options={'enabled_toolsets':['files']})
        job = runner.create(name='good', schedule_text='0 9 * * *', action={'type':'ask','prompt':'hi','deliver':False}, options={'enabled_toolsets':['basic']})
        await runner._ask(job, job.action)
        assert seen == [False]
        runner.edit(job.id, options={})
        await runner._ask(store.get(job.id), job.action)
        assert seen == [False, True]
        runner.edit(job.id, options={'enabled_toolsets':['basic']})
        store.close()
        store = JobStore(tmp_path / 'jobs.db')
        runner = JobRunner(store, orch=runner._orch, scheduler=lambda: None)
        del server._tools['time']
        with pytest.raises(ValueError, match='unavailable'):
            await runner._ask(store.get(job.id), job.action)
        assert seen == [False, True]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_runner_cancellation_revokes_late_intake(tmp_path):
    server, calls = server_fixture()
    entered, resume = asyncio.Event(), asyncio.Event()
    children = []
    async def process(*args, **kwargs):
        async def late():
            await resume.wait()
            return await server.handle({'tool':'echo','args':{}})
        children.append(asyncio.create_task(late()))
        entered.set()
        await asyncio.Event().wait()
    store = JobStore(tmp_path / 'jobs.db')
    runner = JobRunner(store, orch=SimpleNamespace(process=process,tool_rpc=server), scheduler=lambda:None)
    try:
        job = runner.create(name='test',schedule_text='0 9 * * *',action={'type':'ask','prompt':'hi','deliver':False},options={'enabled_toolsets':['basic']})
        task = asyncio.create_task(runner._ask(job, job.action))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        resume.set()
        assert (await children[0])['reason'] == 'job_toolset_not_allowed'
        assert not calls
    finally:
        store.close()


@pytest.mark.asyncio
async def test_ask_payload_remains_concrete_and_separate_from_request_scope():
    from tests.test_tool_rpc_h20_1 import _FakeQueue, _Task
    q = _FakeQueue()
    calls = []
    server = ToolRPCServer(enqueue=q.enqueue)
    async def write(args):
        calls.append(args)
        return args
    server.register_tool('file_write',write,gated=True)
    with scope.toolset_scope(frozenset(['file_write'])):
        result = await server.handle({'tool':'file_write','args':{'path':'allowed.txt','content':'original'}})
        assert result['reason'] == 'approval_required'
    payload = q.calls[0]['payload']
    assert payload == {'tool':'file_write','args':{'path':'allowed.txt','content':'original'},'target':'file_write'}
    assert not calls
    # Approved execution is an existing separate authority, not a restarted model turn.
    assert (await server.execute(_Task(payload)))['status'] == 'ok'
    assert calls == [{'path':'allowed.txt','content':'original'}]


def test_doctor_reports_catalog_and_effective_selection(tmp_path):
    server, _ = server_fixture()
    store = JobStore(tmp_path/'jobs.db')
    runner = JobRunner(store,orch=SimpleNamespace(tool_rpc=server),scheduler=lambda:None)
    try:
        job = runner.create(name='test',schedule_text='0 9 * * *',action={'type':'ask','prompt':'hi','deliver':False},options={'enabled_toolsets':['basic']})
        report = runner.doctor()
        assert 'enabled_toolsets' in report['supported_options']
        assert 'enabled_toolsets' not in report['unsupported_options']
        assert report['toolsets'][0] == {'id':'basic','tools':['echo','time'],'available':True}
        row = next(row for row in report['jobs'] if row['job_id'] == job.id)
        assert row['toolset_upper_bound'] == ['echo','time']
        del server._tools['time']
        assert any(p['code']=='toolsets_unavailable' for p in runner.doctor()['problems'])
    finally:
        store.close()


def test_cli_authors_and_clears_real_option():
    from agents.cli.nerva import _job_cli_options, build_parser
    parser = build_parser()
    for value, expected in [('basic,files',['basic','files']),('none',[]),('default',None)]:
        ns = parser.parse_args(['jobs','edit','job','--options','{"repeat":2}', '--toolsets', value])
        options = _job_cli_options(ns)
        assert options['repeat'] == 2
        if expected is None:
            assert 'enabled_toolsets' not in options
        else:
            assert options['enabled_toolsets'] == expected
    with pytest.raises(ValueError, match='complete --options'):
        _job_cli_options(parser.parse_args(['jobs','edit','job','--toolsets','none']))


@pytest.mark.asyncio
async def test_runner_to_actual_agent_tool_loop_and_empty_text_fallback(tmp_path):
    from agents.core.agent import Agent
    server, calls = server_fixture()
    backend = _ScriptedBackend([
        ToolTurn(tool_calls=(ToolCall(id='a',name='echo',raw_arguments='{"value":1}',arguments={'value':1}),)),
        ToolTurn(content='tool answer'),
    ])
    texts = []
    async def generate(**kwargs):
        texts.append(kwargs)
        return 'text answer'
    backend.generate = generate
    agent = Agent('jarvis',{'name':'Jarvis'})
    agent.tool_runtime = AgentToolRuntime(server,enabled=lambda:True)
    async def process(prompt,**kwargs):
        return await agent.generate_response(backend=backend,model='m',prompt=prompt,system='system',max_tokens=128,temperature=0.2)
    store = JobStore(tmp_path/'jobs.db')
    runner = JobRunner(store,orch=SimpleNamespace(process=process,tool_rpc=server),scheduler=lambda:None)
    try:
        job = runner.create(name='test',schedule_text='0 9 * * *',action={'type':'ask','prompt':'hi','deliver':False},options={'enabled_toolsets':['basic']})
        assert (await runner._ask(job,job.action))[1] == 'tool answer'
        assert {row.name for row in backend.calls[0]['tools']} == {'echo','time'}
        assert calls == [{'value':1}]
        job = runner.edit(job.id,options={'enabled_toolsets':[]})
        assert (await runner._ask(job,job.action))[1] == 'text answer'
        assert len(texts) == 1 and len(backend.calls) == 2
    finally:
        store.close()


@pytest.mark.asyncio
async def test_changed_queued_toolset_selection_is_cancelled(tmp_path, monkeypatch):
    from agents.core import estop
    monkeypatch.setattr(estop,'check_paused',lambda *args:False)
    server, calls = server_fixture()
    store = JobStore(tmp_path/'jobs.db')
    runner = JobRunner(store,orch=SimpleNamespace(tool_rpc=server),scheduler=lambda:None)
    try:
        job = runner.create(name='test',schedule_text='0 9 * * *',action={'type':'ask','prompt':'hi'},options={'enabled_toolsets':['basic']})
        receipt = runner.request_run(job.id)
        runner.edit(job.id,options={'enabled_toolsets':[]})
        await runner.drain_manual()
        assert store.dispatch.get(receipt['id'])['status'] == 'cancelled'
        assert not calls
    finally:
        store.close()


def test_cli_real_dispatch_sends_toolset_option():
    from tests.test_nerva_cli import EXIT_OK, JOB, _FakeHub, _run
    hub = _FakeHub({'POST /api/jobs': {'ok':True,'job':JOB}, 'PATCH /api/jobs/j1': {'ok':True,'job':JOB}})
    code, _, err, _ = _run(['jobs','create','--name','test','--when','daily','--action','{"type":"ask","prompt":"hi"}','--options','{"repeat":2}','--toolsets','basic'],hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1][2]['options'] == {'repeat':2,'enabled_toolsets':['basic']}
    code, _, err, _ = _run(['jobs','edit','j1','--options','{"enabled_toolsets":["basic"]}','--toolsets','default'],hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1][2]['options'] == {}


@pytest.mark.asyncio
async def test_admin_route_authors_refuses_and_executes_exact_selection(tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from agents import web
    from agents.core.routers import jobs
    server, calls = server_fixture()
    seen = []
    async def process(*args, **kwargs):
        seen.append((scope.allows('echo'),scope.allows('execute_code')))
        return 'answer'
    store = JobStore(tmp_path/'jobs.db')
    orch = SimpleNamespace(tool_rpc=server,process=process)
    runner = JobRunner(store,orch=orch,scheduler=lambda:None)
    orch.jobs = runner
    monkeypatch.setattr(jobs,'get_orch',lambda:orch)
    monkeypatch.setattr(web,'ADMIN_TOKEN','owner-fixture')
    app = FastAPI()
    app.include_router(jobs.router)
    body = {'name':'test','schedule_text':'0 9 * * *','action':{'type':'ask','prompt':'hi','deliver':False},'options':{'enabled_toolsets':['basic']}}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            assert (await client.post('/api/jobs',json=body)).status_code in (401,403)
            headers = {'X-Admin-Token':'owner-fixture'}
            created = await client.post('/api/jobs',json=body,headers=headers)
            assert created.status_code == 201
            job = store.get(created.json()['job']['id'])
            await runner._ask(job,job.action)
            assert seen == [(True,False)]
            refused = await client.patch('/api/jobs/'+job.id,json={'options':{'enabled_toolsets':['execute_code']}},headers=headers)
            assert refused.status_code == 422
            cleared = await client.patch('/api/jobs/'+job.id,json={'options':{}},headers=headers)
            assert cleared.status_code == 200
            assert store.get(job.id).options == {}
    finally:
        store.close()


@pytest.mark.parametrize('options', [['basic'], 'basic', True])
def test_runner_malformed_options_stay_validation_refusals(tmp_path, options):
    store = JobStore(tmp_path/'jobs.db')
    runner = JobRunner(store,orch=SimpleNamespace(),scheduler=lambda:None)
    try:
        with pytest.raises(ValueError,match='options must be an object'):
            runner.create(name='test',schedule_text='0 9 * * *',action={'type':'ask','prompt':'hi'},options=options)
    finally:
        store.close()


def test_selection_cannot_enable_internal_mutating_posture():
    from agents.core.tool_profiles import ToolPosture, resolve_tools
    metadata = [{'name':'echo','gated':False},{'name':'file_write','gated':True}]
    with scope.toolset_scope(frozenset(['echo','file_write'])):
        offered, withheld = resolve_tools(metadata,posture=ToolPosture('internal','system'))
        assert [row['name'] for row in offered] == ['echo']
        assert withheld == ['file_write']
