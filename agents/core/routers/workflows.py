"""Workflow pipeline endpoints (H5.6 / H9.1 / H10.7 / H10.11) — extracted from web.py (CLN-3).

Covers the `/api/workflows*` surface: list (built-in + user-defined merged), run,
recent traces, the user-defined CRUD (create/update/delete), the "describe this
step" AI builder, and the hierarchical (manager+crew) runner.

The `_wf_store_instance` singleton + its `_wf_store()` accessor STAY in web.py:
`tests/test_workflow_builder.py` and `tests/test_workflows_autonomy_api.py` rebind
`web._wf_store_instance` directly. Handlers reach the store at REQUEST time via the
local `_wf_store()` below, which resolves `web._wf_store()` through `sys.modules` —
so the rebind is observed and there is no static import edge into web. The
orchestrator is resolved the same way via `get_orch()`.
"""

import logging
import sys

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import error_json, nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["workflows"])


def _wf_store():
    # web owns the lazy singleton (tests rebind web._wf_store_instance); resolve it
    # at request time so the rebind is observed and no static import edge is created.
    return sys.modules.get("agents.web")._wf_store()


class GenerateStepBody(BaseModel):
    description: str = Field(..., max_length=2000)


class WorkflowRunBody(BaseModel):
    pipeline_id: str
    input: str = ""


class WorkflowSaveBody(BaseModel):
    """Body for creating or updating a user-defined workflow."""
    id: str
    name: str = ""
    description: str = ""
    steps: list[dict] = []


@router.get("/api/workflows")
async def list_workflows():
    """List all registered workflow pipelines (H5.6 + H9.1 user-defined)."""
    orch = get_orch()
    builtin: list[dict] = []
    if orch and hasattr(orch, "workflow_registry"):
        builtin = orch.workflow_registry.list()

    # Merge user-defined pipelines from the store.
    user_dicts = _wf_store().list()
    # Build merged list: built-ins first, user-defined after (user overrides builtin by id).
    merged: dict[str, dict] = {w["id"]: w for w in builtin}
    for u in user_dicts:
        merged[u["id"]] = u
    workflows = list(merged.values())
    return nocache_json({"workflows": workflows, "total": len(workflows)})


@router.post("/api/workflows/run", dependencies=[Depends(user_guard)])
async def run_workflow(body: WorkflowRunBody):
    """Execute a named workflow pipeline (H5.6)."""
    orch = get_orch()
    if not orch or not hasattr(orch, "workflow_engine") or not orch.workflow_engine:
        return nocache_json({"ok": False, "error": "workflow engine not initialized"})
    # Look in registry first, then in the user store.
    pipeline = orch.workflow_registry.get(body.pipeline_id)
    if pipeline is None:
        stored = _wf_store().get(body.pipeline_id)
        if stored:
            try:
                from core.workflows.pipeline import Pipeline as _Pipeline
                pipeline = _Pipeline.from_dict(stored)
            except Exception as e:
                return error_json(e, 200, "invalid stored pipeline", extra={"ok": False})
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{body.pipeline_id}' not found")
    try:
        result = await orch.workflow_engine.run(pipeline, initial_input=body.input)
        return nocache_json({"ok": result.get("_ok", True), "result": result})
    except Exception as e:
        return error_json(e, 200, "workflow run failed", extra={"ok": False})


@router.get("/api/workflows/traces")
async def workflow_traces(limit: int = Query(20, ge=1, le=50)):
    """H10.2 — recent workflow runs with per-step trace for the visual overlay."""
    orch = get_orch()
    engine = getattr(orch, "workflow_engine", None) if orch else None
    if engine is None:
        return nocache_json({"runs": []})
    return nocache_json({"runs": engine.recent(limit)})


@router.post("/api/workflows", dependencies=[Depends(admin_guard)])
async def create_workflow(body: WorkflowSaveBody):
    """Create or update a user-defined workflow pipeline (H9.1)."""
    orch = get_orch()
    if not orch:
        return nocache_json({"ok": False, "error": "not initialized"}, status_code=503)
    raw = body.model_dump()
    try:
        saved = _wf_store().save(raw)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning(f"workflow/save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    # Register into live registry so it is immediately runnable.
    try:
        from core.workflows.pipeline import Pipeline as _Pipeline
        orch.workflow_registry.register(_Pipeline.from_dict(saved))
    except Exception:
        pass
    return nocache_json(saved)


@router.put("/api/workflows/{pipeline_id}", dependencies=[Depends(admin_guard)])
async def update_workflow(pipeline_id: str, body: WorkflowSaveBody):
    """Update an existing user-defined workflow pipeline (H9.1)."""
    orch = get_orch()
    if not orch:
        return nocache_json({"ok": False, "error": "not initialized"}, status_code=503)
    raw = body.model_dump()
    raw["id"] = pipeline_id  # id in URL takes precedence
    try:
        saved = _wf_store().save(raw)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning(f"workflow/update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    try:
        from core.workflows.pipeline import Pipeline as _Pipeline
        orch.workflow_registry.register(_Pipeline.from_dict(saved))
    except Exception:
        pass
    return nocache_json(saved)


@router.delete("/api/workflows/{pipeline_id}", dependencies=[Depends(admin_guard)])
async def delete_workflow(pipeline_id: str):
    """Delete a user-defined workflow pipeline (H9.1)."""
    orch = get_orch()
    if not orch:
        return nocache_json({"ok": False, "error": "not initialized"}, status_code=503)
    deleted = _wf_store().delete(pipeline_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Workflow '{pipeline_id}' not found in store")
    # Best-effort removal from live registry (built-ins are intentionally kept).
    try:
        orch.workflow_registry._pipelines.pop(pipeline_id, None)
    except Exception:
        pass
    return nocache_json({"ok": True, "deleted": pipeline_id})


@router.post("/api/workflows/step/generate", dependencies=[Depends(user_guard)])
async def generate_workflow_step(body: GenerateStepBody):
    """H10.7 — 'Describe this step' → a validated workflow-step config.

    Uses the live LLM when available, else a deterministic keyword heuristic.
    """
    from agents.core.workflows.ai_builder import generate_step
    orch = get_orch()
    agents_list = list(orch.agents.keys()) if orch else []
    llm = None
    if orch:
        async def _llm(prompt: str) -> str:
            return await orch.handle_input(prompt, channel="builder")
        llm = _llm
    cfg = await generate_step(body.description, agents_list, llm=llm)
    return nocache_json({"ok": True, "step": cfg})


@router.post("/api/workflows/hierarchical", dependencies=[Depends(user_guard)])
async def workflow_hierarchical(req: Request):
    """H10.11 — run a hierarchical workflow: a manager coordinates a crew."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    goal = (body or {}).get("goal", "")
    crew = (body or {}).get("crew") or []
    if not goal or not crew:
        return JSONResponse({"error": "goal and crew required"}, status_code=400)
    from agents.core.workflows.hierarchical import HierarchicalManager
    mgr = HierarchicalManager(
        orch,
        manager_agent=(body or {}).get("manager", "jarvis"),
        max_retries=int((body or {}).get("max_retries", 1)),
    )
    return nocache_json(await mgr.run(goal, crew))
