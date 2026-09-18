"""Frozen H679 empty vocabulary means no reasoning request parameters."""
import json

import httpx
import pytest

from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.reasoning_effort import (
    apply_anthropic,
    declare_reasoning_efforts,
    forget_reasoning_efforts,
    supported_reasoning_efforts,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['override','registry'])
@pytest.mark.parametrize('model', ['claude-opus-4-7','claude-opus-5','claude-sonnet-4-5'])
@pytest.mark.parametrize('method', ['generate','generate_stream','generate_tool_turn'])
async def test_explicit_empty_omits_all_reasoning_on_actual_wire(source, model, method):
    forget_reasoning_efforts('anthropic', model)
    if source == 'registry':
        declare_reasoning_efforts('anthropic', model, ())
    backend = ClaudeBackend('fixture', reasoning_effort='high',
                            effort_overrides={model:[]} if source=='override' else None)
    await backend.client.aclose()
    bodies = []
    def handle(req):
        body = json.loads(req.content)
        bodies.append(body)
        if body.get('stream'):
            return httpx.Response(200, text='data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"answer"}}\n\ndata: {"type":"message_stop"}\n\n')
        return httpx.Response(200,json={'content':[{'type':'text','text':'answer'}]})
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    kwargs = {'model':model,'max_tokens':4096}
    kwargs.update({'messages':[],'tools':[]} if method=='generate_tool_turn' else {'prompt':'hello'})
    try:
        result = await getattr(backend, method)(**kwargs)
        assert (result.content if method=='generate_tool_turn' else result) == 'answer'
        assert len(bodies) == 1
        assert 'thinking' not in bodies[0]
        assert 'effort' not in bodies[0].get('output_config', {})
    finally:
        await backend.client.aclose()
        forget_reasoning_efforts('anthropic',model)


@pytest.mark.parametrize('requested', [None,'none','high'])
def test_empty_removes_prior_controls_but_preserves_output_format(requested):
    payload = {'model':'claude-opus-5','max_tokens':4096,'temperature':0.5,
               'thinking':{'type':'adaptive'},'output_config':{'effort':'high','format':{'type':'json_schema'}}}
    result = apply_anthropic(payload,payload['model'],requested,overrides={'claude-opus-5':()})
    assert 'thinking' not in payload and 'temperature' not in payload
    assert payload['output_config'] == {'format':{'type':'json_schema'}}
    assert result.reason == 'unsupported'


def test_budget_family_advertises_product_rungs_without_effort_wire_field():
    vocab = supported_reasoning_efforts('anthropic','claude-sonnet-4-5')
    assert vocab and 'minimal' in vocab and 'high' in vocab
    payload = {'max_tokens':4096}
    apply_anthropic(payload,'claude-sonnet-4-5','high')
    assert payload['thinking'] == {'type':'enabled','budget_tokens':3072}
    assert 'output_config' not in payload


def test_budget_declaration_clamps_without_creating_effort_parameter():
    payload = {'max_tokens':16384}
    apply_anthropic(payload,'claude-sonnet-4-5','ultra',overrides={'claude-sonnet-4-5':('low',)})
    assert payload['thinking'] == {'type':'enabled','budget_tokens':2048}
    assert 'output_config' not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['generate','generate_stream','generate_tool_turn'])
@pytest.mark.parametrize('declared', [False,True])
async def test_budget_only_real_wire_never_invents_effort_field(method, declared):
    model = 'claude-sonnet-4-5'
    forget_reasoning_efforts('anthropic',model)
    if declared:
        declare_reasoning_efforts('anthropic',model,('low',))
    backend = ClaudeBackend('fixture', reasoning_effort='ultra')
    await backend.client.aclose()
    bodies = []
    def handle(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200,json={'content':[{'type':'text','text':'answer'}]})
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    kwargs = {'model':model,'max_tokens':16384}
    kwargs.update({'messages':[],'tools':[]} if method=='generate_tool_turn' else {'prompt':'hello'})
    try:
        await getattr(backend,method)(**kwargs)
        assert len(bodies) == 1
        assert bodies[0]['thinking'] == {'type':'enabled','budget_tokens':2048 if declared else 15360}
        assert 'output_config' not in bodies[0]
    finally:
        await backend.client.aclose()
        forget_reasoning_efforts('anthropic',model)


def test_empty_removes_an_output_config_containing_only_effort():
    payload = {'max_tokens':4096,'thinking':{'type':'enabled'},'output_config':{'effort':'high'}}
    apply_anthropic(payload,'claude-sonnet-4-5','high',overrides={'claude-sonnet-4-5':()})
    assert payload == {'max_tokens':4096}


def test_budget_declared_floor_does_not_bypass_no_escalation():
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    with pytest.raises(ReasoningEffortRefused):
        apply_anthropic({'max_tokens':4096},'claude-sonnet-4-5','minimal',
                        overrides={'claude-sonnet-4-5':('high',)})


@pytest.mark.parametrize('model',['claude-opus-5','claude-sonnet-4-5'])
def test_empty_constructor_declaration_wins_over_nonempty_registry(model):
    declare_reasoning_efforts('anthropic',model,('high',))
    try:
        assert supported_reasoning_efforts('anthropic',model,overrides={model:()}) == ()
        payload = {'max_tokens':4096}
        apply_anthropic(payload,model,'high',overrides={model:()})
        assert 'thinking' not in payload and 'output_config' not in payload
    finally:
        forget_reasoning_efforts('anthropic',model)


@pytest.mark.parametrize('model',['claude-opus-5','claude-sonnet-4-5'])
def test_empty_registry_wins_over_nonempty_constructor_declaration(model):
    declare_reasoning_efforts('anthropic',model,())
    try:
        payload = {'max_tokens':4096}
        apply_anthropic(payload,model,'high',overrides={model:('high',)})
        assert 'thinking' not in payload and 'output_config' not in payload
    finally:
        forget_reasoning_efforts('anthropic',model)
