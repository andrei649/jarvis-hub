"""Autonomy / Proactive-Cortex endpoints — extracted from web.py (CLN-3).

Covers the autonomy surface in two address spaces:

* `/api/autonomy/*` — dry-run preview (H12.5), escalation routing (H12.11),
  per-task preview, and the governed outbound-call request (H12.22).
* `/autonomy/*` — the admin proactive-cortex console (H6.x / H12.1): task list,
  queue status, OS-observer state, task submit/decision, morning brief / evening
  retro, global autonomy mode, autonomy-raise suggestions, and the reversible vs
  irreversible approval queue.

Orchestrator-only: each handler reads its subsystem off the live orchestrator
(`orch.autonomy` / `orch.autonomy_queue` / `orch.observer` / `orch.autonomy_prefs`
/ `orch.call_broker`) via `get_orch()`, with no web-module globals. The
`_approval_projection(task)` is the autonomy-local task/rollback projection shared by
the task list and approval endpoint. Leaf imports (`put_category`, `TaskQueueError`,
digest builders, …) stay inline at call time as in the originals.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, UTC
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.core.routers._deps import user_guard, admin_guard
from agents.core.routers._component import require_component

from agents.core.web_helpers import nocache_json, error_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["autonomy"])


class KanbanDispatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board: str = Field("default", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$", max_length=64, strict=True)
    limit: int = Field(4, ge=1, le=16, strict=True)


@router.post("/api/autonomy/kanban/dispatch", dependencies=[Depends(admin_guard)])
async def autonomy_kanban_dispatch(body: KanbanDispatchBody):
    """Ask the governed dispatcher to intake ready cards from one board."""
    from agents.core.commands import Principal

    orch = get_orch()
    coordinator = getattr(orch, "_autonomy", None) if orch is not None else None
    controller = getattr(coordinator, "kanban_dispatcher", None)
    if not callable(controller):
        return nocache_json(
            {"ok": False, "status": "refused", "reason": "governed_worker_unavailable", "queued": []},
            status_code=503,
        )
    result = await controller().request(
        Principal(channel="web", admin=True), board=body.board, limit=body.limit
    )
    return nocache_json(result, status_code=200 if result.get("ok") else 503)


@router.post("/api/autonomy/preview", dependencies=[Depends(user_guard)])
async def autonomy_preview(req: Request):
    """H12.5 — dry-run preview of an action (no execution). Body: a task dict."""
    from agents.core.autonomy.dry_run import preview_task
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not (body or {}).get("kind") and not (body or {}).get("title"):
        return JSONResponse({"error": "task with kind/title required"}, status_code=400)
    return nocache_json(preview_task(body))


@router.get("/api/autonomy/escalation/targets")
async def escalation_targets():
    """H12.11 — which channels would receive an escalation (governed)."""
    from agents.core.autonomy.escalation import EscalationRouter
    orch = get_orch()
    channels = getattr(orch, "channels", {}) if orch else {}
    allow = None
    if orch:
        try:
            allow = (orch._runtime_settings.get("autonomy", {}) or {}).get("escalation_channels")
        except Exception:
            allow = None
    return nocache_json({"targets": EscalationRouter(channels, allow=allow).targets(),
                         "available": sorted(channels.keys())})


@router.post("/api/autonomy/escalate", dependencies=[Depends(admin_guard)])
async def escalation_send(req: Request):
    """H12.11 — deliver an escalation to governed channels (admin)."""
    from agents.core.autonomy.escalation import EscalationRouter, render_escalation
    orch = get_orch()
    channels = getattr(orch, "channels", {}) if orch else {}
    try:
        body = await req.json()
    except Exception:
        body = {}
    message = (body or {}).get("message", "")
    if not message and (body or {}).get("task"):
        message = render_escalation(body["task"])
    if not message:
        return JSONResponse({"error": "message or task required"}, status_code=400)
    allow = None
    if orch:
        try:
            allow = (orch._runtime_settings.get("autonomy", {}) or {}).get("escalation_channels")
        except Exception:
            allow = None
    router_ = EscalationRouter(channels, allow=allow)
    return nocache_json(await router_.escalate(message, (body or {}).get("channels")))


# Admin like every sibling autonomy read (ch05 gap 7): the preview echoes the
# queued task's real payload values (to/body/amount/command/path) via effects[].
@router.get("/api/autonomy/tasks/{task_id}/preview", dependencies=[Depends(admin_guard)])
async def autonomy_task_preview(task_id: int):
    """H12.5 — dry-run preview of a queued task by id."""
    orch, q, err = require_component("autonomy_queue", "autonomy queue not available")
    if err is not None:
        return err
    task = q.get(task_id) if hasattr(q, "get") else None
    if task is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    from agents.core.autonomy.dry_run import preview_task
    preview = preview_task(task)
    if task.kind == "channel.reply" and isinstance(task.payload, dict) and "native_prompt" in task.payload:
        review = getattr(getattr(orch, "channel_replies", None), "review_prompt", None)
        preview["prompt"] = review(task) if callable(review) else {"available": False}
    return nocache_json(preview)


class CallRequestBody(BaseModel):
    to: str = Field(..., max_length=40)
    message: str = Field(..., max_length=2000)
    provider: str = Field("twilio", max_length=20)
    reason: str = Field("", max_length=200)
    agent: Optional[str] = Field(None, max_length=40)


@router.post("/api/autonomy/call", dependencies=[Depends(user_guard)])
async def autonomy_call(body: CallRequestBody):
    """H12.22 — request a governed outbound call (budget-gated + approval).

    Nothing dials here; on approval the worker draws an interrupt-budget slot,
    resolves the telephony credential behind approval, and places the call via an
    injectable client (live Twilio/Telnyx = host seam)."""
    from agents.core.autonomy.call_broker import CallBroker
    orch = get_orch()
    cb = getattr(orch, "call_broker", None) if orch else None
    if cb is None:
        q = getattr(orch, "autonomy_queue", None) if orch else None
        cb = CallBroker(enqueue=q.enqueue if q is not None else None)
    result = cb.request(body.to, body.message, provider=body.provider,
                        reason=body.reason, agent=body.agent)
    return nocache_json(result, status_code=200 if result.get("ok") else 422)


# ── Autonomy / Proactive Cortex (H6.1–H6.3) ─────────────────────


class AutonomyTaskBody(BaseModel):
    agent: str
    kind: str
    title: str
    payload: Optional[dict] = None
    origin: str = "generated"
    approval_deadline_at: Optional[str] = Field(None, max_length=64, strict=True)

    @field_validator("approval_deadline_at")
    @classmethod
    def approval_deadline(cls, value):
        from agents.core.autonomy.queue import normalize_approval_deadline

        stamp = normalize_approval_deadline(value)
        if stamp is not None and datetime.fromisoformat(stamp) <= datetime.now(UTC):
            raise ValueError("approval deadline must be in the future")
        return stamp


class AutonomyDecisionBody(BaseModel):
    action: str            # accept / edit / reject / defer
    payload: Optional[dict] = None
    reason: Optional[str] = Field(None, max_length=280, strict=True)


class AutonomyConsentBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    choice: Literal['session', 'always', 'deny']
    revision: str = Field(pattern=r'^[a-f0-9]{64}$', strict=True)
    reason: Optional[str] = Field(None, max_length=280, strict=True)


class AutonomyGroupRejectBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot: str = Field(min_length=32, max_length=32, strict=True)
    member_ids: list[Annotated[int, Field(strict=True, ge=1)]] = Field(min_length=2, max_length=64)
    reason: Optional[str] = Field(None, max_length=280, strict=True)


def _task_judge(orch):
    return getattr(getattr(orch, "autonomy", None), "approval_judge", None)


def _task_judge_status(orch) -> dict:
    adapter = _task_judge(orch)
    if adapter is None:
        return {}
    status = adapter.judge_status_public()
    # Preserve the original no-judge response shape.
    return {"judge": status} if status.get("configured") else {}


def _recalled_waiting(orch) -> int:
    """H484 — how many tasks `off` returned to the inbox still wait there."""
    count = getattr(getattr(orch, "autonomy_queue", None), "recalled_waiting", None)
    try:
        return int(count()) if callable(count) else 0
    except Exception:
        return 0


#: The statuses in which a task is an approval card (it waits on the owner).
_WAITING_STATUSES = frozenset({"proposed", "blocked", "deferred"})


def _mode_projection(orch, task) -> dict:
    """H484 — the approval mode that applies to a waiting task's agent right now
    (``approval_mode``) and the one it was held under (``asked_under``, when recorded).
    Only a card that still waits carries them."""
    from agents.core.autonomy import mode as approval_mode

    status = getattr(task, "status", None)
    if str(getattr(status, "value", status)) not in _WAITING_STATUSES:
        return {}
    shown = {"approval_mode": approval_mode.describe(orch, getattr(task, "agent", None))}
    # The mode in force when the task was held, and whether the mode itself is why it
    # asks — recorded by the worker at that moment. Absent for a task held another way.
    lookup = getattr(getattr(orch, "autonomy_queue", None), "ask_context", None)
    asked = lookup(task.id) if callable(lookup) else None
    if (isinstance(asked, dict) and asked.get("mode") in approval_mode.MODES
            and asked.get("global") in approval_mode.MODES):
        shown["asked_under"] = {"mode": asked["mode"],
                                "source": "agent" if asked.get("source") == "agent" else "global",
                                "global": asked["global"], "by_mode": asked.get("by_mode") is True}
    if isinstance(asked, dict) and isinstance(asked.get("delegated"), dict):
        # H400 review (M2): a sub-agent asked for this, on behalf of an agent's turn.
        from agents.core.subagents import delegation_label

        delegated = asked["delegated"]
        shown["delegated_by"] = {"spawn_id": delegated.get("spawn_id", ""),
                                 "parent": delegated.get("parent", ""),
                                 "turn": delegated.get("turn", ""),
                                 "label": delegation_label(delegated)}
    return shown


def _consent_projection(queue, task) -> dict:
    """Expose reviewed choices without private producer or owner evidence."""
    from agents.core.autonomy.terminal_consent_categories import terminal_consent_descriptions
    from agents.core.autonomy.consent_types import ConsentOffer

    lookup = getattr(queue, 'pending_consent_offer', None)
    offer = lookup(task.id) if callable(lookup) else None
    if type(offer) is not ConsentOffer:
        return {}
    descriptions = terminal_consent_descriptions()
    if any(category.key not in descriptions for category in offer.categories):
        return {}
    return {'consent_offer': {
        'revision': offer.revision, 'count': len(offer.member_ids),
        'choices': ['session', 'always', 'deny'],
        'categories': [{'description': descriptions[category.key], 'permanent': category.permanent}
                       for category in offer.categories],
    }}


@router.get("/autonomy/tasks", dependencies=[Depends(admin_guard)])
async def autonomy_list(status: str = None, origin: str = None, limit: int = Query(100, ge=1, le=200)):
    """List autonomy tasks, optionally filtered by status/origin."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    tasks = orch.autonomy_queue.list(status=status, origin=origin, limit=limit)
    groups = []
    if status in (None, 'blocked'):
        visible = {task.id for task in tasks}
        groups = [group for group in orch.autonomy_queue.pending_groups()
                  if set(group['member_ids']) <= visible]
    return nocache_json({"tasks": [{**_approval_projection(t, _task_judge(orch)),
                                   **_consent_projection(orch.autonomy_queue, t),
                                   **_mode_projection(orch, t)} for t in tasks], "total": len(tasks),
                         **_task_judge_status(orch), **({'groups': groups} if groups else {})})


