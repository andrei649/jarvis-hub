"""Authenticated Nerva host for the adapted Hermes board consumers."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.websockets import WebSocketDisconnect

from agents.core.app_state import get_orch
from agents.core.commands import Principal
from agents.core.env_config import env_str
from agents.core.host_policy import allowed_hosts, host_accepted
from agents.core.kanban import dashboard_api
from agents.core.kanban.cli import execute_command
from agents.core.kanban.cli_upstream.board_selection import selected_board
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.paths import data_path

from ._deps import admin_guard

router = APIRouter(tags=["kanban"])


def _enabled():
    orch = get_orch()
    return orch is not None and orch.get_setting("llm.kanban", False) is True


async def owner_scope():
    if not _enabled():
        raise HTTPException(503, "Kanban is disabled (llm.kanban)")
    home = data_path("kanban")
    with kanban_scope(KanbanContext(home, "owner", board=selected_board(home), can_mutate=True)):
        yield


http_router = APIRouter(prefix="/api/kanban", dependencies=[Depends(admin_guard), Depends(owner_scope)])
http_router.include_router(dashboard_api.router)


class CommandBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    argv: list[str] = Field(max_length=128)

    @field_validator("argv")
    @classmethod
    def bounded_arguments(cls, argv):
        sizes = [len(arg.encode("utf-8")) for arg in argv]
        if any(size > 8192 for size in sizes) or sum(sizes) > 65536:
            raise ValueError("Kanban arguments exceed the size limit")
        return argv


@http_router.post("/command")
async def command(body: CommandBody):
    return await execute_command(get_orch(), body.argv, Principal(channel="web", admin=True))


router.include_router(http_router)


def _upgrade_request(ws: WebSocket) -> tuple[Request, str | None]:
    """Apply HTTP host/auth policy to upgrades without URL credentials."""
    if set(ws.query_params) - {"board", "since"}:
        raise HTTPException(403, "unsupported event query")
    server = ws.scope.get("server") or ("", 0)
    host = ws.headers.get("host", "")
    if not host_accepted(host, bind_host=env_str("JARVIS_HOST", "127.0.0.1"),
                         server_host=server[0] or "", allowed=allowed_hosts()):
        raise HTTPException(403, "host not allowed")
    scheme = "https" if ws.url.scheme == "wss" else "http"
    origin = ws.headers.get("origin")
    if origin is not None:
        try:
            actual, expected = urlsplit(origin), urlsplit(f"{scheme}://{host}")
            if (actual.scheme, actual.hostname, actual.port or (443 if actual.scheme == "https" else 80)) != (
                expected.scheme, expected.hostname, expected.port or (443 if scheme == "https" else 80)
            ) or actual.username is not None or actual.password is not None or actual.path not in {"", "/"} or actual.query or actual.fragment:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(403, "origin not allowed") from exc
    protocols = ws.scope.get("subprotocols", [])
    credentials = [p[len("nerva-admin."):] for p in protocols if p.startswith("nerva-admin.")]
    if len(credentials) > 1 or (credentials and "nerva-kanban" not in protocols):
        raise HTTPException(403, "invalid event authentication")
    headers = list(ws.scope.get("headers", []))
    if credentials:
        if ws.headers.get("x-admin-token") or not credentials[0] or len(credentials[0]) > 4096:
            raise HTTPException(403, "invalid event authentication")
        headers.append((b"x-admin-token", credentials[0].encode("ascii")))
    scope = {**ws.scope, "type": "http", "method": "GET", "scheme": scheme, "headers": headers}
    return Request(scope), "nerva-kanban" if "nerva-kanban" in protocols else None


@router.websocket("/api/kanban/events")
async def events(ws: WebSocket):
    tail = None
    try:
        request, protocol = _upgrade_request(ws)
        await admin_guard(request)
        if not _enabled():
            raise HTTPException(503, "Kanban is disabled")
        raw_cursor = ws.query_params.get("since")
        if raw_cursor is not None and (not raw_cursor.isascii() or not raw_cursor.isdecimal()
                                       or len(raw_cursor) > 19 or int(raw_cursor) > 2**63 - 1):
            raise HTTPException(400, "invalid event cursor")
        home = data_path("kanban")
        with kanban_scope(KanbanContext(home, "owner", board=selected_board(home), can_mutate=False)):
            # Pass the raw board to the strict validator, not the donor's lenient helper.
            tail = dashboard_api._EventTail(ws.query_params.get("board"))
            cursor = int(raw_cursor) if raw_cursor is not None else await tail.latest()
            await ws.accept(subprotocol=protocol)
            while True:
                await admin_guard(request)
                if not _enabled():
                    raise HTTPException(503, "Kanban is disabled")
                cursor, batch = await tail.poll(cursor)
                if batch:
                    await ws.send_json({"events": batch, "cursor": cursor})
                try:
                    message = await asyncio.wait_for(ws.receive(), dashboard_api._EVENT_POLL_SECONDS)
                except TimeoutError:
                    continue
                if message["type"] == "websocket.disconnect":
                    break
    except (HTTPException, ValueError, PermissionError, UnicodeError):
        await ws.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        if tail is not None:
            await tail.shutdown()
