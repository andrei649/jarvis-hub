"""Session endpoints — extracted from web.py (CLN-3).

Covers the `/sessions` surface: list recent sessions and resume a session by id.
Both are user-guarded. The orchestrator (which owns `checkpoints` + `memory`) is
resolved at request time via `get_orch()` (late binding to `web.orch`), matching
the other extracted routers. Behavior is unchanged from the inline versions.

H315 adds the agent's own plans: `GET /sessions/todo` (the ones the agent most
recently wrote or read) and `GET /sessions/{id}/todo` (one session's), both
user-guarded and never cached — a plan is work in flight and a stale copy misstates it.

H262 adds the pin (`POST /sessions/{id}/pin` and `/unpin`, user-guarded): a pinned chat is
never auto-archived and never deleted by retention; each list row carries `pinned_at`.
H262 review: unarchiving or resuming a chat stamps `kept_at`, from which the archiver
counts its idle time again, so the next sweep does not archive it straight back.

H652 adds ``GET /sessions/{id}/trajectories`` (admin): the session's saved full turns,
exported as ShareGPT or OpenAI chat rows for training (``agents/core/trajectory.py``).

H440 adds the owner's rename (`PATCH /sessions/{id}/title`, user-guarded and owner-fenced
like the pin: a human title is never replaced by the automatic ones), hides the continued
parts of a conversation from `GET /sessions` (each row says which session a resume opens:
`resume_id`, how many other sessions its conversation has: `continuations`, and whether it
is an `earlier_part` still in use), and lets `POST /sessions/resume` take a `title`, which
opens that conversation where it was last used.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.validation import is_valid_session_id

router = APIRouter(tags=["sessions"])


class ResolveSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: str
    latest_mode: bool = False


@router.post("/sessions/resolve", dependencies=[Depends(admin_guard)])
async def resolve_session(body: ResolveSessionRequest):
    """Select and recap without changing the shared active/default session."""
    from agents.core.memory.recap import render_recap
    from agents.core.session_continuation import ContinuationRefused, prepare_session
    from agents.core.session_selectors import SessionSelectionError, resolve

    orch = get_orch()
    if orch is None:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        import asyncio
        sid = await asyncio.to_thread(resolve, orch.checkpoints, body.selector,
                                      latest_mode=body.latest_mode)
        await prepare_session(orch, sid)
        history = await orch.memory.get_history(sid)
    except (SessionSelectionError, ContinuationRefused) as exc:
        return JSONResponse({"error": exc.reason,
                             **({"candidates": exc.candidates} if getattr(exc, "candidates", None) else {})},
                            status_code=exc.status)
    return JSONResponse({"session_id": sid, "recap": render_recap(history)}, headers=_NO_STORE)


class ImportSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    external_id: str
    turns: list[dict]
    request_id: UUID
    source_sha256: str | None = None


@router.post("/sessions/import", dependencies=[Depends(admin_guard)])
async def import_session(body: ImportSessionRequest):
    """Accept owner-attested, canonical text only; SQLite owns the durable seed."""
    from agents.core.foreign_history import ForeignHistoryRefused
    from agents.core.session_import import import_turns

    orch = get_orch()
    if orch is None:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        import asyncio
        result = await asyncio.to_thread(import_turns, orch.checkpoints, source=body.source,
                                         external_id=body.external_id, turns=body.turns,
                                         request_id=str(body.request_id), source_sha256=body.source_sha256)
    except ForeignHistoryRefused as exc:
        return JSONResponse({"error": exc.reason}, status_code=exc.status)
    return JSONResponse(result, status_code=201, headers=_NO_STORE)


@router.get("/sessions", dependencies=[Depends(user_guard)])
async def get_sessions(req: Request, archived: bool = False):
    """The newest sessions; H218: archived ones only with ``?archived=true``, never mixed in.
    H262: each row carries its ``pinned_at``."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents import web
    from agents.core.foreign_history import status
    admin = web._web_principal(req).admin
    # The lineage predicate runs before the limit, so newer foreign rows cannot push
    # a guest's native history out of the window; the row probe below stays authoritative.
    # H440: both views list every session nobody continued yet — the newest part of a
    # continued chat (each branch of one continued more than once) and every plain chat;
    # the parts that were continued are not rows — except one that got turns after it was
    # continued (third review: ``/sessions/continue`` does not move the chat that is open,
    # so those turns are in no continuation): it is a row again, under its own title,
    # marked ``earlier_part``. Archive, unarchive, pin and (with ``lineage=true``) delete
    # act on the whole conversation.
    sessions = orch.checkpoints.get_sessions(limit=20, archived=archived, native_only=not admin,
                                             hide_continuations=True)
    if not admin:
        import asyncio
        sessions = [row for row in sessions if not (await asyncio.to_thread(
            status, orch.checkpoints, row.get("session_id") or row.get("id"))).tainted]
    from ..session_titles import title_fields  # H413: each session's title and its source

    ids = [row.get("session_id") or row.get("id") for row in sessions]
    others = getattr(orch.checkpoints, "lineage_others", None)
    others = others(ids) if callable(others) else {}
    continued = getattr(orch.checkpoints, "continued_sessions", None)
    continued = continued(ids) if callable(continued) else set()
    return {"sessions": [{**row, **title_fields(row.get("metadata")), **_stamp_fields(row),
                          **_lineage_fields(sid, others, continued)} for sid, row in zip(ids, sessions, strict=True)]}


