"""Quickbar routes — resolve one typed line into a plan, and nothing else.

`agents/core/quickbar.py` has shipped a complete, pure command service since 0.64
with no route and no consumer: a parser nobody could reach, which is code that
looks alive and is not. These are the two routes that make it reachable.

Both are **read-only**, and that is the whole design rather than an omission:

* **Resolving is not doing.** The route returns a plan; the HUD then takes the
  ordinary path for whatever the plan names. A quickbar that also *executed*
  would be a second, keyboard-shaped route to every action in the product —
  reached in one keystroke, bypassing the affordances that make the normal paths
  reviewable. The parser's own docstring promises it "never performs the action";
  a route that performed would make that promise false from outside the module.
* **A `summon` plan is not a summon.** It names an agent. Sending the message is
  the chat path, with the governance the chat path has.
* **No history on the server.** `CommandBar` keeps a bounded in-memory recall
  list, and this deliberately does not expose it: a server-side quickbar history
  is a keystroke log of everything the owner typed into a floating bar, and it
  would be the most sensitive store in the product for the least reason. Recall
  belongs in the browser, per viewer.

The parser is offline, synchronous and deterministic, so there is nothing to
thread off the loop and nothing that can fail slowly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["quickbar"])

# The parser caps input at 2000 chars itself. This cap is smaller and exists so a
# request body that large is refused at the edge rather than parsed and trimmed —
# the bar is one line, and anything longer is not a bar line.
MAX_INPUT = 2_000


class QuickbarBody(BaseModel):
    text: str = Field(default="", max_length=MAX_INPUT)


@router.post("/api/quickbar/resolve", dependencies=[Depends(user_guard)])
async def quickbar_resolve(body: QuickbarBody):
    """What one typed line means. Returns a plan; performs nothing.

    A POST rather than a GET because the line is user text that should not land
    in a URL, a proxy log or a browser history — not because anything changes.
    """
    from agents.core.quickbar import parse_command

    return nocache_json({"ok": True, "plan": parse_command(body.text)})


@router.get("/api/quickbar/help", dependencies=[Depends(user_guard)])
async def quickbar_help():
    """The command menu, grounded in the destinations that actually exist.

    Built from the same `_NAV` table the parser resolves against, so the menu
    cannot advertise a destination a plan could never point at.
    """
    from agents.core.quickbar import AGENTS, CENTER_TABS, HUD_MODES, help_commands

    return nocache_json(
        {
            "ok": True,
            "commands": help_commands(),
            "agents": list(AGENTS),
            "modes": list(HUD_MODES),
            "tabs": list(CENTER_TABS),
        }
    )
