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

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard, admin_guard

from agents.core.web_helpers import nocache_json, error_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["autonomy"])


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
    orch = get_orch()
    q = getattr(orch, "autonomy_queue", None) if orch else None
    if q is None:
        return JSONResponse({"error": "autonomy queue not available"}, status_code=503)
    task = q.get(task_id) if hasattr(q, "get") else None
    if task is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    from agents.core.autonomy.dry_run import preview_task
    return nocache_json(preview_task(task))


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


class AutonomyDecisionBody(BaseModel):
    action: str            # accept / edit / reject / defer
    payload: Optional[dict] = None


@router.get("/autonomy/tasks", dependencies=[Depends(admin_guard)])
async def autonomy_list(status: str = None, origin: str = None, limit: int = Query(100, ge=1, le=200)):
    """List autonomy tasks, optionally filtered by status/origin."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    tasks = orch.autonomy_queue.list(status=status, origin=origin, limit=limit)
    return nocache_json({"tasks": [_approval_projection(t) for t in tasks], "total": len(tasks)})


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
async def autonomy_submit(body: AutonomyTaskBody):
    """Submit a task to the autonomy worker (gated through the risk policy)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    task = await orch.autonomy.submit(
        agent=body.agent.strip().lower(), kind=body.kind.strip(),
        title=body.title, payload=body.payload, origin=body.origin,
    )
    return nocache_json({"ok": True, "task": task.to_dict()})


@router.post("/autonomy/tasks/{task_id}/decision", dependencies=[Depends(admin_guard)])
async def autonomy_decide(task_id: int, body: AutonomyDecisionBody):
    """Resolve a blocked task (accept/edit/reject/defer)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from core.autonomy.queue import TaskQueueError
    try:
        task = await orch.autonomy.apply_decision(
            task_id, body.action.strip().lower(), decided_by="admin", payload=body.payload,
        )
    except TaskQueueError as e:
        return error_json(e, 409, "decision could not be applied")
    return nocache_json({"ok": True, "task": task.to_dict()})


@router.get("/autonomy/brief", dependencies=[Depends(admin_guard)])
async def autonomy_brief(kind: str = "morning"):
    """Render the morning brief or evening retro (H6.4)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from core.autonomy.digest import build_morning_brief, build_evening_retro
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
        text = build_morning_brief(orch.autonomy_queue, memory_entries=memory_entries)
    return nocache_json({"kind": kind, "text": text})


@router.get("/autonomy/mode", dependencies=[Depends(admin_guard)])
async def autonomy_get_mode():
    """Current global autonomy mode (AUTO/ASK/OFF) — the HUD AutonomyMode control."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    mode = getattr(getattr(orch.autonomy, "policy", None), "mode", None) or orch.get_setting("autonomy.mode", "auto")
    return nocache_json({"mode": str(mode).lower()})


class AutonomyModeBody(BaseModel):
    mode: str


@router.post("/autonomy/mode", dependencies=[Depends(admin_guard)])
async def autonomy_set_mode(body: AutonomyModeBody):
    """Set the global autonomy mode. Persists the setting and applies it live:
    auto = balanced; ask = side-effects wait for approval; off = nothing auto-runs
    and the proactive loop is paused."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    mode = str(body.mode or "").lower()
    if mode not in ("auto", "ask", "off"):
        return JSONResponse({"error": "mode must be auto|ask|off"}, status_code=422)
    from core.settings_db import put_category
    put_category("autonomy", {"mode": mode})  # persist (read back by the autonomy loop)
    if getattr(orch.autonomy, "policy", None) is not None:
        orch.autonomy.policy.mode = mode      # apply immediately
    return nocache_json({"mode": mode, "ok": True})


@router.get("/autonomy/policy", dependencies=[Depends(admin_guard)])
async def autonomy_get_policy():
    """Per-agent autonomy modes (HUD v3) — the global default + any per-agent overrides.

    An agent absent from ``agents`` runs at the global mode; one present runs at its
    own AUTO/ASK/OFF."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    pol = getattr(orch.autonomy, "policy", None)
    global_mode = str(getattr(pol, "mode", None) or orch.get_setting("autonomy.mode", "auto")).lower()
    agents = dict(getattr(pol, "agent_modes", None) or orch.get_setting("autonomy.agent_modes", {}) or {})
    return nocache_json({"global": global_mode, "agents": agents})


class AutonomyPolicyBody(BaseModel):
    agent: str = Field(..., min_length=1, max_length=64)
    mode: str   # auto | ask | off | default (clears the override → falls back to global)


@router.post("/autonomy/policy", dependencies=[Depends(admin_guard)])
async def autonomy_set_policy(body: AutonomyPolicyBody):
    """Set (or clear) one agent's autonomy mode. ``mode=default`` removes the override
    so the agent falls back to the global mode. Persists + applies live."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    agent = body.agent.strip()
    mode = str(body.mode or "").lower()
    if mode not in ("auto", "ask", "off", "default"):
        return JSONResponse({"error": "mode must be auto|ask|off|default"}, status_code=422)

    # Start from the persisted map, apply the change, persist + apply live.
    agents = dict(orch.get_setting("autonomy.agent_modes", {}) or {})
    if mode == "default":
        agents.pop(agent, None)
    else:
        agents[agent] = mode
    from core.settings_db import put_category
    put_category("autonomy", {"agent_modes": agents})   # persist (resynced by the loop)
    pol = getattr(orch.autonomy, "policy", None)
    if pol is not None:
        pol.agent_modes = dict(agents)                  # apply immediately
    return nocache_json({"ok": True, "agent": agent,
                         "mode": (mode if mode != "default" else None), "agents": agents})


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


def _approval_projection(task) -> dict:
    """Annotate a queued Task with a human-facing reversibility verdict."""
    from core.autonomy.policy import RiskTier
    from agents.core.capability_manifests import manifest_for_action

    tier = int(task.risk_tier)
    reversible = tier <= int(RiskTier.REVERSIBLE)
    try:
        tier_name = RiskTier(tier).name
    except ValueError:
        tier_name = "UNKNOWN"
    d = task.to_dict()
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
    pending = orch.autonomy_queue.pending_decisions()
    annotated = [_approval_projection(t) for t in pending]
    reversible = [t for t in annotated if t["reversible"]]
    irreversible = [t for t in annotated if not t["reversible"]]
    return nocache_json({
        "pending": annotated,
        "reversible": reversible,
        "irreversible": irreversible,
        "counts": {
            "total": len(annotated),
            "reversible": len(reversible),
            "irreversible": len(irreversible),
        },
    })
