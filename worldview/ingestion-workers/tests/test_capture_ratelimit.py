"""Tests for the deterministic capture rate limiter (ticket H19.5.7).

Pure/no-I/O: every call takes an injected ``now`` (UTC UNIX seconds) so refill and
burst behaviour are exercised with a fake clock — no wall-clock, no sleeps. Covers
the single :class:`TokenBucket` and the two-tier (per-source + global)
:class:`RateLimiter`.
"""

from __future__ import annotations

import pytest

from worldview_ingest.capture.ratelimit import RateLimiter, TokenBucket

# --------------------------------------------------------------------------- #
# TokenBucket
# --------------------------------------------------------------------------- #


def test_bucket_allows_up_to_burst_immediately() -> None:
    """A fresh bucket starts full: exactly ``burst`` acquires succeed at t0."""
    bucket = TokenBucket(rate=1.0, burst=3.0)
    t0 = 1_700_000_000.0
    assert [bucket.acquire(t0) for _ in range(3)] == [True, True, True]
    # The 4th at the same instant is denied — bucket drained, no time has passed.
    assert bucket.acquire(t0) is False


def test_bucket_blocks_over_rate_until_refill() -> None:
    """Once drained, no token is granted until enough time elapses to refill one."""
    bucket = TokenBucket(rate=2.0, burst=2.0)  # 2 tokens/sec
    t0 = 1_700_000_000.0
    assert bucket.acquire(t0) and bucket.acquire(t0)
    assert bucket.acquire(t0) is False
    # 0.4s -> 0.8 tokens, still < 1.
    assert bucket.acquire(t0 + 0.4) is False
    # 0.5s -> exactly 1.0 token available.
    assert bucket.acquire(t0 + 0.5) is True


def test_bucket_refills_over_time_and_clamps_to_burst() -> None:
    """Tokens accrue at ``rate`` and never exceed ``burst`` no matter how long idle."""
    bucket = TokenBucket(rate=1.0, burst=5.0)
    t0 = 1_700_000_000.0
    # Drain it.
    for _ in range(5):
        assert bucket.acquire(t0)
    # Idle for an hour: refill clamps to burst (5), not 3600.
    assert bucket.tokens(t0 + 3600.0) == 5.0
    assert [bucket.acquire(t0 + 3600.0) for _ in range(5)] == [True] * 5
    assert bucket.acquire(t0 + 3600.0) is False


def test_bucket_allow_is_non_consuming_peek() -> None:
    """``allow`` reports availability without spending a token."""
    bucket = TokenBucket(rate=1.0, burst=1.0)
    t0 = 1_700_000_000.0
    assert bucket.allow(t0) is True
    assert bucket.allow(t0) is True  # still available — allow() did not consume
    assert bucket.acquire(t0) is True
    assert bucket.allow(t0) is False


def test_bucket_non_advancing_clock_never_mints() -> None:
    """A backwards/non-advancing ``now`` never adds tokens or rewinds state."""
    bucket = TokenBucket(rate=10.0, burst=2.0)
    t0 = 1_700_000_000.0
    assert bucket.acquire(t0) and bucket.acquire(t0)
    assert bucket.acquire(t0) is False
    # Clock goes backwards: still no token (no negative elapsed credit).
    assert bucket.acquire(t0 - 100.0) is False
    # And forward progress from the real t0 still works as normal.
    assert bucket.acquire(t0 + 1.0) is True


@pytest.mark.parametrize("rate,burst", [(-1.0, 1.0), (1.0, 0.0), (1.0, -2.0)])
def test_bucket_rejects_invalid_config(rate: float, burst: float) -> None:
    """Negative rate or non-positive burst is a configuration error."""
    with pytest.raises(ValueError):
        TokenBucket(rate=rate, burst=burst)


# --------------------------------------------------------------------------- #
# RateLimiter (per-source + global)
# --------------------------------------------------------------------------- #


def test_limiter_per_source_isolation() -> None:
    """Draining one source's bucket does not affect another source's bucket."""
    limiter = RateLimiter(rate=1.0, burst=2.0, global_rate=100.0, global_burst=100.0)
    t0 = 1_700_000_000.0
    assert limiter.acquire("adsb", t0) and limiter.acquire("adsb", t0)
    assert limiter.acquire("adsb", t0) is False  # adsb drained
    # A different source is untouched — its own bucket is still full.
    assert limiter.acquire("ais", t0) and limiter.acquire("ais", t0)
    assert limiter.acquire("ais", t0) is False


def test_limiter_global_ceiling_blocks_across_sources() -> None:
    """The global bucket caps total captures even when per-source buckets allow more."""
    # Per-source generous, global tight: only 2 total acquires at t0.
    limiter = RateLimiter(rate=100.0, burst=100.0, global_rate=2.0, global_burst=2.0)
    t0 = 1_700_000_000.0
    assert limiter.acquire("adsb", t0) is True
    assert limiter.acquire("ais", t0) is True
    # Global drained: a third, even from a fresh source, is denied.
    assert limiter.acquire("ew", t0) is False


def test_limiter_no_partial_debit_when_source_blocks() -> None:
    """A source-bucket block must NOT spend a global token (no partial debit)."""
    # Global generous, one source tight.
    limiter = RateLimiter(rate=1.0, burst=1.0, global_rate=100.0, global_burst=100.0)
    t0 = 1_700_000_000.0
    assert limiter.acquire("adsb", t0) is True
    # adsb is now empty -> denied; this must not have consumed a global token.
    assert limiter.acquire("adsb", t0) is False
    # Global still has plenty for other sources (would be short if it had been debited).
    assert all(limiter.acquire(f"src{i}", t0) for i in range(50))


def test_limiter_no_partial_debit_when_global_blocks() -> None:
    """A global block must NOT spend the source token (source recovers when global does)."""
    limiter = RateLimiter(rate=100.0, burst=100.0, global_rate=1.0, global_burst=1.0)
    t0 = 1_700_000_000.0
    assert limiter.acquire("adsb", t0) is True  # spends the only global token
    assert limiter.acquire("ais", t0) is False  # blocked by global
    # 1s later the global refills one token; ais (never debited) gets through.
    assert limiter.acquire("ais", t0 + 1.0) is True


def test_limiter_allow_matches_acquire_without_consuming() -> None:
    """``allow`` predicts ``acquire`` and does not spend tokens."""
    limiter = RateLimiter(rate=1.0, burst=1.0)
    t0 = 1_700_000_000.0
    assert limiter.allow("adsb", t0) is True
    assert limiter.allow("adsb", t0) is True  # peeks don't drain
    assert limiter.acquire("adsb", t0) is True
    assert limiter.allow("adsb", t0) is False


def test_limiter_global_defaults_to_per_source() -> None:
    """Unset global_* mirrors the per-source limits."""
    limiter = RateLimiter(rate=1.0, burst=4.0)
    t0 = 1_700_000_000.0
    # Single source can burst up to 4 (global also 4, so not the binding constraint).
    assert sum(limiter.acquire("adsb", t0) for _ in range(6)) == 4
