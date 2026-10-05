"""Conversation-only undo backed by the durable rewind protocol.

The caller must hold the session turn lease, verify current owner authority and
route generation, and intercept the command before appending it to the history.
"""

from __future__ import annotations

import asyncio

from agents.core.conversation_clock import ClockSnapshot
from agents.core.memory.manager import MemoryManager, RewindRefused, RollbackRewindResult


async def undo_last_exchange(
    memory: MemoryManager, session_id: str, expected_clock: ClockSnapshot, *, authorize=None
) -> RollbackRewindResult:
    """Remove the last user exchange using the existing durable rewind fences."""
    ticket = await memory.prepare_rollback_rewind(
        session_id, expected_clock.instance_id, expected_clock
    )
    committed = False
    try:
        if authorize is not None and authorize() is not True:
            raise RewindRefused("Undo authority changed")
        result = (await memory.commit_rollback_rewind(ticket) if authorize is None
                  else await memory.commit_rollback_rewind(ticket, authorize=authorize))
        committed = True
        return result
    finally:
        if not committed:
            await asyncio.shield(memory.discard_rollback_rewind(ticket))
