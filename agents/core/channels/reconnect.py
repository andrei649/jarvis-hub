"""reconnect.py — one reconnect ladder and one health record for every channel (H100).

Before this, each channel recovered its own way: Telegram slept a flat 3 s after any
error, forever, whether the network blinked or the bot token had been revoked; ntfy had a
ladder of its own; nothing outside a channel could tell a dead one from a quiet one.

Three pieces, shared by every polling or socket adapter:

* :class:`Backoff` — the ladder (1, 2, 5, 10, 30, 60 s) with ±20 % jitter, so several
  channels that lost the same network do not all knock again in the same second. It
  climbs one rung per consecutive failure and returns to the bottom only after the
  connection has stayed healthy for ``healthy_after`` seconds — a link that flaps
  (one good poll, one bad) keeps climbing instead of hammering at the bottom rung.
* :func:`classify_status` / :func:`classify_exception` — which failures are worth
  retrying. HTTP 401, 403 and 404 on the channel's own endpoint mean the credential is
  wrong or revoked (Telegram answers 404 for an unknown bot token): retrying cannot fix
  that, so the channel stops and says so. 409 (another poller holds the bot), 429 and
  5xx are transient and climb the ladder; a 429's ``retry_after`` is honoured.
* :class:`ChannelHealth` — what ``GET /status`` shows per channel: ``healthy``,
  ``retrying`` (with the error kind, how many failures in a row, and when the next try
  is), ``fatal`` (with the reason) or ``stopped``. Kinds and counts only — never a URL,
  a token or a response body.

The ladder shape follows Hermes's ntfy adapter (MIT, pinned 59b2aeef, plugins/platforms/
ntfy/adapter.py), generalised; the classifier is Nerva's own.
"""

from __future__ import annotations

import logging
import math
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

#: Seconds to wait after the 1st, 2nd, … consecutive failure; the last rung repeats.
LADDER: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
#: Each wait is scaled by a factor drawn from [1 - JITTER, 1 + JITTER].
JITTER = 0.2
#: A connection that stayed healthy this long earns a fresh ladder.
HEALTHY_AFTER = 60.0
#: Longest wait a server's retry_after can impose (a bogus huge value must not park us).
MAX_RETRY_AFTER = 300.0

# An inbound poller probes once after this much quiet time when transient calls
# have repeatedly failed. Existing Backoff and provider Retry-After may wait longer.
CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_RECOVERY_TIMEOUT = 120.0
_BUSY_RECHECK = 1.0

#: How often a channel stopped by a fatal answer looks again (a fixed token heals by itself).
FATAL_REPROBE_S = 600.0

#: Status codes that mean "your credential or address is wrong": stop, do not retry.
FATAL_STATUSES = {401: "unauthorized", 403: "forbidden", 404: "not_found"}

STATE_IDLE = "idle"
STATE_HEALTHY = "healthy"
STATE_RETRYING = "retrying"
STATE_FATAL = "fatal"
STATE_STOPPED = "stopped"

_RNG = secrets.SystemRandom()


class Backoff:
    """The shared reconnect ladder with jitter and reset-after-healthy."""

    def __init__(self, ladder: tuple[float, ...] = LADDER, *, jitter: float = JITTER,
                 healthy_after: float = HEALTHY_AFTER,
                 clock: Callable[[], float] = time.monotonic,
                 uniform: Callable[[float, float], float] | None = None) -> None:
        if not ladder or any(step <= 0 for step in ladder):
            raise ValueError("a backoff ladder needs positive steps")
        self.ladder = tuple(float(step) for step in ladder)
        self.jitter = max(0.0, min(float(jitter), 0.9))
        self.healthy_after = float(healthy_after)
        self._clock = clock
        self._uniform = uniform or _RNG.uniform
        self.rung = 0
        self._healthy_since: float | None = None

    def success(self, *, at: float | None = None) -> None:
        """The connection works (a poll answered, a stream opened — *at* is when that
        connection began, on this clock). The ladder returns to the bottom only once it has
        kept working for ``healthy_after`` seconds."""
        now = self._clock()
        if self._healthy_since is None:
            self._healthy_since = now if at is None else at
        elif now - self._healthy_since >= self.healthy_after:
            self.rung = 0

    def failure(self) -> float:
        """One more failure: the jittered wait before the next attempt."""
        now = self._clock()
        if self._healthy_since is not None and now - self._healthy_since >= self.healthy_after:
            self.rung = 0
        self._healthy_since = None
        base = self.ladder[min(self.rung, len(self.ladder) - 1)]
        self.rung += 1
        if not self.jitter:
            return base
        return max(0.0, base * self._uniform(1.0 - self.jitter, 1.0 + self.jitter))

    def reset(self) -> None:
        self.rung = 0
        self._healthy_since = None


