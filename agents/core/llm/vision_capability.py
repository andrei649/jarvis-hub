"""Model-scoped, offline eligibility for the selected main image route."""

from __future__ import annotations

import json
from types import MappingProxyType

import httpx

_MAX_METADATA_BYTES = 1024 * 1024


def _valid_model(model: object) -> bool:
    return (type(model) is str and bool(model) and model.strip() == model
            and len(model) <= 512
            and not any(ord(char) < 32 or ord(char) == 127 for char in model))


def main_vision_eligibility(backend: object, model: str) -> bool | None:
    """Read an exact, backend-owned model verdict without provider or network probes.

    ``backend.model_vision_capabilities`` may be a plain dict or read-only
    mapping proxy of exact model IDs to real booleans. A missing entry is
    unknown; provider-wide capabilities and model-name guesses are not proof.
    The snapshot is read directly from instance state so a property cannot
    initiate an ambient lookup while preparing an image turn.
    """
    if not _valid_model(model):
        return None
    try:
        state = object.__getattribute__(backend, "__dict__")
    except (AttributeError, TypeError):
        return None
    if type(state) is not dict:
        return None
    snapshot = state.get("model_vision_capabilities")
    if type(snapshot) not in (dict, MappingProxyType):
        return None
    verdict = snapshot.get(model)
    return verdict if type(verdict) is bool else None


def _publish(backend: object, model: str, verdict: bool | None) -> None:
    snapshot = getattr(backend, "model_vision_capabilities", None)
    entries = dict(snapshot) if type(snapshot) in (dict, MappingProxyType) else {}
    entries.pop(model, None)
    if type(verdict) is bool:
        entries[model] = verdict
    backend.model_vision_capabilities = MappingProxyType(entries)


def _lm_studio_verdict(payload: object, model: str) -> bool | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return None
    matches = [row for row in payload["models"]
               if isinstance(row, dict) and row.get("key") == model]
    if len(matches) != 1 or matches[0].get("type") != "llm":
        return None
    capabilities = matches[0].get("capabilities")
    if not isinstance(capabilities, dict):
        return None
    verdict = capabilities.get("vision")
    return verdict if type(verdict) is bool else None


def _ollama_verdict(payload: object) -> bool | None:
    if not isinstance(payload, dict):
        return None
    capabilities = payload.get("capabilities")
    if (not isinstance(capabilities, list) or not capabilities
            or any(type(item) is not str or not item for item in capabilities)):
        return None
    return "vision" in capabilities


async def prepare_local_model_vision(backend: object, model: str) -> bool | None:
    """Refresh one selected local model's explicit vision verdict before review.

    Metadata is best effort. A failed or unsupported probe clears a prior
    verdict so a stale text-only result cannot silently govern a later turn.
    Cancellation remains visible to the caller.
    """
    from .base import LMStudioBackend, OllamaBackend
    from .data_handling import DataHandlingRefused, physical_request_scope
    from .direct_transport import require_direct_async_transport
    from .model_roles import public_local_origin, same_origin

    if not _valid_model(model) or type(backend) not in (LMStudioBackend, OllamaBackend):
        return None
    _publish(backend, model, None)
    endpoint = str(backend.base_url)
    if not public_local_origin(endpoint):
        return None
    client = backend.client
    lm_studio = type(backend) is LMStudioBackend
    method = "GET" if lm_studio else "POST"
    path = "/api/v1/models" if lm_studio else "/api/show"
    request_json = None if lm_studio else {"model": model}
    try:
        expected_request = client.build_request(method, path, json=request_json)
        expected = expected_request.url
        expected_body = expected_request.content
        if (not same_origin(endpoint, str(client.base_url))
                or not same_origin(endpoint, str(expected))):
            return None
        require_direct_async_transport(client, expected)

        def request_check(request: httpx.Request) -> None:
            if (request.method != method or request.url != expected
                    or request.content != expected_body
                    or backend.client is not client
                    or not public_local_origin(str(backend.base_url))
                    or not same_origin(endpoint, str(backend.base_url))):
                raise DataHandlingRefused("local model metadata request changed")
            require_direct_async_transport(client, request.url)

        with physical_request_scope(None, request_check=request_check):
            async with client.stream(
                method, path, json=request_json,
                timeout=3.0, follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    return None
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_METADATA_BYTES:
                        return None
        payload = json.loads(body)
        verdict = (_lm_studio_verdict(payload, model) if lm_studio
                   else _ollama_verdict(payload))
        _publish(backend, model, verdict)
        return verdict
    except (DataHandlingRefused, httpx.HTTPError, RuntimeError, ValueError, TypeError):
        return None
