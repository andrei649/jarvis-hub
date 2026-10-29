"""H396 whole-turn observations remain request-owned and source-assigned."""

import asyncio
import json

import pytest

from agents.core import turn_outcome


def test_answered_model_turn_is_not_objective_success_and_has_one_info_diagnostic(caplog):
    caplog.set_level('INFO', logger='agents.core.turn_outcome')
    sink, token = turn_outcome.open_turn_outcome()
    try:
        assert turn_outcome.record_turn_completion('answered')
        assert turn_outcome.record_turn_latency(19)
        result = sink.close()
        assert result['completion'] == {
            'kind': 'answered', 'explanation': 'A model answer was returned; the requested objective was not verified.',
            'severity': 'info', 'unanswered_tool_results': 0}
        assert sum('turn_completion' in row.message for row in caplog.records) == 1
        result['completion']['kind'] = 'forged'
        assert sink.close()['completion']['kind'] == 'answered'
        assert turn_outcome.record_turn_completion('failed') is False
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.parametrize('kind', ['command', 'refused', 'partial', 'timeout',
                                  'unavailable', 'failed', 'pending_approval'])
def test_known_source_categories_do_not_depend_on_reply_prose(kind):
    sink, token = turn_outcome.open_turn_outcome()
    try:
        assert turn_outcome.record_turn_completion(kind)
        assert turn_outcome.record_turn_latency(0)
        result = sink.close()
        assert result['completion']['kind'] == kind
        assert result['completion']['severity'] == 'info'
        assert 'verified' not in result['completion']['kind']
    finally:
        turn_outcome.reset_turn_outcome(token)


def test_unconsumed_tool_result_warns_once_but_subsequent_agent_model_consumes_it(caplog):
    caplog.set_level('INFO', logger='agents.core.turn_outcome')
    sink, token = turn_outcome.open_turn_outcome()
    try:
        turn_outcome.record_accepted_tool_result('alpha')
        turn_outcome.record_accepted_tool_result('beta')
        turn_outcome.record_model_completion('alpha')
        turn_outcome.record_turn_completion('partial')
        turn_outcome.record_turn_latency(21)
        result = sink.close()
        assert result['completion']['severity'] == 'warning'
        assert result['completion']['unanswered_tool_results'] == 1
        assert sum('turn_completion' in row.message for row in caplog.records) == 1
        assert turn_outcome.record_model_completion('beta') is False
        assert sink.close() == result
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
async def test_late_cancellation_resistant_child_cannot_change_final_snapshot():
    sink, token = turn_outcome.open_turn_outcome()
    release = asyncio.Event()

    async def late():
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        turn_outcome.record_accepted_tool_result('late')
        turn_outcome.record_turn_completion('answered')

    child = asyncio.create_task(late())
    try:
        await asyncio.sleep(0)
        turn_outcome.record_turn_completion('refused')
        turn_outcome.record_turn_latency(8)
        expected = sink.close()
        child.cancel()
        release.set()
        await child
        assert sink.close() == expected
        assert expected['completion']['kind'] == 'refused'
    finally:
        release.set()
        await asyncio.gather(child, return_exceptions=True)
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
async def test_concurrent_request_outcomes_do_not_share_completion_or_visible_output():
    async def one(kind: str, text: str):
        sink, token = turn_outcome.open_turn_outcome()
        try:
            await asyncio.sleep(0)
            turn_outcome.record_visible_output(text)
            turn_outcome.record_turn_completion(kind)
            turn_outcome.record_turn_latency(1)
            return sink.close()
        finally:
            turn_outcome.reset_turn_outcome(token)

    first, second = await asyncio.gather(one('answered', 'one'), one('refused', 'a much longer reply'))
    assert first['completion']['kind'] == 'answered'
    assert second['completion']['kind'] == 'refused'
    assert first['output']['tokens'] < second['output']['tokens']


@pytest.mark.asyncio
async def test_nonweb_normal_turn_has_one_diagnostic_and_escaping_error_has_none(caplog):
    caplog.set_level('INFO', logger='agents.core.turn_outcome')

    @turn_outcome.measure_turn_latency
    async def completed():
        turn_outcome.record_turn_completion('command')
        return 'done'

    @turn_outcome.measure_turn_latency
    async def escaping():
        turn_outcome.record_turn_completion('failed')
        raise RuntimeError('synthetic escape')

    assert await completed() == 'done'
    with pytest.raises(RuntimeError):
        await escaping()
    assert [row.message for row in caplog.records if 'turn_completion' in row.message] == [
        'turn_completion kind=command unanswered_tool_results=0']


