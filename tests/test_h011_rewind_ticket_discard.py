"""Preparing an approval must not retain a live rewind ticket while it waits."""

from dataclasses import replace

import pytest

from agents.core.memory.manager import RewindRefused
from tests.test_h011_rewind_boot_lifecycle import context


@pytest.mark.asyncio
async def test_discard_requires_exact_ticket_and_never_changes_history(context):
    memory, checkpoints, root = context
    sid = await memory.new_session("approval_wait")
    await memory.add_turn(sid, "user", "preserve this until approved")
    clock = checkpoints.clock_snapshot(sid)
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    before = (root / f"{sid}.json").read_bytes()
    discard = getattr(memory, "discard_rollback_rewind", None)
    assert callable(discard), "approval preparation needs an exact-ticket discard"
    assert await discard(replace(ticket)) is False
    assert memory._rollback_tickets[ticket.nonce] is ticket
    assert await discard(ticket) is True
    assert await discard(ticket) is False
    assert (root / f"{sid}.json").read_bytes() == before
    with pytest.raises(RewindRefused):
        await memory.commit_rollback_rewind(ticket)
    assert [row["content"] for row in await memory.get_history(sid)] == [
        "preserve this until approved"
    ]
