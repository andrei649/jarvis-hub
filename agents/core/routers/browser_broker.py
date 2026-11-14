"""H086 — Identity-scoped remote browser-control broker & one-shot HTTPS artifact routes."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agents.core.browser_broker import MAX_ARTIFACT_BYTES, BrowserBrokerError
from agents.core.routers._component import require_component
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["browser-broker"])


def _caller_principal(request: Request) -> str:
    """Derive non-spoofable caller identity from bearer token digest, defaulting to 'owner'."""
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        raw_tok = auth[7:].strip()
        if raw_tok:
            digest = hashlib.sha256(raw_tok.encode("utf-8")).hexdigest()[:16]
            return f"bearer:{digest}"
    return "owner"


def _effective_scheme(request: Request) -> str:
    scheme = (request.url.scheme or "http").lower()
    client_host = (request.client.host if request.client else "") or ""
    if client_host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        forwarded = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
        if forwarded in {"http", "https"}:
            return forwarded
    return scheme


def _extract_ticket(request: Request, header_name: str) -> str:
    direct = (request.headers.get(header_name) or "").strip()
    if direct:
        return direct
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _broker_err(exc: BrowserBrokerError):
    return nocache_json(
        {"ok": False, "error": exc.reason, "detail": exc.detail},
        status_code=exc.status,
    )


class RegisterControllerBody(BaseModel):
    label: str = Field("remote-browser", max_length=80)
    capabilities: list[str] | None = None
    allow_private_urls: bool = False
    lease_ttl_s: float = Field(120.0, ge=10.0, le=3600.0)


class DispatchStepBody(BaseModel):
    step: dict[str, Any] = Field(default_factory=dict)


class PollCommandsBody(BaseModel):
    limit: int = Field(16, ge=1, le=64)


class CommandResultBody(BaseModel):
    ok: bool = True
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = Field("", max_length=500)


class UploadTicketBody(BaseModel):
    filename: str = Field("screenshot.png", max_length=120)
    mime_type: str = Field("image/png", max_length=80)
    max_bytes: int = Field(MAX_ARTIFACT_BYTES, ge=1, le=MAX_ARTIFACT_BYTES)
    ttl_s: float = Field(300.0, ge=5.0, le=900.0)


class DownloadTicketBody(BaseModel):
    ttl_s: float = Field(300.0, ge=5.0, le=900.0)


# ── Owner / Caller HUD & API surfaces ────────────────────────────────────────


@router.get("/api/browser/broker", dependencies=[Depends(user_guard)])
async def broker_status(request: Request):
    """H086 — identity-scoped status of remote browser sessions, commands, and artifacts."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(broker.status(principal_id=_caller_principal(request)))
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.post("/api/browser/broker/sessions", dependencies=[Depends(admin_guard)])
async def broker_register_session(request: Request, body: RegisterControllerBody):
    """H086 — register an identity-scoped remote browser controller session."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    try:
        res = broker.register_controller(
            principal_id=_caller_principal(request),
            label=body.label,
            capabilities=body.capabilities,
            allow_private_urls=body.allow_private_urls,
            lease_ttl_s=body.lease_ttl_s,
        )
        return nocache_json(res)
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.delete("/api/browser/broker/sessions/{session_id}", dependencies=[Depends(admin_guard)])
async def broker_detach_session(session_id: str, request: Request):
    """H086 — detach and revoke a remote browser controller session."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    try:
        res = broker.detach_session(session_id, principal_id=_caller_principal(request))
        return nocache_json(res)
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.post("/api/browser/broker/sessions/{session_id}/steps", dependencies=[Depends(admin_guard)])
async def broker_dispatch_step(session_id: str, request: Request, body: DispatchStepBody):
    """H086 — dispatch a normalized, SSRF-checked step to an identity-scoped remote browser."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    try:
        res = await broker.dispatch_step(
            session_id,
            principal_id=_caller_principal(request),
            step=body.step,
        )
        return nocache_json(res)
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.get("/api/browser/broker/commands/{command_id}", dependencies=[Depends(user_guard)])
async def broker_command_status(command_id: str, request: Request):
    """H086 — inspect the status and result of a dispatched remote-browser command."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(
            broker.get_command_status(command_id, principal_id=_caller_principal(request))
        )
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.post(
    "/api/browser/broker/sessions/{session_id}/artifacts/upload-ticket",
    dependencies=[Depends(admin_guard)],
)
async def broker_mint_upload_ticket(session_id: str, request: Request, body: UploadTicketBody):
    """H086 — mint a bounded, identity-scoped one-shot HTTPS upload ticket."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    try:
        res = broker.mint_upload_ticket(
            session_id,
            principal_id=_caller_principal(request),
            filename=body.filename,
            mime_type=body.mime_type,
            max_bytes=body.max_bytes,
            ttl_s=body.ttl_s,
        )
        return nocache_json(res)
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.post(
    "/api/browser/broker/artifacts/{artifact_id}/download-ticket",
    dependencies=[Depends(user_guard)],
)
async def broker_mint_download_ticket(
    artifact_id: str, request: Request, body: DownloadTicketBody
):
    """H086 — mint an identity-scoped one-shot HTTPS download ticket."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    try:
        res = broker.mint_download_ticket(
            artifact_id,
            principal_id=_caller_principal(request),
            ttl_s=body.ttl_s,
        )
        return nocache_json(res)
    except BrowserBrokerError as exc:
        return _broker_err(exc)