def test_accounting_bases_and_visible_output_estimate_reconcile_with_provider_usage():
    sink, token = turn_outcome.open_turn_outcome()
    try:
        turn_outcome.record_tool_proposed(queued=True)
        turn_outcome.record_tool_executed(success=False)
        turn_outcome.record_visible_output('hello world')
        estimate = sink.progress()
        assert estimate['output']['basis'] == 'visible_estimate'
        assert estimate['output']['tokens'] > 0
        turn_outcome.record_turn_completion('partial')
        turn_outcome.record_turn_latency(12)
        final = sink.close(usage={'output_tokens': 7, 'usage_basis': 'provider_complete'})
        assert final['tools'] == {'proposed': 1, 'queued': 1, 'executed': 1,
                                  'failures': 1, 'basis': 'observed'}
        assert final['output'] == {'tokens': 7, 'basis': 'provider_complete'}
        assert sink.progress() == final
    finally:
        turn_outcome.reset_turn_outcome(token)


def test_cancelled_handler_before_confirmed_invocation_keeps_execution_count_unknown():
    sink, token = turn_outcome.open_turn_outcome()
    try:
        turn_outcome.record_tool_proposed()
        turn_outcome.record_tool_executed(success=None, known_invocation=False)
        turn_outcome.record_turn_completion('partial')
        turn_outcome.record_turn_latency(1)
        assert sink.close()['tools'] == {
            'proposed': 1, 'queued': 0, 'executed': None, 'failures': None,
            'basis': 'unknown'}
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.parametrize(('observations', 'synthesis', 'expected'), [
    ({'a': 'answered'}, 'none', 'answered'),
    ({'a': 'timeout'}, 'none', 'timeout'),
    ({'a': 'unavailable'}, 'none', 'unavailable'),
    ({'a': 'answered', 'b': 'timeout'}, 'returned', 'partial'),
    ({'a': 'answered', 'b': 'answered'}, 'failed', 'partial'),
    ({'a': 'failed', 'b': 'refused'}, 'failed', 'failed'),
    ({'a': 'pending_approval'}, 'none', 'pending_approval'),
])
def test_agent_observations_map_the_whole_turn(observations, synthesis, expected):
    sink, token = turn_outcome.open_turn_outcome()
    try:
        for agent, kind in observations.items():
            turn_outcome.record_agent_observation(agent, kind)
        assert turn_outcome.settle_agent_turn(synthesis=synthesis)
        turn_outcome.record_turn_latency(1)
        assert sink.close()['completion']['kind'] == expected
    finally:
        turn_outcome.reset_turn_outcome(token)