@router.get("/autonomy/status", dependencies=[Depends(admin_guard)])
async def autonomy_status():
    """Queue stats + remaining interruption budget."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return nocache_json({
        "stats": orch.autonomy_queue.stats(),
        "interrupt_budget_remaining": orch.autonomy.budget.remaining(),
        "interrupt_budget_per_day": orch.autonomy.budget.per_day,
        "pending_decisions": [t.to_dict() for t in orch.autonomy_queue.pending_decisions()],
    })


class MediationCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorized_enqueue: int = Field(strict=True, ge=0)
    governed: int = Field(strict=True, ge=0)
    refused_unmediated: int = Field(strict=True, ge=0)
    ungoverned_detected: int = Field(strict=True, ge=0)


class MediationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "hold", "enforce"]
    valid: bool
    stats: MediationCounts | None


@router.get(
    "/autonomy/mediation", dependencies=[Depends(admin_guard)], response_model=MediationStatus,
)
def autonomy_mediation_status():
    """Read the queue's verified mediation counts off the event-loop thread."""
    unavailable = {"error": "mediation status unavailable"}
    try:
        _, queue, err = require_component("autonomy_queue", unavailable["error"])
        if err is not None:
            return nocache_json(unavailable, status_code=503)
        mode = queue.mediation_mode
        if mode not in {"off", "hold", "enforce"}:
            return nocache_json(unavailable, status_code=503)

        snapshot = queue.verified_mediation_stats()
        if not isinstance(snapshot, Mapping) or type(snapshot.get("valid")) is not bool:
            return nocache_json(unavailable, status_code=503)
        if snapshot["valid"] is False:
            return nocache_json({"mode": mode, "valid": False, "stats": None})

        names = (
            "authorized_enqueue", "governed", "refused_unmediated", "ungoverned_detected",
        )
        stats = {name: snapshot[name] for name in names}
        if any(type(count) is not int or count < 0 for count in stats.values()):
            return nocache_json(unavailable, status_code=503)
        return nocache_json({"mode": mode, "valid": True, "stats": stats})
    except Exception:
        return nocache_json(unavailable, status_code=503)


