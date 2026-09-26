"""H674 — a compaction summary never holds the owner's turn past a short bound.

Two clocks, kept apart on purpose, as Hermes keeps them:

- **The hold** (:class:`SummaryHold`): how long an arriving turn may wait for the
  strict-local LLM summary — ``memory.compression_max_turn_hold_seconds``, default
  10 s (0 = never wait). On expiry the turn goes on without it (verbatim turns when
  they still fit the window, else the deterministic digest) and the owner is told.
  The summary keeps being written in the background, one per session at a time, and
  seeds the next turn's iterative merge when it lands.
- **The inactivity deadline** (:func:`stream_summary`): the summarizer streams, and
  is cut after ``memory.compression_summary_idle_seconds`` (default 60 s) with
  nothing received. A slow stream that keeps talking — reasoning included — is never
  cut; a wedged one no longer holds the backend's whole read budget.

A degraded reply ("⚠️ Ollama is not answering…") is a failure here, never a summary.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("jarvis.compaction")

HOLD_SETTING = "memory.compression_max_turn_hold_seconds"
DEFAULT_HOLD = 10.0
MAX_HOLD = 120.0
IDLE_SETTING = "memory.compression_summary_idle_seconds"
DEFAULT_IDLE = 60.0
MAX_IDLE = 600.0
#: How long a cut-off summarizer gets to close its stream.
CLOSE_GRACE = 1.0

NOTICE_CODE = "compaction_deferred"
DEFERRED_NOTICE = ("The conversation summary is taking longer than usual, so this reply was written "
                   "from a shorter view of the earlier conversation; the summary should be ready "
                   "for the next message.")


class SummaryStalled(RuntimeError):
    """The summarizer went quiet for longer than the inactivity deadline."""


class SummaryUnusable(RuntimeError):
    """The summarizer answered with a failure (a degraded reply) or with nothing."""


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds != seconds or seconds in (float("inf"), float("-inf")):
        return None
    return seconds


def hold_seconds(value: Any) -> float:
    """The configured hold: a finite number clamped to 0..120 (0 = never wait), else 10."""
    seconds = _finite(value)
    if seconds is None:
        return DEFAULT_HOLD
    return min(max(0.0, seconds), MAX_HOLD)


def idle_seconds(value: Any) -> float:
    """The configured inactivity deadline, up to 600 s. There is no "off": a value that
    is not a positive number keeps the default, because a summarizer with no deadline
    is exactly what this row removed."""
    seconds = _finite(value)
    if seconds is None or seconds <= 0:
        return DEFAULT_IDLE
    return min(seconds, MAX_IDLE)


def _accepts(method: Callable, name: str) -> bool:
    try:
        return name in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False


async def stream_summary(backend, idle: float, *, model: str, prompt: str, system: str,
                         max_tokens: int, temperature: float) -> str:
    """One summary from a local *backend*, cut after *idle* seconds with nothing received.

    Everything the backend receives counts as the stream talking: a visible token, and
    — through ``on_activity`` where the backend offers it — a reasoning chunk that
    shows no text. A backend with no stream at all is awaited whole (it cannot say it
    is alive, so the deadline covers the whole call)."""
    from .llm.base import is_degraded_reply

    loop = asyncio.get_running_loop()
    last = loop.time()

    def alive() -> None:
        nonlocal last
        last = loop.time()

    async def on_token(_text: str) -> None:
        alive()

    streamer = getattr(backend, "generate_stream", None)
    if streamer is None:
        call = backend.generate(model=model, prompt=prompt, system=system,
                                max_tokens=max_tokens, temperature=temperature)
    else:
        extra = {"on_activity": alive} if _accepts(streamer, "on_activity") else {}
        call = streamer(model=model, prompt=prompt, system=system, max_tokens=max_tokens,
                        temperature=temperature, on_token=on_token, **extra)
    task = asyncio.ensure_future(call)
    try:
        while not task.done():
            quiet_left = last + idle - loop.time()
            if quiet_left <= 0:
                raise SummaryStalled(f"the summarizer sent nothing for {idle:.0f}s")
            await asyncio.wait({task}, timeout=quiet_left)
    finally:
        if not task.done():
            # Close the stream (its HTTP response with it) before going on; a backend
            # that will not stop within the grace is left to finish on its own.
            task.cancel()
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            await asyncio.wait({task}, timeout=CLOSE_GRACE)
    text = task.result()
    if not isinstance(text, str) or not text.strip() or is_degraded_reply(text):
        raise SummaryUnusable("the summarizer answered with a failure, not a summary")
    return text


class SummaryHold:
    """Per-session single flight for LLM compaction summaries, with a bounded hold."""

    def __init__(self) -> None:
        self._flights: dict[str, asyncio.Task] = {}

    def busy(self, session_id: str) -> bool:
        task = self._flights.get(session_id)
        return task is not None and not task.done()

    async def wait(self, session_id: str, make: Callable[[], Awaitable[str]], hold: float,
                   on_late: Callable[[str], Any]) -> str | None:
        """The summary when it is ready within *hold* seconds; ``None`` when the turn
        must go on without it. A summary still being written for this session from an
        earlier turn is not started again, nor waited on again: this turn goes on, and
        that one seeds the next. A deferred summary calls *on_late* when it lands; one
        that fails seeds nothing. A failure within the hold reaches the caller."""
        if self.busy(session_id):
            return None
        task = asyncio.ensure_future(make())
        self._flights[session_id] = task
        task.add_done_callback(lambda done: self._flights.get(session_id) is done
                               and self._flights.pop(session_id, None))
        try:
            if hold > 0:
                await asyncio.wait({task}, timeout=hold)
        finally:
            # Still being written — past the hold, or this turn was cancelled while it
            # waited: whenever it lands, it seeds the next turn.
            if not task.done():
                task.add_done_callback(lambda done: self._landed(done, on_late))
        if task.done():
            return task.result()
        return None

    @staticmethod
    def _landed(task: asyncio.Task, on_late: Callable[[str], Any]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.info("the deferred summary for this session was not written (%s: %s); the "
                        "next turn tries again", type(error).__name__, error)
            return
        try:
            on_late(task.result())
        except Exception:
            logger.warning("seeding a deferred compaction summary failed", exc_info=True)

    async def aclose(self, budget: float) -> None:
        """Stop every summary still being written, waiting at most *budget* seconds."""
        from .lifecycle_budget import wait_task

        for session_id, task in list(self._flights.items()):
            await wait_task(task, budget, f"deferred compaction summary ({session_id})")
            self._flights.pop(session_id, None)


__all__ = [
    "DEFAULT_HOLD", "DEFAULT_IDLE", "DEFERRED_NOTICE", "HOLD_SETTING", "IDLE_SETTING", "NOTICE_CODE",
    "SummaryHold", "SummaryStalled", "SummaryUnusable", "hold_seconds", "idle_seconds", "stream_summary",
]
