"""OAuth / Oracle-bridge / trust-indicator endpoints — extracted from web.py (CLN-3).

One router for three small, related governance-edge surfaces:

* `/api/oauth/*` — third-party OAuth connect/callback/refresh for Gmail, Google
  Calendar and Spotify (PKCE + encrypted token at rest live in
  `core.plugins.oauth`).
* `/api/oracle/*` — the Oracle bridge: Claude-session status, sync, and
  conflict detection/resolution (read off `orch.oracle_bridge`).
* `/api/trust/status` — the H12.10 trust indicator (mic state + strict-local).

`OAUTH_SERVICES` + the `core.plugins.oauth` symbols are used only by the OAuth
routes, so they move here verbatim (and `init_from_env()` runs at this module's
import, exactly as it did in web.py's body). The `_trust_status` / `_env_truthy`
helpers were used only by the trust route in web.py (grep-confirmed), so they
move here too; `tests/test_trust_api.py` is repointed to import them from this
router. The Oracle handlers reach state only through `get_orch()`, so no web-owned
singleton remains.
"""

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard

from core.plugins.oauth import (
    init_from_env, get_google_auth_url, get_spotify_auth_url,
    exchange_google_code, exchange_spotify_code,
    refresh_google_token, refresh_spotify_token, load_token,
    verify_state,
)

init_from_env()

OAUTH_SERVICES = {
    "gmail": {"label": "Gmail", "url": lambda: get_google_auth_url("gmail")},
    "calendar": {"label": "Google Calendar", "url": lambda: get_google_auth_url("calendar")},
    "spotify": {"label": "Spotify", "url": get_spotify_auth_url},
}


router = APIRouter(tags=["oauth"])


@router.get("/api/oauth/status")
async def oauth_status():
    result = {}
    for sid, info in OAUTH_SERVICES.items():
        token = load_token(sid if sid != "spotify" else "spotify")
        result[sid] = {
            "connected": token is not None and bool(token.get("access_token")),
            "label": info["label"],
            "auth_url": info["url"]() if not (token and token.get("access_token")) else None,
        }
    return result


class OAuthCodeBody(BaseModel):
    code: str
    state: str = ""


@router.post("/api/oauth/callback")
async def oauth_callback(body: OAuthCodeBody):
    state = body.state
    service_id = verify_state(state)
    if service_id is None:
        return JSONResponse({"ok": False, "error": "Invalid or expired state"}, status_code=400)

    if service_id.startswith("google:"):
        service = service_id.split(":")[1]
        result = await exchange_google_code(body.code, state)
    elif service_id == "spotify":
        service = "spotify"
        result = await exchange_spotify_code(body.code, state)
    else:
        return JSONResponse({"ok": False, "error": f"Unknown service: {service_id}"}, status_code=400)

    if result:
        return {"ok": True, "service": service, "has_refresh": "refresh_token" in result}
    return JSONResponse({"ok": False, "error": "Token exchange failed"}, status_code=400)


@router.get("/api/oauth/auth-url")
async def oauth_auth_url(service: str = ""):
    info = OAUTH_SERVICES.get(service)
    if not info:
        return JSONResponse({"error": f"Unknown service: {service}"}, status_code=404)
    return {"url": info["url"]()}


@router.post("/api/oauth/refresh", dependencies=[Depends(admin_guard)])
async def oauth_refresh(service: str = ""):
    if service == "spotify":
        token = await refresh_spotify_token()
    elif service in ("gmail", "calendar"):
        token = await refresh_google_token()
    else:
        return JSONResponse({"error": f"Unknown service: {service}"}, status_code=404)
    return {"ok": token is not None, "service": service}


# ── Oracle Bridge endpoints ──────────────────────────────────────
# These expose Claude session tracking, conflict detection, and
# OpenCode integration via the Oracle agent.


@router.get("/api/oracle/status")
async def oracle_status():
    orch = get_orch()
    bridge = getattr(orch, "oracle_bridge", None)
    if not bridge:
        return JSONResponse({"ok": False, "error": "Oracle bridge not available"}, status_code=503)
    return nocache_json(bridge.status())


@router.post("/api/oracle/sync", dependencies=[Depends(admin_guard)])
async def oracle_sync():
    orch = get_orch()
    bridge = getattr(orch, "oracle_bridge", None)
    if not bridge:
        return JSONResponse({"ok": False, "error": "Oracle bridge not available"}, status_code=503)
    result = await bridge.sync_now()
    return nocache_json(result)


@router.get("/api/oracle/conflicts")
async def oracle_conflicts():
    orch = get_orch()
    bridge = getattr(orch, "oracle_bridge", None)
    if not bridge:
        return JSONResponse({"ok": False, "error": "Oracle bridge not available"}, status_code=503)
    conflicts = await bridge.check_conflicts()
    return nocache_json({"conflicts": conflicts})


@router.post("/api/oracle/conflicts/resolve", dependencies=[Depends(admin_guard)])
async def oracle_resolve_conflicts():
    orch = get_orch()
    bridge = getattr(orch, "oracle_bridge", None)
    if not bridge:
        return JSONResponse({"ok": False, "error": "Oracle bridge not available"}, status_code=503)
    bridge.conflicts = [c for c in bridge.conflicts if c.resolved]
    return nocache_json({"ok": True})


# ── Trust indicator (H12.10): hardware-mute / strict-local ───────


# O26-P2.1: the boolean convention lives in env_config now. The old private
# name stays importable — tests/test_trust_api.py pins its spellings.
from agents.core.env_config import truthy as _env_truthy  # noqa: E402


def _trust_status() -> dict:
    """Compute the two visible, auditable trust states for the HUD.

    - ``mic``: "off" when the (software/hardware) mic is muted, else "on".
      Driven by ``JARVIS_MIC_MUTED`` so a physical mute switch / kiosk wrapper
      can flip it without touching code (inspired by Voice PE's physical mute).
    - ``strict_local``: True when no cloud backend is reachable AND no agent can
      escape to the cloud — i.e. nothing leaves the machine. Derived from the
      live router (``_cloud_available`` / ``_claude_available``) so the signal
      reflects reality, with an explicit ``JARVIS_STRICT_LOCAL`` override that
      can only *tighten* (never loosen) the guarantee.
    """
    orch = get_orch()
    mic_muted = _env_truthy(os.environ.get("JARVIS_MIC_MUTED"))

    cloud_available = False
    claude_available = False
    router_ = getattr(orch, "llm_router", None) if orch else None
    if router_ is not None:
        cloud_available = bool(getattr(router_, "_cloud_available", False))
        claude_available = bool(getattr(router_, "_claude_available", False))

    # Strict-local when no cloud path exists at all; env flag can force it on.
    # Single unconditional assignment (De Morgan of `not (cloud or claude)`)
    # so the value is provably initialized before use.
    strict_local = (not cloud_available and not claude_available) or _env_truthy(
        os.environ.get("JARVIS_STRICT_LOCAL")
    )

    return {
        "mic": "off" if mic_muted else "on",
        "strict_local": strict_local,
        # Auditable detail: why strict_local is (or isn't) set.
        "cloud_available": cloud_available,
        "claude_available": claude_available,
    }


@router.get("/api/trust/status")
async def trust_status():
    """Visible, auditable trust signal for the HUD: mic state + strict-local."""
    return nocache_json(_trust_status())
