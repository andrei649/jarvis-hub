"""Dashboard / HUD-data endpoints — extracted from web.py (CLN-3).

Covers the HUD-facing surface only: `GET /dashboard` (weather + calendar +
notifications), `GET /tasks` (autonomy-queue tasks), and `GET /ticker` (live
status ticker). Behavior is byte-frozen — the inline handlers moved verbatim.

The orchestrator is resolved at request time via `get_orch()` (late binding to
`web.orch`), matching the other extracted routers.

Three web.py module-globals these handlers touch stay in web.py and are resolved
through `sys.modules` on each call rather than captured at import:
`_dashboard_cache` + `_dashboard_lock` (mutable cache state — `tests/test_dashboard.py`
does `monkeypatch.setattr(web, "_dashboard_cache", ...)` / `_dashboard_lock`), and
`_enrich_agents()` (reads the `_AGENT_SETTINGS` singleton). Reading them via
`sys.modules.get("agents.web")` keeps the monkeypatch observed and avoids a static
import edge back into `agents.web`.
"""

import sys
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["dashboard"])


def _web():
    return sys.modules.get("agents.web")


@router.get("/dashboard", dependencies=[Depends(user_guard)])
async def dashboard():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    web = _web()
    _dashboard_cache = web._dashboard_cache
    _dashboard_lock = web._dashboard_lock
    now = time.time()
    if now - _dashboard_cache.get("cached_at", 0) > 120:
        async with _dashboard_lock:
            # Re-check inside the lock: a concurrent request may have just refreshed.
            if now - _dashboard_cache.get("cached_at", 0) > 120:
                try:
                    weather_plugin = orch.plugins.get("weather")
                    w = await weather_plugin.get_weather("") if weather_plugin else ""
                    _dashboard_cache["weather"] = w.strip()
                except Exception:
                    _dashboard_cache["weather"] = _dashboard_cache.get("weather", "")
                _dashboard_cache["cached_at"] = now

    raw = _dashboard_cache["weather"]
    w_temp = "—"
    w_desc = "Indisponibil"
    w_wind = "—"
    w_humidity = "—"
    if raw:
        parts = raw.split(", ")
        for p in parts:
            if "°" in p and ("+" in p or "-" in p):
                cleaned = p.split(":")[-1].strip().replace("+", "").replace("°C", "").strip()
                if cleaned:
                    w_temp = cleaned
            elif "humidity" in p:
                w_humidity = p.replace(" humidity", "").strip()
            elif "wind" in p:
                w_wind = p.replace(" wind", "").strip()
            elif p and "°" not in p and ":" not in p:
                candidate = p.strip()
                if candidate and len(candidate) > 2:
                    w_desc = candidate
    weather_data = {
        "city": "București",
        "temp": w_temp,
        "desc": w_desc,
        "wind": w_wind,
        "humidity": w_humidity,
        "feels": "—",
        "updated": "—",
        "forecast": [],
    }

    calendar_data = _dashboard_cache.get("calendar", [])
    if now - _dashboard_cache.get("calendar_cached_at", 0) > 120 and orch:
        async with _dashboard_lock:
            # Re-check inside the lock to avoid a redundant concurrent fetch.
            if now - _dashboard_cache.get("calendar_cached_at", 0) > 120:
                try:
                    cal_plugin = orch.plugins.get("google-calendar")
                    if cal_plugin and cal_plugin.access_token:
                        events = await cal_plugin.get_today_events()
                        if events and not (len(events) == 1 and "error" in events[0]):
                            calendar_data = events
                            _dashboard_cache["calendar"] = events
                            _dashboard_cache["calendar_cached_at"] = now
                except Exception:
                    pass
            else:
                calendar_data = _dashboard_cache.get("calendar", [])

    notifications = []

    return nocache_json({
        "weather": weather_data,
        "calendar": calendar_data,
        "notifications": notifications,
    })


