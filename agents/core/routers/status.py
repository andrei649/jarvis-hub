"""Status / health endpoints — extracted from web.py (CLN-3).

Covers the small status surface: component-health (`/api/health/components`), the
HUD-compatible `/status` snapshot, and the lightweight `/api/status` smoke probe.
All three are unguarded, exactly as inline. H227 adds the admin-only inspector
(`/api/admin/inspector`): what an agent can do right now, for a given principal.

`/status` leans on web.py's `_sys_info()`, `_enrich_agents()`, and late-bound
`_list_local_models()` compatibility seam.  The latter delegates to the shared
local-model inventory, keeping `/status` and `/api/models/local` on one truth source.

H133 — the live status chrome: `/status` also answers `gateway` (which channels run, so
the HUD can light a gateway dot even on the collapsed rail) and `sessions` (how many
unarchived sessions saw activity in the last `ACTIVE_SESSION_WINDOW_S`; `None` with
`state: "unknown"` when the session store cannot answer — never a guessed zero).

H019 — `nerva status`'s service block and slot usage (Hermes `hermes status` → Gateway
Service, Sessions → Slots): `service` says which service manager runs this hub, the unit,
whether the shipped unit is installed and active, the pid and uptime
(`agents.core.service_status`); `slots` says how many turns hold a session's turn lease
(one per session, no hub-wide cap), each running channel's chat lanes against their cap,
and the sub-agents against theirs. Counts only — no session id or sender leaves this
public read — and a count the hub cannot read is `None`, never a guessed zero. Who holds
the slots (Hermes' one row per holder: surface, session id, age) is
`GET /api/status/slots`, behind the user guard like `GET /sessions`; `nerva status`
prints its rows under `slots:` when the hub returns them.
"""

import asyncio
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from agents.core import service_status
from agents.core.app_state import get_gateway, get_orch
from agents.core.llm.local_model_inventory import project_llm_status
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.validation import is_valid_session_id
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["status"])

#: H133 — a session counts as active when its last turn (or keep) is this recent.
ACTIVE_SESSION_WINDOW_S = 900
#: H019 — at most this many holder rows leave ``GET /api/status/slots`` (the total is sent).
SLOT_HOLDERS_LIMIT = 200
#: A holder's surface is a channel id; anything else is sent as ``unknown``.
_SURFACE = re.compile(r"[a-z0-9][a-z0-9_.\-]{0,31}")


def _web():
    # Always present at request time (the app is running). Not an import edge.
    # The helpers stay owned by web.py; resolve them here on each call so tests'
    # monkeypatches and the runtime orchestrator remain observable.
    return sys.modules.get("agents.web")


def _channels(orch) -> dict:
    manager = getattr(orch, "channel_manager", None)
    return getattr(manager, "channels", None) or getattr(orch, "channels", None) or {}


def _channel_rows(orch):
    channels = _channels(orch)
    running = set(getattr(orch, "running_channels", []) or [])
    gateway = get_gateway()
    rows = []
    for channel_id, channel in channels.items():
        is_running = bool(
            channel_id in running
            or getattr(channel, "_running", False)
            or getattr(channel, "running", False)
        )
        row = {
            "id": str(channel_id),
            "running": is_running,
            "ready": is_running or channel_id in {"web", "voice"},
            # Hermes absorption 5b: how many times pairing held a stranger on this
            # channel — a tally, never an identity (the pairing store owns those).
            "held_senders": _held_count(gateway, str(channel_id)),
        }
        health = _channel_health(channel)
        if health is not None:
            row["health"] = health
        rows.append(row)
    return rows


_HEALTH_KEYS = ("state", "error", "fatal", "failures", "retry_in_s", "since", "last_ok")
_HEALTH_TOKEN = re.compile(r"[a-z0-9_]{1,40}")


def _channel_health(channel) -> dict | None:
    """H100 — the channel's connection health (``ChannelAdapter.health_snapshot``): state,
    the error kind, failures in a row, seconds to the next retry, the fatal reason and what
    the last catch-up did. Kinds and counts only; anything else is dropped."""
    reader = getattr(channel, "health_snapshot", None)
    if not callable(reader):
        return None
    try:
        raw = reader()
    except Exception:
        return {"state": "unknown"}
    if not isinstance(raw, dict):
        return {"state": "unknown"}
    out = {}
    for key in _HEALTH_KEYS:
        value = raw.get(key)
        if isinstance(value, str):
            out[key] = value if _HEALTH_TOKEN.fullmatch(value) else "unknown"
        elif isinstance(value, int) and not isinstance(value, bool):
            out[key] = value
        else:
            out[key] = None
    backfill = raw.get("backfill")
    if isinstance(backfill, dict):
        out["backfill"] = {k: v for k, v in backfill.items()
                           if isinstance(k, str) and _HEALTH_TOKEN.fullmatch(k)
                           and isinstance(v, int) and not isinstance(v, bool)}
    return out


