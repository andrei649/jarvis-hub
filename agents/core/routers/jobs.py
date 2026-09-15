"""Owner-scheduled jobs — the HTTP surface (Hermes absorption, wave 2).

Every route is admin-guarded: arming autonomous work is the owner's decision, and the same
routes serve the HUD, the `nerva jobs` verbs and the chat commands. The runner lives on the
orchestrator (`orch.jobs`); a hub without one answers 503 honestly.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["jobs"])


class JobCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=80)
    schedule_text: str | None = Field(default=None, max_length=200)
    action: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    blueprint: str | None = Field(default=None, max_length=40)
    params: dict[str, Any] | None = None


class JobEditBody(BaseModel):
    """Owner-authored job configuration; run outcomes stay internal."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=80)
    schedule_text: str | None = Field(default=None, max_length=200)
    action: dict[str, Any] | None = None
    options: dict[str, Any] | None = None


class JobPauseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


def _runner():
    orch = get_orch()
    return getattr(orch, "jobs", None) if orch is not None else None


def _refused(reason: str) -> JSONResponse:
    """422 in the routers' agreed shape (`error`), plus the list form the first callers read."""
    return JSONResponse({"error": reason, "errors": [reason]}, status_code=422)


def _unavailable() -> JSONResponse:
    return JSONResponse({"error": "owner jobs are not available on this hub"}, status_code=503)


@router.get("/api/jobs", dependencies=[Depends(admin_guard)])
async def jobs_list():
    runner = _runner()
    if runner is None:
        return _unavailable()
    return nocache_json({"jobs": [job.as_dict() for job in runner.store.list()], "scheduler": runner.snapshot()})


@router.get("/api/jobs/blueprints", dependencies=[Depends(admin_guard)])
async def jobs_blueprints():
    from agents.core.autonomy.jobs import blueprint_catalog

    return nocache_json({"blueprints": blueprint_catalog()})


@router.post("/api/jobs", dependencies=[Depends(admin_guard)])
async def jobs_create(body: JobCreateBody):
    from agents.core.autonomy.jobs import instantiate_blueprint

    runner = _runner()
    if runner is None:
        return _unavailable()
    try:
        if body.blueprint:
            name, schedule_text, action = instantiate_blueprint(body.blueprint, body.params)
            name = body.name or name
            schedule_text = body.schedule_text or schedule_text
        else:
            if not body.name or not body.schedule_text or body.action is None:
                return _refused("name, schedule_text and action are required (or a blueprint)")
            name, schedule_text, action = body.name, body.schedule_text, body.action
        job = runner.create(name=name, schedule_text=schedule_text, action=action, blueprint=body.blueprint, options=body.options)
    except ValueError as exc:
        return _refused(str(exc))
    return nocache_json({"ok": True, "job": job.as_dict()}, status_code=201)


@router.get("/api/jobs/doctor", dependencies=[Depends(admin_guard)])
async def jobs_doctor():
    runner = _runner()
    return nocache_json(runner.doctor()) if runner else _unavailable()


@router.get("/api/jobs/incidents", dependencies=[Depends(admin_guard)])
async def jobs_incidents():
    runner = _runner()
    if runner is None:
        return _unavailable()
    return nocache_json({"incidents": [{"job_id":j.id, "reason":j.paused_reason,
        "failures":j.consecutive_failures} for j in runner.store.list()
        if j.consecutive_failures >= 3 and j.paused_reason]})


@router.post("/api/jobs/tick", dependencies=[Depends(admin_guard)])
async def jobs_tick():
    runner = _runner()
    if runner is None:
        return _unavailable()
    try:
        return nocache_json({"runs":[r.as_dict() for r in await runner.tick()]})
    except ValueError as exc:
        return JSONResponse({"error":str(exc)}, status_code=409)


class JobNotepadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=4096)