@router.get("/autonomy/observer", dependencies=[Depends(admin_guard)])
async def autonomy_observer_status():
    """Proactive OS Observer state: tracked signals + currently unhealthy ones."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not orch.observer:
        return nocache_json({"enabled": False, "reason": "observer not initialized"})
    return nocache_json({
        "enabled": bool(orch.get_setting("system.observer_enabled", True)),
        **orch.observer.status(),
    })


@router.post("/autonomy/observer/run", dependencies=[Depends(admin_guard)])
async def autonomy_observer_run():
    """Trigger one observer sample now (sample → debounce → gate → queue)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not orch.observer:
        return JSONResponse({"error": "observer not initialized"}, status_code=503)
    summary = await orch.observer.observe()
    return nocache_json({"ok": True, "summary": summary})


@router.post("/autonomy/tasks", dependencies=[Depends(admin_guard)])
async def autonomy_submit(body: AutonomyTaskBody, request: Request):
    """Submit a task to the autonomy worker (gated through the risk policy)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.autonomy.inbox import OwnerTaskRegistrationContext

    context = OwnerTaskRegistrationContext.from_request(await request.json())
    from agents.core.autonomy.queue import TaskApprovalExpired
    try:
        task = await orch.autonomy.submit(
            agent=body.agent.strip().lower(), kind=body.kind.strip(),
            title=body.title, payload=body.payload, origin=body.origin,
            **({'grouping_context': context} if context is not None else {}),
            **({'approval_deadline_at': body.approval_deadline_at} if body.approval_deadline_at else {}),
        )
    except TaskApprovalExpired as exc:
        # Return committed durable IDs, never raw exception text or an implied approval.
        return nocache_json({"error": "approval deadline elapsed",
                             "expired_task_ids": [task.id for task in exc.batch.tasks]}, status_code=409)
    return nocache_json({"ok": True, "task": task.to_dict()})


@router.post('/autonomy/tasks/groups/{group_id}/reject', dependencies=[Depends(admin_guard)])
async def autonomy_reject_group(group_id: str, body: AutonomyGroupRejectBody):
    orch = get_orch()
    if not orch:
        return JSONResponse({'error': 'not initialized'}, status_code=503)
    from agents.core.autonomy.queue import TaskQueueError
    try:
        rejected = await orch.autonomy.reject_group(group_id, snapshot=body.snapshot,
                                                   member_ids=body.member_ids, decided_by='admin', reason=body.reason)
    except TaskQueueError as exc:
        return error_json(exc, 409, "approval group changed")
    if rejected is None:
        return JSONResponse({'error': 'approval group changed'}, status_code=409)
    return nocache_json({'ok': True, 'tasks': [task.to_dict() for task in rejected]})


@router.post("/autonomy/tasks/{task_id}/decision", dependencies=[Depends(admin_guard)])
async def autonomy_decide(task_id: int, body: AutonomyDecisionBody):
    """Resolve a blocked task (accept/edit/reject/defer)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.autonomy.queue import TaskQueueError
    try:
        task = await orch.autonomy.apply_decision(
            task_id, body.action.strip().lower(), decided_by="admin", payload=body.payload,
            reason=body.reason,
        )
    except TaskQueueError as e:
        return error_json(e, 409, "decision could not be applied")
    return nocache_json({"ok": True, "task": task.to_dict()})


