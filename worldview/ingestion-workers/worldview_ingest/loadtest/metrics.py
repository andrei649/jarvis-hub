"""Pure latency statistics + SLO verdict for the load-test rig (ticket H19.1.6).

No I/O, no clock: callers record measured latency *samples* (seconds), then ask for
percentiles and an SLO verdict. The percentile method is the "linear interpolation
between closest ranks" definition (a.k.a. NumPy's default / inclusive method), which
is fully deterministic and hand-computable — the tests pin known vectors to known
percentiles.

Percentile definition (inclusive, linear interpolation)
-------------------------------------------------------
For ``n`` sorted samples and percentile ``p`` in [0, 100], the rank is
``r = p/100 * (n - 1)`` (a 0-based fractional index). With ``lo = floor(r)`` and
``hi = ceil(r)``::

    value = sorted[lo] + (r - lo) * (sorted[hi] - sorted[lo])

So p50 of ``[1, 2, 3, 4]`` is rank 1.5 -> ``2 + 0.5*(3-2) = 2.5`` (the median), and
p0/p100 are the min/max. Single-sample and all-equal vectors return that value for
every percentile; an empty sample set has no statistics (``Stats.empty``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor


@dataclass
class LatencyRecorder:
    """Accumulates latency samples (seconds) for later statistics.

    Mutable on purpose — the async probe loop records into a shared recorder. The
    statistics computation itself (:meth:`stats`, :func:`percentile`) is pure over the
    recorded samples.
    """

    samples: list[float] = field(default_factory=list)

    def record(self, latency_s: float) -> None:
        """Record one measured query latency (seconds). Negative values are rejected."""
        if latency_s < 0:
            raise ValueError(f"latency must be >= 0, got {latency_s}")
        self.samples.append(float(latency_s))

    def __len__(self) -> int:
        return len(self.samples)

    def stats(self) -> Stats:
        """Compute the summary statistics over the recorded samples."""
        return Stats.from_samples(self.samples)


def percentile(sorted_samples: list[float], p: float) -> float:
    """The ``p``-th percentile (0..100) of an ALREADY-SORTED non-empty sample list.

    Uses inclusive linear interpolation between closest ranks (see module docstring).
    Raises on an empty list or an out-of-range ``p``.
    """
    if not sorted_samples:
        raise ValueError("percentile of empty sample set is undefined")
    if not 0.0 <= p <= 100.0:
        raise ValueError(f"percentile p must be in [0, 100], got {p}")
    n = len(sorted_samples)
    if n == 1:
        return sorted_samples[0]
    rank = (p / 100.0) * (n - 1)
    lo = floor(rank)
    hi = ceil(rank)
    if lo == hi:
        return sorted_samples[lo]
    frac = rank - lo
    return sorted_samples[lo] + frac * (sorted_samples[hi] - sorted_samples[lo])


@dataclass(frozen=True)
class Stats:
    """Summary latency statistics (seconds). All fields are ``None`` when ``count == 0``."""

    count: int
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None
    max: float | None = None
    mean: float | None = None

    @classmethod
    def empty(cls) -> Stats:
        """The no-samples sentinel: ``count == 0`` and every statistic ``None``."""
        return cls(count=0)

    @classmethod
    def from_samples(cls, samples: list[float]) -> Stats:
        """Compute statistics from raw (unsorted) samples; empty -> :meth:`empty`."""
        if not samples:
            return cls.empty()
        ordered = sorted(samples)
        n = len(ordered)
        return cls(
            count=n,
            p50=percentile(ordered, 50.0),
            p95=percentile(ordered, 95.0),
            p99=percentile(ordered, 99.0),
            max=ordered[-1],
            mean=sum(ordered) / n,
        )

    def to_dict(self) -> dict[str, float | int | None]:
        """Plain-dict form for the report / logging."""
        return {
            "count": self.count,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "max": self.max,
            "mean": self.mean,
        }


@dataclass(frozen=True)
class SloBreach:
    """A single SLO threshold breach: ``metric`` was ``value`` against ``threshold``."""

    metric: str
    value: float
    threshold: float

    def to_dict(self) -> dict[str, float | str]:
        return {"metric": self.metric, "value": self.value, "threshold": self.threshold}


@dataclass(frozen=True)
class SloResult:
    """The SLO verdict: ``passed`` plus the list of any :class:`SloBreach`es."""

    passed: bool
    breaches: list[SloBreach]

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "breaches": [b.to_dict() for b in self.breaches]}


def slo_check(stats: Stats, thresholds: dict[str, float]) -> SloResult:
    """Check ``stats`` against per-percentile ``thresholds`` (e.g. ``{"p95": 0.5}``).

    ``thresholds`` maps a :class:`Stats` field name (``p50``/``p95``/``p99``/``max``/
    ``mean``) to its maximum allowed value (seconds). A metric BREACHES when its value
    is strictly greater than the threshold (``<`` is the SLO, so ``==`` passes).

    With no samples (``stats.count == 0``) there is nothing to measure, so every
    configured threshold is treated as a breach with a ``value`` of ``inf`` — a load
    test that recorded zero latencies has NOT met its SLO. An unknown threshold key
    raises, so a typo can't silently pass.
    """
    breaches: list[SloBreach] = []
    valid = {"p50", "p95", "p99", "max", "mean"}
    for metric, threshold in thresholds.items():
        if metric not in valid:
            raise ValueError(f"unknown SLO metric {metric!r}; valid: {sorted(valid)}")
        value = getattr(stats, metric) if stats.count > 0 else None
        observed = float("inf") if value is None else float(value)
        if observed > threshold:
            breaches.append(SloBreach(metric=metric, value=observed, threshold=threshold))
    return SloResult(passed=not breaches, breaches=breaches)