@router.put("/api/jobs/{job_id}/notepad", dependencies=[Depends(admin_guard)])
async def jobs_notepad(job_id: str, body: JobNotepadBody):
    runner = _runner()
    if runner is None:
        return _unavailable()
    try:
        return nocache_json({"ok":True,"job":runner.store.update(job_id, notepad=body.text).as_dict()})
    except KeyError:
        return JSONResponse({"error":"no such job"},status_code=404)


@router.get("/api/jobs/{job_id}", dependencies=[Depends(admin_guard)])
async def jobs_get(job_id: str):
    runner = _runner()
    if runner is None:
        return _unavailable()
    job = runner.store.get(job_id)
    if job is None:
        return JSONResponse({"error": "no such job"}, status_code=404)
    return nocache_json({"job": job.as_dict(), "runs": [run.as_dict() for run in runner.store.runs(job_id)]})


@router.patch("/api/jobs/{job_id}", dependencies=[Depends(admin_guard)])
async def jobs_edit(job_id: str, body: JobEditBody):
    """Change a job's name, schedule or action. Omitted fields keep their value.

    PATCH rather than PUT: a job carries run history and failure counters the owner never
    authored, so a whole-record replace would either drop them or invite a caller to send
    them back stale.
    """
    runner = _runner()
    if runner is None:
        return _unavailable()
    try:
        job = runner.edit(
            job_id, name=body.name, schedule_text=body.schedule_text, action=body.action, options=body.options
        )
    except KeyError:
        return JSONResponse({"error": "no such job"}, status_code=404)
    except ValueError as exc:
        return _refused(str(exc))
    return nocache_json({"ok": True, "job": job.as_dict()})


@router.get("/api/jobs/{job_id}/runs", dependencies=[Depends(admin_guard)])
async def jobs_runs(job_id: str, limit: int = 20):
    runner = _runner()
    if runner is None:
        return _unavailable()
    if runner.store.get(job_id) is None:
        return JSONResponse({"error": "no such job"}, status_code=404)
    return nocache_json({"runs": [run.as_dict() for run in runner.store.runs(job_id, limit=limit)]})


@router.post("/api/jobs/{job_id}/pause", dependencies=[Depends(admin_guard)])
async def jobs_pause(job_id: str, body: JobPauseBody | None = None):
    runner = _runner()
    if runner is None:
        return _unavailable()
    try:
        job = runner.pause(job_id, (body.reason if body and body.reason else "paused by the owner"))
    except KeyError:
        return JSONResponse({"error": "no such job"}, status_code=404)
    return nocache_json({"ok": True, "job": job.as_dict()})


@router.post("/api/jobs/{job_id}/resume", dependencies=[Depends(admin_guard)])
async def jobs_resume(job_id: str):
    runner = _runner()
    if runner is None:
        return _unavailable()
    try:
        job = runner.resume(job_id)
    except KeyError:
        return JSONResponse({"error": "no such job"}, status_code=404)
    return nocache_json({"ok": True, "job": job.as_dict()})


@router.post("/api/jobs/{job_id}/run", dependencies=[Depends(admin_guard)])
async def jobs_run(job_id: str):
    runner = _runner()
    if runner is None:
        return _unavailable()
    if runner.store.get(job_id) is None:
        return JSONResponse({"error": "no such job"}, status_code=404)
    run = await runner.fire(job_id, force=True)
    job = runner.store.get(job_id)
    pending = run.status == "pending"
    return nocache_json({"ok": run.status in {"ok", "pending"}, "pending": pending,
                         "run": run.as_dict(), "job": job.as_dict() if job else None},
                        status_code=202 if pending else 200)


@router.delete("/api/jobs/{job_id}", dependencies=[Depends(admin_guard)])
async def jobs_delete(job_id: str):
    runner = _runner()
    if runner is None:
        return _unavailable()
    if not runner.delete(job_id):
        return JSONResponse({"error": "no such job"}, status_code=404)
    return nocache_json({"ok": True})
