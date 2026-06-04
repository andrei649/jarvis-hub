"""
Weekly digest generator — summarises user profile and recent activity.
Produces a structured digest dict; delivery (Telegram/email) is handled by channels.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


async def generate_digest(store, checkpoint=None) -> dict:
    """
    Build a weekly digest from MemoryStore facts and optional checkpoint stats.
    Returns a dict suitable for rendering or delivery via a channel.
    """
    digest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": "weekly",
        "profile_summary": {},
        "activity_summary": {},
        "highlights": [],
    }

    try:
        all_memory = await store.get_all()
        for category, entries in all_memory.items():
            digest["profile_summary"][category] = [
                {"key": e["key"], "value": e["value"]} for e in entries[:5]
            ]
    except Exception:
        logger.warning("Digest: failed to read memory store", exc_info=True)

    if checkpoint is not None:
        try:
            stats = await checkpoint.get_agent_stats() if hasattr(checkpoint, "get_agent_stats") else {}
            if stats:
                total_interactions = sum(v.get("interactions", 0) for v in stats.values())
                top_agents = sorted(stats.items(), key=lambda x: x[1].get("interactions", 0), reverse=True)[:3]
                digest["activity_summary"] = {
                    "total_interactions": total_interactions,
                    "top_agents": [{"name": n, "interactions": d.get("interactions", 0)} for n, d in top_agents],
                }
        except Exception:
            logger.warning("Digest: failed to read checkpoint stats", exc_info=True)

    # Build highlights
    facts = digest["profile_summary"].get("fact", [])
    if facts:
        digest["highlights"].append(f"Profile has {len(facts)} known facts about you.")
    prefs = digest["profile_summary"].get("preference", [])
    if prefs:
        digest["highlights"].append(f"{len(prefs)} preferences recorded.")

    return digest
