"""Agent Canvas / A2UI endpoints (H12.18) — extracted from web.py (CLN-3)."""

import asyncio
import time
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from agents.core.office_export import EXCEL_MIME, WORD_MIME, create_docx, create_xlsx
from agents.core.routers._deps import _web, user_guard

from agents.core.web_helpers import nocache_json, error_json, read_bounded_body
from agents.core.app_state import get_orch


router = APIRouter(tags=["canvas"])

_canvas_store = None


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
