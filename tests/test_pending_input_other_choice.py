"""After Other, recognized choices still use their canonical values."""

import pytest

from agents.core.channels.pending_input import PendingInputs, parse_clarify

KEY = ("telegram", "tg:123:topic:8", "42")


@pytest.mark.parametrize(
    ("text", "multi", "expected"),
    [
        ("2", False, "Deploy"),
        (" build (Recommended) ", False, "Build"),
        ("1,2", True, ["Build", "Deploy"]),
        ("Build, Deploy", True, ["Build", "Deploy"]),
    ],
)
def test_other_keeps_existing_choice_coercion(text, multi, expected):
    result = parse_clarify(
        text, ["Build (Recommended)", "Deploy"],
        multi_select=multi, awaiting_text=True,
    )
    assert (result.status, result.value) == ("resolved", expected)


@pytest.mark.parametrize(
    ("text", "multi", "expected"),
    [
        ("my own answer", False, "my own answer"),
        ("9", False, "9"),
        ("1,9", True, "1,9"),
        ("Build, missing", True, "Build, missing"),
    ],
)
def test_other_falls_back_to_entire_unmatched_reply(text, multi, expected):
    result = parse_clarify(text, ["Build", "Deploy"], multi_select=multi, awaiting_text=True)
    assert (result.status, result.value) == ("resolved", expected)


def test_other_preserves_command_fallthrough_and_size_guard():
    assert parse_clarify("/cancel", ["Build"], awaiting_text=True).status == "fallthrough"
    assert parse_clarify("x" * 16385, ["Build"], awaiting_text=True).status == "invalid_selection"


@pytest.mark.asyncio
async def test_mark_other_intercept_wait_resolves_choice_once():
    pending = PendingInputs()
    prompt = pending.register_clarify(KEY, "Choose", ["Build", "Deploy"], multi_select=True)
    assert pending.mark_other(prompt.id, KEY)
    result = pending.intercept(KEY, "1 2")
    assert result.status == "consumed"
    assert (await pending.wait(prompt)).value == ["Build", "Deploy"]
    assert pending.intercept(KEY, "another reply").status == "no_pending"
    assert not pending.resolve(prompt.id, KEY, "late")