class ProbeLease:
    """Opaque ownership of one admitted inbound transport attempt."""

    __slots__ = ()


class PollingCircuit:
    """Per-adapter closed/open/half-open gate with one live recovery probe.

    A quiet stream may become healthy while its lease stays active. That lease
    still blocks a second stream until the first settles. The caller owns all
    sleeps and must check :meth:`admit` immediately before network I/O.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD,
                 recovery_timeout: float = CIRCUIT_RECOVERY_TIMEOUT) -> None:
        if type(failure_threshold) is not int or failure_threshold < 1:
            raise ValueError("invalid circuit failure threshold")
        if not math.isfinite(recovery_timeout) or recovery_timeout <= 0:
            raise ValueError("invalid circuit recovery timeout")
        self._clock = clock
        self.failure_threshold = failure_threshold
        self.recovery_timeout = float(recovery_timeout)
        self.state = "closed"
        self.failures = 0
        self._open_until = 0.0
        self._not_before = 0.0
        self._active: ProbeLease | None = None

    def _remaining(self, now: float) -> float:
        deadline = max(self._not_before, self._open_until if self.state == "open" else 0.0)
        return max(0.0, deadline - now)

    def admit(self) -> tuple[ProbeLease | None, float]:
        """Reserve a transport call or return the positive wait before rechecking."""
        if self._active is not None:
            return None, _BUSY_RECHECK
        now = self._clock()
        remaining = self._remaining(now)
        if remaining > 0:
            return None, remaining
        if self.state == "open":
            self.state = "half_open"
        lease = ProbeLease()
        self._active = lease
        return lease, 0.0

    def mark_healthy(self, lease: ProbeLease) -> bool:
        """Close the circuit while retaining this stream's exclusive lease."""
        if self._active is not lease or lease is None:
            return False
        self.state = "closed"
        self.failures = 0
        self._open_until = 0.0
        self._not_before = 0.0
        return True

    def success(self, lease: ProbeLease) -> bool:
        """Settle a successful one-shot call and release its lease."""
        if not self.mark_healthy(lease):
            return False
        self._active = None
        return True

    def failure(self, lease: ProbeLease, retry_after: float | None = 0) -> float:
        """Settle a transient failure; return the next gate wait in seconds."""
        if self._active is not lease or lease is None:
            return 0.0
        now = self._clock()
        try:
            requested = float(retry_after) if retry_after is not None else 0.0
        except (TypeError, ValueError):
            requested = 0.0
        wait = min(MAX_RETRY_AFTER, max(0.0, requested)) if math.isfinite(requested) else 0.0
        was_half_open = self.state == "half_open"
        self._active = None
        self.failures += 1
        self._not_before = max(self._not_before, now + wait)
        if was_half_open or self.failures >= self.failure_threshold:
            self.state = "open"
            self._open_until = now + max(self.recovery_timeout, wait)
        return self._remaining(now)

    def release(self, lease: ProbeLease) -> bool:
        """Release a cancelled or fatal call without counting a transient error."""
        if self._active is not lease or lease is None:
            return False
        self._active = None
        if self.state == "half_open":
            # An unproved recovery must not allow an immediate next probe.
            self.state = "open"
            self._open_until = self._clock() + self.recovery_timeout
        return True

    def reset(self) -> bool:
        """Reset only after the actual transport has settled."""
        if self._active is not None:
            return False
        self.state = "closed"
        self.failures = 0
        self._open_until = 0.0
        self._not_before = 0.0
        return True

    def snapshot(self) -> dict:
        """Fixed metadata only; no URL, token, exception, or response body."""
        return {"state": self.state, "failures": self.failures,
                "retry_in_s": math.ceil(self._remaining(self._clock())),
                "probe_active": self._active is not None}


@dataclass
class Failure:
    """One classified failure: its kind, whether retrying can help, and a server-asked wait."""

    kind: str
    fatal: bool = False
    retry_after: float | None = None
    status: int | None = None


