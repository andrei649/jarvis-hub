"""Request/response helpers shared by every workspace router (spec §5, §7).

Bodies are read with :func:`read_json`, not pydantic models, for two reasons: the
size cap is enforced while streaming (a 2 GB body never reaches memory), and every
validation failure maps onto the workspace's own ``422 invalid_request`` with the
offending ``field`` instead of FastAPI's ``{"detail": [...]}``. The small ``require_*``
/ ``optional_*`` validators keep handlers declarative: each returns a clean Python
value or raises a :class:`WorkspaceError` naming the field and a ``reason``.

Single-line text fields refuse control characters (names and titles end up in email
headers and CSV exports); multi-line fields allow line breaks (normalized to ``\\n``)
and tabs only.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send

from agents.core.workspace.errors import WorkspaceError


async def offload[T](fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run synchronous SQLite work (``BEGIN IMMEDIATE``, FTS) off the event loop.

    A write transaction waits up to the 5 s busy timeout for the lock; run inline in an
    ``async def`` handler that wait would freeze every other request. The request's one
    connection is opened ``check_same_thread=False`` and used by one thread at a time
    (the caller awaits this), and the context variables (action origin) are copied.
    """
    worker = asyncio.ensure_future(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # The thread cannot be interrupted, and FastAPI closes the request connection as soon
        # as the cancellation unwinds: drain the worker first so it never meets a closed database.
        while not worker.done():
            try:
                await asyncio.wait({worker})
            except asyncio.CancelledError:
                continue
        if not worker.cancelled():
            worker.exception()  # retrieved: nothing may log "never retrieved"
        raise


NO_STORE = {"Cache-Control": "no-store"}
MAX_EMAIL_LEN = 254
MAX_EMAILS = 20
MAX_IDS = 50
#: SQLite's INTEGER range. A larger Python int makes sqlite3 raise OverflowError (a 500)
#: when bound as a parameter, so every integer the API accepts stays inside it — routers
#: bound their id path/query parameters with ``le=MAX_ID`` for the same reason.
MAX_ID = 2 ** 63 - 1
MIN_INT = -(2 ** 63)

# C0 and C1 control characters (U+0085 NEL is a C1 line break) plus the Unicode line and
# paragraph separators: str.splitlines() and many renderers treat all of them as breaks.
# Lone surrogates (JSON allows "\ud800") are refused too: they cannot be encoded as
# UTF-8, so SQLite, hashing and email would all raise on them.
_SINGLE_LINE_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")
_MULTI_LINE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")
_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def invalid(field: str, reason: str, message: str = "") -> WorkspaceError:
    """A ``422 invalid_request`` naming *field* and a machine *reason*."""
    return WorkspaceError("invalid_request", message or f"{field}: {reason}", 422,
                          field=field, reason=reason)


def _is_json_content_type(request: Request) -> bool:
    raw = request.headers.get("content-type", "")
    return raw.split(";", 1)[0].strip().lower() == "application/json"


def _finite_float(text: str) -> float:
    """Numbers like ``1e999`` overflow to infinity, which JSON responses cannot carry."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("number out of range")
    return value


def _refuse_constant(name: str) -> float:
    """``NaN``/``Infinity`` are Python extensions, not JSON."""
    raise ValueError(f"{name} is not valid JSON")


async def read_json(request: Request, *, max_bytes: int = 65536,
                    allow_empty: bool = False) -> dict:
    """Read a JSON object body: 415 without ``application/json``, 413 above *max_bytes*.

    The cap is checked against ``Content-Length`` first and again while streaming, so a
    lying or absent header cannot push more than *max_bytes* into memory. With
    *allow_empty* an empty body (any content type) reads as ``{}`` — for routes whose
    fields are all optional.
    """
    declared = request.headers.get("content-length", "").strip()
    if declared.isdigit() and int(declared) > max_bytes:
        raise WorkspaceError("payload_too_large", "request body is too large", 413,
                             max_bytes=max_bytes)
    if allow_empty and declared == "0":
        return {}
    if not _is_json_content_type(request) and not allow_empty:
        raise WorkspaceError("unsupported_media_type", "send application/json", 415)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise WorkspaceError("payload_too_large", "request body is too large", 413,
                                 max_bytes=max_bytes)
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw.strip():
        if allow_empty:
            return {}
        raise invalid("body", "empty", "a JSON object is required")
    if not _is_json_content_type(request):
        raise WorkspaceError("unsupported_media_type", "send application/json", 415)
    try:
        data = json.loads(raw.decode("utf-8"), parse_float=_finite_float,
                          parse_constant=_refuse_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        # RecursionError: "[[[[…" nested deeper than the parser's stack, within the cap.
        raise invalid("body", "malformed", "the body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise invalid("body", "not_an_object", "the body must be a JSON object")
    return data


def ws_json(data: Any, status: int = 200, headers: Mapping[str, str] | None = None, *,
            cookies_from: Response | None = None) -> JSONResponse:
    """A JSON response with ``Cache-Control: no-store``.

    *cookies_from* copies the ``Set-Cookie`` headers of a holder response (the one
    :func:`agents.core.workspace.auth.issue_session` wrote the session cookie on): the
    payload carries the CSRF token that issuing the session produced, so the cookie
    has to be written before the final response exists.
    """
    response = JSONResponse(data, status_code=status, headers={**NO_STORE, **(headers or {})})
    if cookies_from is not None:
        response.headers.raw.extend(
            (name, value) for name, value in cookies_from.headers.raw if name == b"set-cookie"
        )
    return response


def ws_no_content() -> Response:
    """``204 No Content`` with ``Cache-Control: no-store``."""
    return Response(status_code=204, headers=dict(NO_STORE))


def _clean_text(value: str, key: str, *, max_len: int, min_len: int, strip: bool,
                multiline: bool) -> str:
    text = value.strip() if strip else value
    if multiline:
        text = (text.replace("\r\n", "\n").replace("\r", "\n")
                .replace("\u2028", "\n").replace("\u2029", "\n"))
    pattern = _MULTI_LINE_CONTROL if multiline else _SINGLE_LINE_CONTROL
    if pattern.search(text):
        raise invalid(key, "control_characters")
    if len(text) > max_len:
        raise invalid(key, "too_long", f"{key} is longer than {max_len} characters")
    if len(text) < min_len:
        raise invalid(key, "too_short" if text else "required")
    return text


def require_str(d: Mapping[str, Any], key: str, *, max_len: int, min_len: int = 0,
                required: bool = True, strip: bool = True, multiline: bool = False) -> str:
    """A string field; absent and not *required* → ``''``. Passwords pass ``strip=False``."""
    value = d.get(key)
    if value is None:
        if required:
            raise invalid(key, "required")
        return ""
    if not isinstance(value, str):
        raise invalid(key, "type", f"{key} must be a string")
    return _clean_text(value, key, max_len=max_len, min_len=min_len, strip=strip,
                       multiline=multiline)


def optional_str(d: Mapping[str, Any], key: str, *, max_len: int, min_len: int = 0,
                 strip: bool = True, multiline: bool = False) -> str | None:
    """A string field for partial updates: ``None`` when absent or null."""
    if d.get(key) is None:
        return None
    return require_str(d, key, max_len=max_len, min_len=min_len, strip=strip,
                       multiline=multiline)


def _as_int(value: Any, key: str, minimum: int | None, maximum: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(key, "type", f"{key} must be an integer")
    if value < (MIN_INT if minimum is None else max(minimum, MIN_INT)):
        raise invalid(key, "too_small")
    if value > (MAX_ID if maximum is None else min(maximum, MAX_ID)):
        raise invalid(key, "too_large")
    return value


def require_int(d: Mapping[str, Any], key: str, *, minimum: int | None = None,
                maximum: int | None = None) -> int:
    """A required integer (``true`` is not an integer here)."""
    value = d.get(key)
    if value is None:
        raise invalid(key, "required")
    return _as_int(value, key, minimum, maximum)


def optional_int(d: Mapping[str, Any], key: str, *, minimum: int | None = None,
                 maximum: int | None = None) -> int | None:
    """An integer field for partial updates: ``None`` when absent or null."""
    value = d.get(key)
    return None if value is None else _as_int(value, key, minimum, maximum)


def optional_bool(d: Mapping[str, Any], key: str, *, default: bool | None = None) -> bool | None:
    """A JSON boolean; absent or null → *default*. ``1``/``"true"`` are refused."""
    value = d.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise invalid(key, "type", f"{key} must be true or false")
    return value


def require_choice(d: Mapping[str, Any], key: str, choices: Iterable[str], *,
                   default: str | None = None) -> str:
    """One of *choices*; absent → *default* (required when no default)."""
    value = d.get(key)
    if value is None:
        if default is None:
            raise invalid(key, "required")
        return default
    allowed = tuple(choices)
    if not isinstance(value, str) or value not in allowed:
        raise invalid(key, "invalid_choice", f"{key} must be one of: {', '.join(allowed)}")
    return value


def optional_choice(d: Mapping[str, Any], key: str, choices: Iterable[str]) -> str | None:
    """A choice field for partial updates: ``None`` when absent or null."""
    if d.get(key) is None:
        return None
    return require_choice(d, key, choices)


def require_list(d: Mapping[str, Any], key: str, *, max_items: int, min_items: int = 0,
                 required: bool = True) -> list:
    """A JSON array of at most *max_items*; absent and not *required* → ``[]``."""
    value = d.get(key)
    if value is None:
        if required:
            raise invalid(key, "required")
        value = []
    if not isinstance(value, list):
        raise invalid(key, "type", f"{key} must be a list")
    if len(value) > max_items:
        raise invalid(key, "too_many", f"{key} holds more than {max_items} items")
    if len(value) < min_items:
        raise invalid(key, "too_few", f"{key} needs at least {min_items} item(s)")
    return value


def require_id_list(d: Mapping[str, Any], key: str, *, max_items: int = MAX_IDS,
                    min_items: int = 0, required: bool = True) -> list[int]:
    """A list of positive integer ids, de-duplicated in order."""
    items = require_list(d, key, max_items=max_items, required=required)
    ids: list[int] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise invalid(key, "type", f"{key} must hold positive integer ids")
        if item > MAX_ID:
            raise invalid(key, "too_large", f"{key} holds an id beyond the database range")
        if item not in ids:
            ids.append(item)
    if len(ids) < min_items:
        raise invalid(key, "too_few", f"{key} needs at least {min_items} item(s)")
    return ids


def optional_id_list(d: Mapping[str, Any], key: str, *, max_items: int = MAX_IDS,
                     min_items: int = 0) -> list[int] | None:
    """An id list for partial updates: ``None`` when absent or null."""
    if d.get(key) is None:
        return None
    return require_id_list(d, key, max_items=max_items, min_items=min_items)


def normalize_email(value: Any) -> str | None:
    """The lower-cased address when *value* is a plausible single email, else ``None``.

    Deliberately strict: no display names, no commas, no whitespace or CR/LF — the
    value is used as a login, in SQL lookups and in mail headers.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_EMAIL_LEN or not _EMAIL.match(text):
        return None
    return text.lower()


def is_valid_email(value: Any) -> bool:
    """True when :func:`normalize_email` accepts *value*."""
    return normalize_email(value) is not None


def require_email(d: Mapping[str, Any], key: str, *, required: bool = True) -> str:
    """A lower-cased email address; absent and not *required* → ``''``."""
    value = d.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise invalid(key, "required")
        return ""
    email = normalize_email(value)
    if email is None:
        raise invalid(key, "invalid_email", f"{key} is not a valid email address")
    return email


def require_email_list(d: Mapping[str, Any], key: str, *, max_items: int = MAX_EMAILS,
                       required: bool = False) -> list[str]:
    """Up to *max_items* distinct lower-cased addresses (absent → ``[]``)."""
    items = require_list(d, key, max_items=max_items, required=required)
    emails: list[str] = []
    for item in items:
        email = normalize_email(item)
        if email is None:
            raise invalid(key, "invalid_email", f"{key} holds an invalid email address")
        if email not in emails:
            emails.append(email)
    return emails


# ── CORS: the hub's, never the workspace's (spec §6 "CSRF") ───────────────────────────

#: The workspace app and API, as logical paths (the root path stripped).
WORKSPACE_PATH_PREFIXES = ("/api/workspace", "/workspace")


def is_workspace_scope(scope: Scope) -> bool:
    """True for an HTTP scope addressed to ``/api/workspace*`` or ``/workspace*``."""
    path = str(scope.get("path") or "")
    root = str(scope.get("root_path") or "")
    if root and path.startswith(root):
        path = path[len(root):]
    return any(path == prefix or path.startswith(prefix + "/") for prefix in WORKSPACE_PATH_PREFIXES)


class WorkspaceExemptCORSMiddleware(CORSMiddleware):
    """The hub's ``CORSMiddleware`` (``JARVIS_CORS_ORIGINS``), skipped for the workspace.

    The workspace never sends CORS headers: its session cookie is ``SameSite=Lax``, so a
    page on a listed origin of the same site would otherwise read a signed-in user's
    ``/session`` (CSRF token included), documents and conversations with credentialed
    CORS. A workspace request — preflights included — passes straight to the app, which
    answers it without any ``Access-Control-*`` header.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and is_workspace_scope(scope):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

