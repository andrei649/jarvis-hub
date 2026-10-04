"""Owner checkpoint queries through the existing chat command registry.

Metadata previews never grant restore or maintenance authority. The approved
effect executor is a separate integration boundary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex

from .checkpoint_inventory import CheckpointInventory
from .commands import CommandContext, Principal
from .env_config import env_flag
from .file_tools import FileScope, SnapshotStore
from .turn_notices import record_turn_notice

logger = logging.getLogger("jarvis.checkpoint_commands")
_MAINTENANCE = {"prune", "clear", "clear-legacy"}
_MAX_REPLY = 14_000


def _parse(args: str, *, rollback: bool) -> dict:
    tokens = shlex.split(args)
    action = tokens.pop(0).lower() if tokens else ("list" if rollback else "status")
    if rollback and action != "list":
        return {"action": "restore_unavailable"}
    if action not in {"status", "list", *_MAINTENANCE}:
        raise ValueError("invalid action")
    result = {"action": action, "project": None, "limit": 20, "execute": False}
    seen = set()
    while tokens:
        flag = tokens.pop(0)
        if flag in seen:
            raise ValueError("duplicate option")
        seen.add(flag)
        if flag in {"--project", "--limit"}:
            if not tokens or action in {"clear", "clear-legacy"}:
                raise ValueError("invalid query option")
            value = tokens.pop(0)
            if flag == "--limit":
                if action not in {"status", "list"} or not value.isascii() or not value.isdecimal():
                    raise ValueError("invalid limit")
                result["limit"] = int(value)
            else:
                result["project"] = value
        elif flag in {"--dry-run", "--execute", "--force"}:
            if action not in _MAINTENANCE:
                raise ValueError("invalid maintenance option")
            result["execute"] = "--execute" in seen
        else:
            raise ValueError("unknown option")
    if (("--dry-run" in seen and "--execute" in seen)
            or ("--force" in seen and "--execute" not in seen)):
        raise ValueError("conflicting maintenance options")
    CheckpointInventory._arguments(result["project"], result["limit"])
    return result


def _query(principal: Principal, query: dict) -> dict:
    # This function runs off the event loop; do not construct/probe roots for guests.
    CheckpointInventory._authorize(principal)
    from .environments.local_transport import default_roots

    scope = FileScope([*FileScope.from_env().roots, *default_roots()])
    inventory = CheckpointInventory(
        SnapshotStore(), scope,
        terminal_enabled=env_flag("JARVIS_TERMINAL_CHECKPOINTS"),
        file_enabled=env_flag("JARVIS_FILE_TOOLS"),
    )
    kwargs = {"project": query["project"], "limit": query["limit"]}
    if query["action"] in _MAINTENANCE:
        return inventory.maintenance_preview(principal, query["action"], **kwargs)
    return getattr(inventory, query["action"])(principal, **kwargs)


def _notice(code: str, text: str) -> str:
    record_turn_notice(code, text)
    return text


async def checkpoint_command(ctx: CommandContext) -> str:
    if type(ctx.principal) is not Principal or ctx.principal.admin is not True:
        return _notice("checkpoint.refused", "Checkpoint commands require the owner channel.")
    if not isinstance(ctx.args, str) or len(ctx.args) > 2_000:
        return _notice("checkpoint.refused", "Checkpoint command is too long; nothing changed.")
    try:
        query = _parse(ctx.args, rollback=ctx.name == "rollback")
    except ValueError:
        return _notice("checkpoint.refused", "Invalid checkpoint command. Use /checkpoints "
                       "status|list [--project ROOT] [--limit 1..500], or "
                       "prune|clear|clear-legacy --dry-run.")
    if query["action"] == "restore_unavailable" or query["execute"]:
        return _notice("checkpoint.unavailable", "Checkpoint restore/maintenance execution "
                       "is unavailable until its approved executor is connected; nothing changed.")
    try:
        result = await asyncio.to_thread(_query, ctx.principal, query)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    except Exception:
        logger.warning("Checkpoint inventory unavailable", exc_info=True)
        return _notice("checkpoint.unavailable", "Checkpoint inventory unavailable; nothing changed.")
    complete = result.get("ok") is True and not result.get("truncated", False)
    if len(text) > _MAX_REPLY:
        text = json.dumps({"ok": False, "truncated": True, "reason": "response_too_large",
                           "hint": "Use a smaller --limit or --project."})
        complete = False
    code = ("checkpoint.preview" if query["action"] in _MAINTENANCE else "checkpoint.complete")
    return _notice(code if complete else "checkpoint.partial", text)
