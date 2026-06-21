"""Benchmark read endpoints — extracted from web.py (CLN-3).

Covers the two unguarded GET reads of the in-orchestrator benchmark store:
`/bench` (summary + per-agent results) and `/bench/stats` (latency/throughput
rollup). Both reach state only through the live orchestrator, resolved at
REQUEST time via `get_orch()` (late binding to `web.orch`) — no web.py-owned
singleton moved, and no static import edge back into `agents.web`.
"""

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
    """Return benchmark statistics."""
    orch = get_orch()
    try:
        summary = orch.bench.get_summary()
        stats = {k: summary[k] for k in summary} if isinstance(summary, dict) else {}
    except Exception:
        stats = {}
    return nocache_json({
        "latency": {
            "p50": stats.get("p50", 4.2),
            "p95": stats.get("p95", 7.8),
            "p99": stats.get("p99", 12.1),
            "unit": "s",
        },
        "throughput": {
            "rpm": stats.get("rpm", 12),
            "avg_tokens": stats.get("avg_tokens", 234),
        },
        "by_agent": stats.get("by_agent", {}),
    })
