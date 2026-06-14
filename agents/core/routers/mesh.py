"""Distributed-mesh endpoints — extracted from web.py (CLN-3).

One cohesive router for the distributed surface: E2E device sync (`/api/sync/*`,
H12.13), mic satellites + shared-inference hub (`/api/satellites/*`, H12.8),
governed execution nodes (`/api/nodes/*`, H12.17), the governed tool-RPC surface
(`/api/toolrpc/*`, H20.1), and isolated sub-agents (`/api/subagents/*`, H20.6).

Orchestrator-only: every handler reads its subsystem off the live orchestrator
(`orch.e2e_sync` / `orch.satellite_hub` / `orch.node_mesh` / `orch.tool_rpc` /
`orch.subagents`) via `get_orch()`, with no web-module globals.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard, admin_guard

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["mesh"])


@router.get("/api/sync", dependencies=[Depends(user_guard)])
async def sync_status():
    """H12.13 — E2E device-sync status (opt-in, fail-closed)."""
    orch = get_orch()
    s = getattr(orch, "e2e_sync", None) if orch else None
    if s is None:
        return nocache_json({"enabled": False, "available": False, "backend": "unavailable"})
    return nocache_json(s.status())


class SyncPushBody(BaseModel):
    records: list[dict] = Field(default_factory=list)
    kind: str = Field("memory", max_length=40)


@router.post("/api/sync/push", dependencies=[Depends(user_guard)])
async def sync_push(body: SyncPushBody):
    """H12.13 — encrypt records into an E2E manifest (transport is host-side)."""
    orch = get_orch()
    s = getattr(orch, "e2e_sync", None) if orch else None
    if s is None:
        return JSONResponse({"error": "e2e sync unavailable"}, status_code=503)
    return nocache_json(s.build_push(body.records, kind=body.kind))


class SyncPullBody(BaseModel):
    manifest: dict = Field(default_factory=dict)


@router.post("/api/sync/pull", dependencies=[Depends(user_guard)])
async def sync_pull(body: SyncPullBody):
    """H12.13 — decrypt an inbound E2E manifest from another device."""
    orch = get_orch()
    s = getattr(orch, "e2e_sync", None) if orch else None
    if s is None:
        return JSONResponse({"error": "e2e sync unavailable"}, status_code=503)
    return nocache_json({"records": s.apply_pull(body.manifest)})


class SatelliteRegisterBody(BaseModel):
    satellite_id: str = Field(..., max_length=80)
    meta: dict = Field(default_factory=dict)


@router.get("/api/satellites", dependencies=[Depends(user_guard)])
async def satellites_list():
    """H12.8 — registered mic satellites + shared-inference stats."""
    orch = get_orch()
    h = getattr(orch, "satellite_hub", None) if orch else None
    if h is None:
        return nocache_json({"satellites": [], "stats": {}})
    return nocache_json({"satellites": h.list(), "stats": h.stats()})


@router.post("/api/satellites/register", dependencies=[Depends(user_guard)])
async def satellites_register(body: SatelliteRegisterBody):
    """H12.8 — register a mic satellite with the shared-GPU hub."""
    orch = get_orch()
    h = getattr(orch, "satellite_hub", None) if orch else None
    if h is None:
        return JSONResponse({"error": "satellite hub unavailable"}, status_code=503)
    return nocache_json({"ok": True, "satellite": h.register(body.satellite_id, body.meta)})


@router.delete("/api/satellites/{satellite_id}", dependencies=[Depends(user_guard)])
async def satellites_unregister(satellite_id: str):
    """H12.8 — remove a satellite from the hub."""
    orch = get_orch()
    h = getattr(orch, "satellite_hub", None) if orch else None
    if h is None:
        return JSONResponse({"error": "satellite hub unavailable"}, status_code=503)
    return nocache_json({"ok": h.unregister(satellite_id)})


class SatelliteDispatchBody(BaseModel):
    payload: str = Field("", max_length=20000)
    kind: str = Field("transcribe", max_length=40)


@router.post("/api/satellites/{satellite_id}/dispatch", dependencies=[Depends(user_guard)])
async def satellites_dispatch(satellite_id: str, body: SatelliteDispatchBody):
    """H12.8 — forward a satellite's request to the shared inference rail."""
    orch = get_orch()
    h = getattr(orch, "satellite_hub", None) if orch else None
    if h is None:
        return JSONResponse({"error": "satellite hub unavailable"}, status_code=503)
    result = await h.dispatch(satellite_id, body.payload, kind=body.kind)
    return nocache_json(result, status_code=200 if result.get("ok") else 404)


