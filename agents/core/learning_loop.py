"""
Weekly learning loop: analyse agent performance and propose promote/demote decisions.
Runs as a background asyncio task. All mutations require human approval via decision inbox.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

LOOP_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly


async def _analyse_and_propose(orchestrator):
    """Read agent interaction counts from checkpoint DB, propose top/bottom performers."""
    try:
        # Read recent stats — use orchestrator.checkpoint if available
        checkpoint = getattr(orchestrator, 'checkpoint', None)
        if checkpoint is None:
            return

        # Propose to decision inbox (non-destructive)
        inbox = getattr(orchestrator, 'decision_inbox', None)
        if inbox is None:
            logger.debug("No decision_inbox on orchestrator — skipping learning loop proposal")
            return

        proposal = {
            "type": "learning_loop_review",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": "Weekly agent performance review. Human approval required before any changes.",
            "proposals": [],  # populated from real stats when checkpoint has data
        }

        # Try to get interaction counts from checkpoint
        try:
            stats = await checkpoint.get_agent_stats() if hasattr(checkpoint, 'get_agent_stats') else {}
        except Exception:
            stats = {}

        if stats:
            sorted_agents = sorted(stats.items(), key=lambda x: x[1].get('interactions', 0), reverse=True)
            top = sorted_agents[:3]
            bottom = sorted_agents[-3:] if len(sorted_agents) > 6 else []
            for name, data in top:
                proposal["proposals"].append({"agent": name, "action": "promote", "reason": f"Top performer: {data.get('interactions', 0)} interactions"})
            for name, data in bottom:
                proposal["proposals"].append({"agent": name, "action": "review", "reason": f"Low activity: {data.get('interactions', 0)} interactions"})

        await inbox.add(proposal)
        logger.info("Learning loop: proposed %d items to decision inbox", len(proposal["proposals"]))

    except Exception:
        logger.warning("Learning loop analysis failed", exc_info=True)


async def run_learning_loop(orchestrator):
    """Background task: run weekly analysis. Exits cleanly on cancellation."""
    logger.info("Learning loop started (interval: 7 days)")
    while True:
        try:
            await asyncio.sleep(LOOP_INTERVAL_SECONDS)
            await _analyse_and_propose(orchestrator)
        except asyncio.CancelledError:
            logger.info("Learning loop cancelled")
            break
        except Exception:
            logger.warning("Learning loop iteration failed — will retry next cycle", exc_info=True)
