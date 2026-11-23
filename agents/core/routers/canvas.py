"""Agent Canvas / A2UI endpoints (H12.18) — extracted from web.py (CLN-3)."""

import asyncio
import threading
import time
from functools import partial
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from agents.core.office_export import EXCEL_MIME, WORD_MIME, create_docx, create_xlsx
from agents.core.routers._deps import _web, admin_guard, user_guard

from agents.core.web_helpers import nocache_json, error_json, read_bounded_body
from agents.core.app_state import get_orch
from agents.core.workspace import extract


router = APIRouter(tags=["canvas"])

_canvas_store = None
_preview_slots = threading.BoundedSemaphore(2)
_blend_preview_slot = threading.BoundedSemaphore(1)


class OfficePreviewSegment(BaseModel):
    label: str
    text: str
    truncated: bool
    offset: int | None = None
    total_characters: int | None = None


class OfficePreview(BaseModel):
    kind: Literal["docx", "xlsx"]
    segments: list[OfficePreviewSegment]
    total_segments: int


class BlenderPreview(BaseModel):
    kind: Literal["blend"]
    segments: list[OfficePreviewSegment]
    total_segments: int
    thumbnail_png: str | None = None


def _release_preview_slot(task: asyncio.Task, *, slots: threading.BoundedSemaphore) -> None:
    slots.release()
    if not task.cancelled():
        task.exception()  # retrieve an error if the HTTP caller disconnected


def _get_canvas():
    orch = get_orch()
    if orch is not None and getattr(orch, "canvas", None) is not None:
        return orch.canvas
    global _canvas_store
    if _canvas_store is None:
        from agents.core.canvas import CanvasStore
        _canvas_store = CanvasStore()
    return _canvas_store


class CanvasPostBody(BaseModel):
    agent: str = Field("agent", max_length=64)
    type: str = Field(..., max_length=32)
    payload: dict = Field(default_factory=dict)
    pinned: bool = False


class WordExport(BaseModel, extra="forbid"):
    format: Literal["docx"]
    text: str = Field(min_length=1, max_length=65536)


class ExcelExport(BaseModel, extra="forbid"):
    format: Literal["xlsx"]
    rows: list[Annotated[list[str], Field(max_length=64)]] = Field(min_length=1, max_length=1001)


_EXPORT_BODY = TypeAdapter(Annotated[WordExport | ExcelExport, Field(discriminator="format")])


@router.post(
    "/api/canvas/export", dependencies=[Depends(user_guard)], response_class=Response,
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": {
        "oneOf": [WordExport.model_json_schema(), ExcelExport.model_json_schema()],
    }}}}},
    responses={200: {"content": {mime: {"schema": {"type": "string", "format": "binary"}}
                                for mime in (WORD_MIME, EXCEL_MIME)}}},
)
async def canvas_export(request: Request):
    """Download the supplied reply or table without storing its contents."""
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
        return nocache_json({"error": "Expected application/json"}, 415)
    raw = await read_bounded_body(request, 1024 * 1024)
    if raw is None:
        return nocache_json({"error": "Export request exceeds 1 MiB"}, 413)
    try:
        body = _EXPORT_BODY.validate_json(raw)
    except ValidationError:
        return nocache_json({"error": "Supply a Word reply or an Excel table within the export limits"}, 422)

    try:
        if isinstance(body, WordExport):
            data = await asyncio.to_thread(create_docx, body.text)
            mime, filename = WORD_MIME, "Nerva reply.docx"
        else:
            data = await asyncio.to_thread(create_xlsx, body.rows)
            mime, filename = EXCEL_MIME, "Nerva table.xlsx"
    except ValueError:
        return nocache_json({"error": "This content exceeds the format limits or contains unsupported characters"}, 422)
    except ModuleNotFoundError as exc:
        if exc.name != "docx":
            raise
        return nocache_json({"error": "The Word export dependency is unavailable"}, 503)
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    })


