"""The HUD's Files panel — the owner's file browser over approved folders (G21 · H142).

Owner/admin only (``admin_guard``) on every route, reads included: a listing is a view of
the owner's disk. Writes also need this origin (``integrations_setup.same_origin_write``:
a browser-marked cross-site request is refused and a POST must be JSON); the upload is a
``PUT`` with a raw body, which no page can send cross-origin without a pre-check. Every
rule — approved folders, the credential denylist, no links, no hard links, the size caps —
lives in ``agents/core/file_browser.py``; a refusal is a bounded reason, never an echo.

* ``GET  /api/files/roots`` — the approved folders (opaque ids) and the limits.
* ``GET  /api/files/list?root=&path=`` — one folder; denied names hidden and counted.
* ``GET  /api/files/read?root=&path=`` — a text preview (256 KiB at most).
* ``GET  /api/files/download?root=&path=`` — the bytes, as an attachment
  (``application/octet-stream``, ``nosniff``), within ``JARVIS_FILE_BROWSER_MAX_BYTES``.
* ``PUT  /api/files/upload?root=&path=&name=`` — a new file; never replaces one (409).
* ``POST /api/files/mkdir`` — a new folder; never replaces one (409).
* ``POST /api/files/rename`` / ``POST /api/files/delete`` — **never applied here**: a
  ``files.rename`` / ``files.delete`` card at the approval queue's irreversible tier,
  answered 202 ``{"pending": task id}`` (an identical card already waiting is answered
  instead); 503 when no approval queue can take it.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from agents.core import file_browser as fb
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.routers.integrations_setup import same_origin_write
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.routers.files")

router = APIRouter(tags=["files"])

WRITE_GUARDS = [Depends(admin_guard), Depends(same_origin_write)]
_ROOT = Query(..., min_length=1, max_length=32)
_PATH = Query("", max_length=fb.MAX_REL_CHARS)


class FilesTargetBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    root: StrictStr = Field(min_length=1, max_length=32)
    path: StrictStr = Field(min_length=1, max_length=fb.MAX_REL_CHARS)


class FilesMkdirBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    root: StrictStr = Field(min_length=1, max_length=32)
    path: StrictStr = Field("", max_length=fb.MAX_REL_CHARS)
    name: StrictStr = Field(min_length=1, max_length=fb.MAX_NAME_CHARS)


class FilesRenameBody(FilesTargetBody):
    new_name: StrictStr = Field(min_length=1, max_length=fb.MAX_NAME_CHARS)


def _refusal(exc: fb.FileBrowserError):
    return nocache_json(exc.payload(), status_code=exc.status)


@router.get("/api/files/roots", dependencies=[Depends(admin_guard)])
async def files_roots():
    """The approved folders the browser may show, and its limits."""
    found = await asyncio.to_thread(fb.roots)
    return nocache_json({"roots": [r.view() for r in found], "max_bytes": fb.max_bytes(),
                         "preview_bytes": fb.PREVIEW_BYTES, "configured_by": fb.DIRS_ENV})


@router.get("/api/files/list", dependencies=[Depends(admin_guard)])
async def files_list(root: str = _ROOT, path: str = _PATH):
    try:
        return nocache_json(await asyncio.to_thread(fb.list_dir, root, path))
    except fb.FileBrowserError as exc:
        return _refusal(exc)


@router.get("/api/files/read", dependencies=[Depends(admin_guard)])
async def files_read(root: str = _ROOT, path: str = _PATH):
    try:
        return nocache_json(await asyncio.to_thread(fb.read_preview, root, path))
    except fb.FileBrowserError as exc:
        return _refusal(exc)


@router.get("/api/files/download", dependencies=[Depends(admin_guard)])
async def files_download(root: str = _ROOT, path: str = _PATH):
    try:
        download = await asyncio.to_thread(fb.prepare_download, root, path)
    except fb.FileBrowserError as exc:
        return _refusal(exc)
    await fb.audit(get_orch(), f"downloaded {download.size} bytes from {download.root.label}",
                   "file_browser_download")
    safe = download.name.encode("ascii", "replace").decode("ascii").replace('"', "_")
    headers = {
        "Content-Disposition": f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quote(download.name)}",
        "Content-Length": str(download.size),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(download.chunks(), media_type="application/octet-stream", headers=headers)


@router.put("/api/files/upload", dependencies=WRITE_GUARDS)
async def files_upload(request: Request, root: str = _ROOT, path: str = _PATH,
                       name: str = Query(..., min_length=1, max_length=fb.MAX_NAME_CHARS)):
    """A new file from the raw request body; never replaces an existing name."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > fb.max_bytes():
        return _refusal(fb.FileBrowserError("too_large"))
    try:
        upload = await asyncio.to_thread(fb.Upload, root, path, name)
    except fb.FileBrowserError as exc:
        return _refusal(exc)
    try:
        async for chunk in request.stream():
            if chunk:
                upload.write(chunk)
        result = await asyncio.to_thread(upload.commit)
    except fb.FileBrowserError as exc:
        return _refusal(exc)
    finally:
        await asyncio.to_thread(upload.close)
    await fb.audit(get_orch(), f"uploaded {result['size']} bytes into {upload.root.label}",
                   "file_browser_upload")
    return nocache_json({"ok": True, **result}, status_code=201)


@router.post("/api/files/mkdir", dependencies=WRITE_GUARDS)
async def files_mkdir(body: FilesMkdirBody):
    try:
        result = await asyncio.to_thread(fb.make_dir, body.root, body.path, body.name)
    except fb.FileBrowserError as exc:
        return _refusal(exc)
    await fb.audit(get_orch(), f"created a folder in {result['root']}", "file_browser_mkdir")
    return nocache_json({"ok": True, **result}, status_code=201)


async def _queue(kind: str, request: dict):
    """One card per identical request: an equal one already waiting is answered instead."""
    from agents.core.autonomy import irreversible

    orch = get_orch()
    for task in await asyncio.to_thread(irreversible.pending, orch, kind):
        payload = getattr(task, "payload", None) or {}
        if all(payload.get(k) == request["payload"].get(k)
               for k in ("op", "root_id", "path", "new_name", "target")):
            return nocache_json({"pending": int(task.id), "existing": True}, status_code=202)
    queued = irreversible.enqueue(orch, kind, **request)
    if "pending" not in queued:
        return nocache_json({"error": "approval_queue_unavailable", "reason": queued.get("refused"),
                             "detail": "a rename or delete needs the approval queue; nothing was changed"},
                            status_code=503)
    await fb.audit(orch, f"{kind} requested (task {queued['pending']}): {request['payload']['path']}",
                   "file_browser_request")
    return nocache_json({**queued, "preview": request["preview"]}, status_code=202)


@router.post("/api/files/delete", dependencies=WRITE_GUARDS)
async def files_delete(body: FilesTargetBody):
    """Queue a delete for the owner's decision; nothing is deleted on this request."""
    try:
        request = await asyncio.to_thread(fb.delete_request, body.root, body.path)
    except fb.FileBrowserError as exc:
        return _refusal(exc)
    return await _queue(fb.KIND_DELETE, request)


@router.post("/api/files/rename", dependencies=WRITE_GUARDS)
async def files_rename(body: FilesRenameBody):
    """Queue a rename (same folder) for the owner's decision; nothing moves on this request."""
    try:
        request = await asyncio.to_thread(fb.rename_request, body.root, body.path, body.new_name)
    except fb.FileBrowserError as exc:
        return _refusal(exc)
    return await _queue(fb.KIND_RENAME, request)