def _consent_admin_current(request: Request, orch) -> bool:
    """Recheck the existing admin credential policy at the queue mutation seam."""
    from agents.core.routers._deps import _web

    try:
        web = _web()
        if web is None or get_orch() is not orch:
            return False
        if web._admin_credential_ok(request.headers.get('x-admin-token', '')):
            return True
        return (not web._admin_configured()
                and web._real_client_host(request) in web._LOCALHOSTS)
    except Exception:
        return False


@router.post("/autonomy/tasks/{task_id}/consent", dependencies=[Depends(admin_guard)])
async def autonomy_consent(task_id: int, body: AutonomyConsentBody, request: Request):
    """Resolve an exact reusable offer using the authenticated owner identity."""
    from agents.core.autonomy.consent_types import OwnerConsentActor
    from agents.core.autonomy.queue import TaskQueueError

    orch = get_orch()
    apply = getattr(getattr(orch, 'autonomy', None), 'apply_consent_decision', None)
    if orch is None or not callable(apply):
        return JSONResponse({'error': 'consent runtime not initialized'}, status_code=503)
    actor = OwnerConsentActor(
        label='admin', decided_by='admin',
        live=lambda: _consent_admin_current(request, orch),
    )
    try:
        result = await apply(task_id, body.revision, choice=body.choice,
                             actor=actor, reason=body.reason)
    except TaskQueueError as exc:
        return error_json(exc, 409, 'consent offer changed')
    if result is None:
        return JSONResponse({'error': 'consent offer changed'}, status_code=409)
    return nocache_json({'ok': True, 'tasks': [task.to_dict() for task in result.tasks]})