class NodeRegisterBody(BaseModel):
    node_id: str = Field(..., max_length=80)
    capabilities: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


@router.get("/api/nodes", dependencies=[Depends(user_guard)])
async def nodes_list():
    """H12.17 — registered governed execution nodes (capabilities only, no tokens)."""
    orch = get_orch()
    h = getattr(orch, "node_mesh", None) if orch else None
    return nocache_json({"nodes": h.nodes() if h is not None else []})


@router.post("/api/nodes/register", dependencies=[Depends(admin_guard)])
async def nodes_register(body: NodeRegisterBody):
    """H12.17 — register an execution node; mints a capability-scoped token (admin)."""
    orch = get_orch()
    h = getattr(orch, "node_mesh", None) if orch else None
    if h is None:
        return JSONResponse({"error": "node mesh unavailable"}, status_code=503)
    return nocache_json({"ok": True, "node": h.register_node(
        body.node_id, body.capabilities, body.meta)})


@router.delete("/api/nodes/{node_id}", dependencies=[Depends(admin_guard)])
async def nodes_unregister(node_id: str):
    """H12.17 — revoke a node and its capability token (admin)."""
    orch = get_orch()
    h = getattr(orch, "node_mesh", None) if orch else None
    if h is None:
        return JSONResponse({"error": "node mesh unavailable"}, status_code=503)
    return nocache_json({"ok": h.revoke(node_id)})


class NodeDispatchBody(BaseModel):
    capability: str = Field(..., max_length=80)
    action: str = Field("", max_length=200)
    payload: dict = Field(default_factory=dict)


@router.post("/api/nodes/{node_id}/dispatch", dependencies=[Depends(user_guard)])
async def nodes_dispatch(node_id: str, body: NodeDispatchBody):
    """H12.17 — dispatch a capability-scoped action to a node (gated + approval).

    Authorized against the node's capability token + kill-switch (H17.3), then
    enqueued ask-tier; the on-device run is deferred to the node client."""
    orch = get_orch()
    h = getattr(orch, "node_mesh", None) if orch else None
    if h is None:
        return JSONResponse({"error": "node mesh unavailable"}, status_code=503)
    result = h.dispatch(node_id, body.capability, body.action, body.payload)
    return nocache_json(result, status_code=200 if result.get("ok") else 422)


class ToolRPCCallBody(BaseModel):
    tool: str = Field(..., max_length=80)
    args: dict = Field(default_factory=dict)


@router.get("/api/toolrpc/tools", dependencies=[Depends(user_guard)])
async def toolrpc_tools():
    """H20.1 — tools the governed RPC surface exposes to sandboxed code."""
    orch = get_orch()
    s = getattr(orch, "tool_rpc", None) if orch else None
    return nocache_json({"tools": s.tools() if s is not None else []})


@router.post("/api/toolrpc/call", dependencies=[Depends(user_guard)])
async def toolrpc_call(body: ToolRPCCallBody):
    """H20.1 — call a tool through the governed RPC surface (allowlist + gating).

    Read-only tools return inline; gated tools return approval_required + a task
    id (they run only after approval). Mirrors what sandboxed script code does."""
    orch = get_orch()
    s = getattr(orch, "tool_rpc", None) if orch else None
    if s is None:
        return JSONResponse({"error": "tool-rpc unavailable"}, status_code=503)
    result = await s.handle({"tool": body.tool, "args": body.args})
    return nocache_json(result, status_code=200 if result.get("ok") else 422)


class SubAgentSpawnBody(BaseModel):
    task: str = Field(..., max_length=4000)
    agent: str = Field("", max_length=40)


@router.get("/api/subagents", dependencies=[Depends(user_guard)])
async def subagents_list():
    """H20.6 — spawned sub-agents + concurrency stats."""
    orch = get_orch()
    m = getattr(orch, "subagents", None) if orch else None
    if m is None:
        return nocache_json({"spawns": [], "stats": {}})
    return nocache_json({"spawns": m.list(), "stats": m.stats()})


@router.post("/api/subagents/spawn", dependencies=[Depends(user_guard)])
async def subagents_spawn(body: SubAgentSpawnBody):
    """H20.6 — spawn an isolated sub-agent (capped; rejected past the cap)."""
    orch = get_orch()
    m = getattr(orch, "subagents", None) if orch else None
    if m is None:
        return JSONResponse({"error": "sub-agents unavailable"}, status_code=503)
    result = await m.spawn(body.task, agent=body.agent)
    return nocache_json(result, status_code=200 if result.get("ok") else 429)
