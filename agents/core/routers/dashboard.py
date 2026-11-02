"""Dashboard / HUD-data endpoints — extracted from web.py (CLN-3).

Covers the HUD-facing surface only: `GET /dashboard` (weather + calendar +
notifications), `GET /tasks` (autonomy-queue tasks), and `GET /ticker` (live
status ticker). Behavior is byte-frozen — the inline handlers moved verbatim.
Also the "Today" timeline (`GET /api/dashboard/today`), every learned entry with its
id (`GET /api/dashboard/today/entries`: the curated rings' facts, the learned skills, the
fact store's rows) and, by that id, read / edit / delete of one learned entry
(`/api/dashboard/today/entries/{entry_id}`, H046, crossing `kg.write`; writes are admin).

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

import asyncio
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictStr

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["dashboard"])


class TasksResponse(BaseModel):
    tasks: list[dict[str, Any]]
    view: Literal["legacy", "running", "history"]
    source: Literal["autonomy_queue"] = "autonomy_queue"
    history_included: bool
    as_of: datetime


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
                except Exception:
                    pass
                # Advance the cache clock after every attempt (empty day or a
                # failing plugin included), so /dashboard doesn't make a live
                # Google Calendar call under the shared lock on every poll —
                # matching the weather branch's failure-caching semantics.
                _dashboard_cache["calendar_cached_at"] = now
            else:
                calendar_data = _dashboard_cache.get("calendar", [])

    notifications = []

    return nocache_json({
        "weather": weather_data,
        "calendar": calendar_data,
        "notifications": notifications,
    })


def _effective_task_state(task: dict[str, Any]) -> str:
    state = task.get("state")
    value = state if isinstance(state, str) and state.strip() else task.get("status")
    return value.strip().lower() if isinstance(value, str) else ""


@router.get("/tasks", dependencies=[Depends(user_guard)], response_model=TasksResponse)
async def get_tasks(
    view: Literal["running", "history"] | None = Query(default=None),
) -> TasksResponse:
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
        # TASK-5: this is a USER-tier surface; the raw row carries the full payload
        # and result (email drafts, writeback bodies) that every /autonomy/* read
        # keeps admin-only. Titles/decisions/status only — never payload/result.
        d.pop("payload", None)
        d.pop("result", None)
        # Ensure owner, state, label, and project are present for React component compatibility (e.g. NetworkBrain)
        d["owner"] = d.get("owner") or d.get("agent_id") or d.get("agent") or "jarvis"
        d["state"] = d.get("state") or d.get("status") or "done"
        d["label"] = d.get("label") or d.get("title") or "Task"
        d["project"] = d.get("project") or d.get("kind") or "Autonomy"
        return d

    if view == "running":
        formatted_tasks = [format_task(t) for t in all_tasks]
        result_tasks = [t for t in formatted_tasks if _effective_task_state(t) == "running"]
        response_view: Literal["legacy", "running", "history"] = "running"
        history_included = False
    elif view == "history":
        formatted_tasks = [format_task(t) for t in all_tasks]
        result_tasks = [t for t in formatted_tasks if _effective_task_state(t) != "running"]
        response_view = "history"
        history_included = True
    else:
        # Migration window: preserve the original raw, case-sensitive selection.
        running_tasks = [
            t
            for t in all_tasks
            if getattr(t, "status", None) == "running"
            or getattr(t, "state", None) == "running"
        ]
        if running_tasks:
            result_tasks = [format_task(t) for t in running_tasks]
            history_included = False
        elif all_tasks:
            result_tasks = [format_task(t) for t in all_tasks]
            history_included = True
        else:
            # H7.7: No active tasks — return empty list instead of misleading dummy data
            result_tasks = []
            history_included = False
        response_view = "legacy"

    return TasksResponse(
        tasks=result_tasks,
        view=response_view,
        history_included=history_included,
        as_of=datetime.now(UTC),
    )


@router.get("/api/dashboard/today", dependencies=[Depends(user_guard)])
async def dashboard_today(days: int = Query(1, ge=1, le=30), limit: int = Query(50, ge=1, le=500),
                          kind: Literal["action", "learning", "followup"] | None = None):
    """P1 G1 — the unified "Today in Jarvis" feed.

    Fuses what Jarvis *did* (completed autonomy actions) and what it *learned*
    (new / updated memory facts) into one timestamp-ordered story — closing the
    gap where the task recap (`autonomy/digest.py`) and learnings (`memory/digest.py`)
    lived in separate places. Pure read over existing rows; `user_guard`'d because
    it surfaces personal facts. `days` defaults to 1 ("today"), clamped 1–30.

    H046 (the learning timeline `nerva journey` prints): every item carries a stable
    ``entry_id``; ``kind`` keeps one kind of item and ``limit`` (default 50, at most
    500) bounds the newest items returned; ``counts`` always covers the whole window.
    A learned entry is read, edited and deleted by that id under
    ``/api/dashboard/today/entries/{entry_id}``, and ``/api/dashboard/today/entries``
    lists every learned entry whatever its age.

    H046 review: the learned half is what the assistant really keeps — the facts of the
    two curated rings every prompt carries (the agent's notes and the user profile, which
    the model's ``memory`` tool, the post-turn review and the daily reflection write;
    each dated by when it entered its ring, so a new fact never brings the older ones
    into the window, and one no save dated yet by its ring's last save), the skills it
    learned (dated by their last use) and the fact store's rows. ``drift`` says a ring
    file could not be read back."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    queue = getattr(orch, "autonomy_queue", None)
    memory_entries = await _store_rows()
    # H046 review: the rings' facts and the learned skills are learnings too.
    learned, drift = await asyncio.to_thread(_read_learned, orch)

    from agents.core.memory.timeline import build_unified_digest
    body = build_unified_digest(queue, memory_entries, days=days, limit=limit, kind=kind, learned=learned)
    if drift:
        body["drift"] = drift
    return nocache_json(body)


# ── H046: one learned entry of the timeline, by its id (Hermes `hermes journey`) ─────
# What the assistant learned is kept in three stores, and the journey reaches each by its
# own id (``memory/timeline.py``): the curated rings every prompt carries (Hermes's memory
# cards: the agent's notes and the user profile, ``memory:<ring>:<digest>``), the skills it
# learned (``skill:<name>``) and the structured fact store (``learning:<row id>``).
#
# Changing or deleting one is a memory write: it crosses `kg.write` exactly as the
# externally-driven `/api/kg/*` writes do (the write contract, then the Action Kernel with a
# capability token, minted for the already proven caller when none is presented), and the
# kernel's deny comes before the lookup so a halt never says whether the entry exists. The
# payload carries ids and lengths only, and for a ring fact not even its id (a digest of
# the fact). The write itself then takes the store's own path: a ring fact the memory
# tool's (`memory_tool.owner_change`: locks, reread, scan, budget, an undo ref, the intent
# log), a skill the owner's skill batch (`skills/batch.run_batch`: checked, swapped
# atomically, the old folder archived), a fact the store's by-id calls. The writes are
# admin, as every other owner write to the rings and the skills is (`/api/memory/core/undo`,
# `/api/memory/reset`, `/api/skills/batch`). An action is the hub's record of what it did
# and a follow-up is derived from another entry: neither is learned material.

_LEARNING_VALUE_MAX = 2000
_GONE = object()   # the store call has not answered (a cancelled call may still have written)
#: A memory-tool refusal → the status the entry routes answer it with (else 400).
_RING_REFUSAL_STATUS = {
    "memory_no_match": 404, "memory_unavailable": 503, "memory_audit_unavailable": 503,
    "memory_write_failed": 503, "memory_locked": 409, "memory_drift": 409, "memory_drift_unreadable": 409,
    "memory_changed_meanwhile": 409, "memory_duplicate": 409, "memory_over_budget": 409,
    "memory_text_too_long": 422,
}


def _skill_md_max() -> int:
    from agents.core.skills.batch import MAX_SKILL_MD_CHARS

    return MAX_SKILL_MD_CHARS


class TimelineEntryEdit(BaseModel):
    """The new text of a learned entry: a fact's value (at most 2000 characters; a ring
    fact, 300), or a learned skill's whole SKILL.md. A fact keeps its category and key."""

    value: StrictStr = Field(..., max_length=100_000)


_ID_HELP = ("not a timeline entry id: memory:<memory|user>:<digest>, skill:<name>, learning:<n>, "
            "action:<n> or followup:<reason>:<source>")


def _learned_ref(entry_id: str):
    """``((store, ref), None)`` for a learned entry's id — store ``facts`` (ref: the row
    id), ``memory`` / ``user`` (ref: the id itself) or ``skill`` (ref: its name) — else
    ``(None, the refusal)``."""
    from agents.core.memory.timeline import parse_entry_id

    parsed = parse_entry_id(entry_id)
    if parsed is None:
        return None, JSONResponse({"error": _ID_HELP}, status_code=400)
    kind, ref = parsed
    if kind == "action":
        return None, JSONResponse(
            {"error": "an action is the hub's record of what it did, not something it learned; "
                      "only a learned entry is read, edited or deleted here", "kind": kind},
            status_code=409)
    if kind == "followup":
        return None, JSONResponse(
            {"error": f"a follow-up is derived from {ref}; read, edit or delete that entry instead",
             "kind": kind, "source": ref},
            status_code=409)
    if kind == "memory":
        return (ref.split(":", 1)[0], entry_id), None
    if kind == "skill":
        return ("skill", ref), None
    return ("facts", int(ref)), None


def _learning_write_denied(orch, payload: dict, req: Request | None):
    """The kg.write mediation every externally-driven memory write takes, or None (allow)."""
    from agents.core.routers.memory_kg import _kg_contract_denial, _kg_kernel_denial

    denied = _kg_contract_denial(payload)
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    # req is None only for a direct (non-HTTP) call; the kernel helper then mints the token.
    token_id = req.headers.get("x-capability-token", "") if req is not None else ""
    denied = _kg_kernel_denial(orch, payload, token_id)
    if denied is not None:
        return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
    return None


def _write_payload(op: str, store: str, entry_id: str, value_len: int | None = None) -> dict:
    """What the kernel sees: ids and lengths. A ring fact's id is a digest of the fact, so
    only its ring is named."""
    payload = {"op": op}
    if store in ("memory", "user"):
        payload["store"] = store
    else:
        payload["entry"] = entry_id
    if value_len is not None:
        payload["value_len"] = value_len
    return payload


async def _memory_store():
    from agents.core.memory.store import MemoryStore

    return await asyncio.to_thread(MemoryStore)   # opens SQLite (WAL): off the loop


# ── reading the rings and the skills (blocking: run off the event loop) ──────────────

def _rings_module(orch):
    """The LivingMemory module whatever ``cognition.memory_enabled`` says: the rings are on
    disk with memory switched off too, and the owner may read and forget what they hold."""
    from agents.core.routers.memory_kg import _memory_module

    return _memory_module(orch)


def _ring_saved_epoch(ring) -> float | None:
    path = getattr(ring, "path", None)
    try:
        return path.stat().st_mtime if path is not None else None
    except OSError:
        return None


def _ring_fact_items(target: str, ring) -> list[dict]:
    """The facts of one ring as timeline items, each dated by when it entered the ring
    (``CoreMemory.added_at``), a fact no save dated yet by the ring's last save."""
    from agents.core.memory.timeline import ring_items

    added = None
    if callable(getattr(ring, "added_at", None)):
        try:
            added = ring.added_at()
        except Exception:
            logger.warning("journey: when the facts of the %s ring were added could not be read", target,
                           exc_info=True)
    return ring_items(target, ring.list(), _ring_saved_epoch(ring), added)


def _read_rings_items(orch) -> tuple[list[dict], str | None]:
    """Every fact of both rings, reread from their files first (another process, a hand
    edit), as timeline items; and the drift a ring that cannot be read back reports."""
    from agents.core.memory_tool import TARGETS, MemoryToolError, _read_rings

    living = _rings_module(orch)
    if living is None:
        return [], None
    drift = None
    try:
        _read_rings(living)
    except MemoryToolError as exc:
        drift = exc.detail
    items: list[dict] = []
    for target, attr in TARGETS.items():
        ring = getattr(living, attr, None)
        if ring is not None and callable(getattr(ring, "list", None)):
            items.extend(_ring_fact_items(target, ring))
    return items, drift


def _learned_skills(orch) -> dict:
    """The skills it learned, by name: loaded, not shipped with Nerva, and created by the
    agent or used at least once (Hermes's journey keeps exactly these)."""
    from pathlib import Path

    from agents.core.skills.loader import _shipped_location
    from agents.core.skills.usage import ORIGIN_AGENT

    loader = getattr(orch, "skills", None)
    usage = getattr(orch, "skill_usage", None)
    out: dict = {}
    for name, skill in list((getattr(loader, "skills", None) or {}).items()):
        try:
            if not getattr(skill, "external", True) or _shipped_location(Path(skill.path)):
                continue
            rec = (usage.get(name) if usage is not None else None) or {}
            if rec.get("origin") != ORIGIN_AGENT and int(rec.get("use_count") or 0) <= 0:
                continue
        except Exception:
            logger.debug("journey: skill %s skipped", name, exc_info=True)
            continue
        out[name] = (skill, rec)
    return out


def _skill_entry(name: str, skill, rec: dict, file_epoch) -> dict:
    from pathlib import Path

    from agents.core.memory.timeline import skill_item

    item = skill_item(name, rec, description=getattr(skill, "description", "") or "", file_epoch=file_epoch)
    # A skill the agent generated waits in quarantine until the owner approves it: it is
    # listed (it was learned) but a batch does not change it before that.
    item["pending_review"] = (Path(skill.path) / "PENDING_REVIEW").exists()
    return item


def _skill_items(orch) -> list[dict]:
    from pathlib import Path

    items = []
    for name, (skill, rec) in _learned_skills(orch).items():
        try:
            file_epoch = (Path(skill.path) / "SKILL.md").stat().st_mtime
        except OSError:
            file_epoch = None
        items.append(_skill_entry(name, skill, rec, file_epoch))
    return items


def _read_learned(orch) -> tuple[list[dict], str | None]:
    items, drift = _read_rings_items(orch)
    try:
        items.extend(_skill_items(orch))
    except Exception:
        logger.warning("journey: the learned skills could not be read", exc_info=True)
    return items, drift


async def _store_rows() -> list[dict]:
    # Read the persistent fact store the same way memory_kg/data_spaces do — a fresh
    # handle on the shared SQLite DB under JARVIS_HOME (no orch coupling).
    rows: list[dict] = []
    try:
        allmem = await (await _memory_store()).get_all()
        for entries in (allmem or {}).values():
            rows.extend(entries)
    except Exception:
        rows = []
    return rows


@router.get("/api/dashboard/today/entries", dependencies=[Depends(user_guard)])
async def dashboard_today_entries(store: Literal["facts", "memory", "user", "skill"] | None = None,
                                  limit: int = Query(1000, ge=1, le=5000)):
    """Every learned entry, whatever its age, oldest first, each with its id (Hermes's
    ``journey list``: the lookup table ``journey show|edit|delete`` take an id from): the
    facts of both curated rings (``memory``: the agent's notes, ``user``: the user
    profile), the skills it learned (``skill``) and the fact store's rows (``facts``).
    ``store`` keeps one store; past ``limit`` the newest are kept. ``total`` and
    ``counts`` cover every entry; ``drift`` says a ring could not be read back."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    from agents.core.memory.timeline import LEARNED_STORES, journey_entries

    learned, drift = await asyncio.to_thread(_read_learned, orch)
    entries = journey_entries(await _store_rows(), learned)
    counts = {name: sum(1 for it in entries if it.get("store") == name) for name in LEARNED_STORES}
    if store is not None:
        entries = [it for it in entries if it.get("store") == store]
    body = {"entries": entries[-limit:], "total": len(entries), "counts": counts}
    if drift:
        body["drift"] = drift
    return nocache_json(body)


def _find_ring_fact(orch, store: str, entry_id: str):
    """(the ring item, its fact) of the ring fact with this id, else None."""
    items, _drift = _read_rings_items(orch)
    for item in items:
        if item["store"] == store and item["entry_id"] == entry_id:
            return item
    return None


def _pending_withheld(name: str) -> str:
    return (f"{name!r} awaits the owner's review (quarantined, never run): its files are read in the "
            f"review (GET /api/skills/pending/{name}, admin); approve it or discard it (delete this entry)")


def _skill_detail(orch, name: str):
    """A learned skill as the entry routes answer it, with its whole SKILL.md, else None.

    H046 review: a skill the agent generated that still awaits the owner's review is the
    model's text, quarantined: only the admin review (``GET /api/skills/pending/{name}``)
    reads it, and the model's ``skill_view`` does not serve it. Its entry therefore carries
    no ``content`` and says why (``content_withheld``)."""
    from pathlib import Path

    found = _learned_skills(orch).get(name)
    if found is None:
        return None
    skill, rec = found
    md = Path(skill.path) / "SKILL.md"
    try:
        file_epoch = md.stat().st_mtime
    except OSError:
        file_epoch = None
    item = _skill_entry(name, skill, rec, file_epoch)
    item["content"] = None
    if item["pending_review"]:
        item["content_withheld"] = _pending_withheld(name)
        return item
    try:
        item["content"] = md.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        logger.debug("journey: the SKILL.md of %s could not be read", name, exc_info=True)
    return item


def _no_learned_skill(name: str) -> JSONResponse:
    return JSONResponse({"error": f"no learned skill named {name!r} (journey list names them)"}, status_code=404)


def _ring_refusal(exc) -> JSONResponse:
    return JSONResponse({"error": exc.detail, "reason": exc.reason}, status_code=_RING_REFUSAL_STATUS.get(exc.reason, 400))


def _ring_written(orch) -> None:
    """A ring changed: a reread a turn made before it (with the facts as they were) must
    not reach a block rendered after it, as a reset makes sure (routers/memory_kg.py)."""
    if getattr(orch, "_core_rings_reread", None) is not None:
        orch._core_rings_reread = None


@router.get("/api/dashboard/today/entries/{entry_id}", dependencies=[Depends(user_guard)])
async def dashboard_today_entry(entry_id: str):
    """One learned entry, whatever its age: a ring fact, a learned skill (with its whole
    SKILL.md as ``content``; for one still awaiting the owner's review, none: only the admin
    review reads a quarantined skill, and ``content_withheld`` says so) or a fact-store row."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    ref, refusal = _learned_ref(entry_id)
    if refusal is not None:
        return refusal
    store, key = ref
    if store in ("memory", "user"):
        item = await asyncio.to_thread(_find_ring_fact, orch, store, entry_id)
        if item is None:
            return JSONResponse({"error": "not found (the ring changed, or the id is from before the hub "
                                          "restarted): list the journey again"}, status_code=404)
        return nocache_json({"entry": item})
    if store == "skill":
        item = await asyncio.to_thread(_skill_detail, orch, key)
        return nocache_json({"entry": item}) if item is not None else _no_learned_skill(key)
    from agents.core.memory.timeline import learning_item

    row = await (await _memory_store()).get_by_id(key)
    if row is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"entry": learning_item(row)})


