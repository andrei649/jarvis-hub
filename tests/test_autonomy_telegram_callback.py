"""Telegram decision-inbox callback dispatch (H6.2) — offline, no network."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from agents.core.channels.telegram import TelegramChannel


@pytest.fixture
def channel(monkeypatch):
    ch = TelegramChannel(token="fake-token")

    async def _noop_answer(callback_id, text=""):
        return None

    # Avoid any network in tests.
    monkeypatch.setattr(ch, "_answer_callback", _noop_answer)
    return ch


async def test_callback_dispatches_parsed_decision(channel):
    received = []

    async def on_callback(task_id, action, **kwargs):
        received.append((task_id, action))

    channel.on_callback = on_callback
    cb = {"id": "cb1", "from": {"id": 99},
          "message": {"chat": {"id": 5}}, "data": "aut:42:accept"}
    await channel._handle_callback(cb)
    assert received == [(42, "accept")]


async def test_callback_ignores_garbage_data(channel):
    received = []

    async def on_callback(task_id, action, **kwargs):
        received.append((task_id, action))

    channel.on_callback = on_callback
    await channel._handle_callback({"id": "x", "from": {"id": 1}, "data": "junk"})
    assert received == []


async def test_callback_respects_allowed_users(channel):
    channel.allowed_users = [1234]
    received = []

    async def on_callback(task_id, action, **kwargs):
        received.append((task_id, action))

    channel.on_callback = on_callback
    cb = {"id": "cb", "from": {"id": 99}, "message": {"chat": {"id": 5}},
          "data": "aut:1:accept"}
    await channel._handle_callback(cb)
    assert received == []  # user not allowed
