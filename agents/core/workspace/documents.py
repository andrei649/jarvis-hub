"""Company documents: upload, indexing, access rules and the publish effect (spec §6, §7).

One upload, and why its steps run in this order:

1. Cheap refusals first — the extension allow-list, the target department, the
   per-user rate limit and the per-user cap on uploads in flight — so a refused upload
   never streams 25 MiB into memory.
2. The body is streamed under the size cap (``413 file_too_large`` the moment it is
   crossed) and its magic number is checked against the extension.
3. The bytes go to a private temporary file inside the store; then one ``BEGIN
   IMMEDIATE`` re-checks the rate limit, inserts the document as ``processing``, writes
   the audit row and renames the file to ``files/<id>.bin`` (parallel uploads cannot
   outrun the limit, and nobody ever sees the row without its file). The user's
   filename never touches the filesystem.
4. Extraction (worker thread, 60 s bound), chunking and indexing run outside any
   transaction. The outcome — ``ready`` with its chunks, or ``failed`` with a stable
   error code — is written in one transaction that applies only while the row is
   still the ``processing`` claim this run made (its ``updated_at`` stamp). Document
   ids can be reused once the newest document is deleted, so a late result must
   never land on a newer document that took the same id — that would index one
   department's text under another department's document.

Access rules (§6): everyone reads their own departments' documents plus every
company-wide one, admins read everything, and a document out of scope answers
``404 not_found``. Uploading needs membership of the target department (admins may
upload to any live department, or company-wide). Deleting and re-indexing: the
uploader, an approver of the document's department, or an admin. Making a department
document company-wide is the ``document.company_publish`` approval, decided by an admin.

Chunks are about :data:`CHUNK_TARGET` characters, cut at paragraph, line or sentence
boundaries, and each one repeats up to :data:`CHUNK_OVERLAP` characters of the end of
the previous one, so a fact split across a boundary is still retrievable in one piece.
A Markdown table is split between rows and every part repeats the header row, so a
retrieved slice of a spreadsheet still says what its columns mean.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import tempfile
import threading
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from fastapi import Request
from starlette.requests import ClientDisconnect

from agents.core.workspace import audit, config, db, extract, notifications, retrieval
from agents.core.workspace.effects_api import EffectSpec, ValidatedRequest, register_effect
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.http import MAX_ID, invalid, offload, require_int, require_str
from agents.core.workspace.identity import COMPANY, WorkspaceUser

logger = logging.getLogger("nerva.workspace.documents")

FILES_DIR = config.FILES_DIRNAME
PUBLISH_KIND = "document.company_publish"
MAX_FILENAME = 255
MAX_TITLE = 200
PREVIEW_CHARS = 4000
#: Per user and hour. Re-indexing re-runs the same extraction, so it spends from the
#: same budget — otherwise one user could keep the extraction pool busy at will.
UPLOADS_PER_HOUR = 60
UPLOAD_WINDOW_SECONDS = 3600
#: Uploads one user may have in flight at once. Each holds its whole body in memory
#: until it is indexed; the workspace UI sends one file at a time.
PARALLEL_UPLOADS_PER_USER = 3
PARALLEL_RETRY_SECONDS = 5
#: A ``processing`` row this old belongs to an upload that died (extraction is bounded
#: at 60 s); it may be re-indexed instead of answering ``document_busy`` forever.
STALE_PROCESSING_SECONDS = 600
CHUNK_TARGET = 1000
CHUNK_OVERLAP = 150
FILE_CHUNK_BYTES = 256 * 1024

_MIN_FILL = 200      # never close a chunk smaller than this, even if the next piece is big
_MIN_OVERLAP = 20    # a shorter overlap adds noise, not context
_MAX_HEADING = 200
_PREVIEW_CHUNKS = 16
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")
_TABLE_RULE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")
_WHITESPACE = re.compile(r"\s")
# Bidirectional overrides make "raport\u202efdp.exe" display as "raportexe.pdf"; they
# are removed from names and titles so what a colleague sees is what was uploaded.
_BIDI_CONTROLS = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")

_NOTIFY_TITLES = {
    "ro": "Document publicat în toată compania",
    "en": "Document published company-wide",
}

_DOCUMENT_COLUMNS_SQL = (
    "SELECT d.*, u.name AS uploader_name, dep.name AS department_name FROM documents d "
    "LEFT JOIN users u ON u.id = d.uploader_id "
    "LEFT JOIN departments dep ON dep.id = d.department_id WHERE d.id = ?"
)
_SAME_DOCUMENT_SQL = (
    "SELECT d.*, u.name AS uploader_name, dep.name AS department_name FROM documents d "
    "LEFT JOIN users u ON u.id = d.uploader_id "
    "LEFT JOIN departments dep ON dep.id = d.department_id "
    "WHERE d.id = ? AND d.created_at = ?"
)
_VISIBLE_DOCUMENT_SQL = (
    "SELECT d.*, u.name AS uploader_name, dep.name AS department_name FROM documents d "
    "LEFT JOIN users u ON u.id = d.uploader_id "
    "LEFT JOIN departments dep ON dep.id = d.department_id "
    "WHERE d.id = ? AND (? = 1 OR d.visibility = 'company' "
    "OR d.department_id IN (SELECT value FROM json_each(?)))"
)
_VISIBLE_IDS_SQL = (
    "SELECT d.id FROM documents d WHERE d.id IN (SELECT value FROM json_each(?)) "
    "AND (? = 1 OR d.visibility = 'company' OR d.department_id IN (SELECT value FROM json_each(?)))"
)
_LIST_SQL = (
    "SELECT d.*, u.name AS uploader_name, dep.name AS department_name FROM documents d "
    "LEFT JOIN users u ON u.id = d.uploader_id "
    "LEFT JOIN departments dep ON dep.id = d.department_id "
    "WHERE (? = 1 OR d.visibility = 'company' "
    "OR d.department_id IN (SELECT value FROM json_each(?))) "
    "AND (? IS NULL OR d.status = ?) "
    "AND (? IS NULL OR d.department_id = ?) "
    "AND (? = 0 OR d.visibility = 'company') "
    "ORDER BY d.created_at DESC, d.id DESC"
)
_CONTENT_MATCH_SQL = (
    "SELECT DISTINCT c.document_id FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
    "WHERE chunks_fts MATCH ? AND c.document_id IN (SELECT value FROM json_each(?))"
)
_PENDING_PUBLISH_SQL = (
    "SELECT payload_json FROM approvals WHERE kind = ? AND status IN ('pending', 'executing')"
)
_RECENT_UPLOADS_SQL = (
    "SELECT ts FROM audit WHERE actor_user_id = ? "
    "AND action IN ('document.uploaded', 'document.reindexed') AND ts > ? "
    "ORDER BY ts DESC LIMIT ?"
)


# ── errors ───────────────────────────────────────────────────────────────────────────

def _not_found() -> WorkspaceError:
    return WorkspaceError("not_found", "document not found", 404)


def _forbidden() -> WorkspaceError:
    return WorkspaceError("forbidden", "you may not change this document", 403)


def _unsupported(reason: str) -> WorkspaceError:
    message = ("this file type is not accepted" if reason == "extension"
               else "the file's content does not match its extension")
    return WorkspaceError("unsupported_file_type", message, 415, reason=reason,
                          allowed=list(extract.ALLOWED_EXTENSIONS))


def _too_large(limit: int) -> WorkspaceError:
    return WorkspaceError("file_too_large", "the file is larger than the upload limit", 413,
                          max_bytes=limit)


def _storage_failed() -> WorkspaceError:
    return WorkspaceError("storage_failed", "the file could not be stored", 507)


# ── storage ──────────────────────────────────────────────────────────────────────────

def files_dir() -> Path:
    """``<data>/business/files`` (mode 0700, created on demand)."""
    path = config.workspace_dir() / FILES_DIR
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def file_path(document_id: int) -> Path:
    """Where the original bytes of a document live: ``files/<id>.bin``."""
    return files_dir() / f"{int(document_id)}.bin"


def _write_temp(data: bytes) -> Path:
    """*data* in a fresh 0600 file inside the store (renamed into place once the id exists)."""
    fd, name = tempfile.mkstemp(dir=files_dir(), prefix=".upload-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with suppress(OSError):
            os.unlink(name)
        raise
    return Path(name)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_chunks(handle: BinaryIO) -> Iterator[bytes]:
    """The rest of the open *handle* in :data:`FILE_CHUNK_BYTES` pieces, then closes it."""
    with handle:
        while chunk := handle.read(FILE_CHUNK_BYTES):
            yield chunk


# ── input parsing ────────────────────────────────────────────────────────────────────

def parse_scope(value: str | None, *, required: bool = False,
                field: str = "department_id") -> int | str | None:
    """A ``department_id`` query value: a department id, :data:`COMPANY`, or ``None``."""
    text = (value or "").strip()
    if not text:
        if required:
            raise invalid(field, "required")
        return None
    if text.lower() == COMPANY:
        return COMPANY
    if not (text.isascii() and text.isdigit()):
        raise invalid(field, "malformed", f"{field} must be a department id or 'company'")
    number = int(text)
    if number < 1:
        raise invalid(field, "too_small")
    if number > MAX_ID:
        raise invalid(field, "too_large")
    return number


def clean_filename(raw: str) -> str:
    """The display name of an upload: its last path part, NFC, single-line, ≤ 255 chars."""
    name = _BIDI_CONTROLS.sub("", unicodedata.normalize("NFC", raw))
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return require_str({"filename": name}, "filename", max_len=MAX_FILENAME, min_len=1)


def clean_title(raw: str | None, filename: str) -> str:
    """The given title, or one derived from the filename (``Politica_concedii.pdf`` →
    ``Politica concedii``)."""
    if raw is not None and raw.strip():
        title = _BIDI_CONTROLS.sub("", unicodedata.normalize("NFC", raw))
        return require_str({"title": title}, "title", max_len=MAX_TITLE)
    stem = " ".join(PurePosixPath(filename).stem.replace("_", " ").split())
    return (stem or filename)[:MAX_TITLE].strip() or filename[:MAX_TITLE]


# ── access rules ─────────────────────────────────────────────────────────────────────

def can_view(user: WorkspaceUser, row: sqlite3.Row) -> bool:
    """Admins see everything; others company-wide documents and their departments' ones."""
    if user.is_admin or row["visibility"] == "company":
        return True
    department_id = row["department_id"]
    return department_id is not None and department_id in user.department_ids


