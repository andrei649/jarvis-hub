"""Read-only discovery of the commands the current chat principal may use."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
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