def _retry_after(body) -> float | None:
    params = body.get("parameters") if isinstance(body, dict) else None
    value = params.get("retry_after") if isinstance(params, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(min(value, MAX_RETRY_AFTER))


def classify_status(status: int, body=None) -> Failure:
    """A failed HTTP answer from the channel's own endpoint (poll, stream, identity)."""
    if status in FATAL_STATUSES:
        return Failure(FATAL_STATUSES[status], fatal=True, status=status)
    if status == 409:
        return Failure("conflict", status=status)
    if status == 429:
        return Failure("rate_limited", retry_after=_retry_after(body), status=status)
    if 500 <= status <= 599:
        return Failure("server_error", status=status)
    return Failure("http_error", status=status)


def classify_exception(exc: BaseException) -> Failure:
    """Any failure raised while reaching the channel. Never reads the message text (an
    HTTP error's text names the URL, and a Telegram URL holds the bot token)."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a hub dependency
        httpx = None
    if httpx is not None:
        if isinstance(exc, httpx.HTTPStatusError):
            body = None
            try:
                body = exc.response.json()
            except Exception:
                body = None
            return classify_status(exc.response.status_code, body)
        if isinstance(exc, httpx.TimeoutException):
            return Failure("timeout")
        if isinstance(exc, httpx.TransportError):
            return Failure("network")
    if isinstance(exc, (ConnectionError, OSError)):
        return Failure("network")
    return Failure("error")


@dataclass
class ChannelHealth:
    """What the status surface says about one channel's connection."""

    state: str = STATE_IDLE
    error: str | None = None
    fatal: str | None = None
    failures: int = 0
    next_retry_at: float | None = None   # wall clock
    since: float | None = None           # wall clock of the last state change
    last_ok: float | None = None         # wall clock of the last success
    backfill: dict = field(default_factory=dict)
    #: Called once with the reason when the channel becomes fatal (the manager tells the
    #: owner on another channel). Never raises into the channel.
    on_fatal: Callable[[str], None] | None = field(default=None, repr=False, compare=False)

    def _move(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.since = time.time()

    def ok(self) -> None:
        self._move(STATE_HEALTHY)
        self.error = None
        self.failures = 0
        self.next_retry_at = None
        self.last_ok = time.time()

    def retrying(self, kind: str, delay: float) -> None:
        self._move(STATE_RETRYING)
        self.error = str(kind)[:40]
        self.failures += 1
        self.next_retry_at = time.time() + max(0.0, float(delay))

    def failed_fatally(self, reason: str, *, reprobe_in: float | None = None) -> None:
        """Fatal: retrying on the ladder cannot help. *reprobe_in* is when the channel looks
        again (a fixed, slow probe, so a fixed token heals without a restart)."""
        newly = self.state != STATE_FATAL
        self._move(STATE_FATAL)
        self.fatal = str(reason)[:40]
        self.error = self.fatal
        self.next_retry_at = None if reprobe_in is None else time.time() + max(0.0, reprobe_in)
        hook = self.on_fatal
        if newly and hook is not None:
            try:
                hook(self.fatal)
            except Exception:
                logging.getLogger("jarvis.channels.reconnect").warning(
                    "fatal-channel notice failed", exc_info=True)

    def starting(self) -> None:
        self.fatal = None
        self.error = None
        self.failures = 0
        self.next_retry_at = None
        self._move(STATE_IDLE)

    def stopped(self) -> None:
        if self.state != STATE_FATAL:
            self._move(STATE_STOPPED)
        self.next_retry_at = None

    def snapshot(self) -> dict:
        retry_in = None
        if self.state in (STATE_RETRYING, STATE_FATAL) and self.next_retry_at is not None:
            retry_in = max(0, round(self.next_retry_at - time.time()))
        row = {
            "state": self.state,
            "error": self.error,
            "fatal": self.fatal if self.state == STATE_FATAL else None,
            "failures": self.failures,
            "retry_in_s": retry_in,
            "since": round(self.since) if self.since else None,
            "last_ok": round(self.last_ok) if self.last_ok else None,
        }
        if self.backfill:
            row["backfill"] = {k: v for k, v in self.backfill.items()
                               if isinstance(v, int) and not isinstance(v, bool)}
        return row


__all__ = [
    "Backoff", "ChannelHealth", "CIRCUIT_FAILURE_THRESHOLD", "CIRCUIT_RECOVERY_TIMEOUT",
    "Failure", "FATAL_STATUSES", "HEALTHY_AFTER", "JITTER", "PollingCircuit", "ProbeLease",
    "LADDER", "STATE_FATAL", "STATE_HEALTHY", "STATE_IDLE", "STATE_RETRYING",
    "STATE_STOPPED", "classify_exception", "classify_status",
]