def _gateway_state(rows: list[dict]) -> dict:
    """H133 — the gateway summary the chrome shows: ``running`` when any channel runs,
    ``stopped`` when channels are registered but none runs, ``none`` when there are none."""
    running = sorted(row["id"] for row in rows if row["running"])
    state = "running" if running else ("stopped" if rows else "none")
    return {"state": state, "running": running, "running_count": len(running), "total": len(rows)}


def _session_counts(orch) -> dict:
    """H133 — active sessions in the last ``ACTIVE_SESSION_WINDOW_S``, or an honest unknown."""
    counter = getattr(getattr(orch, "checkpoints", None), "active_session_count", None)
    active = None
    if callable(counter):
        since = (datetime.now(UTC) - timedelta(seconds=ACTIVE_SESSION_WINDOW_S)).isoformat()
        try:
            value = counter(since)
            active = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        except Exception:
            active = None
    return {"active": active, "window_s": ACTIVE_SESSION_WINDOW_S,
            "state": "known" if active is not None else "unknown"}


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _turn_slots(orch) -> dict | None:
    reader = getattr(orch, "turn_slots", None)
    if not callable(reader):
        return None
    try:
        row = reader()
    except Exception:
        return None
    running = _count(row.get("running")) if isinstance(row, dict) else None
    if running is None:
        return None
    return {"running": running, "per_session": _count(row.get("per_session")), "cap": _count(row.get("cap"))}


def _lane_slots(orch) -> list[dict]:
    rows = []
    for channel_id, channel in _channels(orch).items():
        reader = getattr(channel, "lane_usage", None)
        if not callable(reader):
            continue
        try:
            usage = reader()
        except Exception:
            usage = None
        if usage is None:
            continue   # no poll loop runs: the channel holds no lane
        counts = {key: _count(usage.get(key)) if isinstance(usage, dict) else None
                  for key in ("running", "queued", "lanes", "cap")}
        rows.append({"channel": str(channel_id), **counts})
    return sorted(rows, key=lambda row: row["channel"])


def _subagent_slots(orch) -> dict | None:
    stats = getattr(getattr(orch, "subagents", None), "stats", None)
    if not callable(stats):
        return None
    try:
        row = stats()
    except Exception:
        return None
    if not isinstance(row, dict):
        return None
    running, cap = _count(row.get("active")), _count(row.get("cap"))
    return {"running": running, "cap": cap} if running is not None and cap is not None else None


def _slot_usage(orch) -> dict:
    """H019 — concurrency in use against what is allowed: turns holding a session's lease,
    each running channel's chat lanes, the sub-agents. ``None`` is a count the hub could
    not read (an old or stand-in orchestrator, no sub-agent manager wired)."""
    return {"turns": _turn_slots(orch), "lanes": _lane_slots(orch), "subagents": _subagent_slots(orch)}


def _iso_instant(value) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not value > 0:
        return None
    try:
        return datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _holder_row(row) -> dict | None:
    if not isinstance(row, dict):
        return None
    surface, session_id = row.get("surface"), row.get("session_id")
    return {
        "surface": surface if isinstance(surface, str) and _SURFACE.fullmatch(surface) else "unknown",
        "session_id": session_id if is_valid_session_id(session_id) else None,
        "started_at": _iso_instant(row.get("started_at")),
        "age_s": _count(row.get("age_s")),
    }


def _slot_holders(orch) -> list[dict] | None:
    """H019 — one row per turn holding a slot, oldest first (``Orchestrator.turn_holders``):
    the surface, the session id (only an id the session store would accept; else None),
    when it took the slot and its age. None when the hub cannot list them."""
    reader = getattr(orch, "turn_holders", None)
    if not callable(reader):
        return None
    try:
        rows = reader()
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    return [row for row in (_holder_row(item) for item in rows) if row is not None]


async def _service_block() -> dict:
    """H019 — the service block (``service_status.snapshot``) off the event loop: its unit
    probe reads files and may ask the service manager once per ``PROBE_TTL_S``."""
    web = _web()
    started = getattr(web, "_start_time", None) if web is not None else None
    return await asyncio.to_thread(service_status.snapshot, started_at=started)