@router.get("/autonomy/brief", dependencies=[Depends(admin_guard)])
async def autonomy_brief(kind: str = "morning"):
    """Render the morning brief or evening retro (H6.4)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.autonomy.digest import build_morning_brief, build_evening_retro
    if kind == "evening":
        text = build_evening_retro(orch.autonomy_queue)
    else:
        memory_entries = []
        try:
            from agents.core.memory.store import MemoryStore
            allmem = await MemoryStore().get_all()
            for entries in (allmem or {}).values():
                memory_entries.extend(entries)
        except Exception:
            memory_entries = []
        runtime_health = None
        try:
            from agents.core.observability.runtime_log import (
                default_log_path,
                read_runtime_health,
            )
            runtime_health = read_runtime_health(default_log_path())
        except Exception:
            runtime_health = None
        try:
            # T-0.41: same sidecar read the scheduled brief performs, so a
            # manually-triggered brief isn't a different, poorer document.
            from agents.core.scheduler_service import _signal_briefs_or_none
            signal_briefs = await _signal_briefs_or_none(orch)
        except Exception:
            signal_briefs = None
        text = build_morning_brief(
            orch.autonomy_queue,
            memory_entries=memory_entries,
            runtime_health=runtime_health,
            signal_briefs=signal_briefs,
        )
    return nocache_json({"kind": kind, "text": text})


@router.get("/autonomy/mode", dependencies=[Depends(admin_guard)])
async def autonomy_get_mode():
    """Current global autonomy mode (AUTO/ASK/OFF) — the HUD AutonomyMode control."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.autonomy.mode import global_mode

    return nocache_json({"mode": global_mode(orch)})


