"""Owner Telegram command that requests a human-approved restart card only."""

from __future__ import annotations

import asyncio
from importlib import import_module

from .command_source import InboundCommandSource, source_for_dispatch

_REFUSALS = {
    "restart_unavailable": "Restart request refused: this hub cannot restart itself safely.",
    "original_owner_dm_required": "Restart request refused: use an original /restart message in the owner's Telegram DM.",
    "signed_queue_required": "Restart request refused: the signed approval queue is unavailable.",
    "source_attestation_refused": "Restart request refused: the original Telegram message could not be verified.",
    "recipient_changed": "Restart request refused: the owner's Telegram DM is no longer verified.",
    "restart_intake_unavailable": "Restart request refused: signed intake is unavailable.",
    "approval_queue_unavailable": "Restart request refused: the approval queue is unavailable.",
    "approval_queue_refused": "Restart request refused: the approval queue did not admit the card.",
    "restart_in_progress": "Restart request refused: another restart is pending or running.",
    "request_replayed": "Restart request refused: this Telegram message was already used.",
    "restart_request_seen": "Restart request refused: this Telegram message was already used.",
    "update_in_progress": "Restart request refused: an update or rollback may still be in progress.",
    "restore_in_progress": "Restart request refused: a restore is pending or running.",
    "restore_pending": "Restart request refused: a restore is pending or running.",
    "action_changed": "Restart request refused: another hub action changed during intake.",
    "action_running": "Restart request refused: another hub action is running.",
    "state_unavailable": "Restart request refused: current hub action state is unavailable.",
}
_UNKNOWN = "Restart request refused by current policy; nothing was queued."


async def restart_command(ctx) -> str:
    """Queue one exact owner request; never stop the service or send a notice."""
    if ctx.name != "restart" or ctx.args or ctx.principal.admin is not True:
        return "Usage: /restart (owner Telegram DM; no arguments)."
    if (ctx.principal.channel != "telegram" or ctx.principal.scope != "dm"
            or type(ctx.source) is not InboundCommandSource
            or source_for_dispatch(text="/restart", principal=ctx.principal, orch=ctx.orch) is not ctx.source):
        return "Restart request refused: use an original /restart message in the owner's Telegram DM."
    try:
        hub_restart_apply = import_module("agents.core.hub_restart_apply")
        result = await hub_restart_apply.request_restart(
            ctx.orch, principal=ctx.principal, source=ctx.source)
    except asyncio.CancelledError:
        raise
    except Exception:
        return "Restart request outcome is uncertain. Check pending approvals before retrying."
    if type(result) is not dict:
        return "Restart request outcome is uncertain. Check pending approvals before retrying."
    pending = result.get("pending")
    if (type(pending) is int and 0 < pending <= (1 << 63) - 1
            and "refused" not in result):
        return (f"Restart approval card #{pending} queued. A human must approve the "
                "irreversible hub.restart action; this command did not restart Nerva.")
    reason = result.get("refused")
    return _REFUSALS.get(reason, _UNKNOWN) if type(reason) is str else _UNKNOWN


__all__ = ["restart_command"]
