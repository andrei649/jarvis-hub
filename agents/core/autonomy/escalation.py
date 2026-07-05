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
import time
from typing import Optional

from agents.core.automation_contracts import ContractTemplate, contract_denial, predicate

logger = logging.getLogger("jarvis.escalation")

ESCALATION_CONTRACT_KIND = "autonomy.escalation"
_MAX_ESCALATION_MESSAGE_LEN = 4_000
_MAX_ESCALATION_TARGETS = 20


def _escalation_contract_template() -> ContractTemplate:
    def _kind_ok(view, now) -> bool:
        return view.get("kind") == ESCALATION_CONTRACT_KIND

    def _message_len_ok(view, now) -> bool:
        message_len = view.get("message_len")
        return isinstance(message_len, int) and 0 < message_len <= _MAX_ESCALATION_MESSAGE_LEN

    def _target_count_ok(view, now) -> bool:
        target_count = view.get("target_count")
        return isinstance(target_count, int) and 0 <= target_count <= _MAX_ESCALATION_TARGETS

    def _channels_ok(view, now) -> bool:
        channels = view.get("target_channels", ())
        requested = view.get("requested_channels", ())
        all_channels = list(channels or ()) + list(requested or ())
        return all(isinstance(c, str) and 0 < len(c) <= 128 for c in all_channels)

    return ContractTemplate(
        kind=ESCALATION_CONTRACT_KIND,
        constraints=(
            predicate("kind_matches", _kind_ok, reason="wrong_kind"),
            predicate("message_len_bounded", _message_len_ok, reason="invalid_message_length"),
            predicate("target_count_bounded", _target_count_ok, reason="invalid_target_count"),
            predicate("channels_valid", _channels_ok, reason="invalid_channel"),
        ),
        requires_approval=False,
        description="Autonomy escalation broadcasts must be bounded and sent only to resolved governed channels.",
    )


ESCALATION_CONTRACT = _escalation_contract_template()


def _safe_channels(channels: Optional[list]) -> list[str] | None:
    if channels is None:
        return None
    return sorted(str(c)[:128] for c in channels)


def _escalation_contract_denial(message: str, targets: list[str], requested: Optional[list]) -> str | None:
    payload = {
        "kind": ESCALATION_CONTRACT_KIND,
        "target_channels": list(targets),
        "requested_channels": _safe_channels(requested),
        "target_count": len(targets),
        "message_len": len(message or ""),
    }
    try:
        decision = ESCALATION_CONTRACT.evaluate(payload, now=time.time())
    except Exception:
        return "contract_error"
    return contract_denial(decision)


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
        logger.debug("escalation preview skipped", exc_info=True)  # B2: best-effort, but traceable
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
        targets = self.targets(channels)
        denied = _escalation_contract_denial(message, targets, channels) if targets else None
        if denied:
            results = dict.fromkeys(targets, False)
            return {"delivered": [],
                    "failed": targets,
                    "results": results,
                    "denied": f"contract denied: {denied}"}
        for cid in targets:
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
