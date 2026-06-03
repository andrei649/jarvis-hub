"""
scheduler.py — H7.11 Learning-loop activation (auto promote/demote).

Wires the existing LearningLoop.suggest_promotions mechanism to the autonomy
decision inbox: a periodic job proposes agent evolution (e.g. activating a bench
agent after N interactions) as a *gated, reversible* task — it lands in the
decision queue (origin="generated", autonomy_level="ask") and only takes effect
once a human approves it. Idempotent: won't re-propose a bench agent that already
has an open proposal.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("jarvis.learning.scheduler")

PROMOTION_KIND = "agent_promotion"


def propose_promotions(learning, queue, active_ids: list[str]) -> list[dict]:
    """Run suggest_promotions and enqueue gated proposals for new candidates.

    Returns the list of enqueued proposals ({task_id, bench_agent, ...}).
    """
    if learning is None or queue is None:
        return []
    try:
        suggestions = learning.suggest_promotions(active_ids=list(active_ids or []))
    except Exception:
        logger.warning("suggest_promotions failed", exc_info=True)
        return []

    # Dedup against bench agents that already have an open (proposed) promotion.
    open_for: set[str] = set()
    try:
        for t in queue.list(status="proposed"):
            if getattr(t, "kind", "") == PROMOTION_KIND:
                open_for.add((t.payload or {}).get("bench_agent"))
    except Exception:
        logger.debug("could not read open proposals", exc_info=True)

    enqueued = []
    for s in suggestions:
        bench = s.get("bench_agent")
        if not bench or bench in open_for:
            continue
        try:
            task_id = queue.enqueue(
                agent=bench,
                kind=PROMOTION_KIND,
                title=f"Activează agentul '{bench}'",
                payload={
                    "bench_agent": bench,
                    "source_agent": s.get("source_agent"),
                    "rationale": s.get("reason", ""),
                    "expected": f"Agentul '{bench}' devine activ (reversibil).",
                    "count": s.get("count"),
                    "threshold": s.get("threshold"),
                },
                risk_tier=2,
                autonomy_level="ask",
                origin="generated",
            )
            enqueued.append({"task_id": task_id, **s})
            open_for.add(bench)
        except Exception:
            logger.warning("failed to enqueue promotion for %r", bench, exc_info=True)
    if enqueued:
        logger.info("Learning loop proposed %d promotion(s) to the decision inbox", len(enqueued))
    return enqueued
