"""S3: lifecycle events an extension may *watch*, and nothing more than watch.

The rows that ask for this (H567, H622) ask for something larger: 37 hook points,
shell hooks with an exit code that blocks, `pre_tool_call` able to veto a call and
`pre_llm_call` able to inject text into the turn. Three other rows in the same
inventory — H021, H163 and H514 — deliberately **exclude** exactly that, and their
reasons are the right ones: an owner-authored script running beside the kernel on
every lifecycle event is a second, weaker authorization system parallel to the one
that is the product, and it fires with no human in the loop, around the HARDLINE
denylist rather than through it. Each exclusion names the same re-open path — a
`hook.exec` kernel kind with a per-hook capability token and a hash-pinned script —
and that is an owner decision, not one to take by writing code.

So this file delivers the half that does not re-open the exclusion: **observation**.
An extension already signed, consented, activated and sandboxed (S2) may be told
that something happened. Four properties make that different in kind from a hook:

* **Nothing comes back.** `ExtensionRuntime.observe` reads the exit code and not one
  byte of output. There is no return value to trust, so an observer cannot veto a
  decision, rewrite an identity, admit a sender or add prompt text — not because
  those are filtered out, but because there is no channel for them.
* **The payload is an allowlist, not a redaction.** Each event has a fixed, tiny set
  of fields built here from scratch. A message body, a tool argument, a result, a
  principal or a secret is not omitted — it is never assembled.
* **Emission never blocks the caller.** `emit` builds the payload, picks observers
  and returns. Delivery happens on its own task, because an observer runs in a
  container and a container start is measured in seconds while the hot paths that
  emit here budget milliseconds.
* **The backlog is bounded.** Past `max_pending` deliveries in flight, events are
  dropped and counted. A slow or crashed observer costs a counter, never the chat.

The cost of that isolation is real and worth naming: one container per delivered
event. This is not a hot-path hook system and is not trying to be one.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from typing import Any

from .manifest import EVENTS

logger = logging.getLogger("jarvis.extensions.events")

# Exactly what each event carries, and nothing else. Adding a field here is a
# deliberate act with a privacy consequence; forgetting to add one is harmless.
FIELDS: dict[str, tuple[str, ...]] = {
    "command.completed": ("command", "status"),
    "session.started": ("session_id",),
    "session.ended": ("session_id",),
    "tool.completed": ("tool", "status"),
}
MAX_FIELD_CHARS = 200
MAX_PENDING = 64
DELIVERY_TIMEOUT_SECONDS = 60.0


class ExtensionEventBus:
    """Fan one lifecycle event out to the activated extensions that declared it."""

    def __init__(self, *, runtime, clock=time.time, max_pending: int = MAX_PENDING,
                 timeout: float = DELIVERY_TIMEOUT_SECONDS, loop=None) -> None:
        self.runtime = runtime
        self._clock = clock
        self._max_pending = max(1, int(max_pending))
        self._timeout = max(0.001, float(timeout))
        self._sequence = itertools.count(1)
        self._pending: set[asyncio.Task] = set()
        self.dropped = 0
        # Captured so an emitter that is *not* on the event loop still reaches it.
        # The tool loop hands its events to a worker thread, so without this the
        # busiest of the four events would silently never be delivered.
        self._loop = loop
        if self._loop is None:
            with contextlib.suppress(RuntimeError):
                self._loop = asyncio.get_running_loop()

    # ── the payload ──────────────────────────────────────────────────────────
    def _payload(self, event: str, fields: dict) -> dict:
        """Build the event from the allowlist. Unknown keys are refused, not dropped.

        Refusing rather than ignoring is the point: a caller that passes `body` or
        `token` has made a mistake about what this surface is for, and silently
        discarding it would let the same call be written again next to a field that
        *is* allowed.
        """
        allowed = FIELDS[event]
        if set(fields) - set(allowed):
            raise ValueError("unknown_event_field")
        payload: dict[str, Any] = {
            "event": event,
            "event_id": f"{int(self._clock() * 1000):d}-{next(self._sequence):d}",
            "occurred_at": round(float(self._clock()), 3),
        }
        for name in allowed:
            value = fields.get(name)
            if value is None:
                payload[name] = None
            elif isinstance(value, str):
                payload[name] = value[:MAX_FIELD_CHARS]
            elif type(value) is bool or type(value) is int:
                payload[name] = value
            else:
                raise ValueError("invalid_event_field")
        return payload

    # ── delivery ─────────────────────────────────────────────────────────────
    def observers(self, event: str) -> tuple[str, ...]:
        if event not in EVENTS:
            return ()
        try:
            return tuple(self.runtime.observers(event))
        except Exception:
            logger.debug("extension observer lookup failed", exc_info=True)
            return ()

    async def _deliver(self, extension_id: str, event: str, payload: dict) -> None:
        try:
            async with asyncio.timeout(self._timeout):
                await self.runtime.observe(extension_id, event, payload)
        except Exception:
            # An observer's failure is its own. It is logged and it ends there.
            logger.info("extension %s did not observe %s", extension_id, event, exc_info=True)

    def _spawn(self, loop, extension_id: str, event: str, payload: dict) -> None:
        """Create the delivery task. Only ever runs on the loop thread, so the
        backlog set is single-threaded and its cap is authoritative here."""
        if len(self._pending) >= self._max_pending:
            self.dropped += 1
            return
        task = loop.create_task(self._deliver(extension_id, event, payload))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def _target_loop(self):
        """The loop to deliver on, and whether this thread is already running it."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            return running, True
        loop = self._loop
        if loop is None or loop.is_closed():
            return None, False
        return loop, False

    def emit(self, event: str, **fields) -> dict:
        """Record that something happened and hand it off. Never blocks, never raises.

        Safe to call from a worker thread as well as from the loop: `record` on the
        tool-event store runs off-loop, and an event that only worked from one of the
        two call sites would be worse than none.

        The report is about *this hub's* dispatch decision — which observers were
        selected, whether the backlog refused it — never about what an observer did
        with it, which this bus does not learn.
        """
        if event not in EVENTS or event not in FIELDS:
            # Refused, not delivered: an unknown event name is a bug in the caller,
            # and inventing a payload shape for it would hide that.
            raise ValueError("unknown_event")
        payload = self._payload(event, fields)
        targets = self.observers(event)
        report = {"event": event, "event_id": payload["event_id"],
                  "observers": list(targets), "delivered": [], "dropped": 0}
        if not targets:
            return report
        loop, inline = self._target_loop()
        if loop is None:
            # Nothing to schedule on. Say so rather than blocking a sync caller on a
            # container start.
            report["dropped"] = len(targets)
            self.dropped += len(targets)
            return report
        for extension_id in targets:
            if inline:
                self._spawn(loop, extension_id, event, dict(payload))
            else:
                try:
                    loop.call_soon_threadsafe(self._spawn, loop, extension_id, event, dict(payload))
                except RuntimeError:
                    report["dropped"] += 1
                    self.dropped += 1
                    continue
            report["delivered"].append(extension_id)
        return report

    async def drain(self, timeout: float | None = None) -> int:
        """Await deliveries in flight. For shutdown and for tests; never for a turn."""
        pending = tuple(self._pending)
        if not pending:
            return 0
        await asyncio.wait(pending, timeout=timeout)
        return len(pending)


