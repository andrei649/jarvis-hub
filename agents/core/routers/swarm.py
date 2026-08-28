"""NERVA Mission Control — swarm cockpit (page + aggregated live feed).

Serves the mission-control page (`GET /mission-control`) and the read-only
JSON feed (`GET /api/swarm/summary`) that drives it. One snapshot unifies
everything the swarm is doing:

- the internal agent fleet (live roster + tracer activity rollups),
- the autonomy funnel (queue stats, mode, interrupt budget, pending approvals),
- mission workspaces, workflow runs, spawned sub-agents, the A2A inbox,
- the kill-switch, and
- the *dev* swarm — the external coding agents (Claude, Codex, opencode,
  Antigravity) coordinated through the repo's lock files (`lock.py`).

Read-only by design: steering happens through the already-governed endpoints
(`POST /autonomy/tasks/{id}/decision`, `POST /api/missions/{id}/<action>`,
`POST /api/a2a/inbox/{id}/decide`), which the page calls directly — no new
mutating surface, contract, or kernel path is introduced here.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["swarm"])

# agents/core/routers/swarm.py → parents[2] == agents/ → web/mission_control.html
_MC_HTML = Path(__file__).resolve().parents[2] / "web" / "mission_control.html"

# Dev-swarm lock files written by the repo-root ``lock.py`` CLI. The on-disk
# format is read directly instead of importing lock.py: its import mkdirs the
# lock dir, its "read" helpers auto-release stale locks (a write), and it
# anchors on the repo root — never on JARVIS_HOME — so the reader follows the
# writer's anchor, not ``paths.data_path``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCKS_DIR = _REPO_ROOT / "memory_logs" / "oracle" / "locks"
_STALE_TIMEOUT = 1800  # mirrors lock.py STALE_TIMEOUT (30 min)

# Display roster: lock.py registers {opencode, claude, antigravity}; Codex
# coordinates via GitHub PRs only, but is still part of the dev swarm.
_DEV_AGENTS = ("claude", "codex", "opencode", "antigravity")

_ACTIVITY_CAP = 60
_TRACE_LIMIT = 2000


def _age(ts_now: float, raw_ts) -> int:
    try:
        return max(0, int(ts_now - float(raw_ts or 0)))
    except (TypeError, ValueError):
        return 0


def _basename(path: str) -> str:
    """Basename that works for foreign-OS paths — lock_state.json keys are
    lowercased *Windows* absolute paths when the writer runs on the owner's
    machine, so ``Path(...).name`` on POSIX would return the whole string."""
    tail = str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return tail or str(path)


def read_dev_locks(now: float | None = None) -> dict:
    """Read-only view of the dev-swarm coordination locks (lock.py's format).

    Never writes and never mkdirs; a missing dir or a corrupt file degrades to
    an empty/partial view — the locks live in gitignored ``memory_logs/``, so
    a fresh clone or a CI checkout legitimately has none.
    """
    ts_now = time.time() if now is None else now
    agents: list[dict] = []
    components: list[dict] = []
    available = _LOCKS_DIR.is_dir()
    if available:
        for f in sorted(_LOCKS_DIR.glob("*.active")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                age = _age(ts_now, data.get("ts"))
                agents.append({
                    "agent": str(data.get("agent") or f.stem),
                    "message": str(data.get("message") or ""),
                    "since": str(data.get("time") or ""),
                    "age_s": age,
                    "stale": age > _STALE_TIMEOUT,
                })
            except (OSError, ValueError, AttributeError):
                # corrupt/foreign/non-object file — skip, never fail the feed
                continue
        try:
            state = json.loads((_LOCKS_DIR / "lock_state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if isinstance(state, dict):
            for path, info in state.items():
                if not isinstance(info, dict):
                    continue
                age = _age(ts_now, info.get("ts"))
                components.append({
                    # Stored keys are lowercased absolute paths from the
                    # writer's machine — display the basename, keep the raw
                    # path as secondary detail.
                    "component": _basename(path),
                    "path": str(path),
                    "entity": str(info.get("entity") or "?"),
                    "task": str(info.get("task") or ""),
                    "age_s": age,
                    "stale": age > _STALE_TIMEOUT,
                })
        components.sort(key=lambda r: r["age_s"])
    return {
        "known": list(_DEV_AGENTS),
        "agents": agents,
        "components": components,
        "available": available,
    }


_PR_FEED_DEFAULT = {
    "available": False, "prs": [], "checked_at": 0.0, "capped": False, "error": None,
}


def _pr_feed_block(orch) -> dict:
    """H34.3 — the dev-swarm PR/CI feed, read straight from the Oracle bridge's
    already-cached snapshot (never a live GitHub call on the request path)."""
    bridge = getattr(orch, "oracle_bridge", None) if orch is not None else None
    if bridge is None:
        return dict(_PR_FEED_DEFAULT, error="oracle_bridge_unavailable")
    return _safe(
        lambda: dict(_PR_FEED_DEFAULT, **(bridge.status().get("pr_feed") or {})),
        dict(_PR_FEED_DEFAULT, error="read_failed"),
    )


def _safe(fn, default):
    """Run ``fn``, fall back to ``default`` — a partially initialized
    orchestrator (boot, tests, degraded subsystems) must never 500 the feed."""
    try:
        return fn()
    except Exception:
        return default


# Fields of a pending decision that are safe at the user tier. The full cards
# (payload/result) are served admin-tier by `/autonomy/status` and
# `/autonomy/approvals`, which the page fetches separately with the admin
# token and degrades to this preview without one. (`GET /tasks` applies the
# same rule since the TASK-5 fix — payload/result never leave the admin tier.)
_PREVIEW_FIELDS = ("id", "title", "agent", "kind", "risk_tier", "status", "created_at")


def _payload_free_mission(mission: dict) -> dict:
    """PGE-042: the feed is user-tier — mission step RESULTS are model output
    (payload tier) and stay admin-only; titles/status/progress pass through."""
    out = dict(mission)
    plan = out.get("plan")
    if isinstance(plan, list):
        out["plan"] = [
            {k: v for k, v in step.items() if k != "result"} if isinstance(step, dict) else step
            for step in plan
        ]
    return out


def _payload_free_run(run: dict) -> dict:
    """PGE-042: workflow step traces carry 160-char rendered prompt/output
    previews (personal content); the cockpit needs step names/status/timing.
    Sub-workflow steps nest their own trace under "steps", so strip recursively."""

    def _clean_step(step):
        if not isinstance(step, dict):
            return step
        cleaned = {k: v for k, v in step.items() if k not in ("input_preview", "output_preview")}
        if isinstance(cleaned.get("steps"), list):
            cleaned["steps"] = [_clean_step(sub) for sub in cleaned["steps"]]
        return cleaned

    out = dict(run)
    if isinstance(out.get("steps"), list):
        out["steps"] = [_clean_step(step) for step in out["steps"]]
    return out


def build_swarm_summary(orch) -> dict:
    """Aggregate every swarm surface into the Mission Control feed shape."""
    now = time.time()

    # ── internal fleet: roster seeded, tracer activity overlaid ──────────────
    ag_agg: dict[str, dict] = {}

    def _node(aid: str) -> dict:
        return ag_agg.setdefault(aid, {
            "id": aid, "model": None, "events": 0,
            "tokens_out": 0, "cost_eur": 0.0, "last_ts": 0,
        })

    if orch is not None:
        roster = _safe(lambda: dict(getattr(orch, "agents", None) or {}), {})
        for aid, ag in roster.items():
            node = _node(str(aid))
            node["model"] = _safe(
                lambda a=ag: (getattr(a, "config", None) or {}).get("model"), None)

    traces = _safe(lambda: orch.tracer.list(limit=_TRACE_LIMIT), []) if orch is not None else []
    activity: list[dict] = []
    for t in traces:
        if not isinstance(t, dict):
            continue
        try:
            agent = str(t.get("route") or (t.get("agents") or [""])[0] or "unknown")
            ts_ms = int(float(t.get("ts") or 0) * 1000)
            tokens_out = int(t.get("tokens_out") or 0)
            cost = float(t.get("cost") or 0.0)
        except (TypeError, ValueError, IndexError):
            continue
        node = _node(agent)
        node["events"] += 1
        node["tokens_out"] += tokens_out
        node["cost_eur"] = round(node["cost_eur"] + cost, 6)
        node["last_ts"] = max(node["last_ts"], ts_ms)
        if len(activity) < _ACTIVITY_CAP:  # tracer.list() is already newest-first
            activity.append({
                "ts": ts_ms,
                "agent": agent,
                "channel": str(t.get("channel") or ""),
                "intent": str(t.get("intent") or ""),
                "model": str(t.get("model") or "—"),
                "tokens_out": tokens_out,
                "cost_eur": round(cost, 6),
                "duration_ms": int(t.get("total_ms") or 0),
                "ok": bool(t.get("ok", True)),
            })
    agents_rows = sorted(
        ag_agg.values(),
        key=lambda r: (r["cost_eur"], r["tokens_out"], r["events"]),
        reverse=True,
    )

    # ── autonomy funnel (same accessors as GET /autonomy/status) ─────────────
    autonomy: dict = {
        "stats": {}, "mode": None, "budget": None,
        "pending_count": 0, "pending_preview": [],
    }
    if orch is not None:
        autonomy["stats"] = _safe(lambda: orch.autonomy_queue.stats(), {}) or {}
        autonomy["mode"] = _safe(
            lambda: str(
                getattr(getattr(orch.autonomy, "policy", None), "mode", None)
                or orch.get_setting("autonomy.mode", "auto")
            ).lower(),
            None,
        )
        autonomy["budget"] = _safe(
            lambda: {
                "remaining": orch.autonomy.budget.remaining(),
                "per_day": orch.autonomy.budget.per_day,
            },
            None,
        )
        pending = _safe(lambda: list(orch.autonomy_queue.pending_decisions()), [])
        autonomy["pending_count"] = len(pending)
        preview: list[dict] = []
        for task in pending[:10]:
            d = _safe(lambda t=task: t.to_dict(), None)
            if isinstance(d, dict):
                preview.append({k: d.get(k) for k in _PREVIEW_FIELDS})
        autonomy["pending_preview"] = preview

    # ── owner desk presence (H34.2) — drives away-notify routing ─────────────
    presence: dict | None = None
    if orch is not None:
        presence = _safe(
            lambda: orch.owner_presence.snapshot().to_dict(), None)

    # ── missions / workflows / sub-agents / A2A / kill-switch ────────────────
    if orch is not None:
        missions = _safe(
            lambda: [_payload_free_mission(m.to_dict()) for m in orch.missions.list(limit=10)],
            [],
        )
        wf_runs = _safe(
            lambda: [_payload_free_run(r) for r in (orch.workflow_engine.recent(5) or [])], []
        )
        subagents = _safe(
            lambda: {"spawns": len(orch.subagents.list() or []),
                     "stats": orch.subagents.stats() or {}},
            {"spawns": 0, "stats": {}},
        )
        halted = _safe(lambda: bool(orch.kill_switch.is_halted()), None)
    else:
        missions, wf_runs = [], []
        subagents = {"spawns": 0, "stats": {}}
        halted = None

    def _a2a_block() -> dict:
        from agents.core.a2a import a2a_enabled
        if not a2a_enabled():
            return {"enabled": False, "pending": 0}
        # Only instantiate the registry when A2A is on — it touches disk.
        from agents.core.routers.a2a import _get_a2a_registry
        return {
            "enabled": True,
            "pending": len(_get_a2a_registry().list_inbox("pending") or []),
        }

    a2a = _safe(_a2a_block, {"enabled": False, "pending": 0})

    return {
        "generated_at": now,
        "initialized": orch is not None,
        "halted": halted,
        "agents": agents_rows,
        "activity": activity,
        "autonomy": autonomy,
        "presence": presence,
        "missions": missions,
        "workflows": {"runs": wf_runs},
        "subagents": subagents,
        "a2a": a2a,
        "dev_locks": read_dev_locks(now),
        "pr_feed": _pr_feed_block(orch),
    }


@router.get("/mission-control", dependencies=[Depends(user_guard)])
async def mission_control_page():
    """The NERVA Mission Control page (swarm cockpit + HITL controls)."""
    if not _MC_HTML.is_file():
        return JSONResponse({"error": "mission_control.html not found"}, status_code=404)
    return FileResponse(str(_MC_HTML), media_type="text/html")


@router.get("/api/swarm/summary", dependencies=[Depends(user_guard)])
async def swarm_summary():
    """Aggregated swarm snapshot driving Mission Control — read-only."""
    return nocache_json(build_swarm_summary(get_orch()))
