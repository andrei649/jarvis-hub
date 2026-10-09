"""Ollama response counters distinguish complete pairs from partial observations."""

from collections import OrderedDict
from types import SimpleNamespace

import pytest

from agents.core.llm.tool_dialects import ollama_usage
from agents.core.orchestrator import Orchestrator
from agents.core.route_compaction import remember_usage, trusted_anchor


@pytest.mark.parametrize("prompt,completion", [(0, 0), (123, 17)])
def test_exact_counter_pair_is_complete_with_legacy_four_count_shape(prompt, completion):
    usage = ollama_usage({
        "prompt_eval_count": prompt,
        "eval_count": completion,
        "prompt_eval_duration": 999,
        "total_duration": 999,
        "cache_read": 999,
    })
    assert usage.counts_complete is True
    assert usage.as_dict() == {
        "input_tokens": prompt, "output_tokens": completion,
        "cache_read": 0, "cache_write": 0,
    }
    assert usage.reported is bool(prompt or completion)


_MISSING = object()


@pytest.mark.parametrize("field,bad,expected", [
    ("prompt_eval_count", _MISSING, (0, 17)),
    ("eval_count", _MISSING, (123, 0)),
    ("prompt_eval_count", None, (0, 17)),
    ("prompt_eval_count", True, (0, 17)),
    ("eval_count", False, (123, 0)),
    ("prompt_eval_count", 123.0, (0, 17)),
    ("eval_count", 17.5, (123, 0)),
    ("eval_count", float("inf"), (123, 0)),
    ("prompt_eval_count", float("nan"), (0, 17)),
    ("eval_count", -1, (123, 0)),
    ("prompt_eval_count", "123", (0, 17)),
    ("eval_count", [], (123, 0)),
    ("prompt_eval_count", {}, (0, 17)),
])
def test_bad_or_missing_counter_marks_pair_incomplete_but_preserves_valid_sibling(
    field, bad, expected,
):
    raw = {"prompt_eval_count": 123, "eval_count": 17}
    if bad is _MISSING:
        del raw[field]
    else:
        raw[field] = bad
    usage = ollama_usage(raw)
    assert usage.counts_complete is False
    assert (usage.input_tokens, usage.output_tokens) == expected
    assert usage.cache_read == usage.cache_write == 0
    assert usage.reported


@pytest.mark.parametrize("raw", [{}, None, [], {"prompt_eval_count": None, "eval_count": None}])
def test_missing_pair_is_unavailable_zero_not_a_provider_zero_observation(raw):
    usage = ollama_usage(raw)
    assert usage.counts_complete is False
    assert usage.as_dict() == {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read": 0, "cache_write": 0,
    }
    assert usage.reported is False


def _record(usage, monkeypatch, *, prompt="hi", answer="ok", last_prompt=0):
    from agents.core import cost_tracker

    charges, learning = [], []
    monkeypatch.setattr(cost_tracker, "record", lambda *args, **kwargs: charges.append((args, kwargs)))
    orch = Orchestrator.__new__(Orchestrator)
    orch.agents = {"jarvis": SimpleNamespace(config={"model": "configured"})}
    orch.learning = SimpleNamespace(record=lambda **kwargs: learning.append(kwargs))
    orch.bench = SimpleNamespace(record=lambda **kwargs: None)
    orch.get_setting = lambda *_: False
    orch._last_models = {"jarvis": "openai/gpt-4o-mini"}
    orch._last_routes = {"jarvis": "cloud"}
    orch._last_prompt_tokens = {"jarvis": last_prompt}
    orch._last_reported_usage = {"jarvis": usage}
    orch._record_interactions(prompt, {"jarvis": answer}, answer, route_name="cloud")
    return learning[0]["metadata"], charges[0]


@pytest.mark.parametrize("raw,source,input_floor,output_floor", [
    ({"prompt_eval_count": 0, "eval_count": 0}, "provider", 0, 0),
    ({"prompt_eval_count": 91, "eval_count": 7}, "provider", 91, 7),
    ({"prompt_eval_count": 100_000}, "estimate", 100_000, 1),
    ({"eval_count": 80}, "estimate", 1, 80),
    ({}, "estimate", 1, 1),
])
def test_actual_accounting_uses_provider_only_for_complete_pair_and_floors_partial(
    monkeypatch, raw, source, input_floor, output_floor,
):
    usage = ollama_usage(raw)
    metadata, charge = _record(usage, monkeypatch, last_prompt=3)
    assert metadata["usage_source"] == source
    assert metadata["input_tokens"] >= input_floor
    assert metadata["output_tokens"] >= output_floor
    assert charge[0][1:3] == (metadata["input_tokens"], metadata["output_tokens"])
    if source == "provider":
        assert (metadata["input_tokens"], metadata["output_tokens"]) == (
            usage.input_tokens, usage.output_tokens,
        )


def test_incomplete_positive_prompt_still_replaces_anchor_but_output_only_does_not():
    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {"jarvis": (50, 3)}
    orch._ctx_turns_at_build = 4
    orch._record_context_anchor("jarvis", ollama_usage({"prompt_eval_count": 123}))
    assert orch._context_anchor["jarvis"] == (123, 4)
    orch._record_context_anchor("jarvis", ollama_usage({"eval_count": 900}))
    orch._record_context_anchor("jarvis", ollama_usage({"prompt_eval_count": 0, "eval_count": 0}))
    assert orch._context_anchor["jarvis"] == (123, 4)


def test_shared_anchor_uses_partial_positive_prompt_without_output_or_unchanged_on_output_only():
    owner = object()
    route = SimpleNamespace(identity=owner, model="m")
    routes = {"jarvis": route}
    rows = [{"role": "user", "content": "prompt"}]
    store = OrderedDict()
    remember_usage(store, "s", "jarvis", route, rows, "generation", ollama_usage({"prompt_eval_count": 456}))
    anchor = trusted_anchor(store, "s", routes, rows, "generation")
    assert (anchor.prompt_tokens, anchor.covers) == (456, 1)
    remember_usage(store, "s", "jarvis", route, rows, "generation", ollama_usage({"eval_count": 90}))
    assert trusted_anchor(store, "s", routes, rows, "generation") == anchor
