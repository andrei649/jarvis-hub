"""Benchmark read endpoints — extracted from web.py (CLN-3).

Covers the two unguarded GET reads of the in-orchestrator benchmark store:
`/bench` (summary + per-agent results) and `/bench/stats` (latency/throughput
rollup). Both reach state only through the live orchestrator, resolved at
REQUEST time via `get_orch()` (late binding to `web.orch`) — no web.py-owned
singleton moved, and no static import edge back into `agents.web`.
"""

import statistics

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agents.core.app_state import get_orch
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["bench"])


@router.get("/bench")
async def get_bench():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {
        "summary": orch.bench.get_summary(),
        "agents": {
            aid: orch.bench.get_results(aid)
            for aid in list(orch.agents.keys())[:5]
        },
    }


@router.get("/bench/stats")
async def bench_stats():
    """Return real benchmark statistics computed from recorded samples.

    Previously the handler read p50/p95/p99/rpm/avg_tokens/by_agent keys that
    ``get_summary()`` never emits, so it always returned hardcoded fake numbers.
    Everything here is derived from ``orch.bench.samples`` (0 / {} when empty).
    """
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    samples = list(getattr(orch.bench, "samples", []))
    ok = [s for s in samples if s.success and s.latency > 0]
    lats = sorted(s.latency for s in ok)

    def pct(p: float) -> float:
        if not lats:
            return 0.0
        idx = min(int(len(lats) * p), len(lats) - 1)
        return round(lats[idx], 3)

    rpm = 0.0
    if len(samples) >= 2:
        span = samples[-1].timestamp - samples[0].timestamp
        if span > 0:
            rpm = round(len(samples) / (span / 60.0), 2)
    avg_tokens = round(statistics.mean([s.output_length for s in ok]), 1) if ok else 0

    by_agent: dict[str, dict] = {}
    for aid in {s.agent_id for s in samples}:
        a_lat = sorted(s.latency for s in samples
                       if s.agent_id == aid and s.success and s.latency > 0)
        if a_lat:
            by_agent[aid] = {
                "samples": len(a_lat),
                "p50": round(a_lat[min(int(len(a_lat) * 0.5), len(a_lat) - 1)], 3),
                "mean": round(statistics.mean(a_lat), 3),
            }

    return nocache_json({
        "latency": {"p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99), "unit": "s"},
        "throughput": {"rpm": rpm, "avg_tokens": avg_tokens},
        "by_agent": by_agent,
    })
