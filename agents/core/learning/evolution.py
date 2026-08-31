"""
evolution.py — DRA-41: the production caller for H20.4 self-evolution.

`agents/core/self_evolution.py` shipped the mechanism (a TrajectoryStore + a
gated `propose_optimization`) with no seam into the running hub: nothing built a
store from real traffic, nothing enqueued the result, and no scheduler job fired
it. This module is that seam, and it is deliberately the same shape as
`learning/scheduler.py` (the promotion twin): capture from data the hub ALREADY
records, propose into the same decision inbox, never self-apply.

Honesty contract (the reason no executor handler is registered for
`prompt_optimization`):
  * The score is derived from the learning loop's own two signals — `success`
    and `latency`. It is NOT a human rating, and `payload["score_source"]` says
    so verbatim so nobody downstream reads it as one.
  * Approving the task does not hot-swap anything. Agents load their SOUL from
    disk (`agents/core/agent.py`), and `SoulVersionStore` is a version record,
    not the runtime source. The apply step is the owner committing the prompt in
    the existing prompt-VC surface (`POST /api/admin/prompts/{id}/commit`), and
    `payload["expected"]` names exactly that — the same precedent as
    `agent_promotion`, whose apply step is the existing `/learning/promote`.
"""

from __future__ import annotations

import logging

from ..self_evolution import TrajectoryStore, propose_optimization

logger = logging.getLogger("jarvis.learning.evolution")

PROMPT_OPTIMIZATION_KIND = "prompt_optimization"

# A turn that took this long or longer scores at the floor; below it the score
# rises linearly. Coarse on purpose — it ranks demos, it does not grade them.
_LATENCY_CEILING_S = 20.0
_SCORE_FLOOR = 0.3


def _score(record) -> float:
    """Rank a successful turn from the two signals the loop actually records."""
    latency = float(getattr(record, "latency", 0.0) or 0.0)
    return max(_SCORE_FLOOR, 1.0 - min(latency, _LATENCY_CEILING_S) / (2 * _LATENCY_CEILING_S))


def capture_trajectories(learning, agent_id: str, *, last_n: int = 50, cap: int = 500) -> TrajectoryStore:
    """Build a TrajectoryStore from the agent's recent SUCCESSFUL interactions.

    A failed turn is not a demo, so `success=False` rows are skipped entirely
    rather than recorded with a zero score — a demo list is few-shot input, and
    seeding it with known-bad answers would teach the wrong thing.
    """
    store = TrajectoryStore(cap=cap)
    if learning is None or not agent_id:
        return store
    try:
        records = learning.get_agent_records(agent_id, last_n)
    except Exception:
        logger.warning("could not read records for %r", agent_id, exc_info=True)
        return store
    for r in records:
        if not getattr(r, "success", False):
            continue
        store.record(agent_id, getattr(r, "task", ""), getattr(r, "response", ""), _score(r))
    return store


async def propose_prompt_optimizations(
    learning, agents, queue, *, min_trajectories: int = 3, k: int = 3, optimizer=None
) -> list[dict]:
    """Propose one gated prompt optimization per eligible agent.

    Idempotent in the same way as `propose_promotions`: an agent that already has
    an open (`proposed`) optimization is skipped, so the weekly job cannot flood
    the inbox with the same suggestion.
    """
    if learning is None or queue is None or not agents:
        return []

    open_for: set = set()
    try:
        for t in queue.list(status="proposed"):
            if getattr(t, "kind", "") == PROMPT_OPTIMIZATION_KIND:
                open_for.add((t.payload or {}).get("agent"))
    except Exception:
        logger.debug("could not read open proposals", exc_info=True)

    enqueued: list[dict] = []
    for agent_id, agent in list(agents.items()):
        if agent_id in open_for:
            continue
        current_prompt = (getattr(agent, "soul", None) or {}).get("content", "")
        if not current_prompt:
            continue
        store = capture_trajectories(learning, agent_id)
        out = await propose_optimization(
            agent_id, current_prompt, store,
            optimizer=optimizer, min_trajectories=min_trajectories, k=k,
        )
        if not out.get("ok"):
            continue
        try:
            task_id = queue.enqueue(
                agent=agent_id,
                kind=PROMPT_OPTIMIZATION_KIND,
                title=f"Optimizează promptul agentului '{agent_id}'",
                payload={
                    "agent": agent_id,
                    "proposed_prompt": str(out.get("proposed", ""))[:4000],
                    "from_trajectories": out.get("from_trajectories"),
                    "avg_score": out.get("avg_score"),
                    "score_source": "learning-loop success+latency (not a human rating)",
                    "rationale": (
                        f"{out.get('from_trajectories')} interacțiuni reușite ale agentului "
                        f"'{agent_id}' au fost folosite ca demo-uri few-shot."
                    ),
                    "expected": (
                        "Promptul propus se comită ca versiune nouă în prompt VC "
                        f"(POST /api/admin/prompts/{agent_id}/commit); nimic nu se aplică automat."
                    ),
                    "requires_approval": True,
                    "reversible": True,
                },
                risk_tier=2,
                autonomy_level="ask",
                origin="generated",
                # The payload carries verbatim conversation text — it belongs in the
                # digest, not in an interrupt.
                attention_mode="digest",
            )
        except Exception:
            logger.warning("failed to enqueue prompt optimization for %r", agent_id, exc_info=True)
            continue
        enqueued.append({"task_id": task_id, "agent": agent_id,
                         "from_trajectories": out.get("from_trajectories"),
                         "avg_score": out.get("avg_score")})
        open_for.add(agent_id)
    if enqueued:
        logger.info("Proposed %d prompt optimization(s) to the decision inbox", len(enqueued))
    return enqueued
