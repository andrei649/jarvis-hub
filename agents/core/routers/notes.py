"""Conversation Notes endpoints (H10.21) — extracted from web.py (CLN-3)."""

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.routers._component import require_component

from agents.core.web_helpers import nocache_json, logger
from agents.core.app_state import get_orch


router = APIRouter(tags=["notes"])


class _NoteBody(BaseModel):
    content: str = Field("", max_length=20000)


@router.get("/api/notes", dependencies=[Depends(user_guard)])
async def notes_get():
    orch = get_orch()
    notes = getattr(orch, "notes", None) if orch else None
    sid = getattr(orch, "session_id", "web") if orch else "web"
    return nocache_json({"session": sid, "content": notes.get(sid) if notes else ""})


@router.put("/api/notes", dependencies=[Depends(user_guard)])
async def notes_set(body: _NoteBody):
    orch, notes, err = require_component("notes", "notes not available")
    if err is not None:
        return err
    sid = getattr(orch, "session_id", "web")
    return nocache_json({"ok": True, "session": sid, **notes.set(sid, body.content)})


@router.delete("/api/notes", dependencies=[Depends(user_guard)])
async def notes_clear():
    orch = get_orch()
    notes = getattr(orch, "notes", None) if orch else None
    sid = getattr(orch, "session_id", "web") if orch else "web"
    cleared = notes.clear(sid) if notes else False
    return nocache_json({"ok": True, "cleared": cleared})


@router.post("/api/notes/rewrite", dependencies=[Depends(user_guard)])
async def notes_rewrite(req: Request):
    """H10.21 — 'Rewrite with AI': run the note through an agent; optionally save."""
    orch, notes, err = require_component("notes", "notes not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    sid = getattr(orch, "session_id", "web")
    content = notes.get(sid)
    if not content.strip():
        return JSONResponse({"error": "note is empty"}, status_code=400)
    instruction = (body or {}).get("instruction") or "Rewrite these notes to be clearer and well-organized."
    prompt = f"{instruction}\n\n---\n{content}"
    try:
        rewritten = await orch.handle_input(prompt, channel="notes")
    except Exception:
        logger.exception("notes rewrite failed")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)
    saved = False
    if (body or {}).get("save"):
        notes.set(sid, rewritten)
        saved = True
    return nocache_json({"ok": True, "rewritten": rewritten, "saved": saved})


# ── DRA-53: the block-tree document store, adopted behind real routes ─────────
# `agents/core/notes_store.py` (H22.10) shipped fully tested and ADOPTED BY
# NOTHING — no route, no caller, no way for a person to reach it. The roadmap's
# framing was "adopt it behind a route or delete it"; this is the adoption.
#
# Two different stores share this router's prefix, deliberately: `/api/notes` is
# the per-session free-text scratch note injected into every turn (owned by
# `agents.core.notes`), while `/api/notes/docs` is the structured block tree with
# stable block ids (owned by `agents.core.notes_store`). The block store is
# imported inside each handler so importing this router never opens SQLite —
# `get_note_docs_store()` resolves `data_path("notes.db")` at call time, which is
# what lets a test process point it at its own JARVIS_HOME (or an in-memory DB).
class _DocTitle(BaseModel):
    title: str = Field("", max_length=200)


class _NewBlock(BaseModel):
    type: str = Field("paragraph", max_length=40)
    text: str = Field("", max_length=20000)
    parent_id: str | None = Field(None, max_length=64)
    after: str | None = Field(None, max_length=64)


class _BlockPatch(BaseModel):
    text: str | None = Field(None, max_length=20000)
    type: str | None = Field(None, max_length=40)


def _bad(exc: Exception) -> JSONResponse:
    """A store-level rejection (missing doc/block, cross-doc parent, cycle) is a
    bad request, not a server fault — map it to 400 with the real reason rather
    than letting it surface as an opaque 500."""
    return JSONResponse({"error": str(exc)}, status_code=400)


async def _docs_call(fn, *args, **kwargs):
    """Run a store call in a worker thread.

    Every NotesStore method takes a process-wide `threading.Lock` around SQLite
    work; rendering a large tree while holding it would otherwise block the
    event loop (same reasoning as `_kg_call` in the memory_kg router).
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


@router.get("/api/notes/docs", dependencies=[Depends(user_guard)])
async def note_docs_list(limit: int = 50):
    from agents.core.notes_store import get_note_docs_store

    store = get_note_docs_store()
    return nocache_json({"docs": await _docs_call(store.list_docs, max(1, min(limit, 200)))})


@router.post("/api/notes/docs", dependencies=[Depends(user_guard)])
async def note_docs_create(body: _DocTitle):
    from agents.core.notes_store import get_note_docs_store

    store = get_note_docs_store()
    return nocache_json({"ok": True, "id": await _docs_call(store.create_doc, body.title)})


@router.get("/api/notes/docs/{doc_id}", dependencies=[Depends(user_guard)])
async def note_docs_get(doc_id: str):
    from agents.core.notes_store import NotesStoreError, get_note_docs_store

    store = get_note_docs_store()
    try:
        return nocache_json(await _docs_call(store.render_tree, doc_id))
    except NotesStoreError as e:
        return _bad(e)


@router.delete("/api/notes/docs/{doc_id}", dependencies=[Depends(user_guard)])
async def note_docs_delete(doc_id: str):
    from agents.core.notes_store import NotesStoreError, get_note_docs_store

    store = get_note_docs_store()
    try:
        deleted = await _docs_call(store.delete_doc, doc_id)
    except NotesStoreError as e:
        return _bad(e)
    return nocache_json({"ok": True, "deleted": deleted})


@router.post("/api/notes/docs/{doc_id}/blocks", dependencies=[Depends(user_guard)])
async def note_docs_add_block(doc_id: str, body: _NewBlock):
    from agents.core.notes_store import NotesStoreError, get_note_docs_store

    store = get_note_docs_store()
    try:
        block_id = await _docs_call(
            store.add_block, doc_id, body.type or "paragraph", body.text,
            parent_id=body.parent_id or None, after=body.after or None,
        )
    except NotesStoreError as e:
        return _bad(e)
    return nocache_json({"ok": True, "id": block_id})


@router.patch("/api/notes/blocks/{block_id}", dependencies=[Depends(user_guard)])
async def note_docs_update_block(block_id: str, body: _BlockPatch):
    from agents.core.notes_store import NotesStoreError, get_note_docs_store

    store = get_note_docs_store()
    try:
        block = await _docs_call(store.update_block, block_id, text=body.text, type=body.type)
    except NotesStoreError as e:
        return _bad(e)
    return nocache_json({"ok": True, "block": block})


@router.delete("/api/notes/blocks/{block_id}", dependencies=[Depends(user_guard)])
async def note_docs_delete_block(block_id: str):
    from agents.core.notes_store import NotesStoreError, get_note_docs_store

    store = get_note_docs_store()
    try:
        deleted = await _docs_call(store.delete_block, block_id)
    except NotesStoreError as e:
        return _bad(e)
    return nocache_json({"ok": True, "deleted": deleted})
