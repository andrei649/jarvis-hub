"""Native Telegram cards must preserve the pending-input authority boundary."""

import pytest

from agents.core.channels.pending_input import PendingInputs
from agents.core.channels.pending_input_cards import NativePromptCards

KEY = ("telegram", "chat:5/thread:7", "42")


def callback(markup, label, *, sender=42, chat=5, message=91, thread=7, data=None):
    buttons = [button for row in markup["inline_keyboard"] for button in row]
    selected = next(button for button in buttons if button["text"] == label)
    return {
        "data": selected["callback_data"] if data is None else data,
        "from": {"id": sender},
        "message": {
            "message_id": message,
            "chat": {"id": chat},
            "message_thread_id": thread,
        },
    }


@pytest.mark.asyncio
async def test_choice_requires_exact_successful_receipt_and_identity():
    inputs = PendingInputs()
    prompt = inputs.register_clarify(KEY, "Choose", ["Build (Recommended)", "Ship"])
    cards = NativePromptCards(inputs, lambda candidate: candidate.id == prompt.id)
    offer = cards.register(prompt)
    tap = callback(offer.markup, "Build (Recommended)")
    assert len(tap["data"].encode()) <= 64
    assert not cards.handle(tap).applied
    assert not cards.bind(offer.token, True, 91, 7)
    assert cards.bind(offer.token, 5, 91, 7)
    for changes in ({"sender": 43}, {"chat": 6}, {"message": 92}, {"thread": 8}):
        assert not cards.handle(callback(offer.markup, "Build (Recommended)", **changes)).applied
    assert inputs.pending(KEY).id == prompt.id
    result = cards.handle(tap)
    assert (result.applied, result.status, result.prompt_id) == (True, "resolved", prompt.id)
    assert (await inputs.wait(prompt)).value == "Build"
    assert not cards.handle(tap).applied


@pytest.mark.asyncio
async def test_eligible_is_rechecked_before_mutation_and_exact_offered_prompt_can_answer():
    inputs = PendingInputs()
    first = inputs.register_clarify(KEY, "First?", ["A", "B"])
    second = inputs.register_clarify(KEY, "Second?", ["A", "B"])
    allowed = {second.id}
    cards = NativePromptCards(inputs, lambda prompt: prompt.id in allowed)
    offer = cards.register(second)
    assert cards.bind(offer.token, 5, 91, 7)
    tap = callback(offer.markup, "B")
    allowed.clear()
    assert not cards.handle(tap).applied
    assert inputs.pending(KEY).id == first.id
    allowed.add(second.id)
    assert cards.handle(tap).applied
    assert (await inputs.wait(second)).value == "B"
    assert inputs.pending(KEY).id == first.id
    inputs.cancel_prompt(first.id, KEY)


@pytest.mark.asyncio
async def test_other_marks_text_without_answering_and_cancel_retires_exact_prompt():
    inputs = PendingInputs()
    prompt = inputs.register_clarify(KEY, "Choose", ["A", "B"])
    neighbour = inputs.register_clarify(KEY, "Next", ["C", "D"])
    cards = NativePromptCards(inputs, lambda candidate: True)
    offer = cards.register(prompt)
    assert cards.bind(offer.token, 5, 91, 7)
    other = cards.handle(callback(offer.markup, "Other"))
    assert (other.applied, other.status) == (True, "awaiting_text")
    assert inputs.pending(KEY).awaiting_text
    assert not cards.handle(callback(offer.markup, "A")).applied
    cancelled = cards.handle(callback(other.markup, "Cancel"))
    assert (cancelled.applied, cancelled.status) == (True, "cancelled")
    assert await inputs.wait(prompt) is None
    assert inputs.pending(KEY).id == neighbour.id
    inputs.cancel_prompt(neighbour.id, KEY)


@pytest.mark.asyncio
async def test_multiselect_revision_fences_old_taps_and_submit_commits_selection():
    inputs = PendingInputs()
    prompt = inputs.register_clarify(KEY, "Pick", ["A (Recommended)", "B"], multi_select=True)
    cards = NativePromptCards(inputs, lambda candidate: True)
    offer = cards.register(prompt)
    assert cards.bind(offer.token, 5, 91, 7)
    first = callback(offer.markup, "A (Recommended)")
    updated = cards.handle(first)
    assert (updated.applied, updated.status) == (True, "updated")
    assert updated.markup != offer.markup
    assert not cards.handle(first).applied
    assert not cards.handle(callback(offer.markup, "Submit")).applied
    second = cards.handle(callback(updated.markup, "B"))
    assert second.applied
    assert cards.handle(callback(second.markup, "Submit")).applied
    assert (await inputs.wait(prompt)).value == ["A", "B"]