def _too_long(limit: int) -> JSONResponse:
    return JSONResponse({"error": f"value is over {limit:,} characters"}, status_code=422)


@router.patch("/api/dashboard/today/entries/{entry_id}", dependencies=[Depends(admin_guard)])
async def dashboard_today_entry_edit(entry_id: str, body: TimelineEntryEdit, req: Request = None):
    """Change what a learned entry says. Body: ``{value}``.

    A ring fact is replaced in place, by the memory tool's own write (one clean line of at
    most 300 characters, scanned; the ring's budget; an undo ref; the intent log): its id
    follows its text, so the reply carries the new one. A skill's ``value`` is its whole
    SKILL.md, applied by the owner's skill batch (checked first; the old folder archived);
    one still awaiting the owner's review is refused (409 ``skill_pending_review``).
    A fact-store row (at most 2000 characters) keeps its id, category and key and moves to
    now on the timeline. An unchanged value writes nothing (``changed: false``)."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    ref, refusal = _learned_ref(entry_id)
    if refusal is not None:
        return refusal
    store, key = ref
    if store == "skill":
        return await _edit_skill(orch, entry_id, key, body.value, req)
    value = body.value.strip()
    if not value:
        return JSONResponse({"error": "value required (to remove the entry, delete it)"}, status_code=400)
    if store == "facts" and len(value) > _LEARNING_VALUE_MAX:
        return _too_long(_LEARNING_VALUE_MAX)
    denied = _learning_write_denied(orch, _write_payload("edit_learning", store, entry_id, len(value)), req)
    if denied is not None:
        return denied
    if store in ("memory", "user"):
        return await _edit_ring_fact(orch, store, entry_id, value)
    from agents.core.memory.timeline import learning_item
    from agents.core.routers.memory_kg import _recall_forget

    memory = await _memory_store()
    current = await memory.get_by_id(key)
    if current is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if current.get("value") == value:
        return nocache_json({"ok": True, "changed": False, "entry": learning_item(current)})
    row = _GONE
    try:
        row = await memory.update_value_by_id(key, value)
    finally:
        if row is not None:
            # The old wording must not come back from a cached recall result (H428).
            _recall_forget(orch)
    if row is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "changed": True, "entry": learning_item(row)})


async def _edit_ring_fact(orch, store: str, entry_id: str, value: str):
    from agents.core.memory_tool import MemoryToolError, owner_change

    def _change():
        item = _find_ring_fact(orch, store, entry_id)
        if item is None:
            raise MemoryToolError("memory_no_match", "not found (the ring changed, or the id is from before "
                                  "the hub restarted): list the journey again")
        if item["value"] == value:
            return item, None
        result = owner_change(_rings_module(orch), store, item["value"], value,
                              audit=getattr(orch, "intent_log", None))
        return item, result

    try:
        item, result = await asyncio.to_thread(_change)
    except MemoryToolError as exc:
        return _ring_refusal(exc)
    if result is None or not result.get("changed"):
        return nocache_json({"ok": True, "changed": False, "entry": item})
    _ring_written(orch)
    living = _rings_module(orch)
    from agents.core.memory_tool import TARGETS

    ring = getattr(living, TARGETS[store], None)
    entry = next((it for it in _ring_fact_items(store, ring)
                  if it["value"] == result["fact"]), None) if ring is not None else None
    return nocache_json({"ok": True, "changed": True, "entry": entry, "previous_id": entry_id,
                         "undo_ref": result.get("undo_ref"), "usage": result.get("usage")})


async def _edit_skill(orch, entry_id: str, name: str, content: str, req: Request | None):
    if not content.strip():
        return JSONResponse({"error": "value required: the skill's whole SKILL.md (to remove the skill, "
                                      "delete it)"}, status_code=400)
    if len(content) > _skill_md_max():
        return _too_long(_skill_md_max())
    denied = _learning_write_denied(orch, _write_payload("edit_learning", "skill", entry_id, len(content)), req)
    if denied is not None:
        return denied
    current = await asyncio.to_thread(_skill_detail, orch, name)
    if current is None:
        return _no_learned_skill(name)
    if current.get("pending_review"):
        # A batch never changes a quarantined skill; its text is reviewed whole, then
        # approved or discarded (what it says is the model's, not yet the owner's).
        return JSONResponse({"error": _pending_withheld(name), "reason": "skill_pending_review"}, status_code=409)
    if (current.get("content") or "").strip() == content.strip():
        return nocache_json({"ok": True, "changed": False, "entry": current})
    from agents.core.routers.skills import _batch_archive
    from agents.core.skills.batch import run_batch

    text = content if content.endswith("\n") else content + "\n"
    result = await asyncio.to_thread(run_batch, [{"name": name, "action": "patch", "content": text}],
                                     orch.skills, backup_dir=_batch_archive())
    if not result.get("ok"):
        return JSONResponse({"error": result.get("detail") or "the skill could not be changed", **result},
                            status_code=422)
    entry = await asyncio.to_thread(_skill_detail, orch, name)
    return nocache_json({"ok": True, "changed": True, "entry": entry, "backup": result.get("backup")})


@router.delete("/api/dashboard/today/entries/{entry_id}", dependencies=[Depends(admin_guard)])
async def dashboard_today_entry_delete(entry_id: str, req: Request = None):
    """Forget a learned entry. A ring fact leaves its ring by the memory tool's own write
    (an undo ref keeps the ring as it was beside the rings, as for the model's own remove;
    ``POST /api/memory/core/undo`` puts it back, a reset erases it); a learned skill is
    archived, as Hermes archives one (its folder moved to the skills batch archive,
    recoverable; a pinned skill is refused), and one still awaiting the owner's review is
    discarded as the review's reject does (its folder kept in the discard archive); a
    fact-store row leaves the store (and its search index and write-ahead log), so it
    leaves the timeline and every brief."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    ref, refusal = _learned_ref(entry_id)
    if refusal is not None:
        return refusal
    store, key = ref
    denied = _learning_write_denied(orch, _write_payload("delete_learning", store, entry_id), req)
    if denied is not None:
        return denied
    if store in ("memory", "user"):
        return await _delete_ring_fact(orch, store, entry_id)
    if store == "skill":
        return await _delete_skill(orch, entry_id, key)
    from agents.core.routers.memory_kg import _recall_forget

    memory = await _memory_store()
    removed = _GONE
    try:
        removed = await memory.delete_by_id(key)
    finally:
        if removed is not None:
            _recall_forget(orch)
    if removed is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "deleted": entry_id,
                         "category": removed.get("category"), "key": removed.get("key")})


