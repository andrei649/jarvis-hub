"""Secret broker + embeddable chat widget endpoints — extracted from web.py (CLN-3).

Covers two small, orchestrator-backed surfaces:
  * `/api/secrets/broker...` — H15.4 JIT credential injection (admin only; values
    go in but never come back out via the API).
  * `/api/admin/widgets`, `/api/widget...` — H10.1 embeddable chat widget (admin
    issue/list/revoke; public snippet/config/message).

Both surfaces reach state only through the live orchestrator (`orch.secret_broker`
/ `orch.widgets`), so there is no web.py-owned singleton to keep — no unblock is
needed. `orch` is read at request time via `get_orch()`.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from agents.core.routers._deps import admin_guard
from agents.core.routers._component import require_component

from agents.core.web_helpers import nocache_json, error_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["secrets"])


# ── H15.4 Secret broker (JIT credential injection; handles never expose value) ─

@router.post("/api/secrets/broker", dependencies=[Depends(admin_guard)])
async def secret_broker_put(req: Request):
    """Store a secret value (admin). Values go in, never come back out via API."""
    _, broker, err = require_component("secret_broker", "secret broker not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    name, value = (body or {}).get("name"), (body or {}).get("value")
    if not name or value is None:
        return JSONResponse({"error": "name and value required"}, status_code=400)
    broker.put(name, value)
    return nocache_json({"ok": True, "name": name, "reference": broker.reference(name)})


@router.get("/api/secrets/broker", dependencies=[Depends(admin_guard)])
async def secret_broker_list():
    """List secret NAMES only (never values)."""
    orch = get_orch()
    broker = getattr(orch, "secret_broker", None) if orch else None
    if broker is None:
        return nocache_json({"names": []})
    return nocache_json({"names": broker.names()})


@router.delete("/api/secrets/broker/{name}", dependencies=[Depends(admin_guard)])
async def secret_broker_delete(name: str):
    orch = get_orch()
    broker = getattr(orch, "secret_broker", None) if orch else None
    if broker is None or not broker.delete(name):
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "deleted": name})


@router.post("/api/secrets/broker/redact", dependencies=[Depends(admin_guard)])
async def secret_broker_redact(req: Request):
    """Mask any known secret value present in text (defense-in-depth)."""
    _, broker, err = require_component("secret_broker", "secret broker not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    return nocache_json({"redacted": broker.redact((body or {}).get("text", ""))})


# ── H10.1 Embeddable Chat Widget ──────────────────────────────────────────────

@router.post("/api/admin/widgets", dependencies=[Depends(admin_guard)])
async def widgets_issue(req: Request):
    """Issue a widget token with theming config (admin)."""
    _, store, err = require_component("widgets", "widget store not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    return nocache_json({"ok": True, "widget": store.issue(body or {})})


@router.get("/api/admin/widgets", dependencies=[Depends(admin_guard)])
async def widgets_list():
    orch = get_orch()
    store = getattr(orch, "widgets", None) if orch else None
    if store is None:
        return nocache_json({"widgets": []})
    return nocache_json({"widgets": store.list()})


@router.delete("/api/admin/widgets/{token}", dependencies=[Depends(admin_guard)])
async def widgets_revoke(token: str):
    orch = get_orch()
    store = getattr(orch, "widgets", None) if orch else None
    if store is None or not store.revoke(token):
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "revoked": token})


@router.get("/api/widget/{token}")
async def widget_snippet(token: str, request: Request):
    """Public: return the embeddable JS snippet for a widget token."""
    orch = get_orch()
    store = getattr(orch, "widgets", None) if orch else None
    cfg = store.get(token) if store else None
    if cfg is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    from agents.core.widget import render_snippet
    base = str(request.base_url).rstrip("/")
    js = render_snippet(cfg, base_url=base)
    return Response(content=js, media_type="application/javascript")


@router.get("/api/widget/{token}/config")
async def widget_config(token: str):
    orch = get_orch()
    store = getattr(orch, "widgets", None) if orch else None
    cfg = store.get(token) if store else None
    if cfg is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json(cfg)


@router.post("/api/widget/{token}/message")
async def widget_message(token: str, req: Request):
    """Public, token-scoped: route a widget message through the orchestrator."""
    orch = get_orch()
    store = getattr(orch, "widgets", None) if orch else None
    if store is None or store.get(token) is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        body = await req.json()
    except Exception:
        body = {}
    message = (body or {}).get("message", "")
    if not message:
        return JSONResponse({"error": "message required"}, status_code=400)
    # Q10: the embed is a PUBLIC door — route it through the governed gateway
    # (per-channel rate limit, inbound taint + injection flags) instead of
    # calling the orchestrator directly. No `sender=`: the pairing gate fails
    # closed, and an anonymous visitor has no pairing to approve. Falls back to
    # the orchestrator only when no gateway is running (pre-startup/unit).
    try:
        from agents.core.app_state import get_gateway

        gw = get_gateway()
        if gw is not None:
            reply = await gw.route(message, channel="widget")
            if reply is None:
                # Gateway.route swallows handler failures into None; keep the
                # embed's honest envelope instead of rendering "(no reply)".
                return nocache_json({"reply": "", "error": "request failed"})
        else:
            reply = await orch.handle_input(message, channel="widget")
        return nocache_json({"reply": reply})
    except Exception as e:
        return error_json(e, 200, "request failed", extra={"reply": ""})
