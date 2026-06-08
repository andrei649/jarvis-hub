"""Deterministic token-bucket rate limiter for the capture swarm (ticket H19.5.7).

Pure, no I/O: the caller injects ``now`` (UTC UNIX seconds) on every call so the
limiter is fully unit-testable with a fake clock — there is no wall-clock read in
the testable logic. Used to govern the capture swarm so it cannot hammer a source
or explode globally.

Model
-----
A classic token bucket: a bucket holds up to ``burst`` tokens and refills at
``rate`` tokens/second; :meth:`acquire` succeeds (consuming one token) iff a token
is available at ``now``. The swarm enforces BOTH a per-source bucket AND a single
global bucket via :class:`RateLimiter`: a capture is allowed only when both grant
a token, and a token is consumed from each only on success (no partial debits).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """A single token bucket: capacity ``burst``, refilling at ``rate`` tokens/sec.

    State is the current token count plus the last-refill timestamp. All time comes
    in as ``now`` (UTC UNIX seconds); the bucket never reads a clock itself.
    """

    rate: float
    burst: float
    _tokens: float = field(init=False)
    _last: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.rate < 0:
            raise ValueError(f"rate must be >= 0, got {self.rate}")
        if self.burst <= 0:
            raise ValueError(f"burst must be > 0, got {self.burst}")
        self.rate = float(self.rate)
        self.burst = float(self.burst)
        # Start full so an initial burst is allowed immediately.
        self._tokens = self.burst

    def _refill(self, now: float) -> None:
        """Add tokens for elapsed time since the last call, clamped to ``burst``."""
        if self._last is None:
            self._last = now
            return
        if now <= self._last:
            # Non-advancing (or backwards) clock: never mint tokens, never rewind `_last`.
            return
        elapsed = now - self._last
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last = now

    def tokens(self, now: float) -> float:
        """Current token count at ``now`` (after refill); does not consume."""
        self._refill(now)
        return self._tokens

    def allow(self, now: float) -> bool:
        """Whether a token is available at ``now`` (peek, no consume)."""
        return self.tokens(now) >= 1.0

    def acquire(self, now: float) -> bool:
        """Consume one token if available at ``now``; return whether it succeeded."""
        self._refill(now)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class RateLimiter:
    """Governs captures with a per-source bucket AND a shared global bucket.

    A capture for ``source`` is allowed only when both the global bucket and that
    source's bucket can grant a token. :meth:`acquire` consumes from both ONLY on
    success, so a global-bucket debit never happens when a per-source bucket would
    have blocked the call (and vice versa). Per-source buckets are created lazily.
    """

    def __init__(
        self,
        *,
        rate: float,
        burst: float,
        global_rate: float | None = None,
        global_burst: float | None = None,
    ) -> None:
        """Configure per-source ``rate``/``burst`` and optional global limits.

        ``global_rate``/``global_burst`` default to the per-source values; set them
        higher to allow N sources to run concurrently under one global ceiling.
        """
        self._rate = float(rate)
        self._burst = float(burst)
        self._global = TokenBucket(
            rate=float(global_rate if global_rate is not None else rate),
            burst=float(global_burst if global_burst is not None else burst),
        )
        self._sources: dict[str, TokenBucket] = {}

    def _bucket(self, source: str) -> TokenBucket:
        bucket = self._sources.get(source)
        if bucket is None:
            bucket = TokenBucket(rate=self._rate, burst=self._burst)
            self._sources[source] = bucket
        return bucket

    def allow(self, source: str, now: float) -> bool:
        """Whether a capture for ``source`` would be allowed at ``now`` (no consume)."""
        return self._global.allow(now) and self._bucket(source).allow(now)

    def acquire(self, source: str, now: float) -> bool:
        """Try to consume one token from both the global and ``source`` buckets.

        Refills both at ``now`` first (so a peek is consistent), then consumes from
        each only if BOTH currently hold a token — no partial debits.
        """
        global_tokens = self._global.tokens(now)
        source_bucket = self._bucket(source)
        source_tokens = source_bucket.tokens(now)
        if global_tokens >= 1.0 and source_tokens >= 1.0:
            # Both refilled to `now`; acquire is now a pure in-place debit.
            self._global.acquire(now)
            source_bucket.acquire(now)
            return True
        return False
