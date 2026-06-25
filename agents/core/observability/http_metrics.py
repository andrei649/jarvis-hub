"""AUD-17 — HTTP golden-signals (RED) collector + Prometheus exposition.

Exposes the three RED signals for every HTTP request the app serves — **R**ate
(request counts), **E**rrors (5xx), **D**uration (latency quantiles) — plus an
in-flight gauge, in the Prometheus text exposition format scraped at ``GET
/metrics``. It complements the *business* north-star metrics
(``observability/north_star.py``): those answer "is the assistant useful?", these
answer "is the service healthy?".

Two deliberate design choices:

* **Dependency-free.** We render the Prometheus text format by hand rather than
  pull in ``prometheus_client``. The format is trivial, this keeps the local-first
  install lean, and there is no runtime dependency to break offline. Quantiles
  reuse ``north_star._percentile`` (one percentile implementation in the repo).
* **Route *template* labels, never raw paths.** ``/api/agents/42`` and
  ``/api/agents/99`` both record under ``/api/agents/{id}`` so per-id traffic
  collapses to one series — bounded cardinality, the cardinal sin of /metrics
  done right. Unmatched paths (404s on junk URLs) fold into ``<unmatched>`` so a
  scanner can't explode the series count either.

Thread-safe: a single lock guards the maps, so the scrape handler can render while
request middleware records concurrently.
"""

from __future__ import annotations

import threading
from collections import defaultdict

from agents.core.observability.north_star import _percentile

# Prometheus text exposition content type (the canonical 0.0.4 version string).
PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Quantiles published for the duration summary.
_QUANTILES = (0.5, 0.95, 0.99)

# Cap latency samples kept per (method, route) so memory stays bounded under
# sustained load; the quantiles stay representative of the recent window.
_MAX_SAMPLES = 2048


def _esc(value: str) -> str:
    """Escape a Prometheus label value (backslash, double-quote, newline)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class HTTPMetrics:
    """In-process RED collector. One module-level instance (`HTTP_METRICS`) is
    shared by the request middleware and the scrape endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count: dict[tuple[str, str, int], int] = defaultdict(int)
        self._errors: dict[tuple[str, str], int] = defaultdict(int)
        self._samples: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._dur_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._in_flight = 0

    # ── recording (called from middleware) ──────────────────────────────────

    def inc_in_flight(self) -> None:
        with self._lock:
            self._in_flight += 1

    def dec_in_flight(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def record(self, method: str, route: str, status: int, duration_s: float) -> None:
        method = (method or "GET").upper()
        route = route or "<unmatched>"
        status = int(status)
        key = (method, route)
        with self._lock:
            self._count[(method, route, status)] += 1
            self._dur_sum[key] += duration_s
            samples = self._samples[key]
            samples.append(duration_s)
            if len(samples) > _MAX_SAMPLES:
                del samples[: len(samples) - _MAX_SAMPLES]
            if status >= 500:
                self._errors[key] += 1

    def reset(self) -> None:
        """Drop all series — used by tests for isolation from the shared singleton."""
        with self._lock:
            self._count.clear()
            self._errors.clear()
            self._samples.clear()
            self._dur_sum.clear()
            self._in_flight = 0

    # ── reads (tests / introspection) ────────────────────────────────────────

    def count(self, method: str, route: str) -> int:
        """Total requests recorded for a (method, route), across all statuses."""
        with self._lock:
            return sum(
                v for (m, r, _s), v in self._count.items()
                if m == method.upper() and r == route
            )

    def quantile(self, method: str, route: str, q: float) -> float | None:
        """Latency quantile (seconds) for a (method, route), or None if no samples."""
        with self._lock:
            samples = list(self._samples.get((method.upper(), route), ()))
        return _percentile(samples, q * 100.0)

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    # ── exposition ───────────────────────────────────────────────────────────

    def render(self) -> str:
        """Render the current state as a Prometheus text exposition payload."""
        with self._lock:
            count = dict(self._count)
            errors = dict(self._errors)
            samples = {k: list(v) for k, v in self._samples.items()}
            dur_sum = dict(self._dur_sum)
            in_flight = self._in_flight

        lines: list[str] = []

        lines.append("# HELP jarvis_http_requests_total Total HTTP requests by method, route template, and status.")
        lines.append("# TYPE jarvis_http_requests_total counter")
        for (method, route, status), n in sorted(count.items()):
            lines.append(
                f'jarvis_http_requests_total{{method="{_esc(method)}",'
                f'route="{_esc(route)}",status="{status}"}} {n}'
            )

        lines.append("# HELP jarvis_http_request_duration_seconds HTTP request latency (RED duration) by method and route.")
        lines.append("# TYPE jarvis_http_request_duration_seconds summary")
        for (method, route), vals in sorted(samples.items()):
            labels = f'method="{_esc(method)}",route="{_esc(route)}"'
            for q in _QUANTILES:
                v = _percentile(vals, q * 100.0)
                if v is not None:
                    lines.append(
                        f'jarvis_http_request_duration_seconds{{{labels},quantile="{q}"}} {v:.6f}'
                    )
            lines.append(
                f'jarvis_http_request_duration_seconds_sum{{{labels}}} '
                f'{dur_sum.get((method, route), 0.0):.6f}'
            )
            lines.append(
                f'jarvis_http_request_duration_seconds_count{{{labels}}} {len(vals)}'
            )

        lines.append("# HELP jarvis_http_errors_total HTTP responses with a 5xx status by method and route.")
        lines.append("# TYPE jarvis_http_errors_total counter")
        for (method, route), n in sorted(errors.items()):
            lines.append(
                f'jarvis_http_errors_total{{method="{_esc(method)}",route="{_esc(route)}"}} {n}'
            )

        lines.append("# HELP jarvis_http_requests_in_flight HTTP requests currently being served.")
        lines.append("# TYPE jarvis_http_requests_in_flight gauge")
        lines.append(f"jarvis_http_requests_in_flight {in_flight}")

        return "\n".join(lines) + "\n"


# The one shared collector. Imported by the middleware (record) and ops.py (scrape).
HTTP_METRICS = HTTPMetrics()
