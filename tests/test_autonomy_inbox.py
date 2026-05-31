"""Tests for the decision inbox card + callback parsing (H6.2)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.autonomy.inbox import (
    build_decision_card, parse_callback_data, DECISION_ACTIONS, CALLBACK_PREFIX,
)


def _task(**over):
    base = dict(id=7, agent="jarvis", kind="delete_file", title="Delete old logs",
                risk_tier=3, payload={"rationale": "cleanup", "expected": "free 2GB"})
    base.update(over)
    return base


def test_card_has_four_buttons():
    card = build_decision_card(_task())
    buttons = card["reply_markup"]["inline_keyboard"][0]
    assert len(buttons) == len(DECISION_ACTIONS) == 4
    actions = [b["callback_data"].split(":")[-1] for b in buttons]
    assert set(actions) == set(DECISION_ACTIONS.keys())


def test_card_callback_data_carries_task_id():
    card = build_decision_card(_task(id=42))
    for b in card["reply_markup"]["inline_keyboard"][0]:
        assert b["callback_data"].startswith(f"{CALLBACK_PREFIX}:42:")


def test_card_includes_rationale_and_title():
    card = build_decision_card(_task())
    assert "Delete old logs" in card["text"]
    assert "cleanup" in card["text"]
    assert card["parse_mode"] == "Markdown"


def test_card_accepts_task_object():
    class T:
        def to_dict(self):
            return _task(id=9)
    card = build_decision_card(T())
    assert "9" in card["reply_markup"]["inline_keyboard"][0][0]["callback_data"]


def test_parse_roundtrip():
    for action in DECISION_ACTIONS:
        assert parse_callback_data(f"{CALLBACK_PREFIX}:123:{action}") == (123, action)


def test_parse_rejects_garbage():
    assert parse_callback_data("") is None
    assert parse_callback_data("nope:1:accept") is None
    assert parse_callback_data(f"{CALLBACK_PREFIX}:abc:accept") is None
    assert parse_callback_data(f"{CALLBACK_PREFIX}:1:bogus") is None
    assert parse_callback_data(f"{CALLBACK_PREFIX}:1") is None


def test_markdown_escaping_in_title():
    card = build_decision_card(_task(title="under_score *star*"))
    assert "\\_" in card["text"] and "\\*" in card["text"]
