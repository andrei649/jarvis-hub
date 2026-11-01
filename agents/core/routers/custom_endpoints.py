"""Owner-only named compatible endpoints; body bytes never supply authority."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from agents.core.app_state import get_orch
from agents.core.web_helpers import nocache_json

from ._deps import admin_guard


class _SafeRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return nocache_json({'error': 'invalid_custom_endpoint_request'}, status_code=422)

        return guarded


router = APIRouter(route_class=_SafeRoute)


class CreateBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    key: StrictStr = Field(min_length=1, max_length=64)
    name: StrictStr = Field(min_length=1, max_length=100)
    base_url: StrictStr = Field(min_length=1, max_length=2048)
    model: StrictStr = Field(min_length=1, max_length=256)
    auth_type: StrictStr
    data_policy: StrictStr
    grant_destination: StrictBool = False


class RenameBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: StrictStr = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)


class ActivateBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)
    expected_choice_epoch: int = Field(ge=0)
    acknowledge_unknown_price: StrictBool = False
    acknowledge_data_policy: StrictBool = False
    grant_destination: StrictBool = False


class DeleteBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)


class ClearBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_choice_epoch: int = Field(ge=0)


class CredentialBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    secret: StrictStr = Field(min_length=1, max_length=4096)


def _context(request):
    from agents.core.autonomy.consent_types import OwnerConsentActor
    from agents.core.llm.custom_endpoint_service import get_custom_endpoint_service
    from agents.core.routers.autonomy import _consent_admin_current

    orch = get_orch()
    service = get_custom_endpoint_service(orch)
    if service is None:
        raise HTTPException(status_code=409, detail='custom_endpoint_unavailable')
    actor = OwnerConsentActor('owner', 'admin', lambda: _consent_admin_current(request, orch))
    return service, actor


def _sync(request, method, kwargs):
    service, actor = _context(request)
    return getattr(service, method)(actor=actor, **kwargs)


async def _worker(fn, *args):
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


async def _refresh(request):
    service, _ = await _worker(_context, request)
    orch = get_orch()
    route = getattr(getattr(orch, 'llm_router', None), 'refresh_custom', None)
    if callable(route):
        task = asyncio.create_task(route(service))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError


async def _call(request, method, kwargs, *, refresh=False):
    from agents.core.llm import selection_guards
    from agents.core.llm.custom_endpoints import CustomEndpointConflict, CustomEndpointInvalid
    from agents.core.llm.providers.packages import ProviderPackageError
    from agents.core.llm.providers.selection_gates import SelectionBusy, SelectionUnavailable

    try:
        if method == 'validate':
            service, actor = await _worker(_context, request)
            result = await service.validate(actor=actor, **kwargs)
        else:
            try:
                result = await _worker(_sync, request, method, kwargs)
            except asyncio.CancelledError:
                # The worker has already drained to an outcome. Publish a
                # committed choice to the running router before cancellation
                # unwinds this HTTP handler.
                if refresh:
                    await _refresh(request)
                raise
        if refresh:
            await _refresh(request)
        return nocache_json(result)
    except HTTPException:
        raise
    except (CustomEndpointConflict, SelectionBusy):
        return nocache_json({'error': 'custom_endpoint_stale_or_busy'}, status_code=409)
    except SelectionUnavailable:
        return nocache_json({'error': 'custom_endpoint_lease_unavailable'}, status_code=503)
    except selection_guards.SelectionRefused as exc:
        needs = sorted(set(exc.missing))
        return nocache_json({'error': 'selection_guard', 'needs': needs}, status_code=409)
    except (CustomEndpointInvalid, ProviderPackageError, ValueError, TypeError, KeyError, OSError):
        return nocache_json({'error': 'custom_endpoint_refused'}, status_code=409)


@router.get('/api/admin/llm/custom-endpoints', dependencies=[Depends(admin_guard)])
async def list_custom(request: Request):
    return await _call(request, 'list', {})


@router.post('/api/admin/llm/custom-endpoints', dependencies=[Depends(admin_guard)])
async def create_custom(body: CreateBody, request: Request):
    return await _call(request, 'create', body.model_dump())


@router.put('/api/admin/llm/custom-endpoints/{key}', dependencies=[Depends(admin_guard)])
async def rename_custom(key: str, body: RenameBody, request: Request):
    return await _call(request, 'rename', {'key': key, **body.model_dump()}, refresh=True)


@router.put('/api/admin/llm/custom-endpoints/{key}/activate', dependencies=[Depends(admin_guard)])
async def activate_custom(key: str, body: ActivateBody, request: Request):
    return await _call(request, 'activate', {'key': key, **body.model_dump()}, refresh=True)


@router.delete('/api/admin/llm/custom-endpoints/active', dependencies=[Depends(admin_guard)])
async def clear_custom(body: ClearBody, request: Request):
    return await _call(request, 'clear', body.model_dump(), refresh=True)


@router.delete('/api/admin/llm/custom-endpoints/{key}', dependencies=[Depends(admin_guard)])
async def delete_custom(key: str, body: DeleteBody, request: Request):
    return await _call(request, 'delete', {'key': key, **body.model_dump()}, refresh=True)


@router.post('/api/admin/llm/custom-endpoints/{key}/validate', dependencies=[Depends(admin_guard)])
async def validate_custom(key: str, request: Request):
    return await _call(request, 'validate', {'key': key})


@router.get('/api/admin/llm/custom-endpoints/{key}/credential', dependencies=[Depends(admin_guard)])
async def credential_status(key: str, request: Request):
    return await _call(request, 'credential_status', {'key': key})


@router.put('/api/admin/llm/custom-endpoints/{key}/credential', dependencies=[Depends(admin_guard)])
async def credential_put(key: str, body: CredentialBody, request: Request):
    return await _call(request, 'credential_mutation',
                       {'key': key, 'value': body.secret}, refresh=True)


@router.delete('/api/admin/llm/custom-endpoints/{key}/credential', dependencies=[Depends(admin_guard)])
async def credential_delete(key: str, request: Request):
    return await _call(request, 'credential_mutation',
                       {'key': key, 'delete': True}, refresh=True)