@pytest.mark.asyncio
async def test_confirmation_supersession_timeout_and_close_reject_callbacks():
    now = [100.0]
    inputs = PendingInputs(clock=lambda: now[0])
    cards = NativePromptCards(inputs, lambda candidate: True)
    old = inputs.register_confirmation(KEY, "/new", "Reset?")
    old_offer = cards.register(old)
    assert cards.bind(old_offer.token, 5, 91, 7)
    latest = inputs.register_confirmation(KEY, "/undo", "Undo?")
    assert not cards.handle(callback(old_offer.markup, "Once")).applied
    offer = cards.register(latest)
    assert cards.bind(offer.token, 5, 92, 7)
    assert cards.handle(callback(offer.markup, "Always", message=92)).applied
    assert (await inputs.wait(latest)).choice == "always"
    expired = inputs.register_confirmation(KEY, "/new", "Reset?", timeout_seconds=2)
    exp_offer = cards.register(expired)
    assert cards.bind(exp_offer.token, 5, 93, 7)
    now[0] = 102.0
    assert not cards.handle(callback(exp_offer.markup, "Once", message=93)).applied
    assert await inputs.wait(expired) is None
    active = inputs.register_confirmation(KEY, "/new", "Reset?")
    active_offer = cards.register(active)
    assert cards.bind(active_offer.token, 5, 94, 7)
    cards.close()
    assert not cards.handle(callback(active_offer.markup, "Once", message=94)).applied
    assert inputs.pending(KEY).id == active.id
    inputs.cancel_prompt(active.id, KEY)


def test_capacity_discard_and_malformed_callback_are_bounded():
    inputs = PendingInputs()
    cards = NativePromptCards(inputs, lambda candidate: True, max_pending=1)
    prompt = inputs.register_clarify(KEY, "Choose", ["A", "B"])
    offer = cards.register(prompt)
    assert cards.bind(offer.token, 5, 91, 7)
    another = inputs.register_clarify(KEY, "Next", ["A", "B"])
    with pytest.raises(OverflowError):
        cards.register(another)
    assert not cards.handle({"data": "h067:bad:0:c0"}).applied
    cards.discard(offer.token)
    assert not cards.handle(callback(offer.markup, "A")).applied
    assert cards.register(another).prompt_id == another.id
    inputs.close()


def test_expired_prompt_cannot_get_a_new_card_when_registry_is_empty():
    now = [100.0]
    inputs = PendingInputs(clock=lambda: now[0])
    prompt = inputs.register_clarify(KEY, "Choose", ["A", "B"], timeout_seconds=2)
    now[0] = 102.0
    cards = NativePromptCards(inputs, lambda candidate: True)
    with pytest.raises(ValueError, match="not live"):
        cards.register(prompt)


def test_binding_rechecks_eligibility_and_failure_does_not_claim_a_receipt():
    inputs = PendingInputs()
    prompt = inputs.register_clarify(KEY, "Choose", ["A", "B"])
    allowed = [True]
    cards = NativePromptCards(inputs, lambda candidate: allowed[0])
    offer = cards.register(prompt)
    allowed[0] = False
    assert not cards.bind(offer.token, 5, 91, 7)
    allowed[0] = True
    assert cards.bind(offer.token, 5, 92, 7)
    assert cards.handle(callback(offer.markup, "A", message=92)).applied
    inputs.close()


def test_eligibility_error_fails_closed_without_consuming_answer():
    inputs = PendingInputs()
    prompt = inputs.register_clarify(KEY, "Choose", ["A", "B"])
    allowed = [True]

    def eligible(candidate):
        if allowed[0]:
            return True
        raise RuntimeError("pairing lookup failed")

    cards = NativePromptCards(inputs, eligible)
    offer = cards.register(prompt)
    assert cards.bind(offer.token, 5, 91, 7)
    allowed[0] = False
    assert not cards.handle(callback(offer.markup, "A")).applied
    assert inputs.pending(KEY).id == prompt.id
    inputs.close()
