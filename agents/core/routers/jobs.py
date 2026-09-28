"""Owner-scheduled jobs — the HTTP surface (Hermes absorption, wave 2).

Every route is admin-guarded: arming autonomous work is the owner's decision, and the same
routes serve the HUD, the `nerva jobs` verbs and the chat commands. The runner lives on the
orchestrator (`orch.jobs`); a hub without one answers 503 honestly.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

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
    # H687 — a creation-time choice, never stored: true fires once now whatever the
    # schedule, false never does; absent leaves it to first_run_decision.
    first_run: StrictBool | None = None
    # H378 — the owner's clearance for a model pin a selection guard asks about; never stored.
    confirm_expensive: StrictBool = False
    acknowledge_training: StrictBool = False


class JobEditBody(BaseModel):
    """Owner-authored job configuration; run outcomes stay internal."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=80)
    schedule_text: str | None = Field(default=None, max_length=200)
    action: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    confirm_expensive: StrictBool = False
    acknowledge_training: StrictBool = False


class JobPauseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


def _runner():
    orch = get_orch()
    return getattr(orch, "jobs", None) if orch is not None else None


def _job_view(runner, job):
    result = job.as_dict()
    if 'media_ids' in job.action:
        result['media_delivery'] = runner.media.public(job.id)
    return result


def _refused(reason: str) -> JSONResponse:
    """422 in the routers' agreed shape (`error`), plus the list form the first callers read."""
    return JSONResponse({"error": reason, "errors": [reason]}, status_code=422)


async def _guard_pin(options: Any, body, before: Any = None) -> JSONResponse | None:
    """H378 — a job's model pin passes the model-selection guards, unless it is the pin the
    job already has. The response to send instead (409 / 503), or None to go on."""
    import asyncio

    from agents.core.llm import selection_guards as sg

    choices = sg.choices_from_job(options)
    if not choices or choices == sg.choices_from_job(before):
        return None
    try:
        findings = sg.enforce(choices, confirm_expensive=body.confirm_expensive,
                              acknowledge_training=body.acknowledge_training)
    except sg.SelectionRefused as refused:
        return JSONResponse(refused.payload(), status_code=409)
    orch = get_orch()
    try:
        await asyncio.to_thread(sg.record, findings, "job", getattr(orch, "audit", None) if orch else None)
    except sg.ConsentNotRecorded as exc:
        return JSONResponse({"error": "consent_not_recorded", "detail": str(exc)}, status_code=503)
    return None


def _unavailable() -> JSONResponse:
    return JSONResponse({"error": "owner jobs are not available on this hub"}, status_code=503)


@router.get("/api/jobs", dependencies=[Depends(admin_guard)])
async def jobs_list():
    runner = _runner()
    if runner is None:
        return _unavailable()
    requests = [receipt for row in runner.store.dispatch.outstanding()
                if (receipt := runner.store.dispatch.get(row["id"])) is not None]
    return nocache_json({"jobs": [_job_view(runner, job) for job in runner.store.list()], "scheduler": runner.snapshot(),
                         "requests": requests})


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
        guarded = await _guard_pin(body.options, body)
        if guarded is not None:
            return guarded
        job, first_run, confirmation = runner.arm(name=name, schedule_text=schedule_text, action=action,
                                                  blueprint=body.blueprint, options=body.options,
                                                  first_run=body.first_run)
    except ValueError as exc:
        return _refused(str(exc))
    # H687 — the first-run receipt (queued now) or null when the job waits for its cadence.
    return nocache_json({"ok": True, "job": _job_view(runner, job), "first_run": first_run,
                         "confirmation": confirmation}, status_code=201)


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
    return nocache_json({"job": _job_view(runner, job), "runs": [run.as_dict() for run in runner.store.runs(job_id)]})


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
    if body.options is not None:
        current = runner.store.get(job_id)
        guarded = await _guard_pin(body.options, body, getattr(current, "options", None))
        if guarded is not None:
            return guarded
    try:
        job = runner.edit(
            job_id, name=body.name, schedule_text=body.schedule_text, action=body.action, options=body.options
        )
    except KeyError:
        return JSONResponse({"error": "no such job"}, status_code=404)
    except ValueError as exc:
        return _refused(str(exc))
    return nocache_json({"ok": True, "job": _job_view(runner, job)})


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
    return nocache_json({"ok": True, "job": _job_view(runner, job)})


@router.post("/api/jobs/{job_id}/resume", dependencies=[Depends(admin_guard)])
async def jobs_resume(job_id: str):
    runner = _runner()
    if runner is None:
        return _unavailable()
    try:
        job = runner.resume(job_id)
    except KeyError:
        return JSONResponse({"error": "no such job"}, status_code=404)
    return nocache_json({"ok": True, "job": _job_view(runner, job)})


@router.post("/api/jobs/{job_id}/run", dependencies=[Depends(admin_guard)])
async def jobs_run(job_id: str):
    runner = _runner()
    if runner is None:
        return _unavailable()
    if runner.store.get(job_id) is None:
        return JSONResponse({"error": "no such job"}, status_code=404)
    from agents.core import safe_mode

    if safe_mode.enabled():
        # H275: no owner job runs in safe mode, and a request queued now would run
        # unasked on the next normal boot.
        safe_mode.note("owner_jobs")
        return JSONResponse({"error": safe_mode.REASON,
                             "message": "jobs do not run in safe mode; restart normally first"},
                            status_code=409)
    try:
        receipt = runner.request_run(job_id)
    except KeyError:
        return JSONResponse({"error": "no such job"}, status_code=404)
    except ValueError as exc:
        return _refused(str(exc))
    return nocache_json({"ok": True, "pending": True, "request": receipt}, status_code=202)


@router.get("/api/jobs/{job_id}/requests/{request_id}", dependencies=[Depends(admin_guard)])
async def jobs_request(job_id: str, request_id: str):
    runner = _runner()
    if runner is None:
        return _unavailable()
    receipt = runner.store.dispatch.get(request_id)
    if receipt is None or receipt["job_id"] != job_id:
        return JSONResponse({"error": "no such request"}, status_code=404)
    return nocache_json({"request": receipt})


@router.delete("/api/jobs/{job_id}", dependencies=[Depends(admin_guard)])
async def jobs_delete(job_id: str):
    runner = _runner()
    if runner is None:
        return _unavailable()
    if not runner.delete(job_id):
        return JSONResponse({"error": "no such job"}, status_code=404)
    return nocache_json({"ok": True})
