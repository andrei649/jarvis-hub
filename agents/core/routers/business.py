"""Opt-in, guarded company workspace routes."""

from __future__ import annotations

import asyncio
import os
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field, ValidationError, field_validator

from agents.core.business.catalog import catalog
from agents.core.business.service import BusinessError, BusinessService
from agents.core.business.store import BusinessStore
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["business"])


class _StrictBody(BaseModel):
    model_config = {"extra": "forbid"}


class WorkspaceBody(_StrictBody):
    name: str = Field(min_length=1, max_length=120)
    industry: Literal["ecommerce", "automotive", "services"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    local_only: bool = True


class ConnectionBody(_StrictBody):
    provider: Literal["woocommerce", "hubspot"]
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(max_length=512)
    credentials: dict[str, str]

    @field_validator("credentials", mode="before")
    @classmethod
    def bounded_credentials(cls, value):
        if not isinstance(value, dict) or len(value) > 3 or any(
            not isinstance(key, str) or len(key) > 60 or not isinstance(secret, str) or len(secret) > 4096
            for key, secret in value.items()
        ):
            raise ValueError("Invalid credential fields")
        return value


class ImportBody(_StrictBody):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["orders", "products", "deals"]
    csv_text: str = Field(min_length=1, max_length=1_000_000)


class AskBody(_StrictBody):
    question: str = Field(min_length=1, max_length=2_000)


def enabled() -> bool:
    return os.getenv("NERVA_BUSINESS_ENABLED", "").strip() == "1"


def _service() -> BusinessService:
    return BusinessService(BusinessStore())


def _error(error: BusinessError):
    return nocache_json({"error": {"code": error.code, "message": error.message}}, status_code=error.status)


def _off():
    return _error(BusinessError("business_disabled", "Business workspace is disabled", 409))


@router.get("/api/business/catalog", dependencies=[Depends(user_guard)])
def business_catalog():
    return nocache_json({"enabled": enabled(), **catalog()})


@router.get("/api/business/workspace", dependencies=[Depends(user_guard)])
def business_workspace():
    if not enabled():
        return nocache_json({"enabled": False, "workspace": {"name": "", "industry": "services", "currency": "EUR", "local_only": True}, "connections": [], "reports": [], "activity": []})
    return nocache_json({"enabled": True, **_service().workspace()})


@router.put("/api/business/workspace", dependencies=[Depends(admin_guard)])
def update_business_workspace(body: WorkspaceBody):
    if not enabled():
        return _off()
    return nocache_json(_service().update_workspace(body.model_dump()))


@router.post("/api/business/connections", dependencies=[Depends(admin_guard)])
def add_business_connection(body: Annotated[Any, Body()]):
    if not enabled():
        return _off()
    try:
        parsed = ConnectionBody.model_validate(body)
    except ValidationError:
        return _error(BusinessError("invalid_request", "Check connection fields and credential limits", 422))
    try:
        connection = _service().add_connection(parsed.provider, parsed.name, parsed.base_url, parsed.credentials)
    except BusinessError as error:
        return _error(error)
    return nocache_json({"connection": connection})


@router.post("/api/business/connections/{connection_id}/sync", dependencies=[Depends(admin_guard)])
async def sync_business_connection(connection_id: str):
    if not enabled():
        return _off()
    try:
        service = await asyncio.to_thread(_service)
        connection = await service.sync(connection_id)
    except BusinessError as error:
        return _error(error)
    return nocache_json({"connection": connection})


@router.delete("/api/business/connections/{connection_id}", dependencies=[Depends(admin_guard)])
def delete_business_connection(connection_id: str):
    if not enabled():
        return _off()
    try:
        result = _service().remove_connection(connection_id)
    except BusinessError as error:
        return _error(error)
    return nocache_json(result)


@router.post("/api/business/import", dependencies=[Depends(admin_guard)])
def import_business_csv(body: ImportBody):
    if not enabled():
        return _off()
    try:
        connection = _service().import_csv(body.name, body.kind, body.csv_text)
    except BusinessError as error:
        return _error(error)
    return nocache_json({"connection": connection})


@router.post("/api/business/reports/{workflow_id}/run", dependencies=[Depends(user_guard)])
def run_business_report(workflow_id: str):
    if not enabled():
        return _off()
    try:
        report = _service().run_report(workflow_id)
    except BusinessError as error:
        return _error(error)
    return nocache_json({"report": report})


@router.post("/api/business/ask", dependencies=[Depends(user_guard)])
async def ask_business(body: AskBody):
    if not enabled():
        return _off()
    try:
        service = await asyncio.to_thread(_service)
        answer = await service.ask(body.question)
    except BusinessError as error:
        return _error(error)
    return nocache_json(answer)