@router.post(
    "/api/canvas/office-preview", dependencies=[Depends(user_guard)],
    response_model=OfficePreview,
    openapi_extra={"requestBody": {"required": True, "content": {
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
    }}},
)
async def canvas_office_preview(request: Request, kind: str = Query(..., json_schema_extra={
    "enum": ["docx", "xlsx"],
}), offset: int = 0):
    """Read an owner-supplied Office file without saving or sending it to a model."""
    if kind not in ("docx", "xlsx"):
        return nocache_json({"error": "Choose docx or xlsx"}, 422)
    if offset < 0 or offset > extract.MAX_TEXT_CHARS or offset % 12000 or (kind != "docx" and offset):
        return nocache_json({"error": "Invalid preview offset"}, 422)
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/octet-stream":
        return nocache_json({"error": "Expected application/octet-stream"}, 415)
    if not _preview_slots.acquire(blocking=False):
        return nocache_json({"error": "Office preview is busy"}, 429)
    processing = None
    try:
        data = await read_bounded_body(request, 8 * 1024 * 1024)
        if data is None:
            return nocache_json({"error": "Office file exceeds 8 MiB"}, 413)
        if not data or not extract.content_matches(kind, data):
            return nocache_json({"error": "Invalid Office file"}, 422)
        processing = asyncio.create_task(extract.extract_document(data, kind))
        processing.add_done_callback(partial(_release_preview_slot, slots=_preview_slots))
        try:
            extracted = await asyncio.shield(processing)
        except extract.ExtractionError as exc:
            if exc.code == "no_text":
                return nocache_json({"error": "No readable content"}, 422)
            if exc.code == "too_much_text":
                return nocache_json({"error": "Office file contains too much text"}, 413)
            if exc.code == "timeout":
                return nocache_json({"error": "Office preview timed out"}, 503)
            return nocache_json({"error": "Invalid Office file"}, 422)
        segments = [segment.text for segment in extracted.segments if segment.text.strip()]
        if not segments:
            return nocache_json({"error": "No readable content"}, 422)
        if kind == "docx" and offset >= len(segments[0]):
            return nocache_json({"error": "Invalid preview offset"}, 422)
        return nocache_json({
            "kind": kind,
            "segments": [{
                "label": "Document" if kind == "docx" else text.partition("\n")[0].removeprefix("## "),
                "text": text[offset:offset + 12000],
                "truncated": len(text) > offset + 12000,
                **({"offset": offset, "total_characters": len(text)} if kind == "docx" else {}),
            } for text in segments[:32]],
            "total_segments": len(segments),
        })
    finally:
        if processing is None:
            _preview_slots.release()


@router.post(
    "/api/canvas/blender-preview", dependencies=[Depends(admin_guard)], response_model=BlenderPreview,
    openapi_extra={"requestBody": {"required": True, "content": {
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
    }}},
)
async def canvas_blender_preview(request: Request):
    """Read the project's library inventory with the hub's installed Blender."""
    from agents.core import blender_preview

    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/octet-stream":
        return nocache_json({"error": "Expected application/octet-stream"}, 415)
    if not _blend_preview_slot.acquire(blocking=False):
        return nocache_json({"error": "Blender preview is busy"}, 429)
    processing = None
    try:
        data = await read_bounded_body(request, blender_preview.MAX_BYTES)
        if data is None:
            return nocache_json({"error": "Blender file exceeds 64 MiB"}, 413)
        if not data:
            return nocache_json({"error": "Empty Blender file"}, 422)
        processing = asyncio.create_task(asyncio.to_thread(blender_preview.preview_blend, data))
        processing.add_done_callback(partial(_release_preview_slot, slots=_blend_preview_slot))
        return nocache_json(await asyncio.shield(processing))
    except blender_preview.BlenderUnavailable:
        return nocache_json({"error": "Blender inspection is unavailable on this hub"}, 503)
    except blender_preview.BlenderPreviewError:
        return nocache_json({"error": "Could not inspect this Blender project"}, 422)
    finally:
        if processing is None:
            _blend_preview_slot.release()


