"""``concurrent.futures`` for the vendored A2A client (rewrite rule ``a2a-futures``).

``a2a_orchestrate`` fans one task out to several peers with ``ThreadPoolExecutor``. Here the
executor starts no thread of its own: every task runs on one small pool shared by all
fan-outs (:data:`FANOUT_WORKERS` threads), in a copy of the caller's context, so the egress
binding, the A2A scope and the request guard of the call go with it. A task submitted
outside a bound call therefore has nothing to dial with and is refused at its first request.

``Future`` and ``as_completed`` are the standard library's.
"""

from __future__ import annotations

import concurrent.futures as _cf
import contextvars
from collections.abc import Callable
from typing import Any

Future = _cf.Future
as_completed = _cf.as_completed

#: Threads shared by every fan-out (upstream allows six per call; here six in all would let
#: two calls hold every one, so the pool is smaller and calls queue).
FANOUT_WORKERS = 4

_POOL = _cf.ThreadPoolExecutor(max_workers=FANOUT_WORKERS, thread_name_prefix="hermes-a2a-fanout")


class ThreadPoolExecutor:
    """Submits to the shared pool; ``max_workers`` is accepted and capped by it."""

    def __init__(self, max_workers: int | None = None, **_ignored: Any) -> None:
        self._futures: list[_cf.Future] = []

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> _cf.Future:
        context = contextvars.copy_context()
        future = _POOL.submit(context.run, fn, *args, **kwargs)
        self._futures.append(future)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        if cancel_futures:
            for future in self._futures:
                future.cancel()
        if wait:
            _cf.wait(self._futures)

    def __enter__(self) -> ThreadPoolExecutor:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.shutdown(wait=True)


__all__ = ["FANOUT_WORKERS", "Future", "ThreadPoolExecutor", "as_completed"]
