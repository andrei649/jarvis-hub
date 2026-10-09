"""Behavioral checks for the ephemeral H067 pending-input boundary."""

import asyncio

import pytest

from agents.core.channels.pending_input import (
    PendingInputs,
    parse_clarify,
    parse_confirmation,
)

KEY = ("telegram", "chat:5/thread:7", "verified:owner")
OTHER_KEY = ("telegram", "chat:5/thread:8", "verified:owner")


@pytest.mark.parametrize(
    ("reply", "want"),
    [
        ("1", "Build"),
        (" build (Recommended) ", "Build"),
        ("DEPLOY", "Deploy"),
    ],
)
def test_clarify_resolves_numbers_and_labels_without_presentation_suffix(reply, want):
    result = parse_clarify(reply, ["Build (Recommended)", "Deploy"])
    assert (result.status, result.value) == ("resolved", want)


@pytest.mark.parametrize("reply", ["1,3", "1 3", "Build, Review", "1,1,3"])
def test_multi_select_accepts_numeric_and_label_lists_without_duplicates(reply):
    result = parse_clarify(reply, ["Build", "Deploy", "Review"], multi_select=True)
    assert (result.status, result.value) == ("resolved", ["Build", "Review"])


def test_invalid_selection_retries_while_unmatched_prose_and_slash_fall_through():
    choices = ["Build", "Deploy"]
    assert parse_clarify("9", choices).status == "invalid_selection"
    assert parse_clarify("1,9", choices, multi_select=True).status == "invalid_selection"
    assert parse_clarify("please change direction", choices).status == "prose"
    assert parse_clarify("/status", choices).status == "fallthrough"
    assert parse_clarify("!status", None).status == "fallthrough"
    assert parse_clarify("anything", choices, awaiting_text=True).value == "anything"
    assert parse_clarify("anything", None).value == "anything"


def test_multi_select_rejects_an_answer_above_the_bound_even_if_reply_is_short():
    result = parse_clarify("1 2", ["A" * 9000, "B" * 9000], multi_select=True)
    assert result.status == "invalid_selection"


@pytest.mark.parametrize(
    ("reply", "want"),
    [
        ("approve once", "once"),
        ("/approve", "once"),
        ("!yes", "once"),
        ("always approve", "always"),
        ("/remember", "always"),
        ("!cancel", "cancel"),
        ("no", "cancel"),
        ("/status", None),
        ("yes please", None),
    ],
)
def test_confirmation_aliases_are_exact(reply, want):
    assert parse_confirmation(reply) == want


@pytest.mark.asyncio
async def test_fifo_clarify_and_confirm_supersession_keep_other_identity_isolated():
    pending = PendingInputs()
    first = pending.register_clarify(KEY, "First?")
    second = pending.register_clarify(KEY, "Second?", choices=["Yes", "No"])
    old = pending.register_confirmation(KEY, "/new", "Reset?")
    latest = pending.register_confirmation(KEY, "/undo", "Undo?")
    foreign = pending.register_clarify(OTHER_KEY, "Other topic?")
    assert pending.pending(KEY).id == first.id
    assert pending.pending(KEY, "confirmation").id == latest.id
    assert await pending.wait(old) is None
    assert not pending.resolve(first.id, OTHER_KEY, "stolen")
    assert pending.intercept(KEY, "first answer").prompt_id == first.id
    assert (await pending.wait(first)).value == "first answer"
    assert pending.intercept(KEY, "1").prompt_id == second.id
    assert (await pending.wait(second)).value == "Yes"
    assert pending.intercept(KEY, "/approve").answer.value == "once"
    assert (await pending.wait(latest)).value == "once"
    assert pending.pending(OTHER_KEY).id == foreign.id
    assert pending.close() == 1
    assert await pending.wait(foreign) is None


@pytest.mark.asyncio
async def test_invalid_retry_prose_release_other_and_first_writer():
    pending = PendingInputs()
    prompt = pending.register_clarify(KEY, "Choose", ["Build", "Deploy"])
    assert pending.intercept(KEY, "9").status == "retry"
    assert pending.pending(KEY).id == prompt.id
    assert pending.mark_other(prompt.id, KEY)
    assert pending.pending(KEY).awaiting_text
    assert pending.intercept(KEY, "custom answer").status == "consumed"
    assert (await pending.wait(prompt)).value == "custom answer"
    assert not pending.resolve(prompt.id, KEY, "late")
    next_prompt = pending.register_clarify(KEY, "Again", ["A", "B"])
    assert pending.intercept(KEY, "please reconsider").status == "fallthrough"
    assert await pending.wait(next_prompt) is None
    assert pending.pending(KEY) is None