def can_manage(user: WorkspaceUser, row: sqlite3.Row) -> bool:
    """Delete / re-index: admins, the uploader, or an approver of the document's department."""
    if user.is_admin:
        return True
    if not can_view(user, row):
        return False
    if row["uploader_id"] == user.id:
        return True
    department_id = row["department_id"]
    return department_id is not None and user.can_approve_in(int(department_id))


def _scope_params(user: WorkspaceUser) -> tuple[int, str]:
    return (1 if user.is_admin else 0), json.dumps(list(user.department_ids))


def visible_document(conn: sqlite3.Connection, user: WorkspaceUser,
                     document_id: int) -> sqlite3.Row:
    """The document row (with uploader and department names) or ``404 not_found``."""
    row = conn.execute(_VISIBLE_DOCUMENT_SQL, (document_id, *_scope_params(user))).fetchone()
    if row is None:
        raise _not_found()
    return row


def visible_ids(conn: sqlite3.Connection, user: WorkspaceUser,
                document_ids: Iterable[int]) -> set[int]:
    """The ids among *document_ids* that *user* may open now (the rule of ``visible_document``).

    For content that quotes documents to readers outside their department, such as a report run
    shared company-wide: its citations keep their excerpts, but only these ids may be offered as
    a link to the document or its file.
    """
    ids = sorted({int(document_id) for document_id in document_ids})
    if not ids:
        return set()
    rows = conn.execute(_VISIBLE_IDS_SQL, (json.dumps(ids), *_scope_params(user))).fetchall()
    return {int(row["id"]) for row in rows}


