"""resilience.py — keep one flaky MCP server from wedging the rest (H556).

Three pieces, all native (Hermes ``tools/mcp_tool_health.py`` and ``mcp_tool_discovery.py``
were read as reference only):

* :class:`ReconnectPolicy` — jittered exponential backoff (5 retries, 60 s ceiling, ±20 %),
  a circuit breaker (3 failures inside 60 s open it for 60 s), and a **parked** state after
  the retries run out, probed again every 300 s.
* :class:`ServerHealth` — one server's live record: state, attempts, consecutive failures,
  the last error, when it last answered, when the next retry is due, the last connect's
  duration, and the sampling / elicitation counters the host keeps (``host_requests.py``).
  :meth:`ServerHealth.status` is what the MCP admin list shows.
* :func:`halted` — the e-stop and the kill switch, read together. A reconnect, a keepalive
  ping, a sampling answer and an elicitation card are all refused while either is engaged.

What is *not* here (H556 stays partial): a schema cache with lazy connect, stdio idle and
lifetime recycling, a parent-death watchdog killing the child's process group, an orphan
reaper and a cross-process discovery lock.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("jarvis.mcp.resilience")

STATE_IDLE = "idle"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_BACKOFF = "backoff"
STATE_OPEN = "circuit_open"
STATE_PARKED = "parked"
STATE_DISCONNECTED = "disconnected"
STATE_REFUSED = "refused"


@dataclass(frozen=True)
class ReconnectPolicy:
    """The numbers Hermes uses, as one frozen value a test can shrink."""

    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: float = 0.2
    max_retries: int = 5
    breaker_failures: int = 3
    breaker_window: float = 60.0
    breaker_open: float = 60.0
    park_probe: float = 300.0

    def delay(self, attempt: int, *, rng: random.Random | None = None) -> float:
        """Seconds before retry number *attempt* (1-based): ``base·2^(n-1)``, capped, ±jitter."""
        raw = min(self.max_delay, self.base_delay * (2 ** max(0, attempt - 1)))
        spread = raw * self.jitter
        pick = (rng or random).uniform(-spread, spread)   # noqa: S311 — jitter, not a secret
        return max(0.0, min(self.max_delay * (1 + self.jitter), raw + pick))


@dataclass
class ServerHealth:
    """One server's connection record (mutated only by the manager and the server)."""

    policy: ReconnectPolicy = field(default_factory=ReconnectPolicy)
    state: str = STATE_IDLE
    attempts: int = 0
    consecutive_failures: int = 0
    last_error: str | None = None
    last_ok_at: float | None = None
    last_attempt_at: float | None = None
    next_retry_at: float | None = None
    breaker_open_until: float | None = None
    connect_ms: float | None = None
    reconnects: int = 0
    failures: list[float] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    # ── transitions ──────────────────────────────────────────────────────

    def begin(self, now: float | None = None) -> None:
        self.state = STATE_CONNECTING
        self.attempts += 1
        self.last_attempt_at = time.time() if now is None else now

    def succeeded(self, *, connect_ms: float | None = None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if self.consecutive_failures or self.state in (STATE_BACKOFF, STATE_OPEN, STATE_PARKED):
            self.reconnects += 1
        self.state = STATE_CONNECTED
        self.consecutive_failures = 0
        self.last_error = None
        self.last_ok_at = now
        self.next_retry_at = None
        self.breaker_open_until = None
        self.connect_ms = connect_ms
        # ``failures`` is NOT cleared: a server that connects and then dies again and
        # again (flapping) still trips the breaker, because each post-handshake death
        # (:meth:`lost`) lands in the same 60 s window as the connect failures.

    def failed(self, reason: str, *, now: float | None = None,
               rng: random.Random | None = None) -> None:
        """Record a failure and schedule the next retry: backoff, circuit open, or parked."""
        now = time.time() if now is None else now
        p = self.policy
        self.last_error = str(reason or "connect_failed")[:200]
        self.consecutive_failures += 1
        self.failures = [t for t in self.failures if t > now - p.breaker_window] + [now]
        if self.consecutive_failures > p.max_retries:
            self.state = STATE_PARKED
            self.next_retry_at = now + p.park_probe
            self.breaker_open_until = None
            return
        delay = p.delay(self.consecutive_failures, rng=rng)
        if len(self.failures) >= p.breaker_failures:
            self.state = STATE_OPEN
            self.breaker_open_until = now + p.breaker_open
            self.next_retry_at = max(now + delay, self.breaker_open_until)
            return
        self.state = STATE_BACKOFF
        self.next_retry_at = now + delay

    def lost(self, reason: str, *, now: float | None = None) -> None:
        """A connected server stopped answering (process exited, ping failed): retry soon."""
        if self.state == STATE_CONNECTED:
            self.failed(reason, now=now)

    def refused(self, reason: str) -> None:
        """A configuration refusal (unsafe command, transport off): retrying cannot help."""
        self.last_error = str(reason or "refused")[:200]
        self.state = STATE_REFUSED
        self.next_retry_at = None
        self.breaker_open_until = None

    def stopped(self) -> None:
        """The owner disconnected or removed the server: no retries are scheduled."""
        self.state = STATE_DISCONNECTED
        self.next_retry_at = None
        self.breaker_open_until = None

    def retry_due(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if self.state in (STATE_CONNECTED, STATE_CONNECTING, STATE_DISCONNECTED, STATE_REFUSED):
            return False
        if self.breaker_open_until is not None and now < self.breaker_open_until:
            return False
        return self.next_retry_at is None or now >= self.next_retry_at

    def bump(self, counter: str, amount: int = 1) -> None:
        self.counters[counter] = self.counters.get(counter, 0) + int(amount)

    # ── surface ──────────────────────────────────────────────────────────

    def status(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now

        def _in(ts: float | None) -> float | None:
            return None if ts is None else round(max(0.0, ts - now), 1)

        return {
            "state": self.state,
            "attempts": self.attempts,
            "consecutive_failures": self.consecutive_failures,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "last_ok_at": self.last_ok_at,
            "next_retry_in_s": _in(self.next_retry_at),
            "circuit_open_for_s": _in(self.breaker_open_until),
            "connect_ms": None if self.connect_ms is None else round(self.connect_ms, 1),
            "counters": dict(sorted(self.counters.items())),
        }


def halted(kill_switch: Any = None, scope: str = "mcp", *, server: str | None = None,
           include_estop: bool = True) -> str | None:
    """``"estop_engaged"`` / ``"kill_switch_engaged"`` while either is on, else None.

    The e-stop's own check fails safe (an unreadable sentinel reads as engaged); a kill
    switch that cannot be read is treated the same way. With *server*, both kill-switch
    scopes count: ``mcp`` (every server) and ``mcp:<server>`` (that one); the switch's
    own global scope always counts. Owner chat calls pass ``include_estop=False``: the
    e-stop pauses new autonomous work, not the owner's own conversation.
    """
    if include_estop:
        try:
            from agents.core import estop

            if estop.is_engaged():
                return "estop_engaged"
        except Exception:
            logger.warning("e-stop state unreadable; MCP host work refused", exc_info=True)
            return "estop_engaged"
    if kill_switch is not None:
        scopes = [scope] + ([f"mcp:{server}"] if server else [])
        try:
            if any(kill_switch.is_halted(s) for s in scopes):
                return "kill_switch_engaged"
        except Exception:
            logger.warning("kill switch unreadable; MCP host work refused", exc_info=True)
            return "kill_switch_engaged"
    return None
