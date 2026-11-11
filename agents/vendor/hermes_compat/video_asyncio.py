"""``asyncio`` for the adopted xAI video plugin (rewrite rule ``video-xai-asyncio``).

The plugin runs its submit-and-poll flow on a private event loop it creates on its own
worker thread (``asyncio.new_event_loop``) and waits between polls with
``await asyncio.sleep(5)``. Here that sleep is :func:`video_clock.sleep`: it returns as
soon as the approved task is cancelled or its deadline passes, so a cancelled video stops
polling at once instead of after the next five seconds. Blocking the private loop is the
plugin's own business: no other coroutine runs on it.
"""

from __future__ import annotations

from asyncio import new_event_loop
from typing import Any

from agents.vendor.hermes_compat import video_clock


async def sleep(delay: float, result: Any = None) -> Any:
    video_clock.sleep(delay)
    return result


__all__ = ["new_event_loop", "sleep"]
