"""Reported disjoint cache categories still occupy the request context."""
import pytest

from agents.core.llm.tool_dialects import anthropic_usage, lmstudio_usage, ollama_usage
from agents.core.llm.tool_protocol import TokenUsage
from agents.core.orchestrator import Orchestrator, _billable_from_usage


@pytest.mark.parametrize('plain,read,write', [(12, 700, 300), (0, 700, 0), (0, 0, 300)])
def test_anthropic_complete_prefix_anchor(plain, read, write):
    usage = anthropic_usage({'usage': {'input_tokens': plain, 'output_tokens': 41,
        'cache_read_input_tokens': read, 'cache_creation_input_tokens': write}})
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    orch._record_context_anchor('jarvis', usage)
    assert orch._usage_anchor(6).prompt_tokens == plain + read + write
    assert _billable_from_usage(usage) == (plain + read + write, 41, read)
    orch._record_context_anchor('jarvis', TokenUsage(input_tokens=99))
    orch._record_context_anchor('jarvis', TokenUsage(output_tokens=9999))
    assert orch._usage_anchor(6).prompt_tokens == 99


@pytest.mark.parametrize('usage', [
    lmstudio_usage({'usage': {'prompt_tokens': 1000, 'completion_tokens': 7,
                             'prompt_tokens_details': {'cached_tokens': 900}}}),
    ollama_usage({'prompt_eval_count': 1000, 'eval_count': 7}),
])
def test_totals_only_anchor_is_not_double_counted(usage):
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    orch._record_context_anchor('jarvis', usage)
    assert orch._usage_anchor(6).prompt_tokens == 1000
    assert _billable_from_usage(usage) == (1000, 7, 0)
