"""Shared wait helper for async tests."""

import asyncio


async def until(predicate):
    """Yield to the loop until *predicate* holds, for at most two seconds."""
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)
