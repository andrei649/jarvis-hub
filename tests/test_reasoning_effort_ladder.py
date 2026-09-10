"""H364 — one effort ladder, clamped to what each wire actually accepts.

Two failures are being pinned here, and they pull in opposite directions.

The first is the one the row is named after: a request that asks a wire for a
reasoning level it does not offer, and gets a 400 instead of an answer. The
answer is a per-model capability table plus a nearest-**weaker** clamp — never a
level stronger than the one asked for, and never a parameter the family has no
vocabulary for.

The second is quieter and was already live before any of this: Anthropic removed
the sampling parameters on the 4.7 generation, so every request this build sends
to `claude-opus-5` carried a `temperature` the wire rejects. Which is why the fit
runs on every request, not only the ones that ask to think harder — and why a
"nothing requested" test that only checks *additions* would have missed it.

Everything here is offline: dicts and fake clients, no network.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agents.core.llm.reasoning_effort import (
    LADDER,
    anthropic_capability,
    apply_anthropic,
    clamp,
    normalize,
    parse_overrides,
    plan,
    resolve,
    vendor_efforts,
)

# ── the ladder itself ────────────────────────────────────────────────────────


def test_the_ladder_runs_weakest_to_strongest_with_no_gaps():
    assert LADDER[0] == "none"
    assert LADDER[-1] == "ultra"
    assert list(LADDER) == sorted(LADDER, key=LADDER.index)
    assert len(set(LADDER)) == len(LADDER)


@pytest.mark.parametrize(
    "written,level",
    [
        ("HIGH", "high"),
        ("  medium  ", "medium"),
        ("x-high", "xhigh"),
        ("very high", "xhigh"),
        ("off", "none"),
        ("maximum", "max"),
        ("highest", "ultra"),
    ],
)
def test_a_level_is_recognised_however_it_was_spelled(written, level):
    assert normalize(written) == level


@pytest.mark.parametrize("value", ["", "   ", None, "turbo", "9", "thinking-hard"])
def test_anything_that_names_no_rung_reads_as_no_request(value):
    """A typo must not become a level. None is the only safe reading."""
    assert normalize(value) is None


def test_the_clamp_walks_down_the_ladder_never_up():
    supported = ("low", "medium", "high")
    assert clamp("ultra", supported) == "high"
    assert clamp("xhigh", supported) == "high"
    assert clamp("medium", supported) == "medium"
    assert clamp("minimal", supported) is None


def test_a_request_below_the_wires_floor_lands_on_the_floor_not_on_its_default():
    """Answering "nothing" here would hand the caller the wire's own default.

    Anthropic's default effort is `high`; a caller who asked for `minimal` and
    got silence would be billed for the opposite of the request. The weakest
    rung is the closest honest answer and is never above that default.
    """
    effort, reason = resolve("minimal", ("low", "medium", "high"))
    assert (effort, reason) == ("low", "floored")


def test_a_wire_with_no_vocabulary_is_answered_with_silence():
    assert resolve("high", ()) == (None, "unsupported")


# ── the Anthropic capability table ───────────────────────────────────────────


def test_a_model_the_build_never_heard_of_is_left_exactly_as_it_was():
    payload = {"model": "claude-next-9", "max_tokens": 1024, "temperature": 0.7}
    before = dict(payload)

    applied = apply_anthropic(payload, "claude-next-9", "max")

    assert payload == before
    assert applied.effort is None
    assert applied.reason == "unsupported"


def test_the_specific_family_answers_before_the_generic_one():
    """`claude-opus-4` is a prefix of `claude-opus-4-8`; order decides correctness.

    Get this wrong and a 4.8 request is built for a 4.0 contract: a manual
    thinking budget and a temperature, both of which 4.8 rejects.
    """
    assert anthropic_capability("claude-opus-4-8").efforts == (
        "low", "medium", "high", "xhigh", "max",
    )
    assert anthropic_capability("claude-opus-4-8").accepts_sampling is False
    assert anthropic_capability("claude-opus-4-20250514").efforts == ()
    assert anthropic_capability("claude-opus-4-20250514").thinking == "budget"


def test_a_dated_model_id_still_finds_its_family():
    assert anthropic_capability("claude-sonnet-4-6-20260115").efforts == (
        "low", "medium", "high", "max",
    )


def test_the_generation_that_dropped_xhigh_is_clamped_to_max_not_handed_xhigh():
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 4096, "temperature": 0.4}

    applied = apply_anthropic(payload, "claude-sonnet-4-6", "xhigh")

    assert applied.effort == "high"
    assert applied.reason == "clamped"
    assert payload["output_config"] == {"effort": "high"}
    assert payload["thinking"] == {"type": "adaptive"}
    # 4.6 still accepts sampling — removing it here would change behaviour for
    # the model this build actually ships with.
    assert payload["temperature"] == 0.4


def test_ultra_reaches_max_only_where_the_family_has_it():
    on_four_six = {"model": "m", "max_tokens": 4096}
    apply_anthropic(on_four_six, "claude-sonnet-4-6", "ultra")
    assert on_four_six["output_config"] == {"effort": "max"}

    on_four_five = {"model": "m", "max_tokens": 4096}
    apply_anthropic(on_four_five, "claude-opus-4-5", "ultra")
    assert on_four_five["output_config"] == {"effort": "high"}
    # 4.5 predates adaptive thinking; this build sends it no thinking block.
    assert "thinking" not in on_four_five


# ── the removals ─────────────────────────────────────────────────────────────


def test_a_current_model_loses_the_temperature_it_would_have_400d_on():
    """The live defect: this happens with no effort configured at all."""
    payload = {
        "model": "claude-opus-5",
        "max_tokens": 1024,
        "temperature": 0.7,
        "top_p": 0.9,
        "messages": [],
    }

    applied = apply_anthropic(payload, "claude-opus-5", "")

    assert "temperature" not in payload
    assert "top_p" not in payload
    assert applied.reason == "unset"
    # Nothing was *added*: an install that asked for nothing still asks for
    # nothing. Only the rejected parameters came off.
    assert "thinking" not in payload
    assert "output_config" not in payload


def test_a_model_that_still_takes_sampling_keeps_the_payload_byte_identical():
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 1024, "temperature": 0.7}
    before = dict(payload)

    apply_anthropic(payload, "claude-sonnet-4-6", "")

    assert payload == before


# ── "none" is three different requests depending on the family ───────────────


def test_where_thinking_is_on_by_default_off_has_to_be_said_and_paired():
    """Opus 5 thinks unless told not to, and refuses `disabled` above `high`."""
    payload = {"model": "claude-opus-5", "max_tokens": 2048}

    applied = apply_anthropic(payload, "claude-opus-5", "none")

    assert payload["thinking"] == {"type": "disabled"}
    assert payload["output_config"] == {"effort": "high"}
    assert applied.reason == "disabled"


def test_where_thinking_cannot_be_turned_off_the_weakest_rung_is_the_answer():
    payload = {"model": "claude-fable-5-1", "max_tokens": 2048}

    applied = apply_anthropic(payload, "claude-fable-5-1", "none")

    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "low"}
    assert applied.reason == "floored-instead-of-disabled"


def test_where_omitting_the_block_already_means_off_nothing_is_sent():
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 2048, "temperature": 0.3}

    applied = apply_anthropic(payload, "claude-sonnet-4-6", "none")

    assert "thinking" not in payload
    assert "output_config" not in payload
    assert payload["temperature"] == 0.3
    assert applied.reason == "omitted"


# ── the families that only speak token budgets ───────────────────────────────


def test_a_budget_family_gets_a_budget_and_never_an_effort_key():
    payload = {"model": "claude-sonnet-4-5", "max_tokens": 8192, "temperature": 0.7}

    apply_anthropic(payload, "claude-sonnet-4-5", "high")

    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 7168}
    assert "output_config" not in payload
    # A manual budget and a custom temperature do not travel together.
    assert "temperature" not in payload


def test_a_thinking_budget_never_reaches_the_answer_budget():
    payload = {"model": "claude-sonnet-4-5", "max_tokens": 3000}

    apply_anthropic(payload, "claude-sonnet-4-5", "ultra")

    assert payload["thinking"]["budget_tokens"] == 1976
    assert payload["thinking"]["budget_tokens"] < payload["max_tokens"]


def test_an_answer_with_no_room_to_think_is_sent_without_thinking():
    """Below the 1024-token floor there is no legal budget — so ask for none."""
    payload = {"model": "claude-sonnet-4-5", "max_tokens": 1500, "temperature": 0.7}

    applied = apply_anthropic(payload, "claude-sonnet-4-5", "max")

    assert "thinking" not in payload
    assert payload["temperature"] == 0.7
    assert applied.reason == "unsupported"


# ── the owner's override map ─────────────────────────────────────────────────


def test_an_empty_override_list_silences_a_family_whose_contract_moved():
    overrides = parse_overrides('{"claude-opus-5": []}')
    payload = {"model": "claude-opus-5", "max_tokens": 2048, "temperature": 0.7}

    applied = apply_anthropic(payload, "claude-opus-5", "max", overrides=overrides)

    assert "output_config" not in payload
    assert applied.effort is None
    # The removal is a property of the model, not of the effort key, so it
    # survives the silencing.
    assert "temperature" not in payload


def test_an_override_widens_a_family_the_table_pins_narrow():
    overrides = parse_overrides({"claude-sonnet-4-6": ["low", "medium", "high", "xhigh", "max"]})
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 2048}

    apply_anthropic(payload, "claude-sonnet-4-6", "xhigh", overrides=overrides)

    assert payload["output_config"] == {"effort": "xhigh"}


def test_the_longest_matching_override_wins():
    overrides = parse_overrides({"claude": [], "claude-sonnet-4-6": ["low"]})
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 2048}

    apply_anthropic(payload, "claude-sonnet-4-6", "max", overrides=overrides)

    assert payload["output_config"] == {"effort": "low"}


@pytest.mark.parametrize("raw", ["", "not json", "[1,2]", "null", 17])
def test_an_unreadable_override_map_is_no_override_map(raw):
    assert parse_overrides(raw) == {}


def test_an_override_cannot_smuggle_a_level_off_the_ladder():
    overrides = parse_overrides({"claude-opus-5": ["low", "turbo", "none"]})
    assert overrides["claude-opus-5"] == ("low",)


# ── the wiring: settings → router → backend → payload ────────────────────────


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, json: Any = None, headers: Any = None):
        self.calls.append(json)

        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}

        return _Resp()

    async def aclose(self) -> None:
        return None


def _backend(effort: str = "", overrides: object = None):
    from agents.core.llm.anthropic import ClaudeBackend

    backend = ClaudeBackend(
        api_key="sk-ant-test",
        model="claude-opus-5",
        reasoning_effort=effort,
        effort_overrides=overrides,
    )
    backend.client = _RecordingClient()
    return backend


def test_the_configured_rung_reaches_the_wire_on_a_plain_generate():
    backend = _backend("max")

    asyncio.run(backend.generate(model="claude-opus-5", prompt="hi", max_tokens=2048))

    sent = backend.client.calls[0]
    assert sent["output_config"] == {"effort": "max"}
    assert sent["thinking"] == {"type": "adaptive"}
    assert "temperature" not in sent


def test_the_configured_rung_reaches_the_wire_on_a_tool_turn():
    backend = _backend("low")

    asyncio.run(
        backend.generate_tool_turn(
            model="claude-opus-5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            max_tokens=2048,
        )
    )

    sent = backend.client.calls[0]
    assert sent["output_config"] == {"effort": "low"}
    assert "temperature" not in sent


def test_a_default_install_sends_what_it_always_sent():
    backend = _backend("")
    backend.model = "claude-sonnet-4-6"

    asyncio.run(backend.generate(model="claude-sonnet-4-6", prompt="hi", temperature=0.7))

    sent = backend.client.calls[0]
    assert sent["temperature"] == 0.7
    assert "thinking" not in sent
    assert "output_config" not in sent


def test_the_backend_reads_the_override_map_the_settings_row_stores_as_text():
    backend = _backend("max", '{"claude-opus-5": ["low"]}')

    asyncio.run(backend.generate(model="claude-opus-5", prompt="hi"))

    assert backend.client.calls[0]["output_config"] == {"effort": "low"}


def test_the_streaming_path_is_fitted_too():
    """The stream builds its own payload; a fit that only covers the two POST
    paths leaves the third one carrying the parameter that 400s."""
    backend = _backend("high")

    class _Stream:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for line in ('data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',):
                yield line

    sent: list[dict] = []

    class _StreamClient:
        def stream(self, method, url, headers=None, json=None):
            sent.append(json)
            return _Stream(json)

        async def aclose(self):
            return None

    backend.client = _StreamClient()
    asyncio.run(backend.generate_stream(model="claude-opus-5", prompt="hi", max_tokens=2048))

    assert sent[0]["output_config"] == {"effort": "high"}
    assert "temperature" not in sent[0]


def test_a_reasoning_delta_never_lands_in_the_answer():
    """Asking for thinking is what puts these blocks on the stream at all.

    The block type decides what is part of the reply — not whether a delta
    happens to carry a `text` key.
    """
    backend = _backend("high")

    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for line in (
                'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"weighing","text":"weighing"}}',
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"the answer"}}',
            ):
                yield line

    class _StreamClient:
        def stream(self, method, url, headers=None, json=None):
            return _Stream()

        async def aclose(self):
            return None

    backend.client = _StreamClient()
    answer = asyncio.run(backend.generate_stream(model="claude-opus-5", prompt="hi"))

    assert answer == "the answer"


def test_the_router_hands_the_backend_the_two_admin_settings(monkeypatch):
    """Without this the knob exists in the database and nowhere else."""
    import inspect

    from agents.core.llm import hybrid_router

    source = inspect.getsource(hybrid_router.HybridRouter.detect)
    assert 'reasoning_effort=self._admin_setting("reasoning_effort"' in source
    assert 'effort_overrides=self._admin_setting("reasoning_effort_overrides"' in source


def test_the_settings_row_offers_the_ladder_and_nothing_else():
    from agents.core.settings_db import DEFAULTS

    row = next(
        item for item in DEFAULTS
        if item["category"] == "llm" and item["key"] == "reasoning_effort"
    )
    assert row["value"] == ""
    assert row["opts"] == ["", *LADDER]


def test_the_provider_profile_advertises_only_levels_the_wire_accepts():
    from agents.core.llm.providers import get_profile

    advertised = tuple(get_profile("anthropic").status()["reasoning_efforts"])
    assert advertised == vendor_efforts("anthropic")
    assert advertised == ("low", "medium", "high", "xhigh", "max")
    # A local provider this build sends nothing to must advertise nothing.
    assert get_profile("ollama").status()["reasoning_efforts"] == []


def test_a_plan_that_changes_nothing_says_so():
    capability = anthropic_capability("claude-sonnet-4-6")
    assert plan(capability, None).changes_payload is False
    assert plan(capability, "high").changes_payload is True
