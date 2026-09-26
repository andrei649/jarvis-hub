"""Distributed-mesh endpoints — extracted from web.py (CLN-3).

One cohesive router for the distributed surface: E2E device sync (`/api/sync/*`,
H12.13), mic satellites + shared-inference hub (`/api/satellites/*`, H12.8),
governed execution nodes (`/api/nodes/*`, H12.17), the governed tool-RPC surface
(`/api/toolrpc/*`, H20.1), and isolated sub-agents (`/api/subagents/*`, H20.6).

Orchestrator-only: every handler reads its subsystem off the live orchestrator
(`orch.e2e_sync` / `orch.satellite_hub` / `orch.node_mesh` / `orch.tool_rpc` /
`orch.subagents`) via `get_orch()`, with no web-module globals.
"""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard, admin_guard
from agents.core.routers._component import require_component

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
    _, s, err = require_component("e2e_sync", "e2e sync unavailable")
    if err is not None:
        return err
    return nocache_json(s.build_push(body.records, kind=body.kind))


class SyncPullBody(BaseModel):
    manifest: dict = Field(default_factory=dict)


@router.post("/api/sync/pull", dependencies=[Depends(user_guard)])
async def sync_pull(body: SyncPullBody):
    """H12.13 — decrypt an inbound E2E manifest from another device."""
    _, s, err = require_component("e2e_sync", "e2e sync unavailable")
    if err is not None:
        return err
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
    _, h, err = require_component("satellite_hub", "satellite hub unavailable")
    if err is not None:
        return err
    return nocache_json({"ok": True, "satellite": h.register(body.satellite_id, body.meta)})


@router.delete("/api/satellites/{satellite_id}", dependencies=[Depends(user_guard)])
async def satellites_unregister(satellite_id: str):
    """H12.8 — remove a satellite from the hub."""
    _, h, err = require_component("satellite_hub", "satellite hub unavailable")
    if err is not None:
        return err
    return nocache_json({"ok": h.unregister(satellite_id)})


class SatelliteDispatchBody(BaseModel):
    payload: str = Field("", max_length=20000)
    kind: str = Field("transcribe", max_length=40)


@router.post("/api/satellites/{satellite_id}/dispatch", dependencies=[Depends(user_guard)])
async def satellites_dispatch(satellite_id: str, body: SatelliteDispatchBody):
    """H12.8 — forward a satellite's request to the shared inference rail."""
    _, h, err = require_component("satellite_hub", "satellite hub unavailable")
    if err is not None:
        return err
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
    _, h, err = require_component("node_mesh", "node mesh unavailable")
    if err is not None:
        return err
    return nocache_json({"ok": True, "node": h.register_node(
        body.node_id, body.capabilities, body.meta)})


@router.delete("/api/nodes/{node_id}", dependencies=[Depends(admin_guard)])
async def nodes_unregister(node_id: str):
    """H12.17 — revoke a node and its capability token (admin)."""
    _, h, err = require_component("node_mesh", "node mesh unavailable")
    if err is not None:
        return err
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
    _, h, err = require_component("node_mesh", "node mesh unavailable")
    if err is not None:
        return err
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
    _, s, err = require_component("tool_rpc", "tool-rpc unavailable")
    if err is not None:
        return err
    result = await s.handle({"tool": body.tool, "args": body.args})
    return nocache_json(result, status_code=200 if result.get("ok") else 422)


class SubAgentSpawnBody(BaseModel):
    task: str = Field(..., max_length=4000)
    agent: str = Field("", max_length=40)
    # Typed hand-off: type/required/enum schema the child's result must satisfy.
    output_schema: dict | None = None
    # H681 — the child's own model, provider and request overrides (max_tokens,
    # temperature, extra_body); none given → autonomy.subagent_model, then the parent's.
    model: str | None = Field(None, max_length=256)
    provider: str | None = Field(None, max_length=40)
    overrides: dict | None = None
    # H378 — a model chosen here passes the selection guards like any other choice.
    confirm_expensive: bool = False
    acknowledge_training: bool = False


class SubAgentBatchTask(BaseModel):
    task: str = Field(..., min_length=1, max_length=4000)
    agent: str = Field("", max_length=40)
    output_schema: dict | None = None
    model: str | None = Field(None, max_length=256)
    provider: str | None = Field(None, max_length=40)
    overrides: dict | None = None


class SubAgentBatchBody(BaseModel):
    tasks: list[SubAgentBatchTask] = Field(..., min_length=1, max_length=16)
    confirm_expensive: bool = False
    acknowledge_training: bool = False


def _invalid_selection(manager, items) -> dict | None:
    """The 422 body for the first item whose selection cannot run, checked before any
    guard asks or records anything (None when every item is valid)."""
    resolve = getattr(manager, "_resolve_selection", None)
    if not callable(resolve):
        return None
    for index, item in enumerate(items):
        try:
            resolve(item.model, item.provider, item.overrides)
        except ValueError as exc:
            out = {"ok": False, "reason": "invalid_selection", "detail": str(exc)[:500]}
            if len(items) > 1:
                out["index"] = index
            return out
    return None


