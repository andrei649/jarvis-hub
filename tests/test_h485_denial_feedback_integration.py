"""Guardian denials reach the next real owner turn without replay or authority."""
import asyncio
import json

import httpx
import pytest

from agents.core.approval_outcomes import render_chat_outcomes
from agents.core.autonomy.approval_judge import ApprovalJudge
from agents.core.commands import Principal
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.egress import llm_async_client
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
from tests.test_h277_smart_judge import isolated_judge_settings  # noqa: F401
from tests.test_h487_chat_outcome_integration import chat  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('failed_answer', [False, True])
async def test_three_native_guardian_denials_warn_next_owner_turn_once(chat, monkeypatch, stream, failed_answer):
    monkeypatch.setenv('JARVIS_SMART_APPROVALS', '1')
    monkeypatch.delenv('JARVIS_SMART_DENIAL_BREAKER_THRESHOLD', raising=False)
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'DENY'}}]})

    def backend_for(status):
        backend = object.__new__(LMStudioBackend)
        backend.base_url = 'http://localhost:1234'
        backend.client = llm_async_client('lm-studio', base_url=backend.base_url,
                                          trust_env=False, transport=httpx.MockTransport(handler))
        return backend

    judge = ApprovalJudge(backend_factory=backend_for, settings=lambda *args: 'on-demand')
    chat.worker.attach_approval_judge(judge, loop=asyncio.get_running_loop())

    async def execute(args):
        chat.executed.append(args)
        return {'ok': True}

    chat.server.register_tool('terminal_run', execute, gated=True)
    entry = chat.orch.handle_input_stream if stream else chat.orch.handle_input
    principal = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        for n in range(3):
            args = {'target': 'local-host', 'command': f'pwd # attempt {n}',
                    'cwd': '/tmp', 'timeout': 15}
            chat.backend.turns.append(ToolTurn(tool_calls=(ToolCall(
                id=f'terminal-{n}', name='terminal_run', raw_arguments=json.dumps(args), arguments=args),)))
            await entry('run the terminal operation', channel='web', session_id='s')
            adapter = chat.worker.approval_judge
            if adapter._judge_tasks:
                await asyncio.gather(*tuple(adapter._judge_tasks))
        assert len(requests) == 3
        assert all(task.status == 'rejected' for task in chat.q.list())
        if failed_answer:
            chat.backend.turns.append(ToolTurn(content='[Gemini error: failed]'))
            await entry('what happened?', channel='web', session_id='s')
            assert 'STOP attempting variations' in str(chat.backend.calls[-1]['messages'])
        chat.backend.turns.append(ToolTurn(content='The reviewer denied it; I will stop retrying.'))
        await entry('what happened?', channel='web', session_id='s')
        prompt = str(chat.backend.calls[-1]['messages'])
        assert 'STOP attempting variations' in prompt
        assert 'consecutive_denials' in prompt and 'guardian' in prompt
        assert 'Do not replay' in prompt and chat.executed == []
        chat.backend.turns.append(ToolTurn(content='A different question.'))
        await entry('next question', channel='web', session_id='s')
        assert 'Approval outcome observations' not in str(chat.backend.calls[-1]['messages'])
        assert len(chat.q.list()) == 3 and chat.executed == []
    finally:
        reset_turn_principal(principal)


@pytest.mark.parametrize('guardian', [
    {'decision': 'deny', 'consecutive_denials': 3, 'breaker': True},
    {'decision': 'deny', 'consecutive_denials': 1_000_000, 'breaker': True},
])
def test_breaker_guidance_shares_fenced_output_budget(guardian):
    item = {'task_id': 1, 'state': 'blocked', 'outcome': 'waiting', 'guardian': guardian}
    block, included = render_chat_outcomes([item])
    assert 'STOP attempting variations' in block
    assert 'UNTRUSTED' in block and len(block.encode()) <= 4096
    assert included == [item]
    assert render_chat_outcomes([item], max_bytes=len(block.encode()) - 1) == ('', [])


@pytest.mark.parametrize('guardian', [
    None, {}, {'decision': 'approve', 'consecutive_denials': 3, 'breaker': True},
    {'decision': 'deny', 'consecutive_denials': True, 'breaker': True},
    {'decision': 'deny', 'consecutive_denials': 0, 'breaker': True},
    {'decision': 'deny', 'consecutive_denials': 1_000_001, 'breaker': True},
    {'decision': 'deny', 'consecutive_denials': 3, 'breaker': 'true'},
    {'decision': 'deny', 'consecutive_denials': 3, 'breaker': False},
    {'decision': 'deny', 'consecutive_denials': 3, 'breaker': True, 'message': 'model instruction'},
])
def test_unvalidated_feedback_cannot_insert_stop_instruction(guardian):
    block, _ = render_chat_outcomes([{'task_id': 1, 'guardian': guardian}])
    assert 'STOP attempting variations' not in block