class AutonomyModeBody(BaseModel):
    mode: str


@router.post("/autonomy/mode", dependencies=[Depends(admin_guard)])
async def autonomy_set_mode(body: AutonomyModeBody):
    """Set the global autonomy mode. Persists the setting, applies it live and records
    the change in the audit log (H484 — the same path ``/approvals`` in chat takes):
    auto = balanced; ask = side-effects wait for approval; off = nothing auto-runs
    and the proactive loop is paused."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.autonomy import mode as approval_mode

    mode = str(body.mode or "").strip().lower()
    if mode not in approval_mode.MODES:
        return JSONResponse({"error": "mode must be auto|ask|off"}, status_code=422)
    try:
        result = await asyncio.to_thread(
            approval_mode.set_global_mode, orch, mode, actor="admin", surface="api")
    except approval_mode.ModeNotSaved:
        return JSONResponse({"error": "mode_not_saved", "mode": approval_mode.global_mode(orch)},
                            status_code=503)
    if not result["effective"]:
        # Saved, but the settings the coordinator reads still hold the old value: the
        # live policy keeps the stricter mode until they agree. Not a success.
        return JSONResponse({"error": "mode_not_effective", "requested": result["mode"],
                             "live": result["live"], "was": result["was"],
                             "held": approval_mode.stricter(result["live"], result["mode"]) == result["live"]
                             and result["live"] != result["mode"],
                             "audited": result["audited"]}, status_code=503)
    return nocache_json({"mode": result["mode"], "ok": True, "was": result["was"],
                         "audited": result["audited"], "effective": True,
                         "looser": approval_mode.looser_overrides(orch)})


@router.get("/autonomy/policy", dependencies=[Depends(admin_guard)])
async def autonomy_get_policy():
    """Per-agent autonomy modes (HUD v3) — the global default + any per-agent overrides,
    as the policy reads them (H484: an unknown value is ``ask``, never shown raw).

    An agent absent from ``agents`` runs at the global mode; one present runs at its own
    AUTO/ASK/OFF — except under a global OFF, which no override loosens. ``looser`` names
    the agents whose override lets them ask less than the global mode."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.autonomy import mode as approval_mode

    return nocache_json({"global": approval_mode.global_mode(orch),
                         "agents": approval_mode.agent_modes(orch),
                         "looser": approval_mode.looser_overrides(orch)})


class AutonomyPolicyBody(BaseModel):
    agent: str = Field(..., min_length=1, max_length=64)
    mode: str   # auto | ask | off | default (clears the override → falls back to global)


