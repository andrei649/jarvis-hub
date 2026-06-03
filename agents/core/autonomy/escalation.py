"""
escalation.py — H12.11 Extended escalation channels.

Escalations (decision cards, alerts) can be delivered beyond Telegram — to any
configured channel adapter (WhatsApp / Signal / Slack / Discord / email / …) —
but **governed**: only channels on the allowlist receive escalations, delivery is
best-effort, and a plain channel-agnostic message is rendered (vs the
Telegram-markdown card). The channel adapters already exist (ChannelAdapter).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("jarvis.escalation")


def render_escalation(task: dict) -> str:
    """Channel-agnostic plain-text escalation message from a task dict."""
    t = task or {}
    parts = [
        f"🤖 Decision needed #{t.get('id', '?')}: {t.get('title', '(untitled)')}",
        f"Agent: {t.get('agent', '?')} · Action: {t.get('kind', '?')} · Risk tier: {t.get('risk_tier', '?')}",
    ]
    try:
        from .dry_run import preview_task
        parts.append(f"Preview: {preview_task(t)['summary']}")
    except Exception:
        pass
    return "\n".join(parts)


class EscalationRouter:
    """Fans an escalation message out to governed channel adapters."""

    def __init__(self, channels: Optional[dict] = None, allow: Optional[list] = None) -> None:
        self._channels = channels or {}
        # allowlist of channel ids; None → all available channels are allowed.
        self._allow = set(allow) if allow is not None else None

    def set_allow(self, allow: Optional[list]) -> None:
        self._allow = set(allow) if allow is not None else None

    def targets(self, requested: Optional[list] = None) -> list[str]:
        """Resolve which channel ids would actually receive an escalation."""
        available = set(self._channels.keys())
        chosen = available if requested is None else (available & set(requested))
        if self._allow is not None:
            chosen &= self._allow
        return sorted(chosen)

    async def escalate(self, message: str, channels: Optional[list] = None) -> dict:
        """Send *message* to each governed target. Best-effort; never raises."""
        results: dict[str, bool] = {}
        for cid in self.targets(channels):
            adapter = self._channels.get(cid)
            if adapter is None:
                results[cid] = False
                continue
            try:
                ok = await adapter.send(message)
                results[cid] = bool(ok)
            except Exception:
                logger.warning("escalation to %r failed", cid, exc_info=True)
                results[cid] = False
        return {"delivered": [c for c, ok in results.items() if ok],
                "failed": [c for c, ok in results.items() if not ok],
                "results": results}
