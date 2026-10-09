"""An Anthropic prompt subtotal is not a complete context-size observation."""

from collections import OrderedDict
from types import SimpleNamespace

import pytest

from agents.core.context_compressor import ContextCompressor
from agents.core.llm.tool_dialects import anthropic_usage
from agents.core.llm.tool_protocol import TokenUsage
from agents.core.orchestrator import Orchestrator, _billable_from_usage, _sum_usage
from agents.core.route_compaction import remember_usage, trusted_anchor


def _usage(*, plain=23, read=90, write=10, output=17):
    raw = {"input_tokens": plain, "output_tokens": output,
           "cache_read_input_tokens": read, "cache_creation_input_tokens": write}
    return anthropic_usage({"usage": raw})


def _route():
    return SimpleNamespace(identity=object(), model="claude-test")


def test_complete_prompt_partition_and_output_independence():
    full = _usage()
    assert full.as_dict() == {
        "input_tokens": 23, "output_tokens": 17,
        "cache_read": 90, "cache_write": 10,
    }
    assert full.counts_complete is True
    assert getattr(full, "prompt_counts_complete", None) is True
    assert _billable_from_usage(full) == (123, 17, 90)

    missing_output = anthropic_usage({"usage": {
        "input_tokens": 23, "cache_read_input_tokens": 90,
        "cache_creation_input_tokens": 10,
    }})
    assert missing_output.as_dict() == {
        "input_tokens": 23, "output_tokens": 0,
        "cache_read": 90, "cache_write": 10,
    }
    assert missing_output.counts_complete is False
    assert getattr(missing_output, "prompt_counts_complete", None) is True
    assert _billable_from_usage(missing_output) is None

    zero = _usage(plain=0, read=0, write=0, output=0)
    assert zero.reported is False
    assert zero.as_dict() == dict.fromkeys(full.as_dict(), 0)
    assert getattr(zero, "prompt_counts_complete", None) is True


@pytest.mark.parametrize("field", [
    "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
])
@pytest.mark.parametrize("defect", ["missing", None, True, 0.0, -1])
def test_partial_prompt_partition_preserves_valid_siblings(field, defect):
    raw = {"input_tokens": 23, "output_tokens": 17,
           "cache_read_input_tokens": 90, "cache_creation_input_tokens": 10}
    if defect == "missing":
        raw.pop(field)
    else:
        raw[field] = defect
    usage = anthropic_usage({"usage": raw})
    normalized = {"input_tokens": 23, "output_tokens": 17,
                  "cache_read": 90, "cache_write": 10}
    normalized[{"input_tokens": "input_tokens",
                "cache_read_input_tokens": "cache_read",
                "cache_creation_input_tokens": "cache_write"}[field]] = 0
    assert usage.as_dict() == normalized
    assert usage.counts_complete is False
    assert getattr(usage, "prompt_counts_complete", None) is False


@pytest.mark.parametrize("wire", [{}, {"usage": None}, {"usage": []}])
def test_absent_usage_is_not_complete_prompt_evidence(wire):
    usage = anthropic_usage(wire)
    assert usage.as_dict() == dict.fromkeys(TokenUsage().as_dict(), 0)
    assert getattr(usage, "prompt_counts_complete", None) is False


def test_unmanaged_complete_high_anchor_survives_partial_low_observation():
    full = _usage(plain=7_000, read=0, write=0)
    partial = anthropic_usage({"usage": {
        "input_tokens": 23, "output_tokens": 17,
        "cache_read_input_tokens": 90,
    }})
    assert partial.as_dict() == {
        "input_tokens": 23, "output_tokens": 17,
        "cache_read": 90, "cache_write": 0,
    }
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    orch._record_context_anchor("jarvis", full)
    orch._record_context_anchor("jarvis", partial)
    assert orch._context_anchor["jarvis"] == (7_000, 6)
    anchor = orch._usage_anchor(7)
    rows = [{"role": "user", "content": "small"}] * 7
    assert ContextCompressor()._used(rows, anchor) >= 7_000
    assert partial.counts_complete is False
    assert getattr(partial, "prompt_counts_complete", None) is False


