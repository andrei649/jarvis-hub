"""Hermes absorption 0.5 — one turn at a time per session.

`channel_handler` held no lock: a second Telegram message during a turn started a
concurrent turn on the same session key — transcript corruption, not just confusion. Now a
turn takes the session's lease; a second message on the same session waits its turn, a
message on another session does not wait at all, a wait past the bound is answered "busy"
rather than started, and a turn that calls back into the orchestrator (a workflow step)
inherits the lease instead of deadlocking on it.

Hermetic: bare orchestrator doubles, an event-gated fake turn, no model.
"""

from __future__ import annotations

import asyncio
import contextvars
from types import SimpleNamespace

import pytest

from agents.core import orchestrator as orchestrator_module
from agents.core.channels.manager import ChannelManager
from agents.core.orchestrator import TURN_BUSY_REPLY, Orchestrator

pytestmark = pytest.mark.asyncio


def _bare(*, max_wait: float | None = None):
    orch = Orchestrator.__new__(Orchestrator)
    orch._channel_sessions = {}
    orch._runtime_settings = {}
    orch.session_id = "shared"
    orch.channel_manager = ChannelManager()
    orch._delivery_router = SimpleNamespace(
        resolve=lambda source, text="": SimpleNamespace(send=False, target=None)
    )
    if max_wait is not None:
        orch._turn_lease_max_wait = max_wait
    log: list[tuple[str, str, str]] = []
    gate = asyncio.Event()

    async def fake_handle_input(text, channel="voice", agent_override=None):
        log.append(("start", text, str(orch.session_id)))
        if text.startswith("slow"):
            await gate.wait()
        log.append(("end", text, str(orch.session_id)))
        return f"reply:{text}"

    class _Memory:
        async def new_session(self, session_id=None):
            return f"session:{session_id}"

        async def resume_session(self, session_id):
            return False

        async def add_turn(self, *args, **kwargs):
            return None

    orch.handle_input = fake_handle_input
    orch.memory = _Memory()
    return orch, log, gate


async def _wait_for(predicate, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            pytest.fail("condition not reached in time")
        await asyncio.sleep(0.005)


async def test_a_second_message_on_the_same_session_waits_its_turn():
    orch, log, gate = _bare()

    first = asyncio.create_task(orch.channel_handler("slow a", channel="telegram", chat_id=1, sender="u"))
    await _wait_for(lambda: len(log) == 1)
    second = asyncio.create_task(orch.channel_handler("b", channel="telegram", chat_id=1, sender="u"))
    await asyncio.sleep(0.05)

    assert [(step, text) for step, text, _ in log] == [("start", "slow a")]  # b has not started
    gate.set()
    assert await asyncio.gather(first, second) == ["reply:slow a", "reply:b"]
    assert [(step, text) for step, text, _ in log] == [
        ("start", "slow a"), ("end", "slow a"), ("start", "b"), ("end", "b"),
    ]


async def test_messages_on_different_sessions_do_not_wait_for_each_other():
    orch, log, gate = _bare()

    first = asyncio.create_task(orch.channel_handler("slow a", channel="telegram", chat_id=1, sender="u"))
    second = asyncio.create_task(orch.channel_handler("b", channel="telegram", chat_id=2, sender="u"))
    await _wait_for(lambda: ("end", "b") in [(step, text) for step, text, _ in log])

    steps = [(step, text) for step, text, _ in log]
    assert ("start", "slow a") in steps
    assert ("end", "slow a") not in steps
    sessions = {session for _, text, session in log}
    assert len(sessions) == 2  # two chats, two sessions
    gate.set()
    await asyncio.gather(first, second)


async def test_the_shared_web_session_is_serialized_too():
    orch, log, gate = _bare()

    first = asyncio.create_task(orch.channel_handler("slow a", channel="web"))
    await _wait_for(lambda: len(log) == 1)
    second = asyncio.create_task(orch.channel_handler("b", channel="web"))
    await asyncio.sleep(0.05)

    assert [text for _, text, _ in log] == ["slow a"]
    gate.set()
    await asyncio.gather(first, second)
    assert [(step, text) for step, text, _ in log][-2:] == [("start", "b"), ("end", "b")]


async def test_a_wait_past_the_bound_is_answered_busy_not_started():
    orch, log, gate = _bare(max_wait=0.05)

    first = asyncio.create_task(orch.channel_handler("slow a", channel="telegram", chat_id=1, sender="u"))
    await _wait_for(lambda: len(log) == 1)

    assert await orch.channel_handler("b", channel="telegram", chat_id=1, sender="u") == TURN_BUSY_REPLY
    assert [text for _, text, _ in log] == ["slow a"]  # b never ran
    gate.set()
    assert await first == "reply:slow a"
    # The lease is free again afterwards.
    assert await orch.channel_handler("c", channel="telegram", chat_id=1, sender="u") == "reply:c"


async def test_the_lease_is_reentrant_within_one_turn():
    orch, _log, _gate = _bare()

    async with orch.turn_lease("k") as outer:
        async with orch.turn_lease("k") as inner:
            assert outer is True and inner is True
        # Still held by the outer scope: another task cannot take it.
        orch._turn_lease_max_wait = 0.02
        async with orch.turn_lease("k") as again:
            assert again is True  # same context → inherited, not blocked

        async def other():
            async with orch.turn_lease("k") as acquired:
                return acquired

        # A task spawned *inside* the turn inherits the lease (a workflow step is part of
        # the turn); a task from an unrelated context does not, and is blocked.
        assert await asyncio.create_task(other()) is True
        assert await asyncio.create_task(other(), context=contextvars.Context()) is False


async def test_an_inherited_lease_is_released_by_its_owner_only():
    orch, _log, _gate = _bare()

    async with orch.turn_lease("k"):
        async with orch.turn_lease("k"):
            pass
        assert orch._turn_leases["k"].locked()
    assert not orch._turn_leases["k"].locked()


async def test_the_lease_table_is_bounded(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_TURN_LEASE_TABLE_LIMIT", 3)
    orch, _log, _gate = _bare()

    for key in ("a", "b", "c", "d", "e"):
        async with orch.turn_lease(key):
            pass

    assert len(orch._turn_leases) <= 3


async def test_an_observed_message_does_not_take_the_lease():
    orch, log, gate = _bare()

    first = asyncio.create_task(orch.channel_handler("slow a", channel="telegram", chat_id=1, sender="u"))
    await _wait_for(lambda: len(log) == 1)
    observed = await asyncio.wait_for(
        orch.channel_handler("chatter", channel="telegram", chat_id=1, sender="u", observe_only=True),
        timeout=1.0,
    )

    assert observed is None
    gate.set()
    await first