def test_chat_json_and_stream_share_completion_with_live_progress(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from tests.h441_native_fixture import bind_native

    class FakeOrch:
        session_id = 'h396-session'
        notes = None

        def get_setting(self, key, default=None):
            return ['latency'] if key == 'display.status_bar_fields' else default

        async def handle_input(self, *_args, **_kwargs):
            turn_outcome.record_turn_completion('command')
            turn_outcome.record_turn_latency(11)
            return 'handled'

        async def handle_input_stream(self, *_args, on_token=None, **_kwargs):
            await on_token('visible output')
            turn_outcome.record_turn_completion('answered')
            turn_outcome.record_turn_latency(17)
            return 'visible output'

    orch = FakeOrch()
    bind_native(orch, monkeypatch, session_ids=(orch.session_id,))
    monkeypatch.setattr(web, 'orch', orch)
    client = TestClient(web.app)
    response = client.post('/chat', json={'message': 'command'}).json()
    assert response['outcome']['completion']['kind'] == 'command'
    assert response['outcome']['latency_ms'] == 11
    events = [json.loads(chunk[6:]) for chunk in client.post(
        '/chat/stream', json={'message': 'generate'}).text.split('\n\n')
        if chunk.startswith('data: ')]
    progress = [event for event in events if event['type'] == 'outcome_progress']
    assert progress and progress[-1]['outcome']['output']['basis'] == 'visible_estimate'
    assert progress[-1]['outcome']['output']['tokens'] > 0
    assert events[-1]['outcome']['completion']['kind'] == 'answered'
    assert events[-1]['outcome']['latency_ms'] == 17


def test_stream_reconciles_visible_estimate_with_late_provider_usage(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.turn_usage import model_usage_scope, record_dispatch, record_usage
    from tests.h441_native_fixture import bind_native

    class FakeOrch:
        session_id = 'h396-observed'
        notes = None

        def get_setting(self, key, default=None):
            return ['latency'] if key == 'display.status_bar_fields' else default

        async def handle_input_stream(self, *_args, on_token=None, **_kwargs):
            await on_token('visible first')
            with model_usage_scope(model='synthetic', route='cloud'):
                record_dispatch('openrouter', httpx.Request('POST',
                    'https://synthetic.invalid/v1/chat/completions', json={'model': 'synthetic'}))
                record_usage(TokenUsage(input_tokens=4, output_tokens=17, counts_complete=True))
            turn_outcome.record_turn_completion('answered')
            turn_outcome.record_turn_latency(3)
            return 'visible first'

    orch = FakeOrch()
    bind_native(orch, monkeypatch, session_ids=(orch.session_id,))
    monkeypatch.setattr(web, 'orch', orch)
    events = [json.loads(chunk[6:]) for chunk in TestClient(web.app).post(
        '/chat/stream', json={'message': 'generate'}).text.split('\n\n') if chunk.startswith('data: ')]
    flow = [item['outcome']['output'] for item in events if item['type'] == 'outcome_progress']
    assert flow[0]['basis'] == 'visible_estimate'
    assert flow[-1] == {'tokens': 17, 'basis': 'provider_complete'}
    assert events[-1]['outcome']['output'] == flow[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize(('complete', 'severity'), [(False, 'warning'), (True, 'info')])
async def test_real_tool_loop_result_is_consumed_only_by_later_successful_model(
        complete, severity):
    from agents.core.llm.tool_protocol import ToolTurn
    from tests.test_tool_loop_results import _Backend, _call, _run, _runtime

    turns = [ToolTurn(tool_calls=(_call(),))]
    if complete:
        turns.append(ToolTurn(content='final answer'))
    sink, token = turn_outcome.open_turn_outcome()
    try:
        runtime = _runtime(max_iterations=lambda: 2 if complete else 1)
        await _run(runtime, _Backend(*turns))
        turn_outcome.record_turn_completion('answered' if complete else 'partial')
        turn_outcome.record_turn_latency(1)
        result = sink.close()
        assert result['completion']['severity'] == severity
        assert result['completion']['unanswered_tool_results'] == (0 if complete else 1)
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
async def test_all_parsed_model_tool_proposals_count_even_when_execution_fanout_is_capped():
    from agents.core.llm.tool_protocol import ToolTurn
    from tests.test_tool_loop_results import _Backend, _call, _run, _runtime

    sink, token = turn_outcome.open_turn_outcome()
    try:
        runtime = _runtime(max_tool_calls_per_turn=1, max_iterations=lambda: 1)
        await _run(runtime, _Backend(ToolTurn(tool_calls=(_call(1), _call(2), _call(3)))))
        turn_outcome.record_turn_completion('partial')
        turn_outcome.record_turn_latency(1)
        assert sink.close()['tools']['proposed'] == 3
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(('iterations', 'expected'), [(4, 'warning'), (5, 'info')])
async def test_compacted_tool_result_keeps_observation_until_real_model_completion(
        monkeypatch, iterations, expected):
    from agents.core import agent_runtime
    from agents.core.agent_runtime import AgentToolRuntime
    from tests.test_tool_loop_compaction import _Backend, _server

    monkeypatch.setattr(agent_runtime, 'estimate_messages',
                        lambda rows: sum(len(str(row.get('content', ''))) for row in rows) // 4)
    events = []
    runtime = AgentToolRuntime(_server(4_000), enabled=lambda: True,
        context_budget_tokens=lambda: 2_400, compaction_keep_recent=1,
        max_iterations=lambda: iterations)
    sink, token = turn_outcome.open_turn_outcome()
    try:
        await runtime.run(agent_id='nerva', backend=_Backend(4), model='local-model',
            prompt='fetch a lot', system='You are Nerva.', max_tokens=256,
            temperature=0.2, event_sink=events.append)
        assert any(item.get('event') == 'tool_context_compacted' for item in events)
        turn_outcome.record_turn_completion('answered' if iterations == 5 else 'partial')
        turn_outcome.record_turn_latency(1)
        assert sink.close()['completion']['severity'] == expected
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
async def test_toolrpc_counts_physical_execution_separately_from_queued_proposal():
    from agents.core.tool_rpc import ToolRPCServer

    server = ToolRPCServer(enqueue=lambda *_args, **_kwargs: 42)
    async def local(_args):
        return {'ok': False, 'reason': 'synthetic_failure'}
    server.register_tool('local', local)
    server.register_tool('approval', local, gated=True)
    sink, token = turn_outcome.open_turn_outcome()
    try:
        turn_outcome.record_tool_proposed()
        assert (await server.handle({'tool': 'local', 'args': {}}))['result']['ok'] is False
        turn_outcome.record_tool_proposed()
        assert (await server.handle({'tool': 'approval', 'args': {}}))['reason'] == 'approval_required'
        turn_outcome.record_turn_completion('pending_approval')
        turn_outcome.record_turn_latency(2)
        assert sink.close()['tools'] == {'proposed': 2, 'queued': 1, 'executed': 1,
                                         'failures': 1, 'basis': 'observed'}
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(('body', 'failures', 'basis'), [
    ({'status': 'blocked', 'reason': 'policy_denied'}, 1, 'observed'),
    ({'status': 'denied', 'reason': 'policy_denied'}, 1, 'observed'),
    ({'status': 'completed'}, 0, 'observed'),
    ({'status': 'unclassified'}, None, 'unknown'),
])
async def test_registered_handler_result_status_is_counted_at_physical_execution(
        body, failures, basis):
    from agents.core.tool_rpc import ToolRPCServer

    server = ToolRPCServer()

    async def result(_args):
        return body

    server.register_tool('synthetic', result)
    sink, token = turn_outcome.open_turn_outcome()
    try:
        turn_outcome.record_tool_proposed()
        response = await server.handle({'tool': 'synthetic', 'args': {}})
        assert response['result'] == body
        turn_outcome.record_turn_completion('answered')
        turn_outcome.record_turn_latency(1)
        tools = sink.close()['tools']
        assert tools['proposed'] == 1 and tools['queued'] == 0
        assert tools['basis'] == basis
        assert tools['failures'] == failures
        assert tools['executed'] == 1  # the handler returned even if its disposition is unknown
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(('structured', 'failures', 'basis'), [
    ({'ok': True, 'image': True}, 0, 'observed'),
    ({'ok': False, 'reason': 'image_unreadable'}, 1, 'observed'),
    ({'status': 'blocked', 'reason': 'policy_denied'}, 1, 'observed'),
    ({'status': 'unclassified'}, None, 'unknown'),
    ('opaque', None, 'unknown'),
    (None, None, 'unknown'),
])
async def test_registered_native_content_structured_disposition_counts_without_image_inspection(
        structured, failures, basis):
    from agents.core.tool_rpc import ToolContent, ToolRPCServer

    server = ToolRPCServer()
    image = b'\x89PNG\r\n\x1a\n' + b'\x00' * 24

    async def native(_args):
        return ToolContent([ToolContent.image(image, 'image/png')], structured=structured)

    server.register_tool('native', native)
    sink, token = turn_outcome.open_turn_outcome()
    try:
        turn_outcome.record_tool_proposed()
        response = await server.handle({'tool': 'native', 'args': {}})
        assert response['ok'] is True
        assert response['result'] == structured
        assert response['content'][0]['bytes'] == len(image)
        turn_outcome.record_turn_completion('answered')
        turn_outcome.record_turn_latency(1)
        assert sink.close()['tools'] == {
            'proposed': 1, 'queued': 0, 'executed': 1,
            'failures': failures, 'basis': basis}
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
async def test_toolrpc_prehandler_refusal_is_failure_but_not_physical_execution():
    from agents.core.tool_rpc import ToolRPCServer

    sink, token = turn_outcome.open_turn_outcome()
    try:
        server = ToolRPCServer()
        turn_outcome.record_tool_proposed()
        assert (await server.handle({'tool': 'not_registered', 'args': {}}))['reason'] == 'tool_not_allowed'
        turn_outcome.record_turn_completion('refused')
        turn_outcome.record_turn_latency(1)
        assert sink.close()['tools'] == {
            'proposed': 1, 'queued': 0, 'executed': 0, 'failures': 1, 'basis': 'observed'}
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
async def test_plain_agent_generation_sets_answered_from_backend_return():
    from agents.core.agent import Agent

    class Backend:
        supports_tools = False

        async def generate(self, **_kwargs):
            return 'ordinary answer'

    agent = Agent.__new__(Agent)
    agent.id = 'jarvis'
    agent.tool_runtime = None
    agent.llm_router = None
    agent.model_system_prompt = lambda _backend, _model, system: system
    sink, token = turn_outcome.open_turn_outcome()
    try:
        assert await agent._generate_response(Backend(), 'synthetic-model', 'question',
                                              'system', 64, 0.2) == 'ordinary answer'
        assert turn_outcome.settle_agent_turn()
        turn_outcome.record_turn_latency(1)
        assert sink.close()['completion']['kind'] == 'answered'
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
async def test_real_orchestrator_direct_command_is_source_classified(stream):
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch._session_id_default = 's'
    orch._resolve_session = lambda _sid: 's'

    async def ready(*_args):
        return None

    async def command(*_args):
        return 'started a new session'

    orch._settle_background_review = ready
    orch._guard_foreign_turn = ready
    orch._guard_media_history = ready
    orch._direct_session_command = command
    sink, token = turn_outcome.open_turn_outcome()
    try:
        if stream:
            emitted = []
            answer = await orch._handle_input_stream_prepared('/new', on_token=emitted.append)
            assert emitted == ['started a new session']
        else:
            answer = await orch._handle_input('/new')
        assert answer == 'started a new session'
        turn_outcome.record_turn_latency(1)
        assert sink.close()['completion']['kind'] == 'command'
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
async def test_real_parallel_agent_deadline_maps_partial_without_reply_text_heuristic():
    from types import SimpleNamespace

    from agents.core.orchestrator import Orchestrator

    class Ready:
        last_latency = 0.01

        async def process(self, *_args, **_kwargs):
            return 'real answer'

    class Stalled:
        last_latency = 0.0

        async def process(self, *_args, **_kwargs):
            await asyncio.Event().wait()

        def _record_failure(self, _reason):
            pass

    orch = Orchestrator.__new__(Orchestrator)
    orch._session_id_default = 's'
    orch.agents = {'ready': Ready(), 'stalled': Stalled()}
    orch.get_setting = lambda key, default=None: False if key == 'memory.context_compression' else default

    async def empty(*_args, **_kwargs):
        return ''

    orch._history_for_prompt = empty
    orch._recall_block = empty
    orch._build_agent_turn_text = empty
    orch._format_plugin_data = lambda *_: ''
    orch._runtime_state_block = lambda: ''
    orch._language_block = lambda: ''
    orch._data_grounding_block = lambda *_: ''
    orch._prompt_context = lambda *_: {}
    orch._timeout_inputs_for = lambda *_args, **_kwargs: ('local', 'synthetic')
    orch._agent_call_timeout = lambda **_kwargs: (0.01, 'flat')
    orch._route_for_agent = lambda *_: 'local'
    sink, token = turn_outcome.open_turn_outcome()
    try:
        replies = await orch._call_agents_parallel_prepared(
            ['ready', 'stalled'], 'question', SimpleNamespace(), {})
        assert replies['ready'] == 'real answer'
        assert 'timeout' in replies['stalled']
        assert turn_outcome.settle_agent_turn(synthesis='returned')
        turn_outcome.record_turn_latency(1)
        assert sink.close()['completion']['kind'] == 'partial'
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize(('synthesis_reply', 'expected'), [
    ('[OpenRouter error] synthetic provider outage', 'partial'),
    ('Synthesized answer', 'answered'),
])
async def test_real_agent_synthesis_return_is_observed_before_whole_turn_settlement(
        monkeypatch, synthesis_reply, expected, stream):
    from types import SimpleNamespace

    from agents.core.agent import Agent
    from tests.test_agent_runtime_v2 import _streamed_orchestrator_for

    class Backend:
        async def generate(self, **_kwargs):
            return synthesis_reply

    async def ready(*_args, **_kwargs):
        return None

    backend = Backend()
    jarvis = Agent('jarvis', {'name': 'Jarvis'})
    jarvis.soul = {'content': 'synthetic policy'}
    jarvis.guardrails = None
    jarvis.llm_router = SimpleNamespace(select_backend=lambda *_: (backend, 'local-model', 'local'))
    jarvis.model_system_prompt = lambda _backend, _model, system, **_kwargs: system
    jarvis._ensure_resident = ready
    jarvis._gen_params = lambda _route: (64, 0.2)
    orch, _, _, _ = _streamed_orchestrator_for(jarvis, monkeypatch=monkeypatch)

    async def classify(*_args):
        return ready_intent()

    orch.router.classify = classify

    async def specialist(*_args, **_kwargs):
        name = 'athena' if stream else 'stark'
        turn_outcome.record_agent_observation(name, 'answered')
        return {name: 'real answer'}

    def ready_intent():
        return SimpleNamespace(target_agents=['stark', 'athena'] if stream else ['stark'],
                               is_general=False,
                               context={'keywords_found': [], 'scores': {}, 'source': 'test'})

    orch._call_agents_parallel = specialist
    orch._detect_handoff = lambda _responses: None
    orch._detect_skill_learning = lambda *_args: None
    orch._chat_outcome_block = lambda: ''
    if stream:
        class Specialist:
            id = 'stark'
            name = 'Stark'
            soul = {'content': 'synthetic specialist policy'}
            config = {'model': 'local-model'}

            def build_prompt(self, text, _context):
                return text

            async def generate_response(self, **_kwargs):
                return 'real answer'

        orch.agents['stark'] = Specialist()
        orch.agents['athena'] = Specialist()

        async def history_parts(*_args, **_kwargs):
            return '', ()

        orch._history_for_prompt_parts = history_parts
    sink, token = turn_outcome.open_turn_outcome()
    try:
        if expected == 'partial':
            turn_outcome.record_accepted_tool_result('stark')
        if stream:
            answer = await orch._handle_input_stream_prepared('question', session_id='s',
                                                               on_token=lambda _text: None)
        else:
            answer = await orch._handle_input('question', session_id='s')
        assert answer == synthesis_reply
        turn_outcome.settle_agent_turn()
        turn_outcome.record_turn_latency(1)
        result = sink.close()
        assert result['completion']['kind'] == expected
        assert result['completion']['severity'] == ('warning' if expected == 'partial' else 'info')
        assert result['completion']['unanswered_tool_results'] == (1 if expected == 'partial' else 0)
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
async def test_nonweb_file_effect_without_authenticated_origin_reports_unknown_attribution(tmp_path):
    from agents.core.file_tools import FileScope, FileTools, SnapshotStore

    root = tmp_path / 'workspace'
    root.mkdir()
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / 'snaps'))
    sink, token = turn_outcome.open_turn_outcome()
    try:
        result = await tools.write_file({'path': 'note.txt', 'content': 'synthetic'})
        assert result['ok'] is True
        turn_outcome.record_turn_completion('answered')
        turn_outcome.record_turn_latency(1)
        outcome = sink.close()
        assert outcome['file_mutation_attribution'] == 'unknown'
        assert 'file_mutations' not in outcome
    finally:
        turn_outcome.reset_turn_outcome(token)


def test_session_archive_skips_one_malformed_or_tampered_file_event_without_losing_valid_rows(
        tmp_path, monkeypatch):
    import hashlib
    import hmac

    from agents.core import session_archive
    from agents.core.approval_outcomes import (
        bind_approval_turn,
        close_approval_turn,
        open_approval_turn,
        tool_approval_scope,
    )
    from agents.core.autonomy.mediation import DetachedHMACSigner
    from agents.core.autonomy.queue import TaskQueue, TaskStatus
    from agents.core.commands import Principal

    signer = DetachedHMACSigner(lambda data: hmac.new(b'synthetic-backup-key', data,
                                                     hashlib.sha256).hexdigest())
    queue = TaskQueue(str(tmp_path / 'tasks.db'), mediation_signer=signer).initialize()
    owner = open_approval_turn(session_id='s', session_instance='one',
        principal=Principal(channel='web', admin=True), session_is_live=lambda *_: True)
    token = bind_approval_turn(owner)
    try:
        with tool_approval_scope('file_write'):
            task_id = queue.enqueue('jarvis', 'toolrpc.file_write', 'synthetic file action',
                payload={'tool': 'file_write', 'target': 'file_write', 'args': {'content': 'synthetic'}},
                risk_tier=3, autonomy_level='ask')
            queue.transition(task_id, TaskStatus.BLOCKED, decided_by='policy', decision='needs-approval')
        queue.transition(task_id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
        queue.transition(task_id, TaskStatus.RUNNING)
        task = queue.get(task_id)
        assert queue.file_execution_origin(task) == owner.turn_id
        for attempt in ('1' * 32, '2' * 32, '3' * 32):
            assert queue.record_file_mutation_outcome(task, owner.turn_id, attempt,
                'a' * 64, 'write', 'refused')
        queue._conn.execute('UPDATE file_mutation_outcomes SET outcome=? WHERE attempt_id=?',
                            ('x' * 20_000, '2' * 32))
        queue._conn.execute('UPDATE file_mutation_outcomes SET signature=? WHERE attempt_id=?',
                            ('0' * 64, '3' * 32))
        queue._conn.commit()
        monkeypatch.setattr(session_archive, '_files', lambda *_args: {})
        archive = session_archive.collect('s', checkpoints=None, todos=None,
            outcomes_queue=queue, session_instance='one')
        assert [row['attempt_id'] for row in archive['chat_approval_outcomes']['file_mutations']] == [
            '1' * 32]
        assert queue._conn.execute('SELECT COUNT(*) FROM file_mutation_outcomes').fetchone()[0] == 3
    finally:
        close_approval_turn(owner, token)
        queue.close()


@pytest.mark.asyncio
async def test_signed_owner_file_task_tracks_verified_effect_without_rewriting_closed_turn(tmp_path, monkeypatch):
    import hashlib
    import hmac
    import threading
    from dataclasses import replace

    from agents.core import file_checkpoint_history as history_module
    from agents.core.approval_outcomes import (
        bind_approval_turn,
        close_approval_turn,
        open_approval_turn,
        tool_approval_scope,
    )
    from agents.core.autonomy.mediation import DetachedHMACSigner
    from agents.core.autonomy.queue import TaskQueue, TaskStatus
    from agents.core.commands import Principal
    from agents.core.file_checkpoint_history import HISTORY_SUPPORTED
    from agents.core.file_tools import FileScope, FileTools, SnapshotStore, register_file_tools
    from agents.core.tool_rpc import ToolRPCServer

    if not HISTORY_SUPPORTED:
        pytest.skip('verified owned history requires no-follow dirfd support')
    root = tmp_path / 'workspace'
    root.mkdir()
    target = root / 'note.txt'
    target.write_bytes(b'old')
    (root / 'alias.txt').symlink_to(target)
    signer = DetachedHMACSigner(lambda data: hmac.new(b'synthetic-queue-key', data, hashlib.sha256).hexdigest())
    queue = TaskQueue(str(tmp_path / 'tasks.db'), mediation_signer=signer).initialize()
    gate = object()
    owner = open_approval_turn(session_id='s', session_instance='one',
        principal=Principal(channel='web', admin=True), session_is_live=lambda *_: True)
    origin_token = bind_approval_turn(owner)
    sink, outcome_token = turn_outcome.open_turn_outcome()
    turn_outcome.bind_approval_origin(owner.turn_id)

    def intake(actor, name, args, labels):
        with tool_approval_scope(name):
            task_id = queue.enqueue(actor, f'toolrpc.{name}', f'{name} synthetic',
                payload={'tool': name, 'target': name, 'args': dict(args), **dict(labels or {})},
                risk_tier=3, autonomy_level='ask')
            queue.transition(task_id, TaskStatus.BLOCKED, decided_by='policy', decision='needs-approval')
            return task_id

    def lookup(task):
        origin_id = queue.file_execution_origin(task)
        return (turn_outcome.FileExecutionOrigin(origin_id,
            lambda attempt, path, op, result: queue.record_file_mutation_outcome(
                task, origin_id, attempt, path, op, result)) if origin_id else None)

    server = ToolRPCServer(execution_context_check=lambda context, task: context is gate,
                           file_origin_lookup=lookup)
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / 'snaps'))
    register_file_tools(server, tools, enabled=True, mutation_intake=intake)
    try:
        proposed = await server.handle({'tool': 'file_write', 'args':
            {'path': 'alias.txt', 'content': 'new'}}, actor='jarvis')
        assert proposed['reason'] == 'approval_required'
        task = queue.get(proposed['task_id'])
        assert queue.file_execution_origin(task) is None  # owner has not approved execution
        assert sink.progress()['tools']['queued'] == 1
        assert sink.progress()['tools']['executed'] == 0

        queue.transition(task.id, TaskStatus.APPROVED, decided_by='owner', decision='accept')
        queue.transition(task.id, TaskStatus.RUNNING)
        task = queue.get(task.id)
        assert queue.file_execution_origin(task) == owner.turn_id
        forged = replace(task, created_at='forged')
        assert queue.file_execution_origin(forged) is None
        assert queue.file_execution_origin(replace(task, agent='forged-agent')) is None
        result = await server.execute(task, execution_context=gate)
        assert result['status'] == 'ok' and target.read_bytes() == b'new'
        events = queue._conn.execute('SELECT target_sha256,outcome FROM file_mutation_outcomes').fetchall()
        assert [(row[0], row[1]) for row in events] == [
            (hashlib.sha256(str(target).encode()).hexdigest(), 'verified')]
        denied = await server.handle({'tool': 'file_delete', 'args': {'path': 'later.txt'}}, actor='jarvis')
        queue.transition(denied['task_id'], TaskStatus.APPROVED, decided_by='owner', decision='accept')
        queue.transition(denied['task_id'], TaskStatus.RUNNING)
        assert (await server.execute(queue.get(denied['task_id']), execution_context=gate))['reason'] == 'not_found'
        recovery = await server.handle({'tool': 'file_write', 'args':
            {'path': 'later.txt', 'content': 'created'}}, actor='jarvis')
        queue.transition(recovery['task_id'], TaskStatus.APPROVED, decided_by='owner', decision='accept')
        queue.transition(recovery['task_id'], TaskStatus.RUNNING)
        assert (await server.execute(queue.get(recovery['task_id']), execution_context=gate))['status'] == 'ok'
        other = await server.handle({'tool': 'file_delete', 'args': {'path': 'other.txt'}}, actor='jarvis')
        queue.transition(other['task_id'], TaskStatus.APPROVED, decided_by='owner', decision='accept')
        queue.transition(other['task_id'], TaskStatus.RUNNING)
        assert (await server.execute(queue.get(other['task_id']), execution_context=gate))['reason'] == 'not_found'
        uncertain = await server.handle({'tool': 'file_write', 'args':
            {'path': 'unverified.txt', 'content': 'physical bytes'}}, actor='jarvis')
        queue.transition(uncertain['task_id'], TaskStatus.APPROVED, decided_by='owner', decision='accept')
        queue.transition(uncertain['task_id'], TaskStatus.RUNNING)
        ordinary_state = history_module._state

        def no_readback(*args, **kwargs):
            if kwargs.get('single_link') and kwargs.get('expected_dev') is not None:
                raise history_module.CheckpointRefusal('readback_unavailable')
            return ordinary_state(*args, **kwargs)

        with monkeypatch.context() as m:
            m.setattr(history_module, '_state', no_readback)
            uncertain_result = await server.execute(queue.get(uncertain['task_id']), execution_context=gate)
            assert uncertain_result['status'] == 'ok', uncertain_result
        assert (root / 'unverified.txt').read_bytes() == b'physical bytes'
        later = await server.handle({'tool': 'file_delete', 'args': {'path': 'note.txt'}}, actor='jarvis')
        assert later['reason'] == 'approval_required'
        turn_outcome.record_turn_completion('pending_approval')
        turn_outcome.record_turn_latency(1)
        final = sink.close()
        assert final['file_mutations'] == [
            {'attempt': 4, 'operation': 'delete', 'outcome': 'refused'},
            {'attempt': 5, 'operation': 'write', 'outcome': 'applied_unverified'}]
        assert str(root) not in str(final)
        queue.transition(later['task_id'], TaskStatus.APPROVED, decided_by='owner', decision='accept')
        queue.transition(later['task_id'], TaskStatus.RUNNING)
        later_task = queue.get(later['task_id'])
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        original_apply = tools.history.apply_mutation

        def held_apply(*args, **kwargs):
            started.set()
            try:
                assert release.wait(3)
                return original_apply(*args, **kwargs)
            finally:
                finished.set()

        monkeypatch.setattr(tools.history, 'apply_mutation', held_apply)
        pending = asyncio.create_task(server.execute(later_task, execution_context=gate))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
        assert not target.exists()
        assert queue._conn.execute('SELECT COUNT(*) FROM file_mutation_outcomes').fetchone()[0] == 6
        assert len(queue.chat_outcomes_for_backup('s', session_instance='one')['file_mutations']) == 6
        queue._conn.execute('UPDATE file_mutation_outcomes SET outcome=? WHERE sequence=5', ('verified',))
        queue._conn.commit()
        assert len(queue.chat_outcomes_for_backup('s', session_instance='one')['file_mutations']) == 5
        queue._conn.execute('UPDATE chat_approval_tasks SET h396_signature=? WHERE task_id=?',
                            ('0' * 64, task.id))
        queue._conn.commit()
        assert queue.file_execution_origin(task) is None
        assert queue.record_file_mutation_outcome(task, owner.turn_id, 'f' * 32,
            '0' * 64, 'write', 'verified') is False
        assert await server.execute(task, execution_context=object()) == {
            'status': 'failed', 'reason': 'trusted_execution_required', 'tool': 'file_write'}
        assert sink.close() == final
    finally:
        turn_outcome.reset_turn_outcome(outcome_token)
        close_approval_turn(owner, origin_token)
        queue.close()