def _document_row(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row:
    row = conn.execute(_DOCUMENT_COLUMNS_SQL, (document_id,)).fetchone()
    if row is None:
        raise _not_found()
    return row


def _same_document(conn: sqlite3.Connection, document_id: int,
                   created_at: float) -> sqlite3.Row:
    """The row of *document_id* while it is still the document created at *created_at*.

    After a long extraction the id may belong to a newer document (deleted meanwhile,
    id reused) — possibly another department's, which must not be shown: ``404``.
    """
    row = conn.execute(_SAME_DOCUMENT_SQL, (document_id, created_at)).fetchone()
    if row is None:
        raise _not_found()
    return row


def _require_department(conn: sqlite3.Connection, user: WorkspaceUser,
                        department_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT id, archived FROM departments WHERE id = ?",
                       (department_id,)).fetchone()
    if row is None or not user.can_access_department(department_id):
        raise WorkspaceError("not_found", "department not found", 404)
    return row


def upload_target(conn: sqlite3.Connection, user: WorkspaceUser,
                  scope: int | str) -> tuple[int | None, str]:
    """``(department_id, visibility)`` for an upload, or the error that refuses it."""
    if scope == COMPANY:
        if not user.is_admin:
            raise WorkspaceError("forbidden", "only administrators upload company-wide", 403)
        return None, "company"
    department = _require_department(conn, user, int(scope))
    if department["archived"]:
        raise WorkspaceError("department_archived", "the department is archived", 409)
    return int(department["id"]), "department"


# ── JSON shapes and listing ──────────────────────────────────────────────────────────

def _names_document(payload: dict, row: sqlite3.Row) -> bool:
    """Whether a publish payload names *row* itself, not an older document with its id.

    Ids are reused once the newest document is deleted, so the payload also carries the
    document's ``created_at``; a request for a deleted document must never publish the
    newer one that took its id.
    """
    return payload.get("document_id") == row["id"] and payload.get("created_at") == row[
        "created_at"]


def _pending_publish(conn: sqlite3.Connection) -> list[dict]:
    """The payloads of open (pending or executing) publish requests; bad JSON is skipped."""
    payloads = []
    for row in conn.execute(_PENDING_PUBLISH_SQL, (PUBLISH_KIND,)).fetchall():
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _publish_pending(row: sqlite3.Row, pending: Sequence[dict]) -> bool:
    return any(_names_document(payload, row) for payload in pending)


def _busy(row: sqlite3.Row) -> bool:
    return (row["status"] == "processing"
            and row["updated_at"] > db.now() - STALE_PROCESSING_SECONDS)


#: ``documents.error`` of an extraction that died with its process (a restart, a crash).
INTERRUPTED = "interrupted"


def fail_interrupted(conn: sqlite3.Connection, now: float, *,
                     claimed_before: float | None = None) -> int:
    """``processing`` documents whose extraction cannot still be running → ``failed``.

    Extraction runs inside the upload or re-index request and is bounded at 60 s, so a
    claim older than :data:`STALE_PROCESSING_SECONDS` — or one made before this process
    started (*claimed_before*: one hub per data root) — belongs to a request that died
    with its process. Such a document would otherwise read as ``processing`` for ever;
    it becomes ``failed`` / ``interrupted``, and Reindex works on it at once. Partial
    chunks go, as for any failed extraction. Returns how many documents were failed.
    """
    cutoff = now - STALE_PROCESSING_SECONDS
    if claimed_before is not None:
        cutoff = max(cutoff, claimed_before - 1e-6)
    with db.tx(conn):
        ids = [int(row[0]) for row in conn.execute(
            "SELECT id FROM documents WHERE status = 'processing' AND updated_at <= ?",
            (cutoff,)).fetchall()]
        if not ids:
            return 0
        listed = json.dumps(ids)
        conn.execute("DELETE FROM chunks WHERE document_id IN (SELECT value FROM json_each(?))",
                     (listed,))
        conn.execute(
            "UPDATE documents SET status = 'failed', error = ?, chunk_count = 0, char_count = 0, "
            "updated_at = ? WHERE status = 'processing' AND id IN (SELECT value FROM json_each(?))",
            (INTERRUPTED, now, listed),
        )
    logger.info("%d document(s) left processing by an interrupted extraction marked failed",
                len(ids))
    return len(ids)


def document_json(row: sqlite3.Row, user: WorkspaceUser, *,
                  publish_pending: bool = False) -> dict:
    """A document as the API shows it, with what *user* may do to it."""
    manage = can_manage(user, row)
    uploader = None
    if row["uploader_id"] is not None:
        uploader = {"id": int(row["uploader_id"]), "name": row["uploader_name"] or ""}
    return {
        "id": int(row["id"]), "title": row["title"], "filename": row["filename"],
        "mime": row["mime"], "size_bytes": int(row["size_bytes"]),
        "department_id": row["department_id"], "department_name": row["department_name"],
        "visibility": row["visibility"], "status": row["status"], "error": row["error"],
        "page_count": row["page_count"], "chunk_count": int(row["chunk_count"]),
        "char_count": int(row["char_count"]), "uploader": uploader,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "can_delete": manage, "can_reindex": manage and not _busy(row),
        "can_publish": (row["visibility"] == "department" and row["status"] == "ready"
                        and not publish_pending),
        "publish_pending": publish_pending,
    }


def _content_matches(conn: sqlite3.Connection, query: str, ids: list[int]) -> set[int]:
    match = retrieval.build_match_query(query, require_all=True)
    if not match or not ids:
        return set()
    try:
        rows = conn.execute(_CONTENT_MATCH_SQL, (match, json.dumps(ids))).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("document search failed (%s)",
                       getattr(exc, "sqlite_errorname", type(exc).__name__))
        return set()
    return {int(row["document_id"]) for row in rows}


def _filter_by_text(conn: sqlite3.Connection, rows: list[sqlite3.Row],
                    query: str) -> list[sqlite3.Row]:
    """Rows whose title/filename holds the query (folded) or whose text has every term."""
    needle = " ".join(retrieval.fold(query).split())
    terms = retrieval.query_terms(query)
    in_text = _content_matches(conn, query, [int(row["id"]) for row in rows])

    def hit(row: sqlite3.Row) -> bool:
        haystack = retrieval.fold(f"{row['title']} {row['filename']}")
        return ((bool(needle) and needle in haystack)
                or (bool(terms) and all(term in haystack for term in terms))
                or int(row["id"]) in in_text)

    return [row for row in rows if hit(row)]


def list_documents(conn: sqlite3.Connection, user: WorkspaceUser, *,
                   scope: int | str | None = None, query: str | None = None,
                   status: str | None = None) -> list[dict]:
    """The documents *user* may read, newest first, optionally filtered.

    *scope* is a department id (its documents, both visibilities) or :data:`COMPANY`
    (company-wide documents only); a department outside the caller's scope is a 404.
    *query* matches titles and filenames (case- and diacritic-insensitive) or, with every
    word, the indexed text.
    """
    department_id = scope if isinstance(scope, int) else None
    if department_id is not None:
        _require_department(conn, user, department_id)
    rows = conn.execute(_LIST_SQL, (*_scope_params(user), status, status, department_id,
                                    department_id, 1 if scope == COMPANY else 0)).fetchall()
    if query and query.strip():
        rows = _filter_by_text(conn, rows, query)
    pending = _pending_publish(conn)
    return [document_json(row, user, publish_pending=_publish_pending(row, pending))
            for row in rows]


def _overlap_length(previous: str, current: str) -> int:
    """Length of the start of *current* that repeats the end of *previous* (0 if none)."""
    longest = min(len(current), len(previous), CHUNK_OVERLAP)
    for length in range(longest, _MIN_OVERLAP - 1, -1):
        if (length == len(current) or current[length].isspace()) and previous.endswith(
                current[:length]):
            return length
    return 0


def preview_text(conn: sqlite3.Connection, document_id: int, *,
                 limit: int = PREVIEW_CHARS) -> str:
    """The first *limit* characters of the document's text, rebuilt from its chunks.

    The overlap each chunk repeats from the previous one is removed again, so the
    preview reads like the document rather than stuttering at every chunk boundary.
    """
    rows = conn.execute("SELECT text FROM chunks WHERE document_id = ? ORDER BY ord LIMIT ?",
                        (document_id, _PREVIEW_CHUNKS)).fetchall()
    merged = ""
    for row in rows:
        text = row["text"]
        if not merged:
            merged = text
        else:
            repeated = _overlap_length(merged, text)
            merged += text[repeated:] if repeated else "\n\n" + text
        if len(merged) >= limit:
            break
    return merged[:limit]


def document_detail(conn: sqlite3.Connection, user: WorkspaceUser, document_id: int) -> dict:
    """``GET /documents/{id}``: the document plus a ``preview`` of its text."""
    row = visible_document(conn, user, document_id)
    data = document_json(row, user, publish_pending=_publish_pending(row, _pending_publish(conn)))
    data["preview"] = preview_text(conn, document_id)
    return data


# ── chunking ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Chunk:
    """One indexed passage: its position, the page it starts on (PDF) and its text."""

    ord: int
    page: int | None
    text: str


@dataclass(frozen=True)
class _Piece:
    """An unsplittable unit of text; ``sep`` joins it to the piece before it in a chunk."""

    text: str
    page: int | None
    sep: str
    carry: bool  # may be repeated as overlap (table parts may not: half a row misleads)


def _hard_split(text: str, target: int) -> list[str]:
    """*text* in word-bounded parts of at most *target* chars (longer words are cut)."""
    parts: list[str] = []
    current = ""
    for word in text.split():
        if len(word) > target:  # cut by index: re-slicing the rest each time is quadratic
            if current:
                parts.append(current)
                current = ""
            whole = len(word) - (len(word) % target or target)
            parts.extend(word[start:start + target] for start in range(0, whole, target))
            word = word[whole:]
        if current and len(current) + 1 + len(word) > target:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        parts.append(current)
    return parts


def _long_paragraph(paragraph: str, page: int | None, target: int) -> Iterator[_Piece]:
    """A paragraph over *target*: its lines, then sentences, then words, as pieces."""
    parts: list[tuple[str, str]] = []
    for line in paragraph.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(line) <= target:
            parts.append((line, "\n"))
            continue
        first = True
        for sentence in _SENTENCE_END.split(line):
            for part in _hard_split(sentence, target):
                parts.append((part, "\n" if first else " "))
                first = False
    for index, (text, sep) in enumerate(parts):
        yield _Piece(text, page, "\n\n" if index == 0 else sep, True)


def _is_table(lines: Sequence[str]) -> bool:
    return (len(lines) >= 2 and all(line.startswith("|") for line in lines)
            and bool(_TABLE_RULE.match(lines[1].strip())))


def _table_pieces(lines: list[str], page: int | None, target: int,
                  heading: str | None) -> Iterator[_Piece]:
    """A Markdown table split between rows; every later part repeats heading and header."""
    text = "\n".join(lines)
    if len(text) <= target:
        yield _Piece(text, page, "\n\n", False)
        return
    header = lines[:2]
    repeat = ([heading, ""] if heading else []) + header
    repeat_size = sum(len(line) + 1 for line in repeat)
    group, size, rows_in_group = list(header), sum(len(line) + 1 for line in header), 0
    for row in lines[2:]:
        if repeat_size + len(row) > target:  # a single row longer than a chunk
            if rows_in_group:
                yield _Piece("\n".join(group), page, "\n\n", False)
            for part in _hard_split(row, target):
                yield _Piece(part, page, "\n", False)
            group, size, rows_in_group = list(repeat), repeat_size, 0
            continue
        if rows_in_group and size + len(row) > target:
            yield _Piece("\n".join(group), page, "\n\n", False)
            group, size, rows_in_group = list(repeat), repeat_size, 0
        group.append(row)
        size += len(row) + 1
        rows_in_group += 1
    if rows_in_group:
        yield _Piece("\n".join(group), page, "\n\n", False)


def _pieces(segments: Sequence[extract.Segment], target: int) -> Iterator[_Piece]:
    heading: str | None = None
    for segment in segments:
        for raw in _PARAGRAPH_BREAK.split(segment.text):
            paragraph = raw.strip()
            if not paragraph:
                continue
            lines = paragraph.split("\n")
            if _is_table(lines):
                yield from _table_pieces(lines, segment.page, target, heading)
                heading = None
                continue
            is_heading = (paragraph.startswith("#") and len(paragraph) <= _MAX_HEADING
                          and len(lines) == 1)
            heading = paragraph if is_heading else None
            if len(paragraph) <= target:
                yield _Piece(paragraph, segment.page, "\n\n", True)
            else:
                yield from _long_paragraph(paragraph, segment.page, target)


def _joined_length(pieces: Sequence[_Piece]) -> int:
    if not pieces:
        return 0
    return len(pieces[0].text) + sum(len(p.sep) + len(p.text) for p in pieces[1:])


def _tail(text: str, overlap: int) -> str:
    """The last ≤ *overlap* chars of *text*, starting at a word boundary."""
    if len(text) <= overlap:
        return text
    boundary = _WHITESPACE.search(text, len(text) - overlap)
    return text[boundary.end():].lstrip() if boundary else ""


def _overlap_pieces(pieces: Sequence[_Piece], overlap: int) -> list[_Piece]:
    """The end of a closed chunk to repeat at the start of the next one (maybe nothing).

    Never the whole chunk: a chunk no longer than the overlap carries nothing.
    """
    if overlap <= 0 or _joined_length(pieces) <= overlap:
        return []
    carried: list[_Piece] = []
    size = 0
    for piece in reversed(pieces):
        if not piece.carry:
            break
        added = len(piece.text) + (len(carried[0].sep) if carried else 0)
        if size + added > overlap:
            break
        carried.insert(0, piece)
        size += added
    if not carried and pieces[-1].carry:
        tail = _tail(pieces[-1].text, overlap)
        if tail:
            carried = [_Piece(tail, pieces[-1].page, pieces[-1].sep, True)]
    return carried if _joined_length(carried) >= _MIN_OVERLAP else []


def _make_chunk(ord_: int, pieces: Sequence[_Piece], page: int | None) -> Chunk:
    text = pieces[0].text + "".join(piece.sep + piece.text for piece in pieces[1:])
    return Chunk(ord=ord_, page=page, text=text)


def chunk_segments(segments: Sequence[extract.Segment], *, target: int = CHUNK_TARGET,
                   overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    """Pack the extracted text into chunks of about *target* chars with *overlap*.

    A chunk's ``page`` is the page its first new (non-overlap) text comes from.
    """
    chunks: list[Chunk] = []
    current: list[_Piece] = []
    size = 0
    fresh_page: int | None = None
    has_fresh = False
    for piece in _pieces(segments, target):
        added = len(piece.text) + (len(piece.sep) if current else 0)
        if has_fresh and size + added > target and size >= _MIN_FILL:
            chunks.append(_make_chunk(len(chunks), current, fresh_page))
            current = _overlap_pieces(current, overlap)
            size = _joined_length(current)
            has_fresh = False
            added = len(piece.text) + (len(piece.sep) if current else 0)
        if not has_fresh:
            fresh_page = piece.page
            has_fresh = True
        current.append(piece)
        size += added
    if has_fresh:
        chunks.append(_make_chunk(len(chunks), current, fresh_page))
    return chunks


# ── the upload pipeline ──────────────────────────────────────────────────────────────

def _recent_upload_times(conn: sqlite3.Connection, user_id: int, stamp: float) -> list[float]:
    rows = conn.execute(_RECENT_UPLOADS_SQL,
                        (user_id, stamp - UPLOAD_WINDOW_SECONDS, UPLOADS_PER_HOUR)).fetchall()
    return [float(row["ts"]) for row in rows]


def check_upload_rate(conn: sqlite3.Connection, user_id: int) -> None:
    """``429 rate_limited`` after :data:`UPLOADS_PER_HOUR` uploads and re-indexes in an hour.

    Counted from the audit trail, which a deleted document does not shrink — deleting
    and re-uploading cannot reset the budget.
    """
    stamp = db.now()
    times = _recent_upload_times(conn, user_id, stamp)
    if len(times) >= UPLOADS_PER_HOUR:
        retry = max(1, math.ceil(times[UPLOADS_PER_HOUR - 1] + UPLOAD_WINDOW_SECONDS - stamp))
        raise WorkspaceError("rate_limited", "too many uploads or re-indexes; try again later",
                             429, retry_after_seconds=retry)


_in_flight: Counter[int] = Counter()
_in_flight_lock = threading.Lock()


@contextmanager
def _upload_slot(user_id: int) -> Iterator[None]:
    """Hold one of the user's :data:`PARALLEL_UPLOADS_PER_USER` slots, else ``429``.

    The hourly budget counts finished uploads only, so without this cap one user could
    open dozens of parallel uploads and hold all their bodies in memory at once.
    """
    with _in_flight_lock:
        if _in_flight[user_id] >= PARALLEL_UPLOADS_PER_USER:
            raise WorkspaceError("rate_limited", "another upload of yours is still running", 429,
                                 retry_after_seconds=PARALLEL_RETRY_SECONDS)
        _in_flight[user_id] += 1
    try:
        yield
    finally:
        with _in_flight_lock:
            _in_flight[user_id] -= 1
            if _in_flight[user_id] <= 0:
                del _in_flight[user_id]


async def read_upload(request: Request, limit: int) -> bytes:
    """The raw request body, refused with ``413 file_too_large`` as soon as it passes *limit*."""
    declared = request.headers.get("content-length", "").strip()
    if declared.isdigit() and int(declared) > limit:
        raise _too_large(limit)
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > limit:
                raise _too_large(limit)
            body.extend(chunk)
    except ClientDisconnect as exc:
        raise WorkspaceError("upload_interrupted", "the upload was interrupted", 400) from exc
    return bytes(body)


@dataclass(frozen=True)
class _Upload:
    department_id: int | None
    visibility: str
    title: str
    filename: str
    kind: str
    size: int
    sha256: str


def _reserve(conn: sqlite3.Connection, user: WorkspaceUser, upload: _Upload, temp: Path,
             ip: str) -> tuple[int, float]:
    """Insert the ``processing`` row, audit it and move the file into place — one transaction.

    Returns the id and the claim stamp (``updated_at``) the result must match. The rate
    limit is re-checked under the write lock, and the file is renamed while that lock is
    held, so a concurrent delete can never see the row without its file nor leave an
    orphaned file behind. Any failure rolls everything back and removes the bytes.
    """
    moved = False
    try:
        with db.tx(conn):
            check_upload_rate(conn, user.id)
            stamp = db.now()
            document_id = int(conn.execute(
                "INSERT INTO documents (department_id, visibility, title, filename, mime, "
                "size_bytes, sha256, uploader_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'processing', ?, ?)",
                (upload.department_id, upload.visibility, upload.title, upload.filename,
                 extract.MIME_TYPES[upload.kind], upload.size, upload.sha256, user.id, stamp,
                 stamp),
            ).lastrowid)
            audit.record(conn, actor=user, action="document.uploaded", target_type="document",
                         target_id=document_id, department_id=upload.department_id, ip=ip,
                         details={"title": upload.title, "filename": upload.filename,
                                  "mime": extract.MIME_TYPES[upload.kind],
                                  "size_bytes": upload.size, "visibility": upload.visibility,
                                  "sha256": upload.sha256})
            os.replace(temp, file_path(document_id))
            moved = True
    except BaseException as exc:
        with suppress(OSError):
            (file_path(document_id) if moved else temp).unlink()
        if isinstance(exc, OSError):
            logger.error("an upload could not be moved into the document store (%s)",
                         type(exc).__name__)
            raise _storage_failed() from exc
        raise
    return document_id, stamp


def _store_failure(document_id: int, claimed_at: float, code: str,
                   page_count: int | None) -> None:
    """Mark the claimed row ``failed`` with *code* (a no-op when the claim is gone).

    Like :func:`_store_success`, it applies only while the row is still ``processing``
    with the claim's ``updated_at`` stamp.
    """
    conn = db.connect()
    try:
        with db.tx(conn):
            updated = conn.execute(
                "UPDATE documents SET status = 'failed', error = ?, page_count = ?, "
                "chunk_count = 0, char_count = 0, updated_at = ? "
                "WHERE id = ? AND status = 'processing' AND updated_at = ?",
                (code, page_count, db.now(), document_id, claimed_at),
            ).rowcount
            if updated:
                conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    finally:
        conn.close()


def _store_success(document_id: int, claimed_at: float, extracted: extract.Extracted) -> None:
    """Chunk and index *extracted*, replacing any previous chunks, in one transaction.

    It applies only to the row this run claimed — still ``processing`` and still
    carrying the claim's ``updated_at`` stamp. A row that was deleted, re-claimed by a
    later re-index, or replaced by a newer document that reused the id is left alone.
    """
    chunks = chunk_segments(extracted.segments)
    conn = db.connect()
    try:
        with db.tx(conn):
            updated = conn.execute(
                "UPDATE documents SET status = 'ready', error = NULL, page_count = ?, "
                "chunk_count = ?, char_count = ?, updated_at = ? "
                "WHERE id = ? AND status = 'processing' AND updated_at = ?",
                (extracted.page_count, len(chunks), extracted.char_count, db.now(), document_id,
                 claimed_at),
            ).rowcount
            if not updated:  # deleted, or claimed again, while it was being extracted
                return
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            conn.executemany(
                "INSERT INTO chunks (document_id, ord, page, text) VALUES (?, ?, ?, ?)",
                [(document_id, chunk.ord, chunk.page, chunk.text) for chunk in chunks],
            )
    finally:
        conn.close()


async def process_document(document_id: int, data: bytes, kind: str, *,
                           claimed_at: float) -> None:
    """Extract, chunk and index a ``processing`` document; it ends ``ready`` or ``failed``.

    *claimed_at* is the ``updated_at`` stamp of the claim (upload or re-index) this run
    belongs to; the outcome is written only while the row still carries it.
    """
    try:
        extracted = await extract.extract_document(data, kind)
    except extract.ExtractionError as exc:
        logger.info("document %s: extraction failed (%s)", document_id, exc.code)
        await asyncio.to_thread(_store_failure, document_id, claimed_at, exc.code,
                                exc.page_count)
        return
    except Exception:  # a parser bug must leave a failed row, never a stuck one
        logger.exception("document %s: extraction crashed; marked invalid_file", document_id)
        await asyncio.to_thread(_store_failure, document_id, claimed_at, "invalid_file", None)
        return
    await asyncio.to_thread(_store_success, document_id, claimed_at, extracted)


async def _write_temp_or_fail(data: bytes) -> Path:
    """:func:`_write_temp` off the event loop; a write failure is ``507 storage_failed``."""
    try:
        return await asyncio.to_thread(_write_temp, data)
    except OSError as exc:
        logger.error("an upload could not be written to the document store (%s)",
                     type(exc).__name__)
        raise _storage_failed() from exc


async def upload_document(conn: sqlite3.Connection, request: Request, user: WorkspaceUser, *,
                          scope: int | str, filename: str, title: str | None,
                          ip: str) -> dict:
    """``POST /documents``: store, extract and index one file; returns the document JSON."""
    name = clean_filename(filename)
    kind = extract.kind_for_filename(name)
    if kind is None:
        raise _unsupported("extension")

    def admit() -> tuple[int | None, str]:
        target = upload_target(conn, user, scope)
        check_upload_rate(conn, user.id)
        return target

    department_id, visibility = await offload(admit)
    document_title = clean_title(title, name)
    with _upload_slot(user.id):
        data = await read_upload(request, config.max_upload_bytes())
        if not data:
            raise invalid("body", "empty", "the file is empty")
        if not extract.content_matches(kind, data):
            raise _unsupported("content")
        digest = await asyncio.to_thread(_sha256, data)
        temp = await _write_temp_or_fail(data)
        upload = _Upload(department_id=department_id, visibility=visibility,
                         title=document_title, filename=name, kind=kind, size=len(data),
                         sha256=digest)
        document_id, claimed_at = await offload(_reserve, conn, user, upload, temp, ip)
        await process_document(document_id, data, kind, claimed_at=claimed_at)

    def finish() -> dict:
        # The upload's claim stamp is also its created_at.
        return document_json(_same_document(conn, document_id, claimed_at), user)

    return await offload(finish)


# ── delete, re-index, download ───────────────────────────────────────────────────────

def _detach_file(document_id: int) -> Path | None:
    """Rename the stored file aside (``None`` when there is none); see :func:`delete_document`."""
    doomed = files_dir() / f".deleted-{int(document_id)}.tmp"
    try:
        os.replace(file_path(document_id), doomed)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("document %s: stored file could not be removed (%s)",
                       document_id, type(exc).__name__)
        return None
    return doomed


def delete_document(conn: sqlite3.Connection, user: WorkspaceUser, document_id: int, *,
                    ip: str) -> None:
    """Remove the row (chunks and index entries cascade) and the stored file.

    The file is renamed aside inside the deleting transaction and unlinked after the
    commit: once the row is gone a new upload may reuse the id, and its fresh
    ``files/<id>.bin`` must not be the file this delete removes. If the transaction
    fails, the file is put back.
    """
    row = visible_document(conn, user, document_id)
    if not can_manage(user, row):
        raise _forbidden()
    doomed: Path | None = None
    try:
        with db.tx(conn):
            if not conn.execute("DELETE FROM documents WHERE id = ?", (document_id,)).rowcount:
                raise _not_found()  # a concurrent delete won; it wrote the audit row
            audit.record(conn, actor=user, action="document.deleted", target_type="document",
                         target_id=document_id, department_id=row["department_id"], ip=ip,
                         details={"title": row["title"], "filename": row["filename"],
                                  "visibility": row["visibility"]})
            doomed = _detach_file(document_id)
    except BaseException:
        if doomed is not None:
            with suppress(OSError):
                os.replace(doomed, file_path(document_id))
        raise
    if doomed is not None:
        try:
            doomed.unlink()
        except OSError as exc:
            logger.warning("document %s: stored file could not be removed (%s)",
                           document_id, type(exc).__name__)


def _claim_for_reindex(conn: sqlite3.Connection, user: WorkspaceUser, row: sqlite3.Row,
                       ip: str) -> float:
    """Claim the row for a new extraction (``processing``); returns the claim stamp.

    Refused with ``429`` beyond the user's hourly budget (shared with uploads) and with
    ``409 document_busy`` while a fresh claim is still running.
    """
    document_id = int(row["id"])
    with db.tx(conn):
        check_upload_rate(conn, user.id)
        stamp = db.now()
        claimed = conn.execute(
            "UPDATE documents SET status = 'processing', error = NULL, updated_at = ? "
            "WHERE id = ? AND (status != 'processing' OR updated_at < ?)",
            (stamp, document_id, stamp - STALE_PROCESSING_SECONDS),
        ).rowcount
        if claimed:
            audit.record(conn, actor=user, action="document.reindexed", target_type="document",
                         target_id=document_id, department_id=row["department_id"], ip=ip,
                         details={"title": row["title"], "previous_status": row["status"]})
    if not claimed:
        _document_row(conn, document_id)  # 404 when it was deleted in the meantime
        raise WorkspaceError("document_busy", "the document is still being processed", 409)
    return stamp


async def reindex_document(conn: sqlite3.Connection, user: WorkspaceUser, document_id: int, *,
                           ip: str) -> dict:
    """Extract and index the stored original again (after a failure or an upgrade)."""

    def claim() -> tuple[sqlite3.Row, float]:
        found = visible_document(conn, user, document_id)
        if not can_manage(user, found):
            raise _forbidden()
        return found, _claim_for_reindex(conn, user, found, ip)

    row, claimed_at = await offload(claim)
    # The filename passed the allow-list at upload; an edited row reads as invalid_file.
    kind = extract.kind_for_filename(row["filename"]) or ""
    try:
        data = await asyncio.to_thread(file_path(document_id).read_bytes)
    except OSError as exc:
        logger.warning("document %s: stored file unreadable (%s)", document_id,
                       type(exc).__name__)
        await asyncio.to_thread(_store_failure, document_id, claimed_at, "file_missing", None)
    else:
        await process_document(document_id, data, kind, claimed_at=claimed_at)

    def finish() -> dict:
        fresh = _same_document(conn, document_id, row["created_at"])
        return document_json(fresh, user,
                             publish_pending=_publish_pending(fresh, _pending_publish(conn)))

    return await offload(finish)


def open_original(conn: sqlite3.Connection, user: WorkspaceUser,
                  document_id: int) -> tuple[sqlite3.Row, Iterator[bytes], int]:
    """The visible document, a stream of its stored bytes (already opened) and their size.

    The file is opened before any response exists, so a missing file is a clean
    ``404 file_missing`` instead of a stream that breaks after the headers went out;
    the size comes from the open file, so ``Content-Length`` always matches what is
    sent. Once the file is open, the row is checked to be the same document still: had
    it been deleted and its id reused in between, the open file could be the newer
    document's — possibly another department's.
    """
    row = visible_document(conn, user, document_id)
    try:
        handle = file_path(document_id).open("rb")
    except OSError as exc:  # gone, or unreadable (permissions, a directory in its place)
        if not isinstance(exc, FileNotFoundError):
            logger.warning("document %s: stored file unreadable (%s)", document_id,
                           type(exc).__name__)
        raise WorkspaceError("file_missing", "the stored file is missing", 404) from exc
    try:
        size = os.fstat(handle.fileno()).st_size
        _same_document(conn, document_id, row["created_at"])
    except BaseException:
        handle.close()
        raise
    return row, file_chunks(handle), size


# ── the company-wide publish effect (decided by an admin) ────────────────────────────

def _check_publishable(row: sqlite3.Row) -> None:
    if row["visibility"] == "company":
        raise WorkspaceError("already_company", "the document is already company-wide", 409)
    if row["status"] != "ready":
        raise WorkspaceError("document_not_ready", "only indexed documents can be published",
                             409)


def validate_publish(conn: sqlite3.Connection, requester: WorkspaceUser,
                     payload: dict) -> ValidatedRequest:
    """Approval request check: a ``ready`` department document the requester can see.

    The clean payload pins the document by id and ``created_at``. A re-validation of a
    stored payload whose document was deleted meanwhile answers ``404`` even when a
    newer document has taken the id (see :func:`_names_document`).
    """
    if not isinstance(payload, dict):
        raise invalid("payload", "not_an_object")
    document_id = require_int(payload, "document_id", minimum=1)
    row = visible_document(conn, requester, document_id)
    if "created_at" in payload and not _names_document(payload, row):
        raise _not_found()
    _check_publishable(row)
    title = row["title"]
    summary = (f"Publicare în toată compania: „{title}”" if requester.locale == "ro"
               else f"Publish company-wide: “{title}”")
    return ValidatedRequest(department_id=int(row["department_id"]), summary=summary,
                            payload={"document_id": document_id,
                                     "created_at": row["created_at"]})


def _approval_payload(approval: dict) -> dict:
    payload = approval.get("payload")
    if isinstance(payload, dict):
        return payload
    try:
        decoded = json.loads(approval.get("payload_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _notify_published(conn: sqlite3.Connection, row: sqlite3.Row, requester: WorkspaceUser,
                      decider: WorkspaceUser) -> None:
    """Tell the requester and the uploader (not the decider), each in their language."""
    recipients = sorted({requester.id, row["uploader_id"]} - {None, decider.id})
    if not recipients:
        return
    users = conn.execute(
        "SELECT id, locale FROM users WHERE id IN (SELECT value FROM json_each(?)) "
        "AND status != 'disabled'", (json.dumps(recipients),),
    ).fetchall()
    for locale, title in _NOTIFY_TITLES.items():
        ids = [int(user["id"]) for user in users if (user["locale"] or "ro") == locale]
        notifications.notify(conn, ids, kind="document.published", title=title,
                             body=row["title"], link=f"/workspace/documents?document={row['id']}")


async def execute_publish(approval: dict, requester: WorkspaceUser,
                          decider: WorkspaceUser) -> dict:
    """Approved: make the document company-wide, audit it and notify the people involved."""
    payload = _approval_payload(approval)
    document_id = require_int(payload, "document_id", minimum=1)

    def publish() -> dict:
        conn = db.connect()
        try:
            with db.tx(conn):
                row = conn.execute("SELECT * FROM documents WHERE id = ?",
                                   (document_id,)).fetchone()
                if row is None or not _names_document(payload, row):
                    raise _not_found()
                _check_publishable(row)
                conn.execute("UPDATE documents SET visibility = 'company', updated_at = ? "
                             "WHERE id = ?", (db.now(), document_id))
                audit.record(conn, actor=decider, action="document.published",
                             target_type="document", target_id=document_id,
                             department_id=row["department_id"],
                             details={"approval_id": approval.get("id"),
                                      "requester_id": requester.id, "title": row["title"]})
                _notify_published(conn, row, requester, decider)
        finally:
            conn.close()
        return {"document_id": document_id, "visibility": "company", "title": row["title"]}

    return await offload(publish)


register_effect(EffectSpec(kind=PUBLISH_KIND, validate=validate_publish,
                           execute=execute_publish, decider_rule="admin"))
