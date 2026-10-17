"""The one error type of Nerva Workspace and its JSON shape (spec §5, §7).

Every failure a workspace route reports is a :class:`WorkspaceError` carrying a stable
machine ``code`` the UI translates, an HTTP ``status`` and optional extra fields
(``field``, ``reason``, ``retry_after_seconds`` …). Routes raise it; the handler
registered by :func:`register_handlers` turns it into ``{"error", "message", **extra}``
with ``Cache-Control: no-store`` so an error page is never cached by a proxy.

FastAPI's own request validation (path/query parameters) is reshaped into the same
``422 invalid_request`` for workspace paths, while every other hub path keeps
FastAPI's default ``{"detail": [...]}`` body — the hub's existing clients depend on it.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

API_PREFIX = "/api/workspace"


class WorkspaceError(Exception):
    """A user-facing workspace failure: ``code`` (stable), ``message``, ``status``, ``extra``."""

    def __init__(self, code: str, message: str = "", status: int = 400, **extra: Any) -> None:
        self.code = code
        self.message = message or code.replace("_", " ")
        self.status = status
        self.extra = extra
        super().__init__(f"{code}: {self.message}")


def error_response(exc: WorkspaceError) -> JSONResponse:
    """The JSON body of *exc*; a ``retry_after_seconds`` extra also sets ``Retry-After``."""
    headers = {"Cache-Control": "no-store"}
    retry_after = exc.extra.get("retry_after_seconds")
    if isinstance(retry_after, int) and not isinstance(retry_after, bool):
        headers["Retry-After"] = str(max(1, retry_after))
    body = {**exc.extra, "error": exc.code, "message": exc.message}
    return JSONResponse(body, status_code=exc.status, headers=headers)


async def workspace_error_handler(request: Request, exc: WorkspaceError) -> JSONResponse:
    """Exception handler for :class:`WorkspaceError` (registered on the app)."""
    return error_response(exc)


def _logical_path(request: Request) -> str:
    path = request.url.path
    root = request.scope.get("root_path", "") or ""
    if root and path.startswith(root):
        return path[len(root):]
    return path


def is_workspace_path(request: Request) -> bool:
    """True for ``/api/workspace`` and below (root-path aware)."""
    path = _logical_path(request)
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """``RequestValidationError`` → ``422 invalid_request`` on workspace paths only.

    The first failing location names the ``field`` (``limit``, ``user_id`` …) so the UI
    can point at it; elsewhere FastAPI's default handler answers unchanged.
    """
    if not is_workspace_path(request):
        return await request_validation_exception_handler(request, exc)
    errors = exc.errors()
    field = ""
    if errors:
        location = [str(part) for part in errors[0].get("loc", ()) if part not in ("body",)]
        field = location[-1] if location else ""
    message = f"invalid value for {field}" if field else "invalid request"
    return error_response(WorkspaceError("invalid_request", message, 422, field=field))


def register_handlers(app: FastAPI) -> None:
    """Install the workspace error and validation handlers on *app*."""
    app.add_exception_handler(WorkspaceError, workspace_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