@pytest.mark.asyncio
async def test_timeout_cancel_and_close_unblock_waiters():
    now = [100.0]
    pending = PendingInputs(clock=lambda: now[0])
    expired = pending.register_clarify(KEY, "Soon?", timeout_seconds=2)
    now[0] = 102.0
    assert pending.pending(KEY) is None
    assert await pending.wait(expired) is None
    one = pending.register_clarify(KEY, "One?", timeout_seconds=0)
    two = pending.register_confirmation(KEY, "/undo", "Undo?")
    task = asyncio.create_task(pending.wait(one))
    assert pending.cancel(KEY) == 2
    assert await task is None
    assert await pending.wait(two) is None
    assert pending.close() == 0
    with pytest.raises(RuntimeError):
        pending.register_clarify(KEY, "Closed")


@pytest.mark.asyncio
async def test_validation_capacity_and_defensive_prompt_snapshot():
    pending = PendingInputs(max_pending=1)
    choices = ["A", "B"]
    prompt = pending.register_clarify(KEY, "Choose", choices)
    choices[0] = "mutated"
    assert prompt.choices == ("A", "B")
    with pytest.raises(OverflowError):
        pending.register_clarify(OTHER_KEY, "Full")
    assert pending.cancel(KEY) == 1
    with pytest.raises(ValueError):
        pending.register_clarify(KEY, " ")
    with pytest.raises(ValueError):
        pending.register_clarify(KEY, "x" * 4097)
    with pytest.raises(ValueError):
        pending.register_clarify(KEY, "Choices", ["1", "2", "3", "4", "5"])
    with pytest.raises(ValueError):
        pending.register_clarify(KEY, "Question", timeout_seconds=float("nan"))
    with pytest.raises(TypeError):
        PendingInputs(max_pending=True)
    with pytest.raises(ValueError):
        PendingInputs(clock=lambda: float("inf"))
    with pytest.raises(ValueError):
        PendingInputs(clock=lambda: 1.7e308).register_clarify(
            KEY, "Overflow", timeout_seconds=1e308
        )


@pytest.mark.asyncio
async def test_native_resolution_requires_live_prompt_key_and_valid_choice():
    pending = PendingInputs()
    prompt = pending.register_clarify(KEY, "Pick", ["A (Recommended)", "B"])
    assert not pending.resolve(prompt.id, OTHER_KEY, "A")
    assert not pending.mark_other(prompt.id, OTHER_KEY)
    assert not pending.resolve(prompt.id, KEY, "arbitrary prose")
    assert pending.pending(KEY).id == prompt.id
    assert pending.resolve(prompt.id, KEY, "B")
    assert not pending.resolve(prompt.id, KEY, "A")
    assert (await pending.wait(prompt)).value == "B"
    confirm = pending.register_confirmation(KEY, "/new", "Reset?")
    assert not pending.resolve(confirm.id, KEY, "approve")
    assert pending.resolve(confirm.id, KEY, "always")
    assert (await pending.wait(confirm)).choice == "always"
    assert not pending.mark_other(confirm.id, KEY)


@pytest.mark.asyncio
async def test_native_multi_selection_is_atomic_bounded_and_decorated_labels_are_removed():
    pending = PendingInputs()
    prompt = pending.register_clarify(KEY, "Pick", ["A (Recommended)", "B"], multi_select=True)
    assert not pending.resolve(prompt.id, KEY, ["A", "missing"])
    assert not pending.resolve(prompt.id, KEY, ["A" * 16385])
    assert pending.resolve(prompt.id, KEY, ["A (Recommended)", "B", "A"])
    assert (await pending.wait(prompt)).value == ["A", "B"]


@pytest.mark.asyncio
async def test_real_timeout_releases_waiter_and_stale_confirmation_does_not_resolve():
    pending = PendingInputs()
    prompt = pending.register_confirmation(KEY, "/undo", "Undo?", timeout_seconds=0.01)
    assert await asyncio.wait_for(pending.wait(prompt), 1) is None
    assert pending.pending(KEY) is None
    assert not pending.resolve(prompt.id, KEY, "once")
    with pytest.raises(ValueError):
        pending.register_confirmation(KEY, "/new", "Reset?", timeout_seconds=0)


@pytest.mark.asyncio
async def test_resolved_answer_is_preserved_if_later_session_cancel_occurs():
    pending = PendingInputs()
    answered = pending.register_clarify(KEY, "Name?")
    active = pending.register_clarify(KEY, "Next?")
    assert pending.resolve(answered.id, KEY, "Alice")
    assert pending.cancel(KEY) == 1
    assert (await pending.wait(answered)).value == "Alice"
    assert await pending.wait(active) is None
