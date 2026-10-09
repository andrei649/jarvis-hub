"""Anthropic's optional cache fields are not evidence of known zero counts."""

from collections import OrderedDict
from types import SimpleNamespace

import pytest

from agents.core.llm.tool_dialects import anthropic_usage
from agents.core.orchestrator import Orchestrator, _billable_from_usage
from agents.core.route_compaction import remember_usage, trusted_anchor
from tests.test_usage_counter_accounting import _record

COUNTS = {
    "input_tokens": 23,
    "output_tokens": 17,
    "cache_read_input_tokens": 90,
    "cache_creation_input_tokens": 10,
}
FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}


def test_four_explicit_categories_include_valid_zero_observation():
    usage = anthropic_usage({"usage": COUNTS})
    assert usage.as_dict() == {
        "input_tokens": 23, "output_tokens": 17, "cache_read": 90, "cache_write": 10,
    }
    assert usage.counts_complete is True
    assert _billable_from_usage(usage) == (123, 17, 90)

    zero = anthropic_usage({"usage": dict.fromkeys(COUNTS, 0)})
    assert zero.as_dict() == dict.fromkeys(usage.as_dict(), 0)
    assert zero.reported is False
    assert zero.counts_complete is True
    assert _billable_from_usage(zero) == (0, 0, 0)


@pytest.mark.parametrize("field,normalized", FIELDS.items())
@pytest.mark.parametrize("defect", ["missing", None, True])
def test_each_missing_null_or_invalid_category_preserves_valid_siblings(field, normalized, defect):
    raw = dict(COUNTS)
    if defect == "missing":
        raw.pop(field)
    else:
        raw[field] = defect
    usage = anthropic_usage({"usage": raw})
    expected = {"input_tokens": 23, "output_tokens": 17, "cache_read": 90, "cache_write": 10}
    expected[normalized] = 0
    assert usage.as_dict() == expected
    assert usage.reported is True
    assert usage.counts_complete is False
    assert _billable_from_usage(usage) is None


@pytest.mark.parametrize("wire", [{}, {"usage": None}, {"usage": []}])
def test_absent_usage_is_incomplete_even_when_normalized_to_zero(wire):
    usage = anthropic_usage(wire)
    assert usage.as_dict() == dict.fromkeys(FIELDS.values(), 0)
    assert usage.reported is False
    assert usage.counts_complete is False
    assert _billable_from_usage(usage) is None


def test_partial_cache_categories_estimate_with_numeric_floors_and_no_discount(monkeypatch):
    # The required SDK pair is valid; omitted optional cache creation is still
    # unknown to this application's disjoint, four-category cost consumer.
    usage = anthropic_usage({"usage": {
        "input_tokens": 23, "output_tokens": 17, "cache_read_input_tokens": 90,
    }})
    assert usage.as_dict() == {
        "input_tokens": 23, "output_tokens": 17, "cache_read": 90, "cache_write": 0,
    }
    # A prefix-cache estimate must not become an observed discount on incomplete
    # provider categories, even when the channel supplied that fallback.
    monkeypatch.setattr(Orchestrator, "_last_cached_tokens", property(lambda _: {"jarvis": 999}))
    metadata, charge = _record(usage, monkeypatch, last_prompt=1)
    assert metadata["usage_source"] == "estimate"
    assert metadata["input_tokens"] >= 113
    assert metadata["output_tokens"] >= 17
    assert metadata["cached_tokens"] == 0
    assert metadata["cache_hit"] is False
    assert charge[0][1:3] == (metadata["input_tokens"], metadata["output_tokens"])
    assert usage.counts_complete is False


def test_positive_partial_prompt_anchors_remain_independent_of_billable_availability():
    partial = anthropic_usage({"usage": {
        "input_tokens": 23, "output_tokens": 17, "cache_read_input_tokens": 90,
    }})
    output_only = anthropic_usage({"usage": {"output_tokens": 17}})
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    orch._record_context_anchor("jarvis", partial)
    assert orch._usage_anchor(6).prompt_tokens == 113
    orch._record_context_anchor("jarvis", output_only)
    assert orch._usage_anchor(6).prompt_tokens == 113

    route = SimpleNamespace(identity=object(), model="claude-test")
    rows = [{"role": "user", "content": "hello"}]
    store = OrderedDict()
    remember_usage(store, "session", "jarvis", route, rows, "instance", partial)
    assert trusted_anchor(store, "session", {"jarvis": route}, rows, "instance").prompt_tokens == 113
    remember_usage(store, "session", "jarvis", route, rows, "instance", output_only)
    assert trusted_anchor(store, "session", {"jarvis": route}, rows, "instance").prompt_tokens == 113
