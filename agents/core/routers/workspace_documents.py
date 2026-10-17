"""Nerva Workspace — the company knowledge base (spec §7 "S2").

Every route needs a signed-in user (``WsUser``; mutating ones also pass the CSRF and
same-origin checks) and answers out-of-scope documents with ``404 not_found``. The
handlers stay thin: parsing and shaping here, rules and the pipeline in
``agents.core.workspace.documents`` (importing it registers the
``document.company_publish`` approval effect).

Uploads are a raw request body (no multipart): ``POST /documents?department_id=<id|
company>&filename=<name>[&title=…]``. The response is sent only after extraction and
indexing finished, with ``status`` ``ready`` or ``failed`` plus a stable ``error``.
Downloads are always attachments with ``nosniff`` and a sandboxing CSP, so a stored
HTML-looking file can never render in the workspace's origin.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agents.core.workspace import auth, documents
from agents.core.workspace.auth import WsUser
from agents.core.workspace.db import Db
from agents.core.workspace.http import MAX_ID, ws_json, ws_no_content

logger = logging.getLogger("nerva.workspace.routers.documents")

router = APIRouter(prefix="/api/workspace")

DocumentId = Annotated[int, Path(ge=1, le=MAX_ID)]
DepartmentFilter = Annotated[str | None, Query(max_length=32)]
SearchText = Annotated[str | None, Query(max_length=200)]
StatusFilter = Annotated[str | None, Query(pattern=r"^(processing|ready|failed)$")]

DOWNLOAD_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
_ASCII_FALLBACK = re.compile(r"[^A-Za-z0-9._ -]+")


def content_disposition(filename: str) -> str:
    """``attachment`` with an RFC 5987 UTF-8 name plus a plain-ASCII fallback name."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    fallback = _ASCII_FALLBACK.sub("_", ascii_name).strip(" .") or "document"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("/documents")
def list_documents(user: WsUser, conn: Db, department_id: DepartmentFilter = None,
                   q: SearchText = None, status: StatusFilter = None) -> JSONResponse:
    """Documents the caller may read, newest first (``department_id`` = an id or ``company``)."""
    scope = documents.parse_scope(department_id)
    items = documents.list_documents(conn, user, scope=scope, query=q, status=status)
    return ws_json({"documents": items})


@router.post("/documents")
async def upload_document(
    request: Request, user: WsUser, conn: Db,
    department_id: Annotated[str, Query(max_length=32)],
    filename: Annotated[str, Query(max_length=1024)],
    title: Annotated[str | None, Query(max_length=1024)] = None,
) -> JSONResponse:
    """Store, extract and index one file sent as the raw body → 201 document."""
    scope = documents.parse_scope(department_id, required=True)
    document = await documents.upload_document(conn, request, user, scope=scope,
                                               filename=filename, title=title,
                                               ip=auth.client_ip(request))
    return ws_json(document, status=201)


@router.get("/documents/{document_id}")
def get_document(document_id: DocumentId, user: WsUser, conn: Db) -> JSONResponse:
    """The document plus ``preview`` (its first 4 000 characters of text)."""
    return ws_json(documents.document_detail(conn, user, document_id))


@router.get("/documents/{document_id}/file")
def download_document(document_id: DocumentId, user: WsUser, conn: Db) -> StreamingResponse:
    """The original bytes, as an attachment that can never render inline."""
    row, stream, size = documents.open_original(conn, user, document_id)
    headers = {
        "Content-Disposition": content_disposition(row["filename"]),
        "Content-Length": str(size),
        "Content-Security-Policy": DOWNLOAD_CSP,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(stream, media_type=row["mime"], headers=headers)


@router.delete("/documents/{document_id}")
def delete_document(document_id: DocumentId, request: Request, user: WsUser,
                    conn: Db) -> Response:
    """Delete the document, its index entries and its stored file → 204."""
    documents.delete_document(conn, user, document_id, ip=auth.client_ip(request))
    return ws_no_content()


@router.post("/documents/{document_id}/reindex")
async def reindex_document(document_id: DocumentId, request: Request, user: WsUser,
                           conn: Db) -> JSONResponse:
    """Extract and index the stored original again → the document."""
    document = await documents.reindex_document(conn, user, document_id,
                                                ip=auth.client_ip(request))
    return ws_json(document)
