"""Tests for the capture-swarm governance core (ticket H19.5.7).

Pure/deterministic: ``now`` and ``run_id`` are injected. Covers rate-limited skips,
intra-batch dedup, already-active skips, TTL eviction counting, provenance on every
captured snapshot, and the run summary counts.
"""

from __future__ import annotations

from worldview_ingest.capture.cache import SnapshotCache
from worldview_ingest.capture.ratelimit import RateLimiter
from worldview_ingest.capture.swarm import CandidateSignal, RunSummary, run_capture

T0 = 1_700_000_000.0
RUN = "run-xyz"


def _cand(entity_id: str, *, source: str = "adsb", trigger: str = "squawk", **kw) -> CandidateSignal:
    return CandidateSignal(source=source, entity_id=entity_id, trigger=trigger, **kw)


def _limiter(**kw) -> RateLimiter:
    defaults = {"rate": 100.0, "burst": 100.0, "global_rate": 100.0, "global_burst": 100.0}
    defaults.update(kw)
    return RateLimiter(**defaults)


def _cache(**kw) -> SnapshotCache:
    defaults = {"ttl_s": 100.0, "capacity": 100}
    defaults.update(kw)
    return SnapshotCache(**defaults)


def test_captures_all_when_unconstrained() -> None:
    """With generous limits and an empty cache, every distinct candidate is captured."""
    cands = [_cand("a"), _cand("b"), _cand("c")]
    result = run_capture(cands, limiter=_limiter(), cache=_cache(), now=T0, run_id=RUN)
    assert result.summary == RunSummary(captured=3, rate_limited=0, deduped=0, expired_evicted=0)
    assert {s.entity_id for s in result.snapshots} == {"a", "b", "c"}


def test_every_snapshot_carries_provenance() -> None:
    """Each captured snapshot is stamped with provenance incl. run_id + trigger."""
    cands = [_cand("a", trigger="squawk-7700"), _cand("b", trigger="ais-gap")]
    result = run_capture(cands, limiter=_limiter(), cache=_cache(), now=T0, run_id=RUN)
    assert result.snapshots, "expected captures"
    for snap in result.snapshots:
        prov = dict(snap.provenance)
        assert prov["run_id"] == RUN
        assert prov["captured_at"] == T0
        assert prov["source"] == snap.source
        assert prov["trigger"] == snap.trigger
        assert prov.keys() == {"source", "captured_at", "trigger", "run_id"}
    # Triggers carried through distinctly.
    assert {s.trigger for s in result.snapshots} == {"squawk-7700", "ais-gap"}


def test_intra_batch_dedup_first_wins() -> None:
    """Duplicate keys within one batch collapse to one capture; rest counted deduped."""
    cands = [
        _cand("a", trigger="squawk"),
        _cand("a", trigger="squawk"),  # dup key
        _cand("a", trigger="squawk"),  # dup key
    ]
    result = run_capture(cands, limiter=_limiter(), cache=_cache(), now=T0, run_id=RUN)
    assert result.summary.captured == 1
    assert result.summary.deduped == 2
    assert len(result.snapshots) == 1


def test_distinct_triggers_are_not_dedup() -> None:
    """Same source+entity but different triggers are distinct keys (both captured)."""
    cands = [_cand("a", trigger="squawk"), _cand("a", trigger="ais-gap")]
    result = run_capture(cands, limiter=_limiter(), cache=_cache(), now=T0, run_id=RUN)
    assert result.summary.captured == 2
    assert result.summary.deduped == 0


def test_already_active_in_cache_is_skipped() -> None:
    """A candidate already live in the cache is skipped (counted as deduped)."""
    cache = _cache()
    # Pre-seed the cache with "a" via a first run.
    run_capture([_cand("a")], limiter=_limiter(), cache=cache, now=T0, run_id="run-pre")
    # Second run offers "a" again (still active) plus a new "b".
    result = run_capture(
        [_cand("a"), _cand("b")], limiter=_limiter(), cache=cache, now=T0 + 1.0, run_id=RUN
    )
    assert result.summary.captured == 1  # only "b"
    assert result.summary.deduped == 1  # "a" already active
    assert {s.entity_id for s in result.snapshots} == {"b"}