async def _delete_ring_fact(orch, store: str, entry_id: str):
    from agents.core.memory_tool import MemoryToolError, owner_change

    def _remove():
        item = _find_ring_fact(orch, store, entry_id)
        if item is None:
            raise MemoryToolError("memory_no_match", "not found (the ring changed, or the id is from before "
                                  "the hub restarted): list the journey again")
        return owner_change(_rings_module(orch), store, item["value"], None,
                            audit=getattr(orch, "intent_log", None))

    try:
        result = await asyncio.to_thread(_remove)
    except MemoryToolError as exc:
        return _ring_refusal(exc)
    _ring_written(orch)
    return nocache_json({"ok": True, "deleted": entry_id, "store": store, "undo_ref": result.get("undo_ref"),
                         "usage": result.get("usage")})


async def _discard_pending_skill(orch, entry_id: str, name: str):
    """A learned skill still in quarantine is forgotten the way the owner rejects one
    (``POST /api/skills/{name}/discard``, the loader's own move): its folder leaves the
    skills tree for the discard archive (kept, never loaded again), with its registry entry
    and any approval bound to its path."""
    from agents.core.routers.skills import _discard_archive

    dest = await asyncio.to_thread(orch.skills.discard_generated_skill, name, _discard_archive())
    if dest is None:
        return _no_learned_skill(name)
    return nocache_json({"ok": True, "deleted": entry_id, "store": "skill", "discarded": True,
                         "archived_to": str(dest)})


