"""Heartbeat control endpoints — extracted from web.py (CLN-3).

Covers the `/heartbeat/*` surface: status, and per-agent start/stop/run-now of the
scheduled heartbeats. (`GET /api/status` stays in web.py — different concern.)

The orchestrator (which owns `heartbeat_scheduler` + `agents`) is resolved at
request time via `get_orch()` (late binding to `web.orch`), matching the other
extracted routers. Behavior is unchanged — handlers assume a live orchestrator
exactly as the inline versions did.
"""

from fastapi import APIRouter, Depends, HTTPException

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["heartbeat"])


@router.get("/heartbeat/status")
async def heartbeat_status():
    """Return status of all scheduled heartbeats."""
    return nocache_json(get_orch().heartbeat_scheduler.get_status())


@router.post("/heartbeat/{agent_id}/start", dependencies=[Depends(admin_guard)])
async def heartbeat_start(agent_id: str):
    """Start a heartbeat for an agent."""
    orch = get_orch()
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    success = orch.heartbeat_scheduler.start_heartbeat(agent_id, orch)
    if success:
        return nocache_json({"agent_id": agent_id, "status": "started"})
    else:
        raise HTTPException(status_code=400, detail=f"Failed to start heartbeat for '{agent_id}'")


@router.post("/heartbeat/{agent_id}/stop", dependencies=[Depends(admin_guard)])
async def heartbeat_stop(agent_id: str):
    """Stop a heartbeat for an agent."""
    orch = get_orch()
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    success = orch.heartbeat_scheduler.stop_heartbeat(agent_id)
    if success:
        return nocache_json({"agent_id": agent_id, "status": "stopped"})
    else:
        raise HTTPException(status_code=400, detail=f"Failed to stop heartbeat for '{agent_id}'")


@router.post("/heartbeat/{agent_id}/run", dependencies=[Depends(admin_guard)])
async def heartbeat_run(agent_id: str):
    """Run a heartbeat immediately."""
    orch = get_orch()
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    await orch.heartbeat_scheduler.run_now(agent_id, orch)
    return nocache_json({"agent_id": agent_id, "status": "executed"})