@router.post("/autonomy/policy", dependencies=[Depends(admin_guard)])
async def autonomy_set_policy(body: AutonomyPolicyBody):
    """Set (or clear) one agent's autonomy mode. ``mode=default`` removes the override
    so the agent falls back to the global mode. Persists, applies live and records the
    change in the audit log (H484 — ``autonomy.mode.set_agent_mode``)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.autonomy import mode as approval_mode

    agent = body.agent
    mode = str(body.mode or "").strip().lower()
    if mode not in (*approval_mode.MODES, "default"):
        return JSONResponse({"error": "mode must be auto|ask|off|default"}, status_code=422)
    # H484: a well-formed id of an agent this hub has (or a documented special id). An
    # override that is already stored can always be cleared, whoever it names.
    problem = approval_mode.agent_id_problem(agent) or (
        None if mode == "default" else approval_mode.roster_problem(orch, agent))
    if problem:
        return JSONResponse({"error": "invalid_agent", "detail": problem}, status_code=422)
    try:
        result = await asyncio.to_thread(
            approval_mode.set_agent_mode, orch, agent, mode, actor="admin", surface="api")
    except approval_mode.ModeNotSaved:
        return JSONResponse({"error": "mode_not_saved"}, status_code=503)
    if not result["effective"]:
        # Saved, but not what the agent runs (safe mode serves no looser override; or the
        # store could not be read back). Not a success: say what is in force.
        return JSONResponse({"error": "mode_not_effective", "agent": agent, "requested": result["mode"],
                             "live": approval_mode.describe(orch, agent)["effective"],
                             "agents": result["agents"], "audited": result["audited"]}, status_code=503)
    return nocache_json({"ok": True, "agent": agent, "mode": result["mode"],
                         "agents": result["agents"], "audited": result["audited"],
                         "effective": True,
                         "looser": approval_mode.looser_overrides(orch)})


@router.get("/autonomy/interrupts", dependencies=[Depends(admin_guard)])
async def autonomy_interrupts():
    """Interrupt budget — the "calm-by-the-numbers" surface (HUD v3). How many
    proactive interruptions remain today vs. the daily ceiling."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    bud = getattr(orch.autonomy, "budget", None)
    if bud is None:
        return nocache_json({"remaining": None, "per_day": None, "used": None})
    remaining, per_day = bud.remaining(), bud.per_day
    return nocache_json({"remaining": remaining, "per_day": per_day,
                         "used": max(0, per_day - remaining)})


@router.get("/autonomy/preferences/suggestions", dependencies=[Depends(admin_guard)])
async def autonomy_pref_suggestions():
    """Classes consistently approved → autonomy-raise suggestions (H6.5)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return nocache_json({"suggestions": orch.autonomy_prefs.suggest_autonomy_raise()})


# ── H12.1: reversible / irreversible approval queue + security posture ──
# RiskTier 0-1 (read-only / reversible) are undoable; 2-3 (external /
# irreversible-or-money) are not. The HUD surfaces this so the user knows which
# pending actions can be safely auto-approved vs. which need scrutiny — the
# "anti-OpenClaw" reversibility story.


def _approval_projection(task, judge=None) -> dict:
    """Annotate a queued Task with a human-facing reversibility verdict."""
    from agents.core.autonomy.policy import RiskTier
    from agents.core.capability_manifests import manifest_for_action

    tier = int(task.risk_tier)
    reversible = tier <= int(RiskTier.REVERSIBLE)
    try:
        tier_name = RiskTier(tier).name
    except ValueError:
        tier_name = "UNKNOWN"
    d = judge.project(task) if judge is not None else task.to_dict()
    d["reversible"] = reversible
    d["tier_name"] = tier_name
    d["reversibility"] = "reversible" if reversible else "irreversible"
    manifest = manifest_for_action(str(task.kind))
    d["capability_id"] = manifest.id if manifest is not None else None
    d["rollback"] = asdict(manifest.rollback) if manifest is not None else None
    return d


@router.get("/autonomy/approvals", dependencies=[Depends(admin_guard)])
async def autonomy_approvals():
    """Pending approvals split into reversible vs irreversible buckets (H12.1)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.autonomy import mode as approval_mode

    pending = orch.autonomy_queue.pending_decisions()
    # H484: every card says which mode applies to its agent right now (_mode_projection).
    annotated = [{**_approval_projection(t, _task_judge(orch)),
                  **_consent_projection(orch.autonomy_queue, t),
                  **_mode_projection(orch, t)} for t in pending]
    reversible = [t for t in annotated if t["reversible"]]
    irreversible = [t for t in annotated if not t["reversible"]]
    return nocache_json({
        "pending": annotated,
        "mode": approval_mode.global_mode(orch),
        "recalled_waiting": _recalled_waiting(orch),
        **_task_judge_status(orch),
        "reversible": reversible,
        "irreversible": irreversible,
        "counts": {
            "total": len(annotated),
            "reversible": len(reversible),
            "irreversible": len(irreversible),
        },
    })
