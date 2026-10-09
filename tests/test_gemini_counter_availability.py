"""Gemini tool-use prompt input must not disappear into measured zero."""

from collections import OrderedDict
from types import SimpleNamespace

import pytest

from agents.core.llm.tool_dialects import gemini_usage
from agents.core.orchestrator import Orchestrator, _billable_from_usage
from agents.core.route_compaction import remember_usage, trusted_anchor
from tests.test_usage_counter_accounting import _record

COUNTS = {
    "promptTokenCount": 123,
    "candidatesTokenCount": 14,
    "thoughtsTokenCount": 3,
    "toolUsePromptTokenCount": 0,
    "totalTokenCount": 140,
}


def test_explicit_supported_counts_and_zero_are_complete_observations():
    usage = gemini_usage({"usageMetadata": COUNTS})
    assert usage.as_dict() == {
        "input_tokens": 123, "output_tokens": 17, "cache_read": 0, "cache_write": 0,
    }
    assert usage.counts_complete is True
    assert _billable_from_usage(usage) == (123, 17, 0)

    zero = gemini_usage({"usageMetadata": dict.fromkeys(COUNTS, 0)})
    assert zero.as_dict() == dict.fromkeys(usage.as_dict(), 0)
    assert zero.reported is False
    assert zero.counts_complete is True
    assert _billable_from_usage(zero) == (0, 0, 0)

    without_redundant_total = {k: v for k, v in COUNTS.items() if k != "totalTokenCount"}
    assert gemini_usage({"usageMetadata": without_redundant_total}).counts_complete is True


@pytest.mark.parametrize(
    "field,expected_output",
    [("promptTokenCount", 17), ("candidatesTokenCount", 3), ("thoughtsTokenCount", 14)],
)
@pytest.mark.parametrize("defect", ["missing", None, True])
def test_unavailable_mapped_component_keeps_valid_siblings(field, expected_output, defect):
    raw = {k: v for k, v in COUNTS.items() if k != "totalTokenCount"}
    if defect == "missing":
        raw.pop(field)
    else:
        raw[field] = defect
    usage = gemini_usage({"usageMetadata": raw})
    assert usage.input_tokens == (0 if field == "promptTokenCount" else 123)
    assert usage.output_tokens == expected_output
    assert usage.counts_complete is False
    assert _billable_from_usage(usage) is None


@pytest.mark.parametrize("defect", ["missing", None, True, False, 0.0, -1, "0", 50])
def test_unknown_or_positive_unmapped_tool_use_is_not_measured_zero(defect):
    raw = {k: v for k, v in COUNTS.items() if k != "totalTokenCount"}
    if defect == "missing":
        raw.pop("toolUsePromptTokenCount")
        raw["totalTokenCount"] = 140  # Even a matching total does not infer the missing field.
    else:
        raw["toolUsePromptTokenCount"] = defect
        if defect == 50:
            raw["totalTokenCount"] = 190  # Internally consistent positive tool use.
    usage = gemini_usage({"usageMetadata": raw})
    assert usage.as_dict() == {
        "input_tokens": 123, "output_tokens": 17, "cache_read": 0, "cache_write": 0,
    }
    assert usage.counts_complete is False
    assert _billable_from_usage(usage) is None


@pytest.mark.parametrize("bad_total", [None, True, 140.0, -1, "140", 141])
def test_supplied_total_must_be_exact_and_consistent(bad_total):
    raw = {**COUNTS, "totalTokenCount": bad_total}
    usage = gemini_usage({"usageMetadata": raw})
    assert (usage.input_tokens, usage.output_tokens) == (123, 17)
    assert usage.counts_complete is False


@pytest.mark.parametrize("wire", [{}, {"usageMetadata": None}, {"usageMetadata": []}])
def test_absent_metadata_is_incomplete_zero(wire):
    usage = gemini_usage(wire)
    assert usage.as_dict() == {"input_tokens": 0, "output_tokens": 0,
                               "cache_read": 0, "cache_write": 0}
    assert usage.reported is False
    assert usage.counts_complete is False


def test_positive_unmapped_tool_use_estimates_with_mapped_floors_no_discount(monkeypatch):
    usage = gemini_usage({"usageMetadata": {**COUNTS,
        "toolUsePromptTokenCount": 50, "totalTokenCount": 190,
    }})
    assert usage.as_dict() == {"input_tokens": 123, "output_tokens": 17,
                               "cache_read": 0, "cache_write": 0}
    monkeypatch.setattr(Orchestrator, "_last_cached_tokens", property(lambda _: {"jarvis": 999}))
    metadata, charge = _record(usage, monkeypatch, last_prompt=1)
    assert metadata["usage_source"] == "estimate"
    assert metadata["input_tokens"] == 123  # Tool-use input is not mapped/floored in this unit.
    assert metadata["output_tokens"] >= 17
    assert metadata["cached_tokens"] == 0 and metadata["cache_hit"] is False
    assert charge[0][1:3] == (metadata["input_tokens"], metadata["output_tokens"])
    assert usage.counts_complete is False


def test_known_prompt_anchor_remains_independent_of_output_or_tool_use_availability():
    incomplete = gemini_usage({"usageMetadata": {
        "promptTokenCount": 123, "candidatesTokenCount": True,
        "thoughtsTokenCount": 3, "toolUsePromptTokenCount": 50,
    }})
    output_only = gemini_usage({"usageMetadata": {"candidatesTokenCount": 14}})

    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    orch._record_context_anchor("jarvis", incomplete)
    assert orch._usage_anchor(6).prompt_tokens == 123
    orch._record_context_anchor("jarvis", output_only)
    assert orch._usage_anchor(6).prompt_tokens == 123

    route = SimpleNamespace(identity=object(), model="gemini-test")
    rows = [{"role": "user", "content": "hello"}]
    store = OrderedDict()
    remember_usage(store, "session", "jarvis", route, rows, "instance", incomplete)
    assert trusted_anchor(store, "session", {"jarvis": route}, rows, "instance").prompt_tokens == 123
    remember_usage(store, "session", "jarvis", route, rows, "instance", output_only)
    assert trusted_anchor(store, "session", {"jarvis": route}, rows, "instance").prompt_tokens == 123