def _held_count(gateway, channel_id: str) -> int:
    if gateway is None:
        return 0
    try:
        info = gateway.get_channel_info(channel_id) or {}
        return max(0, int(info.get("held_senders", 0) or 0))
    except Exception:
        return 0


# ── Status (HUD-compatible) ──────────────────────────────────────

@router.get("/api/health/components")
async def component_health():
    """A8: which optional components initialized (vs failed silently)."""
    orch = get_orch()
    reg = getattr(orch, "components", None) if orch else None
    if reg is None:
        return nocache_json({"components": {}, "summary": "registry unavailable"})
    return nocache_json({"components": reg.health(), "failed": reg.failed(),
                         "summary": reg.summary()})


@router.get("/status")
async def status():
    orch = get_orch()
    if not orch:
        return nocache_json({"status": "starting"})
    web = _web()
    enriched = web._enrich_agents()
    voice_state = "idle"
    inventory = await web._list_local_models()
    ready = project_llm_status(inventory)
    lm_online = any(provider.get("online") for provider in inventory.get("providers", []))
    from agents import __version__
    channels = _channel_rows(orch)
    return nocache_json({
        "version": __version__,
        "sys": web._sys_info(),
        "voice_state": voice_state,
        "lm_online": lm_online,                       # backend configured/reachable
        "model_state": ready["model_state"],
        "model_loaded": ready["model_loaded"],
        "loaded_model": ready["loaded_model"],
        "resident_models": ready["resident_models"],
        "residency_state": ready["residency_state"],
        "configured_model": inventory.get("configured_model"),
        "llm_backend": inventory.get("backend", "none"),
        "active_model": inventory.get("configured_model"),
        "agents": [{"id": a["id"], "status": a["status"]} for a in enriched],
        "agents_online": sum(1 for a in enriched if a["status"] != "idle"),
        "agents_total": len(enriched),
        "channels": channels,
        "gateway": _gateway_state(channels),          # H133: the chrome's gateway dot
        "sessions": _session_counts(orch),            # H133: the status strip's count
        "service": await _service_block(),            # H019: service manager, unit, pid, uptime
        "slots": _slot_usage(orch),                   # H019: turns / lanes / sub-agents in use
        # H275: the HUD shows a banner while the hub runs in safe mode.
        "safe_mode": _safe_mode_status(),
    })


@router.get("/api/status/slots", dependencies=[Depends(user_guard)])
async def status_slots():
    """H019 — who holds the slots ``GET /status`` counts (Hermes ``hermes status`` →
    Slots, one row per holder: surface, session id, age). User-guarded like
    ``GET /sessions``: session ids never leave the public ``/status``. Read-only."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    holders = _slot_holders(orch)
    return nocache_json({
        "slots": _slot_usage(orch),
        "holders": holders[:SLOT_HOLDERS_LIMIT] if holders is not None else None,
        "holders_total": len(holders) if holders is not None else None,
    })


@router.get("/api/status")
async def api_status():
    """Return service version, agent count, and health status."""
    from agents import AGENT_COUNT, __version__
    from agents.core.lifecycle_budget import WARMUP

    return {"version": __version__, "agents": AGENT_COUNT, "status": "ok", "safe_mode": _safe_mode_status(),
            "warmup": WARMUP.snapshot()}   # H677: warming while the boot warm-up is still running


@router.get("/api/admin/inspector", dependencies=[Depends(admin_guard)])
async def admin_inspector(agent: str = "jarvis", view: str = "owner",
                          section: Annotated[list[str] | None, Query()] = None):
    """H227 — what *agent* can do right now as *view* sees it: status, the tools its
    profile offers, the skills its prompt names, the MCP servers and the resolved prompt
    (secrets masked, 64 KB at most). Read-only; ``section`` narrows it (repeatable)."""
    from agents.core.inspector import SECTIONS, VIEWS, build_inspector

    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    if view not in VIEWS:
        return nocache_json({"error": "unknown_view", "views": list(VIEWS)}, status_code=400)
    if section and any(name not in SECTIONS for name in section):
        return nocache_json({"error": "unknown_section", "sections": list(SECTIONS)}, status_code=400)
    try:
        payload = await build_inspector(orch, agent, view=view, sections=section or None,
                                        inventory=_web()._list_local_models)
    except LookupError:
        return nocache_json({"error": "unknown_agent", "agent": agent}, status_code=404)
    return nocache_json(payload)


def _safe_mode_status() -> dict:
    from agents.core import safe_mode

    return safe_mode.status()