async def _guard_subagent_models(items, body):
    """H378 — every model a spawn names passes the selection guards before a child runs:
    409 naming what is not cleared, 503 when a required consent row could not be written,
    None to go on. A spawn that names no model is never asked (the setting it falls back
    to was guarded when it was stored)."""
    from agents.core.llm import selection_guards as sg

    choices, seen = [], set()
    for item in items:
        for choice in sg.choices_from_subagent(item.model, item.provider or ""):
            if (choice.provider, choice.model) not in seen:
                seen.add((choice.provider, choice.model))
                choices.append(choice)
    if not choices:
        return None
    try:
        findings = sg.enforce(choices, confirm_expensive=body.confirm_expensive,
                              acknowledge_training=body.acknowledge_training)
    except sg.SelectionRefused as refused:
        return nocache_json(refused.payload(), status_code=409)
    orch = get_orch()
    try:
        await asyncio.to_thread(sg.record, findings, "sub-agent", getattr(orch, "audit", None) if orch else None)
    except sg.ConsentNotRecorded as exc:
        return nocache_json({"error": "consent_not_recorded", "detail": str(exc)}, status_code=503)
    return None


# Reasons a spawn was refused at the gate (429), as opposed to a child that ran
# and failed / violated its output schema (422 — the request itself was fine).
_SPAWN_GATE_REASONS = frozenset({
    "concurrency_cap", "spawn_budget_exhausted", "recursion_depth_cap",
})


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
    _, m, err = require_component("subagents", "sub-agents unavailable")
    if err is not None:
        return err
    invalid = _invalid_selection(m, [body])
    if invalid is not None:
        return nocache_json(invalid, status_code=422)
    guarded = await _guard_subagent_models([body], body)
    if guarded is not None:
        return guarded
    result = await m.spawn(body.task, agent=body.agent, output_schema=body.output_schema,
                           model=body.model, provider=body.provider, overrides=body.overrides)
    if result.get("ok"):
        status = 200
    elif result.get("reason") in _SPAWN_GATE_REASONS:
        status = 429
    else:
        status = 422        # ran and failed / schema violation / invalid schema
    return nocache_json(result, status_code=status)


@router.post("/api/subagents/batch", dependencies=[Depends(user_guard)])
async def subagents_batch(body: SubAgentBatchBody):
    """H681 — run up to 16 isolated sub-agents, within the free slots, each with its own
    optional model / provider / overrides. The answer reports every child and, when all
    of them failed because the provider does not know the model autonomy.subagent_model
    chose, one ``subagent_model_rejected`` notice naming the model, the setting and
    whether a fallback exists."""
    _, m, err = require_component("subagents", "sub-agents unavailable")
    if err is not None:
        return err
    invalid = _invalid_selection(m, body.tasks)
    if invalid is not None:
        return nocache_json(invalid, status_code=422)
    guarded = await _guard_subagent_models(body.tasks, body)
    if guarded is not None:
        return guarded
    result = await m.spawn_batch([t.model_dump(exclude_none=True) for t in body.tasks])
    return nocache_json(result, status_code=200 if "children" in result else 422)


class SubAgentSteerBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


def _steer_status(result: dict) -> int:
    if result.get("ok"):
        return 200
    reason = result.get("reason")
    if reason == "unknown_spawn":
        return 404
    if reason == "not_running":
        return 409
    return 422


@router.post("/api/subagents/{spawn_id}/steer", dependencies=[Depends(user_guard)])
async def subagents_steer(spawn_id: str, body: SubAgentSteerBody):
    """Steer a running sub-agent (company mode). The message is delivered to the
    child's inbox with origin=user; it is guidance, never an approval — a queue
    decision only ever comes from the inbox path (worker.apply_decision)."""
    _, m, err = require_component("subagents", "sub-agents unavailable")
    if err is not None:
        return err
    result = m.steer(spawn_id, body.message, origin="user")
    return nocache_json(result, status_code=_steer_status(result))


@router.post("/api/subagents/{spawn_id}/stop", dependencies=[Depends(user_guard)])
async def subagents_stop(spawn_id: str):
    """Stop (cancel) a running sub-agent. Yields once so a child that unwinds
    immediately reports `stopped` rather than the transient `stopping`."""
    _, m, err = require_component("subagents", "sub-agents unavailable")
    if err is not None:
        return err
    result = m.stop(spawn_id, reason="operator")
    if result.get("ok"):
        await asyncio.sleep(0)
        rec = m.get(spawn_id) or {}
        result["status"] = rec.get("status", result.get("status"))
    return nocache_json(result, status_code=_steer_status(result))