# ── Machine-facing remote-controller & one-shot artifact wire transfer ───────


@router.post(
    "/api/browser/broker/controller/{session_id}/heartbeat",
    dependencies=[Depends(user_guard)],
)
async def broker_controller_heartbeat(session_id: str, request: Request):
    """H086 — remote browser controller lease renewal."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    token = _extract_ticket(request, "x-controller-token")
    try:
        return nocache_json(broker.heartbeat(session_id, controller_token=token))
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.post(
    "/api/browser/broker/controller/{session_id}/poll",
    dependencies=[Depends(user_guard)],
)
async def broker_controller_poll(session_id: str, request: Request, body: PollCommandsBody):
    """H086 — remote browser controller command pickup."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    token = _extract_ticket(request, "x-controller-token")
    try:
        return nocache_json(
            broker.poll_commands(session_id, controller_token=token, limit=body.limit)
        )
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.post(
    "/api/browser/broker/controller/{session_id}/commands/{command_id}/result",
    dependencies=[Depends(user_guard)],
)
async def broker_controller_result(
    session_id: str, command_id: str, request: Request, body: CommandResultBody
):
    """H086 — remote browser controller step completion report."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    token = _extract_ticket(request, "x-controller-token")
    try:
        return nocache_json(
            broker.submit_result(
                session_id,
                command_id,
                controller_token=token,
                ok=body.ok,
                output=body.output,
                error=body.error,
            )
        )
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.post(
    "/api/browser/broker/controller/{session_id}/detach",
    dependencies=[Depends(user_guard)],
)
async def broker_controller_detach(session_id: str, request: Request):
    """H086 — remote browser controller clean detach."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    token = _extract_ticket(request, "x-controller-token")
    try:
        return nocache_json(broker.detach_by_controller(session_id, controller_token=token))
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.put(
    "/api/browser/broker/artifacts/{artifact_id}/upload",
    dependencies=[Depends(user_guard)],
)
async def broker_artifact_upload(artifact_id: str, request: Request):
    """H086 — authenticated one-shot HTTPS upload of bounded browser artifact bytes."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    ticket = _extract_ticket(request, "x-artifact-ticket")
    # Read bounded stream (cap at MAX_ARTIFACT_BYTES + 1 to detect oversize without OOM).
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total <= MAX_ARTIFACT_BYTES + 1:
            chunks.append(chunk)
        else:
            break
    raw = b"".join(chunks)
    client_host = (request.client.host if request.client else "") or ""
    try:
        res = broker.consume_upload(
            artifact_id,
            upload_ticket=ticket,
            data=raw,
            content_type=request.headers.get("content-type", ""),
            scheme=_effective_scheme(request),
            client_host=client_host,
        )
        return nocache_json(res)
    except BrowserBrokerError as exc:
        return _broker_err(exc)


@router.get(
    "/api/browser/broker/artifacts/{artifact_id}/download",
    dependencies=[Depends(user_guard)],
)
async def broker_artifact_download(artifact_id: str, request: Request):
    """H086 — authenticated one-shot HTTPS download of bounded browser artifact bytes."""
    _, broker, err = require_component("browser_broker", "browser broker unavailable")
    if err is not None:
        return err
    ticket = _extract_ticket(request, "x-artifact-ticket")
    client_host = (request.client.host if request.client else "") or ""
    try:
        art = broker.consume_download(
            artifact_id,
            download_ticket=ticket,
            scheme=_effective_scheme(request),
            client_host=client_host,
        )
    except BrowserBrokerError as exc:
        return _broker_err(exc)
    return Response(
        content=art["data"],
        media_type=art["mime_type"],
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Artifact-SHA256": art["sha256"],
            "Content-Disposition": f'attachment; filename="{art["filename"]}"',
        },
    )
