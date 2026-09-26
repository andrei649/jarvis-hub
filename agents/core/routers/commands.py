"""Read-only discovery of the commands the current chat principal may use."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from agents.core.app_state import get_orch
from agents.core.commands import CommandRegistry
from agents.core.routers._deps import _web, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["commands"])


class CommandSummary(BaseModel):
    name: str
    command: str
    description: str
    tier: Literal["user", "admin"]
    usage: str


class CommandCatalog(BaseModel):
    ok: bool
    commands: list[CommandSummary]


@router.get("/api/commands", response_model=CommandCatalog, dependencies=[Depends(user_guard)])
async def command_catalog(request: Request):
    """List the live registry using the same owner identity as the chat endpoint.

    No handler is invoked. A hub that has not started its registry reports that
    absence, rather than advertising commands it cannot currently dispatch.
    """
    registry = getattr(get_orch(), "commands", None)
    if not isinstance(registry, CommandRegistry):
        return nocache_json(
            {"ok": False, "reason": "commands_unavailable", "commands": []}, status_code=503,
        )
    principal = _web()._web_principal(request)
    return nocache_json({
        "ok": True,
        "commands": [
            {"name": command.name, "command": f"/{command.name}",
             "description": command.description, "tier": command.tier, "usage": command.usage}
            for command in registry.visible(principal)
        ],
    })


class ContextRef(BaseModel):
    ref: str
    kind: Literal["file", "dir"]


class ContextRefCompletions(BaseModel):
    ok: bool
    types: list[str]
    items: list[ContextRef]


@router.get("/api/context-refs", response_model=ContextRefCompletions, dependencies=[Depends(user_guard)])
async def context_ref_completions(prefix: str = Query("", max_length=1024)):
    """H579 — what can follow ``@file:`` in the composer: in-scope paths for ``prefix``
    (directories end in ``/``), resolved through the file tools' own scope; read-only."""
    import asyncio

    from agents.core import context_refs

    try:
        items = await asyncio.to_thread(context_refs.complete, prefix)
    except Exception:
        return nocache_json({"ok": False, "reason": "no_file_roots", "types": list(context_refs.REFERENCE_TYPES),
                             "items": []}, status_code=503)
    return nocache_json({"ok": True, "types": list(context_refs.REFERENCE_TYPES), "items": items})