@router.post(
    "/api/canvas/blender-export", dependencies=[Depends(admin_guard)], response_class=Response,
    openapi_extra={"requestBody": {"required": True, "content": {
        "text/plain": {"schema": {"type": "string"}},
    }}},
    responses={200: {"content": {"application/x-blender": {
        "schema": {"type": "string", "format": "binary"},
    }}}},
)
async def canvas_blender_export(request: Request):
    """Download a native editable Blender mesh from a bounded OBJ subset."""
    from agents.core import blender_export, blender_preview

    content_type, _, charset = request.headers.get("content-type", "").partition(";")
    if content_type.strip().lower() != "text/plain" or (charset and charset.strip().lower() != "charset=utf-8"):
        return nocache_json({"error": "Expected text/plain UTF-8 OBJ"}, 415)
    if not _blend_preview_slot.acquire(blocking=False):
        return nocache_json({"error": "Blender is busy"}, 429)
    processing = None
    try:
        data = await read_bounded_body(request, blender_export.MAX_BYTES)
        if data is None:
            return nocache_json({"error": "OBJ exceeds 256 KiB"}, 413)
        processing = asyncio.create_task(asyncio.to_thread(blender_export.export_obj, data))
        processing.add_done_callback(partial(_release_preview_slot, slots=_blend_preview_slot))
        result = await asyncio.shield(processing)
        return Response(result, media_type="application/x-blender", headers={
            "Content-Disposition": 'attachment; filename="Nerva model.blend"',
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        })
    except blender_preview.BlenderUnavailable:
        return nocache_json({"error": "Blender export is unavailable on this hub"}, 503)
    except blender_export.BlenderExportError as exc:
        return nocache_json({"error": str(exc)}, 422)
    except blender_export.BlenderBuildError:
        return nocache_json({"error": "Blender could not save this model"}, 503)
    finally:
        if processing is None:
            _blend_preview_slot.release()


@router.get("/api/canvas", dependencies=[Depends(user_guard)])
async def canvas_list(agent: Optional[str] = None):
    return nocache_json({"elements": _get_canvas().list(agent)})


@router.get("/api/canvas/pointers", dependencies=[Depends(user_guard)])
async def canvas_pointers():
    """H309 — only the live tips and tours, with the hub's clock: what the HUD's pointer
    overlay polls, instead of the whole canvas every few seconds."""
    now = time.time()
    return nocache_json({"elements": _get_canvas().pointers(now), "now": now})


@router.post("/api/canvas/post", dependencies=[Depends(user_guard)])
async def canvas_post(body: CanvasPostBody, request: Request):
    """Add a typed, sanitized element. Unsafe/unknown types are rejected (422).

    H309: a tip or a tour posted here is marked untrusted unless the owner (an admin
    credential) sent it; the payload has no say in that."""
    untrusted = not _web()._web_principal(request).admin
    try:
        return nocache_json(_get_canvas().post(body.agent, body.type, body.payload,
                                                    pinned=body.pinned, untrusted=untrusted))
    except ValueError as e:
        return error_json(e, 422, "invalid or unsupported canvas element")


@router.post("/api/canvas/{el_id}/pin", dependencies=[Depends(user_guard)])
async def canvas_pin(el_id: str, pinned: bool = True):
    el = _get_canvas().pin(el_id, pinned)
    return nocache_json(el or {"error": "not found"}, status_code=200 if el else 404)


@router.delete("/api/canvas/{el_id}", dependencies=[Depends(user_guard)])
async def canvas_remove(el_id: str):
    ok = _get_canvas().remove(el_id)
    return nocache_json({"removed": ok}, status_code=200 if ok else 404)


@router.post("/api/canvas/clear", dependencies=[Depends(user_guard)])
async def canvas_clear(agent: Optional[str] = None, keep_pinned: bool = True):
    return nocache_json({"removed": _get_canvas().clear(agent, keep_pinned=keep_pinned)})