def test_expired_cache_entry_allows_recapture_and_counts_eviction() -> None:
    """Once a cached snapshot's TTL lapses it is evicted (counted) and can be recaptured."""
    cache = _cache(ttl_s=10.0)
    run_capture([_cand("a")], limiter=_limiter(), cache=cache, now=T0, run_id="run-pre")
    # At T0+20 the prior "a" is expired -> evicted, and "a" can be captured again.
    result = run_capture([_cand("a")], limiter=_limiter(), cache=cache, now=T0 + 20.0, run_id=RUN)
    assert result.summary.expired_evicted == 1
    assert result.summary.captured == 1
    assert result.snapshots[0].provenance["run_id"] == RUN


def test_rate_limited_signals_are_skipped_and_counted() -> None:
    """Beyond the burst, candidates are skipped and counted as rate_limited."""
    # Per-source burst of 2 (rate 0 so no refill within the instant), global generous.
    limiter = _limiter(rate=0.0, burst=2.0)
    cands = [_cand(f"e{i}", source="adsb") for i in range(5)]
    result = run_capture(cands, limiter=limiter, cache=_cache(), now=T0, run_id=RUN)
    assert result.summary.captured == 2
    assert result.summary.rate_limited == 3
    assert len(result.snapshots) == 2


def test_global_limit_governs_across_sources() -> None:
    """The global bucket caps total captures even across distinct sources."""
    # Per-source generous; global burst 2 -> only 2 total captured this instant.
    limiter = _limiter(rate=100.0, burst=100.0, global_rate=0.0, global_burst=2.0)
    cands = [_cand("a", source="adsb"), _cand("b", source="ais"), _cand("c", source="ew")]
    result = run_capture(cands, limiter=limiter, cache=_cache(), now=T0, run_id=RUN)
    assert result.summary.captured == 2
    assert result.summary.rate_limited == 1


def test_candidate_ttl_override_used_else_cache_default() -> None:
    """A candidate's own ttl_s is honoured; otherwise the cache default applies."""
    cache = _cache(ttl_s=100.0)
    cands = [_cand("a"), _cand("b", ttl_s=7.0)]
    result = run_capture(cands, limiter=_limiter(), cache=cache, now=T0, run_id=RUN)
    by_id = {s.entity_id: s for s in result.snapshots}
    assert by_id["a"].ttl_s == 100.0
    assert by_id["b"].ttl_s == 7.0


def test_empty_batch_is_noop_summary_zeroed() -> None:
    """An empty candidate list produces an all-zero summary and no snapshots."""
    result = run_capture([], limiter=_limiter(), cache=_cache(), now=T0, run_id=RUN)
    assert result.snapshots == []
    assert result.summary == RunSummary()
    assert result.summary.to_dict() == {
        "captured": 0, "rate_limited": 0, "deduped": 0, "expired_evicted": 0,
    }


def test_summary_counts_are_consistent() -> None:
    """captured + rate_limited + deduped accounts for every distinct decision."""
    cache = _cache(ttl_s=1000.0)
    run_capture([_cand("seed")], limiter=_limiter(), cache=cache, now=T0, run_id="pre")
    limiter = _limiter(rate=0.0, burst=1.0)  # only 1 fresh capture allowed
    cands = [
        _cand("seed"),   # already active -> deduped
        _cand("x"),      # captured (uses the 1 token)
        _cand("x"),      # intra-batch dup -> deduped
        _cand("y"),      # rate limited (token spent)
    ]
    result = run_capture(cands, limiter=limiter, cache=cache, now=T0 + 1.0, run_id=RUN)
    s = result.summary
    assert s.captured == 1
    assert s.deduped == 2
    assert s.rate_limited == 1
