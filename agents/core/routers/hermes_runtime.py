"""Owner-only HTTP and WebSocket surface for the managed Hermes runtime."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.websockets import WebSocketDisconnect

from agents.core.env_config import env_str
from agents.core.host_policy import allowed_hosts, host_accepted

from ._deps import admin_guard

MAX_FRAME_BYTES = 128 * 1024
MAX_RPC_IDS = 1024
MAX_ACTIVE_RPC = 8
PROTOCOL = "hermes-runtime-v1"
router = APIRouter(prefix="/api/hermes", tags=["hermes-runtime"])


def _service():
    # Lazy resolution avoids a router <-> service <-> web import cycle.
    from agents.core.hermes_runtime.service import get_service

    return get_service()


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RpcBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    method: str = Field(min_length=1, max_length=256)
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded(self):
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode("utf-8")) > MAX_FRAME_BYTES:
            raise ValueError("Hermes RPC request exceeds size limit")
        return self


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    approved: bool


def _http_error(exc: Exception) -> HTTPException:
    from agents.core.hermes_runtime.service import RuntimeDenied, RuntimeUnavailable

    if isinstance(exc, RuntimeDenied):
        verdict = getattr(exc, "verdict", "deny")
        if verdict == "queue":
            return HTTPException(409, {"error": "approval_required",
                                       "task_id": getattr(exc, "task_id", None),
                                       "disposition": "queued"})
        return HTTPException(403, {"error": "runtime_denied"})
    if isinstance(exc, RuntimeUnavailable):
        return HTTPException(503, {"error": "runtime_unavailable"})
    return HTTPException(503, {"error": "runtime_unavailable"})


@router.get("/status", dependencies=[Depends(admin_guard)])
async def status():
    try:
        return await _service().status()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/catalog", dependencies=[Depends(admin_guard)])
async def catalog():
    try:
        return _service().catalog()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/start", dependencies=[Depends(admin_guard)])
async def start(body: EmptyBody | None = None):
    try:
        return await _service().start()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/stop", dependencies=[Depends(admin_guard)])
async def stop(body: EmptyBody | None = None):
    try:
        return await _service().stop()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/rpc", dependencies=[Depends(admin_guard)])
async def rpc(body: RpcBody):
    try:
        return {"result": await _service().rpc(body.method, body.params)}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/approvals", dependencies=[Depends(admin_guard)])
async def approvals():
    try:
        return await _service().approval_list()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/approvals/{task_id}/decision", dependencies=[Depends(admin_guard)])
async def approval_decision(task_id: int, body: DecisionBody):
    try:
        return await _service().approval_decide(task_id, body.approved)
    except Exception as exc:
        raise _http_error(exc) from exc


def _upgrade_request(ws: WebSocket) -> tuple[Request, str | None]:
    """Run the HTTP host/admin policy on a WebSocket upgrade."""
    if ws.query_params:
        raise HTTPException(403, "unsupported Hermes query")
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
    if len(credentials) > 1 or (credentials and PROTOCOL not in protocols):
        raise HTTPException(403, "invalid Hermes authentication")
    headers = list(ws.scope.get("headers", []))
    if credentials:
        if ws.headers.get("x-admin-token") or not credentials[0] or len(credentials[0]) > 4096:
            raise HTTPException(403, "invalid Hermes authentication")
        try:
            headers.append((b"x-admin-token", credentials[0].encode("ascii")))
        except UnicodeError as exc:
            raise HTTPException(403, "invalid Hermes authentication") from exc
    scope = {**ws.scope, "type": "http", "method": "GET", "scheme": scheme, "headers": headers}
    return Request(scope), PROTOCOL if PROTOCOL in protocols else None


def _valid_id(value: Any) -> bool:
    return (type(value) is int and 0 <= value <= 2**63 - 1
            or type(value) is str and 0 < len(value) <= 128)


async def _send_events(ws: WebSocket, service: Any, request: Request, send_lock: asyncio.Lock):
    async for event in service.events():
        await admin_guard(request)
        if not isinstance(event, dict):
            raise ValueError("invalid Hermes event")
        if len(json.dumps(event, ensure_ascii=False).encode("utf-8")) > MAX_FRAME_BYTES:
            raise ValueError("Hermes event exceeds size limit")
        async with send_lock:
            await ws.send_json(event)


async def _run_rpc(ws: WebSocket, service: Any, method: str, params: dict,
                   request_id: str | int, send_lock: asyncio.Lock):
    try:
        result = await service.rpc(method, params)
        response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        denied = _http_error(exc)
        response = {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32000, "message": denied.detail["error"],
                              "data": denied.detail}}
    async with send_lock:
        await ws.send_json(response)


async def _handle_frame(ws: WebSocket, service: Any, raw: str, send_lock: asyncio.Lock,
                        seen_ids: set[str | int], active_rpc: set[asyncio.Task]):
    if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ValueError("Hermes frame exceeds size limit")
    frame = json.loads(raw)
    if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0" or not _valid_id(frame.get("id")):
        raise ValueError("invalid Hermes JSON-RPC frame")
    if "method" in frame:
        if set(frame) - {"jsonrpc", "id", "method", "params"}:
            raise ValueError("unsupported Hermes RPC fields")
        method, params = frame["method"], frame.get("params", {})
        if not isinstance(method, str) or not 0 < len(method) <= 256 or not isinstance(params, dict):
            raise ValueError("invalid Hermes RPC method or params")
        if frame["id"] in seen_ids or len(seen_ids) >= MAX_RPC_IDS or len(active_rpc) >= MAX_ACTIVE_RPC:
            raise ValueError("replayed or excessive Hermes RPC identifier")
        seen_ids.add(frame["id"])
        task = asyncio.create_task(_run_rpc(ws, service, method, params, frame["id"], send_lock))
        active_rpc.add(task)
        task.add_done_callback(active_rpc.discard)
        return
    if (set(frame) - {"jsonrpc", "id", "result", "error", "generation"}
            or ("result" in frame) == ("error" in frame)
            or not isinstance(frame.get("generation"), str)
            or not 0 < len(frame["generation"]) <= 128):
        raise ValueError("invalid Hermes server-request reply")
    await service.reply(frame)


@router.websocket("/ws")
async def websocket_rpc(ws: WebSocket):
    sender = None
    active_rpc: set[asyncio.Task] = set()
    try:
        request, protocol = _upgrade_request(ws)
        await admin_guard(request)
        service = _service()
        if not (await service.status()).get("ready"):
            raise HTTPException(503, "Hermes runtime unavailable")
        await ws.accept(subprotocol=protocol)
        send_lock = asyncio.Lock()
        seen_ids: set[str | int] = set()
        sender = asyncio.create_task(_send_events(ws, service, request, send_lock))
        while True:
            await admin_guard(request)
            if sender.done():
                sender.result()
                await ws.close(code=1000)
                break
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=5)
            except TimeoutError:
                continue
            await _handle_frame(ws, service, raw, send_lock, seen_ids, active_rpc)
    except (HTTPException, ValueError, UnicodeError, json.JSONDecodeError):
        await ws.close(code=1008)
    except WebSocketDisconnect:
        pass
    except Exception:
        await ws.close(code=1011)
    finally:
        for task in active_rpc:
            task.cancel()
        if active_rpc:
            await asyncio.gather(*active_rpc, return_exceptions=True)
        if sender is not None:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await sender
