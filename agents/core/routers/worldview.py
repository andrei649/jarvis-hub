"""worldview.py — HUD bridge for the standalone WorldView 4D OSINT stack.

The HUD's World tab (`frontend/src/modes_world.tsx`) links out to WorldView's own
UI (`http://localhost:3000`, a separate Next.js app — see `worldview/README.md`:
"a separate stack from the Python JARVIS platform... shares no runtime with
`agents/`"). That link was previously a dead `<a>` with no indication of whether
the backend behind it is actually running. This route gives the HUD a real,
honest connected/not-connected signal to render next to it, reusing the existing
chat-agent `WorldViewPlugin` client rather than adding a second one.
"""

from fastapi import APIRouter

from agents.core.app_state import get_orch
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["observe"])


@router.get("/api/worldview/status")
async def worldview_status():
    """Liveness of the standalone WorldView backend-api, for the HUD World tab.

    Open like the sibling meters (`/api/analytics/locality`, `/api/metrics/capabilities`)
    — non-sensitive (a local dev service's up/down state), and the whole app is
    localhost-only until a token is set. Never fabricates "connected"."""
    orch = get_orch()
    plugin = orch.plugins.get("worldview") if orch else None
    if plugin is None:
        return nocache_json({"connected": False, "api_url": None})
    return nocache_json(await plugin.status())


@router.get("/api/worldview/overview")
async def worldview_overview():
    """Liveness + the flagship read data (recon windows / due alerts) in one call.

    What the World tab actually renders. Same open meter tier as /status. Honest at
    every level: not connected ⇒ ``recon: None`` (never a fabricated pass); connected
    but recon unavailable ⇒ the plugin's own ``{"status": "unavailable"}`` passes
    through so the HUD can say "connected, no recon data" instead of pretending."""
    orch = get_orch()
    plugin = orch.plugins.get("worldview") if orch else None
    if plugin is None:
        return nocache_json({"connected": False, "api_url": None, "recon": None})
    status = await plugin.status()
    if not status.get("connected"):
        return nocache_json({**status, "recon": None})
    return nocache_json({**status, "recon": await plugin.recon_overview()})
