"""Owner-only metadata and mutation for exact signed provider credentials."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictStr

from agents.core.web_helpers import nocache_json

from ._deps import admin_guard


class _CredentialRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's standard validation detail includes rejected input.
                return nocache_json({"error": "invalid_provider_credential_request"},
                                    status_code=422)

        return guarded


router = APIRouter(route_class=_CredentialRoute)


class CredentialTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: StrictStr = Field(min_length=1, max_length=128,
                                pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    package_hash: StrictStr = Field(min_length=64, max_length=64,
                                    pattern=r"^[0-9a-f]{64}$")


class CredentialPut(CredentialTarget):
    value: SecretStr = Field(min_length=1, max_length=4096)


def _sync(request, method, args):
    from .models_llm import _provider_install_context

    # Resolve the live web owner inside the worker that performs the mutation.
    service, actor = _provider_install_context(request)
    return getattr(service, method)(*args, actor=actor)


async def _call(request, method, *args):
    from agents.core.llm.providers.packages import ProviderPackageError

    from .models_llm import _provider_install_worker

    try:
        if method in {'put_credential', 'delete_credential'}:
            from agents.core.llm.providers import lifecycle_gates

            from .models_llm import _provider_install_context

            service, actor = await _provider_install_worker(_provider_install_context, request)
            await _provider_install_worker(service._owner, actor)
            store = await _provider_install_worker(lambda: service._store(actor=actor))
            await lifecycle_gates.quiesce(service.root, args[0], store)
        return nocache_json(await _provider_install_worker(_sync, request, method, args))
    except HTTPException:
        raise
    except (ProviderPackageError, ValueError, TypeError, KeyError, OSError):
        return nocache_json({"error": "provider_credential_refused"}, status_code=409)


@router.get("/api/admin/llm/provider-credentials", dependencies=[Depends(admin_guard)])
async def credential_status(request: Request,
                            provider: str = Query(min_length=1, max_length=128,
                                                  pattern=r"^[a-z0-9][a-z0-9._:-]*$"),
                            package_hash: str = Query(min_length=64, max_length=64,
                                                      pattern=r"^[0-9a-f]{64}$")):
    return await _call(request, "credential_status", provider, package_hash)


@router.put("/api/admin/llm/provider-credentials", dependencies=[Depends(admin_guard)])
async def put_credential(body: CredentialPut, request: Request):
    return await _call(request, "put_credential", body.provider, body.package_hash,
                       body.value.get_secret_value())


@router.delete("/api/admin/llm/provider-credentials", dependencies=[Depends(admin_guard)])
async def delete_credential(body: CredentialTarget, request: Request):
    return await _call(request, "delete_credential", body.provider, body.package_hash)
