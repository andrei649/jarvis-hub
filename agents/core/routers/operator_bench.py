"""Operator benchmark routes — read the S1 result, and know when it went stale.

Two user-guarded reads, and no route that runs the pack:

* ``GET /api/operator/benchmark`` — the stored result, plus whether it still
  describes the current pack.
* ``GET /api/operator/benchmark/pack`` — the questions themselves, as data.

Running the pack is a CLI job (``scripts/operator_bench.py``), not an HTTP one.
A benchmark run is minutes of work whose live half needs a real desktop in front
of a real person; an endpoint that kicked it off would either block for minutes or
lie about having finished. Reading the result is what a HUD needs, and reading is
all this offers.

The stored result carries the pack's fingerprint. When the questions change, the
read reports ``stale: true`` rather than serving a rate for a pack that no longer
exists — a number measured against different questions is not a number for these.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from agents.core.observability.operator_benchmark import load_report
from agents.core.observability.operator_pack import (
    NEGATIVE_CONTROLS,
    TASKS,
    scored_tasks,
)
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["operator"])


@router.get("/api/operator/benchmark", dependencies=[Depends(user_guard)])
async def operator_benchmark():
    """The stored S1 result, or an honest "never run"."""
    report = await asyncio.to_thread(load_report, None, tasks=scored_tasks())
    if report is None:
        return nocache_json({
            "ok": True,
            "recorded": False,
            # Not a zero score. Nobody has measured, which is a different claim
            # from "measured and scored nothing".
            "reason": "the operator benchmark has not been run on this install",
            "how": "python scripts/operator_bench.py",
            "tasks": len(scored_tasks()),
        })
    return nocache_json({"ok": True, "recorded": True, **report})


@router.get("/api/operator/benchmark/pack", dependencies=[Depends(user_guard)])
async def operator_benchmark_pack():
    """The questions, as data — so a rate can be read against what it measured."""
    return nocache_json({
        "ok": True,
        "tasks": [
            {**task.identity(), "negative_control": task.id in NEGATIVE_CONTROLS}
            for task in TASKS
        ],
        "scored": len(scored_tasks()),
        "negative_controls": sorted(NEGATIVE_CONTROLS),
    })
