"""Scoped observers cannot outlive a call or publish tool usage twice."""
import asyncio

import pytest

from agents.core.llm.tool_protocol import TokenUsage


def module():
    from agents.core.llm import usage_context
    return usage_context


def test_nested_scopes_restore_and_direct_calls_are_silent():
    m = module()
    outer, inner = [], []
    with m.observer_scope(outer.append) as observe:
        assert m.current_observer() is observe
        m.report_text_usage(TokenUsage(input_tokens=1))
        with m.text_usage_scope(observe):
            m.report_text_usage(TokenUsage(input_tokens=2))
            with m.text_usage_scope(inner.append):
                m.report_text_usage(TokenUsage(input_tokens=3))
            m.report_text_usage(TokenUsage(input_tokens=4))
        with m.observer_scope(inner.append):
            assert m.current_observer() is not observe
        assert m.current_observer() is observe
    observe(TokenUsage(input_tokens=99))
    assert m.current_observer() is None
    assert [u.input_tokens for u in outer] == [2, 4]
    assert [u.input_tokens for u in inner] == [3]


def test_empty_usage_and_raising_observer_are_nonfatal():
    m = module()
    calls = []
    def broken(usage):
        calls.append(usage)
        raise ValueError('meter unavailable')
    with m.observer_scope(broken) as observer, m.text_usage_scope(observer):
        m.report_text_usage(TokenUsage())
        m.report_text_usage(TokenUsage(input_tokens=3))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cancelled_scope_closes_inherited_late_task():
    m = module()
    events, children = [], []
    ready, release = asyncio.Event(), asyncio.Event()
    async def late():
        await release.wait()
        m.report_text_usage(TokenUsage(input_tokens=99))
        m.current_observer()(TokenUsage(input_tokens=99))
    async def run():
        with m.observer_scope(events.append) as observer, m.text_usage_scope(observer):
            children.append(asyncio.create_task(late()))
            ready.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(run())
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await children[0]
    assert events == [] and m.current_observer() is None


@pytest.mark.asyncio
@pytest.mark.parametrize('tools', [False, True])
async def test_agent_and_real_nonstream_gather_report_once(tools):
    from agents.core.agent import Agent
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.base import LLMBackend
    from agents.core.llm.tool_protocol import ToolTurn
    from agents.core.tool_rpc import ToolRPCServer
    from tests.test_reasoning_timeout import _orch
    m = module()
    class Backend(LLMBackend):
        supports_tools = True
        async def generate(self, model, prompt, system='', max_tokens=1024, temperature=.7):
            m.report_text_usage(TokenUsage(input_tokens=int(prompt), output_tokens=7))
            return 'answer'
        async def generate_tool_turn(self, model, messages, tools, max_tokens=1024, temperature=.7):
            usage = TokenUsage(input_tokens=int(messages[-1]['content']), output_tokens=7)
            # A tool backend attempting text publication must not duplicate its ToolTurn.
            m.report_text_usage(usage)
            return ToolTurn(content='answer', usage=usage)
    backend = Backend()
    def make_agent(aid):
        agent = Agent.__new__(Agent)
        agent.id = aid
        agent._checkpoint_manager = None
        agent.tool_event_sink = lambda event: None
        agent.tool_runtime = None
        if tools:
            server = ToolRPCServer()
            server.register_tool('unused', lambda args: None, input_schema={'type': 'object'})
            agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)
        agent._last_latency = 0.1
        from types import SimpleNamespace
        agent.soul = {}
        agent.guardrails = None
        agent.llm_router = SimpleNamespace(select_backend=lambda aid, prompt: (backend, 'model', 'local'))
        agent.default_model = lambda: 'model'
        agent.build_prompt = lambda text, context: text
        agent._gen_params = lambda route: (128, .2)
        return agent
    orch = _orch(agents={aid: make_agent(aid) for aid in ('jarvis', 'stark')})
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    async def build(aid, text, **kwargs):
        return '9000' if aid == 'jarvis' else '123'
    orch._build_agent_turn_text = build
    accidental = []
    with m.text_usage_scope(accidental.append):
        assert await orch._call_agents_parallel(['jarvis', 'stark'], 'hello', {}) == {'jarvis': 'answer', 'stark': 'answer'}
    assert accidental == []
    assert {key: value.input_tokens for key, value in orch._last_reported_usage.items()} == {'jarvis': 9000, 'stark': 123}
    assert orch._context_anchor == {'jarvis': (9000, 6), 'stark': (123, 6)}
    await orch._call_agents_parallel([], 'empty next turn', {})
    assert orch._last_reported_usage == {}
    assert m.current_observer() is None
