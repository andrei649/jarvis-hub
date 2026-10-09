"""Responses counters remain useful evidence without inventing complete accounting."""

from collections import OrderedDict
from types import SimpleNamespace

import pytest

from agents.core.llm.responses_dialect import usage as responses_usage
from agents.core.orchestrator import Orchestrator, _billable_from_usage
from agents.core.route_compaction import remember_usage, trusted_anchor
from tests.test_usage_counter_accounting import _record

MAX_COUNT = 2**63 - 1
FULL = {
    "input_tokens": 100,
    "output_tokens": 7,
    "input_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 0},
    "total_tokens": 107,
}


def test_complete_split_and_explicit_zero_are_observed():
    measured = responses_usage(FULL)
    assert measured.as_dict() == {
        "input_tokens": 40, "output_tokens": 7, "cache_read": 60, "cache_write": 0,
    }
    assert measured.counts_complete is True
    assert _billable_from_usage(measured) == (100, 7, 60)

    zero = responses_usage({
        "input_tokens": 0, "output_tokens": 0,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "total_tokens": 0,
    })
    assert zero.as_dict() == dict.fromkeys(measured.as_dict(), 0)
    assert zero.reported is False
    assert zero.counts_complete is True
    assert _billable_from_usage(zero) == (0, 0, 0)


def test_valid_upper_bound_and_absent_redundant_total():
    measured = responses_usage({
        "input_tokens": MAX_COUNT, "output_tokens": MAX_COUNT,
        "input_tokens_details": {"cached_tokens": MAX_COUNT, "cache_write_tokens": 0},
    })
    assert measured.as_dict() == {
        "input_tokens": 0, "output_tokens": MAX_COUNT,
        "cache_read": MAX_COUNT, "cache_write": 0,
    }
    assert measured.counts_complete is True


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
@pytest.mark.parametrize("defect", ["missing", None, True, 0.0, "3", -1, MAX_COUNT + 1])
def test_bad_core_count_preserves_valid_sibling_without_claiming_complete(field, defect):
    raw = {**FULL, "input_tokens_details": dict(FULL["input_tokens_details"])}
    if defect == "missing":
        raw.pop(field)
    else:
        raw[field] = defect
    parsed = responses_usage(raw)
    if field == "input_tokens":
        # The existing split falls back to no cache when its inclusive bound is bad.
        assert (parsed.input_tokens, parsed.cache_read, parsed.output_tokens) == (0, 0, 7)
    else:
        assert (parsed.input_tokens, parsed.cache_read, parsed.output_tokens) == (40, 60, 0)
    assert parsed.counts_complete is False
    assert _billable_from_usage(parsed) is None


@pytest.mark.parametrize("defect", ["missing", None, False, 0.0, -1, MAX_COUNT + 1, 101])
def test_bad_cached_subset_preserves_inclusive_input(defect):
    raw = {**FULL, "input_tokens_details": dict(FULL["input_tokens_details"])}
    if defect == "missing":
        raw["input_tokens_details"].pop("cached_tokens")
    else:
        raw["input_tokens_details"]["cached_tokens"] = defect
    parsed = responses_usage(raw)
    assert (parsed.input_tokens, parsed.cache_read, parsed.output_tokens) == (100, 0, 7)
    assert parsed.counts_complete is False


@pytest.mark.parametrize("defect", ["missing", None, False, 0.0, "0", 1, -1])
def test_unmapped_cache_write_requires_explicit_exact_zero(defect):
    raw = {**FULL, "input_tokens_details": dict(FULL["input_tokens_details"])}
    if defect == "missing":
        raw["input_tokens_details"].pop("cache_write_tokens")
    else:
        raw["input_tokens_details"]["cache_write_tokens"] = defect
    parsed = responses_usage(raw)
    assert parsed.as_dict() == {
        "input_tokens": 40, "output_tokens": 7, "cache_read": 60, "cache_write": 0,
    }
    assert parsed.counts_complete is False


@pytest.mark.parametrize("defect", [None, True, 107.0, "107", -1, MAX_COUNT + 1, 106])
def test_supplied_total_must_be_strict_consistent_and_within_cap(defect):
    parsed = responses_usage({**FULL, "total_tokens": defect})
    assert parsed.as_dict() == {
        "input_tokens": 40, "output_tokens": 7, "cache_read": 60, "cache_write": 0,
    }
    assert parsed.counts_complete is False


@pytest.mark.parametrize("raw", [
    None, [], {}, {"input_tokens": 100, "output_tokens": 7},
    {"input_tokens": 100, "output_tokens": 7, "input_tokens_details": None},
    {"input_tokens": 100, "output_tokens": 7, "input_tokens_details": []},
])
def test_missing_usage_or_cache_details_is_incomplete(raw):
    parsed = responses_usage(raw)
    assert parsed.counts_complete is False
    if isinstance(raw, dict) and raw.get("input_tokens") == 100:
        assert parsed.as_dict() == {
            "input_tokens": 100, "output_tokens": 7, "cache_read": 0, "cache_write": 0,
        }


def test_partial_positive_response_estimates_with_inclusive_floor_and_no_discount(monkeypatch):
    # This xAI-compatible shape contains real counts, but no cache-write evidence.
    partial = responses_usage({
        "input_tokens": 100_000, "output_tokens": 7,
        "input_tokens_details": {"cached_tokens": 60_000},
    })
    assert partial.as_dict() == {
        "input_tokens": 40_000, "output_tokens": 7,
        "cache_read": 60_000, "cache_write": 0,
    }
    monkeypatch.setattr(Orchestrator, "_last_cached_tokens", property(lambda _: {"jarvis": 999}))
    metadata, charge = _record(partial, monkeypatch, last_prompt=1)
    # This assertion must fail on the old parser before the flag assertion does.
    assert metadata["usage_source"] == "estimate"
    assert metadata["input_tokens"] >= 100_000
    assert metadata["output_tokens"] >= 7
    assert metadata["cached_tokens"] == 0
    assert metadata["cache_hit"] is False
    assert charge[0][1:3] == (metadata["input_tokens"], metadata["output_tokens"])
    assert partial.counts_complete is False


def test_known_inclusive_prompt_anchor_is_independent_of_accounting_availability():
    partial = responses_usage({
        "input_tokens": 100, "output_tokens": 7,
        "input_tokens_details": {"cached_tokens": 60},
    })
    output_only = responses_usage({"output_tokens": 7})
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 6
    orch._record_context_anchor("jarvis", partial)
    assert orch._usage_anchor(6).prompt_tokens == 100
    orch._record_context_anchor("jarvis", output_only)
    assert orch._usage_anchor(6).prompt_tokens == 100

    route = SimpleNamespace(identity=object(), model="responses-test")
    rows = [{"role": "user", "content": "hello"}]
    store = OrderedDict()
    remember_usage(store, "session", "jarvis", route, rows, "instance", partial)
    assert trusted_anchor(store, "session", {"jarvis": route}, rows, "instance").prompt_tokens == 100
    remember_usage(store, "session", "jarvis", route, rows, "instance", output_only)
    assert trusted_anchor(store, "session", {"jarvis": route}, rows, "instance").prompt_tokens == 100
