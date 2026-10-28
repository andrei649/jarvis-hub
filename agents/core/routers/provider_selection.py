"""Owner-only signed provider selection; request bodies never supply authority."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from agents.core.web_helpers import nocache_json

from ._deps import admin_guard


class _SelectionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return nocache_json({'error': 'invalid_provider_selection_request'}, status_code=422)

        return guarded


router = APIRouter(route_class=_SelectionRoute)


class SelectBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    provider: StrictStr = Field(min_length=1, max_length=128,
                                pattern=r'^[a-z0-9][a-z0-9._:-]*$')
    package_hash: StrictStr = Field(min_length=64, max_length=64,
                                    pattern=r'^[0-9a-f]{64}$')
    model: StrictStr = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=0)
    acknowledge_unknown_price: StrictBool = False
    acknowledge_data_policy: StrictBool = False


class ClearBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=0)


def _sync(request, method, kwargs):
    from .models_llm import _provider_install_context

    service, actor = _provider_install_context(request)
    return getattr(service, method)(actor=actor, **kwargs)


async def _call(request, method, kwargs):
    from agents.core.llm import selection_guards
    from agents.core.llm.provider_selection import SelectionConflict, SelectionInvalid
    from agents.core.llm.providers.packages import ProviderPackageError
    from agents.core.llm.providers.selection_gates import SelectionBusy, SelectionUnavailable

    from .models_llm import _provider_install_worker

    try:
        if method in {'select_provider', 'clear_selection'}:
            from agents.core.llm.provider_selection import read_selection
            from agents.core.llm.providers import lifecycle_gates

            from .models_llm import _provider_install_context

            service, actor = await _provider_install_worker(_provider_install_context, request)
            await _provider_install_worker(service._owner, actor)
            previous = await _provider_install_worker(read_selection)
            if previous is not None:
                store = await _provider_install_worker(lambda: service._store(actor=actor))
                await lifecycle_gates.quiesce(service.root, previous.binding.provider_id, store)
        result = await _provider_install_worker(_sync, request, method, kwargs)
        if method in {'select_provider', 'clear_selection'}:
            from agents.core.app_state import get_orch

            live = get_orch()
            active_router = getattr(live, 'llm_router', None)
            refresher = getattr(active_router, 'refresh_selected', None)
            if callable(refresher):
                await refresher(service)
        return nocache_json(result)
    except HTTPException:
        raise
    except (SelectionConflict, SelectionBusy):
        return nocache_json({'error': 'provider_selection_stale_or_busy'}, status_code=409)
    except SelectionUnavailable:
        return nocache_json({'error': 'provider_selection_unavailable'}, status_code=503)
    except selection_guards.SelectionRefused as exc:
        needs = (['acknowledge_data_policy']
                 if selection_guards.ACKNOWLEDGE_TRAINING in exc.missing else [])
        if any(flag != selection_guards.ACKNOWLEDGE_TRAINING for flag in exc.missing):
            needs.append('additional_guard')
        return nocache_json({'error': 'selection_guard', 'needs': needs}, status_code=409)
    except (ProviderPackageError, SelectionInvalid, ValueError, TypeError, KeyError, OSError):
        return nocache_json({'error': 'provider_selection_refused'}, status_code=409)


@router.get('/api/admin/llm/provider-selection', dependencies=[Depends(admin_guard)])
async def selection_status(request: Request):
    return await _call(request, 'selection_status', {})


@router.put('/api/admin/llm/provider-selection', dependencies=[Depends(admin_guard)])
async def select_provider(body: SelectBody, request: Request):
    return await _call(request, 'select_provider', {
        **body.model_dump(exclude={'provider'}), 'provider_id': body.provider})


@router.delete('/api/admin/llm/provider-selection', dependencies=[Depends(admin_guard)])
async def clear_selection(body: ClearBody, request: Request):
    return await _call(request, 'clear_selection', body.model_dump())