async def _delete_skill(orch, entry_id: str, name: str):
    from pathlib import Path

    found = await asyncio.to_thread(lambda: _learned_skills(orch).get(name))
    if found is None:
        return _no_learned_skill(name)
    skill, rec = found
    if await asyncio.to_thread(lambda: (Path(skill.path) / "PENDING_REVIEW").exists()):
        return await _discard_pending_skill(orch, entry_id, name)
    if rec.get("pinned"):
        return JSONResponse({"error": f"{name!r} is pinned: unpin it first", "reason": "skill_pinned"},
                            status_code=409)
    from agents.core.routers.skills import _batch_archive
    from agents.core.skills.batch import run_batch
    from agents.core.skills.usage import STATE_ARCHIVED

    result = await asyncio.to_thread(run_batch, [{"name": name, "action": "delete"}], orch.skills,
                                     backup_dir=_batch_archive())
    if not result.get("ok"):
        return JSONResponse({"error": result.get("detail") or "the skill could not be archived", **result},
                            status_code=422)
    usage = getattr(orch, "skill_usage", None)
    if usage is not None:
        try:
            usage.set_state(name, STATE_ARCHIVED)
        except Exception:
            logger.warning("journey: the archived state of %s could not be recorded", name, exc_info=True)
    return nocache_json({"ok": True, "deleted": entry_id, "store": "skill", "archived_to": result.get("backup")})


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
            # `ProactiveObserver.status()` returns {"probes", "tracked", "unhealthy"}.
            # This read `obs_status.get("signals", {})` — a key it has never emitted —
            # so the loop body never executed and every unhealthy probe was silently
            # dropped from the ticker. A hub with Qdrant down and the disk filling up
            # scrolled "all agents monitoring" exactly like a healthy one.
            # Entries are {"key", "detail", "severity"} and are unhealthy by
            # construction, so there is no `healthy` flag left to check.
            for signal in obs_status.get("unhealthy", []):
                items.append({
                    "agent": signal.get("agent", "steve"),
                    "verb": "WARNING",
                    "obj": signal.get("detail") or signal.get("key", "unknown signal"),
                    "pct": 100,
                    "pri": "high" if signal.get("severity") == "CRITICAL" else "mid",
                })
        except Exception:
            logger.warning("ticker: observer status unreadable", exc_info=True)

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
