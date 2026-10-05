"""Workspace cards require the exact acknowledged bot message and identity."""

import pytest

from agents.core.channels.pending_input import PendingInputs
from agents.core.channels.pending_input_cards import NativePromptCards


def offered(channel="slack", sender="T1:U2"):
    inputs = PendingInputs()
    prompt = inputs.register_clarify((channel, "route", sender), "Route?", ["Local", "Remote"])
    eligible = {"yes": True}
    cards = NativePromptCards(inputs, lambda _p: eligible["yes"])
    offer = cards.register(prompt)
    receipt = {"channel": channel, "target": "C1" if channel == "slack" else "123",
               "message_id": "171.001" if channel == "slack" else "456",
               "thread_id": "170.001" if channel == "slack" else None,
               "team_id": "T1" if channel == "slack" else None}
    callback = {**receipt, "sender": sender,
                "data": offer.markup["inline_keyboard"][1][0]["callback_data"]}
    return inputs, prompt, cards, offer, receipt, callback, eligible


@pytest.mark.parametrize("channel,sender", [("slack", "T1:U2"), ("discord", "42")])
def test_workspace_receipt_is_required_and_first_answer_wins(channel, sender):
    inputs, prompt, cards, offer, receipt, callback, _ = offered(channel, sender)
    assert not cards.handle_workspace(callback).applied
    assert cards.bind_workspace(offer.token, receipt)
    assert cards.handle_workspace(callback).applied
    assert not cards.handle_workspace(callback).applied
    assert inputs.pending(prompt.key) is None


@pytest.mark.parametrize("field,value", [("target", "C9"), ("message_id", "172.001"),
                                       ("thread_id", None), ("team_id", "T9"),
                                       ("sender", "T1:U9"), ("channel", "discord")])
def test_workspace_callback_cannot_move_between_receipts_or_users(field, value):
    inputs, prompt, cards, offer, receipt, callback, _ = offered()
    assert cards.bind_workspace(offer.token, receipt)
    assert not cards.handle_workspace({**callback, field: value}).applied
    assert inputs.pending(prompt.key).id == prompt.id


def test_workspace_revocation_precedes_mutation():
    inputs, prompt, cards, offer, receipt, callback, eligible = offered()
    assert cards.bind_workspace(offer.token, receipt)
    eligible["yes"] = False
    assert not cards.handle_workspace(callback).applied
    assert inputs.pending(prompt.key).id == prompt.id


@pytest.mark.parametrize("channel,sender", [("slack", "T1:U2"), ("discord", "42")])
def test_workspace_options_have_numbers_before_provider_label_clipping(channel, sender):
    _, _, _, offer, _, _, _ = offered(channel, sender)
    assert offer.markup["inline_keyboard"][0][0]["text"].startswith("1. ")
    assert offer.markup["inline_keyboard"][1][0]["text"].startswith("2. ")