def test_unmanaged_partial_cannot_create_anchor_but_full_prompt_without_output_can():
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    partial = anthropic_usage({"usage": {
        "input_tokens": 23, "cache_read_input_tokens": 90,
    }})
    orch._record_context_anchor("jarvis", partial)
    assert orch._usage_anchor(6) is None

    full_prompt = anthropic_usage({"usage": {
        "input_tokens": 23, "cache_read_input_tokens": 90,
        "cache_creation_input_tokens": 10,
    }})
    assert full_prompt.counts_complete is False
    orch._record_context_anchor("jarvis", full_prompt)
    assert orch._usage_anchor(6).prompt_tokens == 123
    orch._record_context_anchor("jarvis", _usage(plain=0, read=0, write=0, output=0))
    assert orch._usage_anchor(6).prompt_tokens == 123


def test_managed_complete_anchor_survives_partial_with_same_prefix_and_keeps_order():
    route = _route()
    other = _route()
    rows = [{"role": "user", "content": "hello"}]
    store = OrderedDict()
    remember_usage(store, "session", "jarvis", route, rows, "instance",
                   _usage(plain=7_000, read=0, write=0))
    remember_usage(store, "session", "other", other, rows, "instance", _usage())
    old = store[("session", "jarvis")]
    before = list(store)
    partial = anthropic_usage({"usage": {
        "input_tokens": 23, "output_tokens": 17,
        "cache_read_input_tokens": 90,
    }})
    remember_usage(store, "session", "jarvis", route, rows, "instance", partial)
    assert list(store) == before
    assert store[("session", "jarvis")] is old
    assert trusted_anchor(store, "session", {"jarvis": route}, rows, "instance").prompt_tokens == 7_000
    assert trusted_anchor(store, "session", {"jarvis": _route()}, rows, "instance") is None
    assert trusted_anchor(store, "session", {"jarvis": route},
                          [{"role": "user", "content": "changed"}], "instance") is None


def test_managed_partial_cannot_create_anchor_but_complete_prompt_without_output_can():
    route = _route()
    rows = [{"role": "user", "content": "hello"}]
    store = OrderedDict()
    partial = anthropic_usage({"usage": {
        "input_tokens": 23, "cache_read_input_tokens": 90,
    }})
    remember_usage(store, "session", "jarvis", route, rows, "instance", partial)
    assert not store
    full_prompt = anthropic_usage({"usage": {
        "input_tokens": 23, "cache_read_input_tokens": 90,
        "cache_creation_input_tokens": 10,
    }})
    assert full_prompt.counts_complete is False
    remember_usage(store, "session", "jarvis", route, rows, "instance", full_prompt)
    assert trusted_anchor(store, "session", {"jarvis": route}, rows, "instance").prompt_tokens == 123
    before = store[("session", "jarvis")]
    remember_usage(store, "session", "jarvis", route, rows, "instance",
                   _usage(plain=0, read=0, write=0, output=0))
    assert store[("session", "jarvis")] is before


def test_accounting_aggregate_is_never_one_request_prompt_anchor():
    full = _usage()
    assert _sum_usage(None, full) is full
    another = _usage(plain=7, read=0, write=0, output=3)
    combined = _sum_usage(full, another)
    assert combined.as_dict() == {
        "input_tokens": 30, "output_tokens": 20,
        "cache_read": 90, "cache_write": 10,
    }
    assert combined.counts_complete is True
    assert getattr(combined, "prompt_counts_complete", None) is False
    assert _billable_from_usage(combined) == (130, 20, 90)

    legacy = TokenUsage(input_tokens=8)
    assert getattr(legacy, "prompt_counts_complete", None) is None
    legacy_sum = _sum_usage(legacy, TokenUsage(input_tokens=9))
    assert legacy_sum.input_tokens == 17
    assert legacy_sum.counts_complete is None
    assert getattr(legacy_sum, "prompt_counts_complete", None) is False
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 1
    orch._record_context_anchor("jarvis", legacy_sum)
    assert orch._usage_anchor(1) is None
