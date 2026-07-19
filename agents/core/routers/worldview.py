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