class _BoundBus:
    """The one bus the emitting subsystems reach, bound when a runtime is composed.

    A module-level holder rather than a dependency threaded through three
    subsystems, following the `TOOL_EVENTS` precedent in
    `observability/tool_events.py`: the call sites are one guarded line each on hot
    paths, and a hub with no extensions must pay nothing for the seam.

    Everything here is swallowed **except** an unknown event name, which raises even
    on an unbound hub. That asymmetry is deliberate: a delivery failure is the
    observer's problem, but an event name this bus does not define is a bug in the
    caller, and a bug that only shows up once an extension happens to be installed
    is the kind that ships.
    """

    def __init__(self) -> None:
        self.bus: ExtensionEventBus | None = None

    def bind(self, runtime) -> ExtensionEventBus:
        self.bus = ExtensionEventBus(runtime=runtime)
        return self.bus

    def unbind(self) -> None:
        self.bus = None

    def emit(self, event: str, **fields) -> dict | None:
        if event not in EVENTS or event not in FIELDS:
            raise ValueError("unknown_event")
        bus = self.bus
        if bus is None:
            return None
        try:
            return bus.emit(event, **fields)
        except ValueError:
            raise
        except Exception:
            logger.debug("extension event emission failed", exc_info=True)
            return None


EXTENSION_EVENTS = _BoundBus()


__all__ = ["DELIVERY_TIMEOUT_SECONDS", "EXTENSION_EVENTS", "FIELDS", "MAX_PENDING",
           "ExtensionEventBus"]