def _lineage_fields(sid, others: dict, continued=()) -> dict:
    """H440 — ``resume_id``: the session a resume of this row opens (the row itself; the
    field stays for clients written when a row was the first part). ``continuations``: how
    many other sessions its conversation has — earlier and later parts, other branches —
    which is what a whole-conversation delete removes besides this one. ``earlier_part``:
    this session was continued and then used again, so it is listed beside the session
    that continues it."""
    return {"resume_id": sid, "continuations": int(others.get(sid) or 0), "earlier_part": sid in continued}


def _stamp_fields(row: dict) -> dict:
    import json as _json

    try:
        meta = _json.loads(row.get("metadata") or "{}")
    except (TypeError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return {key: meta.get(key) if isinstance(meta.get(key), str) else None for key in ("archived_at", "pinned_at")}


#: The stamps a route may set or clear: the store's writer and the answer's field.
_STAMPS = {"archived": "set_archived", "pinned": "set_pinned"}


async def _set_stamp(session_id: str, field: str, on: bool, req: Request):
    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.foreign_history import http_owner_guard
    try:
        await http_owner_guard(orch.checkpoints, session_id, req)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return JSONResponse({"error": "the session store is unavailable", "reason": "store_unavailable"},
                            status_code=503)
    if (field, on) == ("archived", False):
        done = _keep(orch.checkpoints, session_id)
    else:
        done = getattr(orch.checkpoints, _STAMPS[field])(session_id, on)
    if done is None:
        return JSONResponse({"error": "the session store is unavailable", "reason": "store_unavailable"},
                            status_code=503)
    if not done:
        return JSONResponse({"error": f"session '{session_id}' not found"}, status_code=404)
    if (field, on) == ("archived", True):
        from agents.core.session_archive import forget_skill_loads

        members = getattr(orch.checkpoints, "lineage_members", None)
        for member in (members(session_id) if callable(members) else None) or [session_id]:
            forget_skill_loads(member)          # H326: an archived chat carries no skill loads
    return JSONResponse({"ok": True, "session": session_id, field: on}, headers=_NO_STORE)


def _keep(checkpoints, session_id: str):
    """H262 review — the owner keeps a chat: unarchived, with ``kept_at`` stamped."""
    keep = getattr(checkpoints, "unarchive", None)
    return keep(session_id) if callable(keep) else checkpoints.set_archived(session_id, False)


@router.post("/sessions/{session_id}/archive", dependencies=[Depends(user_guard)])
async def archive_session(session_id: str, req: Request):
    """H218 — put a conversation away: it leaves the list, nothing is deleted."""
    return await _set_stamp(session_id, "archived", True, req)


@router.post("/sessions/{session_id}/unarchive", dependencies=[Depends(user_guard)])
async def unarchive_session(session_id: str, req: Request):
    """H218 — bring an archived conversation back to the list (a pinned one too)."""
    return await _set_stamp(session_id, "archived", False, req)


@router.post("/sessions/{session_id}/pin", dependencies=[Depends(user_guard)])
async def pin_session(session_id: str, req: Request):
    """H262 — pin a conversation: never auto-archived, never deleted by retention."""
    return await _set_stamp(session_id, "pinned", True, req)


@router.post("/sessions/{session_id}/unpin", dependencies=[Depends(user_guard)])
async def unpin_session(session_id: str, req: Request):
    """H262 — take the pin off; the chat is archived and retained like any other again."""
    return await _set_stamp(session_id, "pinned", False, req)


class RenameSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


@router.patch("/sessions/{session_id}/title", dependencies=[Depends(user_guard)])
async def rename_session(session_id: str, body: RenameSessionRequest, req: Request):
    """H440 — the owner names a conversation. A human title is never replaced by the
    first-words title or the local model's upgrade.

    Reach: as the pin and the archive routes, any user-token holder may rename any native
    session (an imported one is the owner's alone). A reserved name (``latest``, an ``@``
    selector, a session id) answers 400 ``title_reserved``; a name another conversation
    already goes by answers 409 ``title_taken``."""
    from agents.core.session_titles import HUMAN, TitleRefused, human_title

    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    title = human_title(body.title)
    if not title:
        return JSONResponse({"error": "a title is one line of 1 to 100 characters", "reason": "invalid_title"},
                            status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.foreign_history import http_owner_guard
    try:
        await http_owner_guard(orch.checkpoints, session_id, req)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return JSONResponse({"error": "the session store is unavailable", "reason": "store_unavailable"},
                            status_code=503)
    try:
        done = orch.checkpoints.rename_session(session_id, title)
    except TitleRefused as exc:
        taken = exc.reason == "title_taken"
        return JSONResponse({"error": ("another conversation already goes by that name" if taken
                                       else "that name is reserved for selecting a session"),
                             "reason": exc.reason}, status_code=409 if taken else 400)
    if done is None:
        return JSONResponse({"error": "the session store is unavailable", "reason": "store_unavailable"},
                            status_code=503)
    if not done:
        return JSONResponse({"error": f"session '{session_id}' not found"}, status_code=404)
    return JSONResponse({"ok": True, "session": session_id, "title": title, "title_source": HUMAN},
                        headers=_NO_STORE)


_DELETE_STATUS = {"active_session": 409, "session_busy": 409, "has_continuations": 409, "not_found": 404,
                  "recall_unavailable": 503}


@router.delete("/sessions/{session_id}", dependencies=[Depends(admin_guard)])
async def delete_session(session_id: str, confirm: str = "", lineage: bool = False):
    """H218 — delete one conversation for good, backup first. Needs ``?confirm=DELETE``.

    H440 review: a chat that others continue still answers 409 ``has_continuations`` — its
    continuations are never deleted in silence. ``&lineage=true`` says the whole
    conversation: every member — every branch — is deleted, newest first, each with its
    own lease and backup (``deleted``, ``backups`` in the answer; older backups are pruned
    once afterwards, never the ones just written); none when a chat is on any of them,
    and a run that stops part way says which are gone. A row's ``continuations`` in
    ``GET /sessions`` is how many sessions that removes besides the row itself.

    Holds the session's turn lease, as ``create_continuation`` does: a turn on it
    finishes first (it would write the transcript back, or add a turn the backup never
    saw), and one still running past the lease's wait answers 409 ``session_busy``."""
    from agents.core import session_archive

    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    if confirm != session_archive.CONFIRM:
        return JSONResponse({"error": "a permanent delete requires ?confirm=DELETE",
                             "reason": "confirm_required"}, status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        # H262: the steps the lifecycle sweep's delete shares (session_archive.delete_leased).
        result = await (session_archive.delete_lineage(orch, session_id) if lineage
                        else session_archive.delete_leased(orch, session_id))
    except session_archive.SessionDeleteError as exc:
        gone = ({"deleted": exc.deleted, "backups": getattr(exc, "backups", []), "pruned": getattr(exc, "pruned", [])}
                if getattr(exc, "deleted", None) else {})
        return JSONResponse({"error": exc.reason.replace("_", " "), "reason": exc.reason, **gone},
                            status_code=_DELETE_STATUS.get(exc.reason, 500))
    return JSONResponse(result, headers=_NO_STORE)


_NO_STORE = {"Cache-Control": "no-store"}


@router.get("/sessions/{session_id}/trajectories", dependencies=[Depends(admin_guard)])
async def get_session_trajectories(session_id: str, format: str = "sharegpt", completed_only: bool = False,
                                   jsonl: bool = False, limit: int = 1000):
    """H652 — the session's saved full turns (system, prompt, tool calls, tool results,
    reply) as training data: ``format=sharegpt`` (Hermes ``conversations`` of from/value)
    or ``format=messages`` (OpenAI chat rows for ``training/sft_grpo.py``).
    ``completed_only`` keeps the turns that ended on the model's own answer; ``jsonl``
    answers one row per line. Admin only — a tool result can carry what the owner read.
    Capture is opt-in (``NERVA_SAVE_TRAJECTORIES``), so ``capture_enabled`` says why a
    session may have none."""
    import asyncio

    from fastapi.responses import Response

    from agents.core import trajectory

    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    if format not in trajectory.FORMATS:
        return JSONResponse({"error": f"format must be one of {', '.join(trajectory.FORMATS)}"},
                            status_code=400)
    rows = await asyncio.to_thread(trajectory.export, session_id, fmt=format,
                                   completed_only=completed_only, limit=limit)
    if jsonl:
        return Response(trajectory.to_jsonl(rows), media_type="application/x-ndjson", headers=_NO_STORE)
    return JSONResponse({"session_id": session_id, "format": format, "count": len(rows),
                         "capture_enabled": trajectory.capture_enabled(), "trajectories": rows},
                        headers=_NO_STORE)


#: How many plans the recent list returns — the Decision Inbox shows a few, `nerva todo`
#: prints them all.
RECENT_PLANS = 20


@router.get("/sessions/todo", dependencies=[Depends(user_guard)])
async def get_recent_plans(req: Request):
    """H315 — the checklists the agent keeps, the one it most recently wrote or read
    first (each carries ``updated_at``, when its list last changed)."""
    from agents.core import todo_tool

    plans = todo_tool.TODOS.recent(RECENT_PLANS)
    from agents import web
    if not web._web_principal(req).admin:
        orch = get_orch()
        if orch is None:
            return JSONResponse({"error": "not initialized"}, status_code=503)
        import asyncio

        from agents.core.foreign_history import status
        plans = [plan for plan in plans if not (await asyncio.to_thread(
            status, orch.checkpoints, plan.get("session_id", ""))).tainted]
    return JSONResponse({"plans": plans}, headers=_NO_STORE)


@router.get("/sessions/{session_id}/todo", dependencies=[Depends(user_guard)])
async def get_session_plan(session_id: str, req: Request):
    """H315 — one session's checklist; a session with none answers an empty list."""
    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    from agents.core.foreign_history import http_owner_guard
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    await http_owner_guard(orch.checkpoints, session_id, req)
    from agents.core import todo_tool

    return JSONResponse(todo_tool.TODOS.read(session_id), headers=_NO_STORE)


@router.post("/sessions/resume", dependencies=[Depends(user_guard)])
async def resume_session(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    sid = body.get("session_id") if isinstance(body, dict) else None
    title = body.get("title") if isinstance(body, dict) else None
    if not sid and title is not None:
        # H440 — resume by name: the newest member of the lineage that title names. A
        # caller who is not the owner resolves among native sessions only, as their list does.
        import asyncio

        from agents import web
        from agents.core.session_selectors import SessionSelectionError, resolve_title

        orch = get_orch()
        if not orch:
            return JSONResponse({"error": "not initialized"}, status_code=503)
        try:
            sid = await asyncio.to_thread(resolve_title, orch.checkpoints, title,
                                          native_only=not web._web_principal(req).admin)
        except SessionSelectionError as exc:
            return JSONResponse({"error": exc.reason, **({"candidates": exc.candidates} if exc.candidates else {})},
                                status_code=exc.status)
    if not sid:
        return JSONResponse({"error": "session_id or title required"}, status_code=400)
    # AUD-5: reject anything that isn't an inert identifier before it can reach a
    # filesystem path (memory/persistence.py builds MEMORY_DIR / f"{sid}.json").
    if not is_valid_session_id(sid):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.foreign_history import http_owner_guard
    await http_owner_guard(orch.checkpoints, sid, req)
    from agents.core.foreign_history import ForeignHistoryRefused
    from agents.core.session_continuation import ContinuationRefused

    try:
        ok = await orch.memory.resume_session(sid)
    except (ContinuationRefused, ForeignHistoryRefused) as exc:  # history cannot be restored
        return JSONResponse({"error": exc.reason}, status_code=exc.status)
    if not ok:
        return JSONResponse({"error": f"session '{sid}' not found"}, status_code=404)
    orch.session_id = sid
    checkpoints = getattr(orch, "checkpoints", None)
    if checkpoints is not None:
        _keep(checkpoints, sid)   # H218: resuming an archived chat brings it back (H262: pin kept, kept_at stamped)
    history = await orch.memory.get_history(sid)
    from agents.core.memory.recap import render_recap

    # H441 — the recap is rendered from the stored turns, never by a model; "turns"
    # stays the last 20 raw turns for the clients that replay them.
    return JSONResponse({"ok": True, "session": sid, "turns": history[-20:],
                         "recap": render_recap(history)})


class ContinueSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_session_id: str
    request_id: UUID

    @field_validator("source_session_id")
    @classmethod
    def valid_source(cls, value):
        if not is_valid_session_id(value):
            raise ValueError("invalid session_id")
        return value


@router.post("/sessions/continue", dependencies=[Depends(admin_guard)])
async def continue_session(body: ContinueSessionRequest):
    from agents.core.session_continuation import ContinuationRefused, create_continuation
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        result = await create_continuation(orch, body.source_session_id, str(body.request_id))
    except ContinuationRefused as exc:
        return JSONResponse({"error": exc.reason}, status_code=exc.status)
    return JSONResponse(result, status_code=201)