@router.get("/tasks", dependencies=[Depends(user_guard)])
async def get_tasks():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)

    try:
        all_tasks = orch.autonomy_queue.list(limit=30)
    except Exception:
        all_tasks = []

    # Format and enrich tasks for both backend model schema and frontend React network/widgets schema
    def format_task(t):
        d = t.to_dict() if hasattr(t, "to_dict") else dict(t)
        # Ensure owner, state, label, and project are present for React component compatibility (e.g. NetworkBrain)
        d["owner"] = d.get("owner") or d.get("agent_id") or "jarvis"
        d["state"] = d.get("state") or d.get("status") or "done"
        d["label"] = d.get("label") or d.get("title") or "Task"
        d["project"] = d.get("project") or d.get("kind") or "Autonomy"
        return d

    # 1. Check for running tasks first
    running_tasks = [t for t in all_tasks if getattr(t, "status", None) == "running" or getattr(t, "state", None) == "running"]

    if running_tasks:
        result_tasks = [format_task(t) for t in running_tasks]
    elif all_tasks:
        # 2. If no running tasks, return recent history
        result_tasks = [format_task(t) for t in all_tasks]
    else:
        # H7.7: No active tasks — return empty list instead of misleading dummy data
        result_tasks = []

    return nocache_json({"tasks": result_tasks})


@router.get("/api/dashboard/today", dependencies=[Depends(user_guard)])
async def dashboard_today(days: int = Query(1, ge=1, le=30)):
    """P1 G1 — the unified "Today in Jarvis" feed.

    Fuses what Jarvis *did* (completed autonomy actions) and what it *learned*
    (new / updated memory facts) into one timestamp-ordered story — closing the
    gap where the task recap (`autonomy/digest.py`) and learnings (`memory/digest.py`)
    lived in separate places. Pure read over existing rows; `user_guard`'d because
    it surfaces personal facts. `days` defaults to 1 ("today"), clamped 1–30."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    queue = getattr(orch, "autonomy_queue", None)

    # Read the persistent fact store the same way memory_kg/data_spaces do — a
    # fresh handle on the shared SQLite DB under JARVIS_HOME (no orch coupling).
    memory_entries: list[dict] = []
    try:
        from agents.core.memory.store import MemoryStore
        allmem = await MemoryStore().get_all()
        for entries in (allmem or {}).values():
            memory_entries.extend(entries)
    except Exception:
        memory_entries = []

    from agents.core.memory.timeline import build_unified_digest
    return nocache_json(build_unified_digest(queue, memory_entries, days=days))


@router.get("/ticker", dependencies=[Depends(user_guard)])
async def get_ticker():
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    items = []

    # 1. Add active unhealthy signals from observer
    if orch.observer:
        try:
            obs_status = orch.observer.status()
            for key, state in obs_status.get("signals", {}).items():
                if not state.get("healthy", True):
                    items.append({
                        "agent": state.get("agent", "steve"),
                        "verb": "WARNING",
                        "obj": state.get("detail", key),
                        "pct": 100,
                        "pri": "high" if state.get("severity") == "CRITICAL" else "mid",
                    })
        except Exception:
            pass

    # 2. Add active unhealthy signals from event watcher
    if getattr(orch, "event_watcher", None):
        try:
            watcher_state = orch.event_watcher._state
            for key, healthy in watcher_state.items():
                if not healthy:
                    agent = "gecko" if "finance" in key else ("pepper" if "calendar" in key else ("stark" if "email" in key else "hercules"))
                    items.append({
                        "agent": agent,
                        "verb": "ALERT",
                        "obj": f"Unhealthy event signal: {key}",
                        "pct": 100,
                        "pri": "mid",
                    })
        except Exception:
            pass

    # 3. Fallback to active agent standby messages so it's never empty
    if not items:
        enriched = _web()._enrich_agents()
        for a in enriched:
            items.append({
                "agent": a["id"],
                "verb": "monitoring" if a["status"] == "ready" else "standby",
                "obj": a["role"],
                "pct": 50,
                "pri": "mid",
            })

    return nocache_json({"ticker": items})
