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

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from agents.core import app_state
from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import BackendTimeout, bounded, degraded, nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["memory"])

# The memory store reaches Qdrant/Neo4j. When those are down these reads used to
# hang forever, so the HUD spun with no error — indistinguishable from loading.
_EMPTY_STATS = {
    "sessions": {"total": 0, "current": "", "active": 0},
    "vectors": {"stored": 0, "dimension": 0, "backend": ""},
    "knowledge_graph": {"entities": 0, "relations": 0, "last_seed": ""},
    "agent_contexts": {},
}


@router.get("/memory", dependencies=[Depends(user_guard)])
async def memory():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        history = await bounded(
            orch.memory.get_history(orch.session_id, last_n=20),
            what="memory.get_history",
        )
    except BackendTimeout as exc:
        # 503, not an empty 200: "no turns" and "we could not read the turns" are
        # different facts and the HUD must not draw them the same way.
        return degraded({"session": orch.session_id, "turns": []},
                        what=exc.what, reason="timeout", status_code=503)
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
    """Live memory stats for SystemsPanel.

    Every failure path here reports *unavailable* rather than zero. It used to do
    the opposite: an unbounded `get_session_stats()` await hung when the backend
    was down, and the broad `except Exception` around it returned a body of zeros
    that the panel drew as "0 vectors, 0 entities" — a dead store rendered as an
    empty one, with nothing logged.
    """
    orch = get_orch()
    if not orch or not getattr(orch, "memory", None):
        # A genuinely absent orchestrator IS a real zero-state, not a failed read.
        return nocache_json(dict(_EMPTY_STATS))
    try:
        stats = (
            await bounded(orch.memory.get_session_stats(), what="memory.get_session_stats")
            if hasattr(orch.memory, 'get_session_stats')
            else {"sessions": 0, "current_session": "", "vectors": 0, "agent_contexts": []}
        )
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
        # `vectors` is None when the vector backend could not be reached. That is not
        # zero — zero says "nothing is stored" — so it is passed through as null and
        # flagged, and the panel renders it as unknown.
        stored = stats.get("vectors")
        body = {
            "sessions": {"total": stats.get("sessions", 0), "current": stats.get("current_session", ""), "active": stats.get("active", stats.get("sessions", 0))},
            "vectors": {
                "stored": stored,
                "dimension": 768 if (stored or 0) > 0 else 0,
                "backend": "in-memory" if (stored or 0) > 0 else "",
                "available": stored is not None,
            },
            "knowledge_graph": {"entities": kg_entities, "relations": kg_relations, "last_seed": kg_last},
            "agent_contexts": contexts,
        }
        if stored is None:
            body["degraded"] = {"source": "vector-store", "reason": "unreachable"}
        return nocache_json(body)
    except BackendTimeout as exc:
        return degraded(dict(_EMPTY_STATS), what=exc.what, reason="timeout")
    except Exception:
        logger.exception("memory stats read failed")
        return degraded(dict(_EMPTY_STATS), what="memory", reason="read-failed")


@router.get("/memory/{agent_id}", dependencies=[Depends(user_guard)])
async def get_agent_memory(agent_id: str):
    """Return per-agent memory context."""
    orch = get_orch()
    # Its sibling routes guard this; this one did not, so a request that arrived
    # before boot finished raised AttributeError on `None.agents` and returned 500.
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    try:
        ctx = await bounded(orch.memory.get_agent_context(agent_id),
                            what="memory.get_agent_context")
    except BackendTimeout as exc:
        return degraded({"agent_id": agent_id, "context_keys": [], "context": {},
                         "last_updated": None},
                        what=exc.what, reason="timeout", status_code=503)
    return nocache_json({
        "agent_id": agent_id,
        "context_keys": list(ctx.keys()) if ctx else [],
        "context": ctx or {},
        "last_updated": ctx.get("_updated") if ctx else None,
    })
