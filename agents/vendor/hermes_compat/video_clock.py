"""``time`` for the adopted video-generation files (rewrite rule ``video-clock``).

Upstream polls a long-running video job with ``time.sleep`` between status requests.
Here the sleep waits on the egress binding of the approved task instead: it returns as
soon as the task is cancelled (the worker abandoned the call) or the task's deadline
passes, so a worker thread never sleeps on for a caller that is gone. The next request
is then refused by the compat ``httpx`` and the vendored code ends its poll. Outside a
bound call a sleep returns at once (there is nothing to wait for).
"""

from __future__ import annotations

import time as _time

from agents.vendor.hermes_compat import httpx as _httpx

#: The longest single sleep a vendored poll may ask for (seconds).
MAX_SLEEP_SECONDS = 30.0

monotonic = _time.monotonic


def time() -> float:
    return _time.time()


def sleep(seconds: float) -> None:
    call = _httpx.current_call()
    if call is None:
        return
    try:
        wanted = max(0.0, min(float(seconds), MAX_SLEEP_SECONDS))
    except (TypeError, ValueError):
        wanted = 0.0
    remaining = call.deadline - _time.monotonic()
    wait = max(0.0, min(wanted, remaining))
    if wait:
        call.abandoned.wait(wait)


__all__ = ["MAX_SLEEP_SECONDS", "monotonic", "sleep", "time"]
