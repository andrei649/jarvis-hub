"""Memory HUD endpoints — extracted from web.py (CLN-3).

Covers the four *bare* `/memory*` routes that back the HUD/SystemsPanel:
`GET /memory`, `POST /memory/clear`, `GET /memory/stats`, and
`GET /memory/{agent_id}`. These are distinct from the `/api/memory/*` surface
owned by the `memory_kg` and `data_spaces` routers, and from the
`/api/admin/memory/clear` route owned by the admin router — none of those are
touched here.

Handlers read the live orchestrator at REQUEST time via `get_orch()` (late
binding to `web.orch`) and the `DEV_MODE` flag via `app_state.dev_mode()`,
matching the other extracted routers (CLN-3 unblock B): both resolve through
`sys.modules` so the test suite's `monkeypatch.setattr(web, "orch"/"DEV_MODE",
...)` is still observed and there is no static import edge back into `agents.web`.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from agents.core import app_state
from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["memory"])


@router.get("/memory", dependencies=[Depends(user_guard)])
async def memory():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    history = await orch.memory.get_history(orch.session_id, last_n=20)
    return nocache_json({"session": orch.session_id, "turns": history})


@router.post("/memory/clear", dependencies=[Depends(user_guard)])
async def clear_memory(req: Request):
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not app_state.dev_mode():
        confirm = req.headers.get("x-confirm", "").lower()
        if confirm != "true":
            return JSONResponse({"error": "memory clear requires confirmation — send X-Confirm: true header or set DEV_MODE=1"}, status_code=400)
    await orch.memory.clear(session_id=orch.session_id)
    orch.session_id = await orch.memory.new_session()
    orch.checkpoints.create_session_record(orch.session_id)
    return JSONResponse({"ok": True, "new_session": orch.session_id})


@router.get("/memory/stats")
async def memory_stats():
    """Live memory stats for SystemsPanel."""
    orch = get_orch()
    try:
        if not orch or not hasattr(orch, 'memory') or not orch.memory:
            return nocache_json({"sessions": {"total": 0, "current": "", "active": 0}, "vectors": {"stored": 0, "dimension": 0, "backend": ""}, "knowledge_graph": {"entities": 0, "relations": 0, "last_seed": ""}, "agent_contexts": {}})
        stats = await orch.memory.get_session_stats() if hasattr(orch.memory, 'get_session_stats') else {"sessions": 0, "current_session": "", "vectors": 0, "agent_contexts": []}
        contexts = {}
        if hasattr(orch.memory, 'agent_contexts') and orch.memory.agent_contexts:
            for aid, ctx in orch.memory.agent_contexts.items():
                contexts[aid] = len(ctx) if isinstance(ctx, dict) else (len(ctx) if hasattr(ctx, '__len__') else 0)
        kg_entities = 0
        kg_relations = 0
        kg_last = ""
        if hasattr(orch.memory, 'graph') and orch.memory.graph:
            try:
                g = orch.memory.graph
                kg_entities = len(g.entities) if hasattr(g, 'entities') else 0
                kg_relations = len(g.relations) if hasattr(g, 'relations') else 0
                kg_last = g.last_seed if hasattr(g, 'last_seed') else ""
            except Exception:
                pass
        return nocache_json({
            "sessions": {"total": stats.get("sessions", 0), "current": stats.get("current_session", ""), "active": stats.get("active", stats.get("sessions", 0))},
            "vectors": {"stored": stats.get("vectors", 0), "dimension": 768 if stats.get("vectors", 0) > 0 else 0, "backend": "in-memory" if stats.get("vectors", 0) > 0 else ""},
            "knowledge_graph": {"entities": kg_entities, "relations": kg_relations, "last_seed": kg_last},
            "agent_contexts": contexts,
        })
    except Exception:
        return nocache_json({"sessions": {"total": 0, "current": "", "active": 0}, "vectors": {"stored": 0, "dimension": 0, "backend": ""}, "knowledge_graph": {"entities": 0, "relations": 0, "last_seed": ""}, "agent_contexts": {}})


@router.get("/memory/{agent_id}", dependencies=[Depends(user_guard)])
async def get_agent_memory(agent_id: str):
    """Return per-agent memory context."""
    orch = get_orch()
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    ctx = await orch.memory.get_agent_context(agent_id)
    return nocache_json({
        "agent_id": agent_id,
        "context_keys": list(ctx.keys()) if ctx else [],
        "context": ctx or {},
        "last_updated": ctx.get("_updated") if ctx else None,
    })
