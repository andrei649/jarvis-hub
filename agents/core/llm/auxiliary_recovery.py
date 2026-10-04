"""Operation-bound permission for one local auxiliary parameter repair."""

from __future__ import annotations

import asyncio
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx


@dataclass
class _RecoveryScope:
    backend: object
    model: str
    task: asyncio.Task | None
    route: _TemperatureCache | None = None
    role: str | None = None
    output_cap_rejected: bool = False
    active: bool = True


@dataclass
class _TemperatureCache:
    client: object
    base_url: str
    client_base_url: str
    transport: object
    models: set[str]


_MAX_TEMPERATURE_ROUTES = 128
_OUTPUT_CAP_ROLES = frozenset({
    "session_title", "query_rewrite", "review", "compression",
    "acquisition_capability", "acquisition_draft", "soul_description",
})


_scope: ContextVar[_RecoveryScope | None] = ContextVar("auxiliary_parameter_recovery", default=None)


def _current_task() -> asyncio.Task | None:
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


@contextmanager
def auxiliary_temperature_recovery_scope(backend: object, model: str, *, role: str | None = None):
    """Permit temperature repair; cap repair also needs a supported guarded role."""
    state = _RecoveryScope(backend, model, _current_task(),
                           _temperature_cache(backend, create=True), role=role)
    token = _scope.set(state)

    def revoke() -> None:
        # A stream supervisor may revoke before cancelling a child that suppresses
        # cancellation. This touches shared state, never another task's ContextVar.
        state.active = False

    try:
        yield revoke
    finally:
        revoke()
        _scope.reset(token)


def may_repair_temperature(backend: object, model: object) -> bool:
    state = _scope.get()
    return bool(state is not None and state.active and state.backend is backend
                and state.model == model and state.task is _current_task()
                and (state.route is None
                     or _temperature_cache(backend, create=False) is state.route))


def _temperature_cache(backend: object, *, create: bool) -> _TemperatureCache | None:
    """Keep learned capability only on this backend's current physical route."""
    try:
        state = vars(backend)
    except TypeError:
        return None
    if type(state) is not dict:
        return None
    client = state.get("client")
    base_url = state.get("base_url")
    if client is None or type(base_url) is not str:
        return None
    try:
        client_base_url = str(client.base_url)
        request_url = client.build_request("POST", "/v1/chat/completions").url
        transport = client._transport_for_url(request_url)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if transport is None:
        return None
    cache = state.get("_auxiliary_temperature_cache")
    if (type(cache) is _TemperatureCache and cache.client is client
            and cache.base_url == base_url
            and cache.client_base_url == client_base_url
            and cache.transport is transport):
        return cache
    state.pop("_auxiliary_temperature_cache", None)
    if not create:
        return None
    cache = _TemperatureCache(client, base_url, client_base_url, transport, set())
    state["_auxiliary_temperature_cache"] = cache
    return cache


def omit_rejected_temperature(backend: object, model: object) -> bool:
    """Return a previously proven omission only inside the exact auxiliary call."""
    if not may_repair_temperature(backend, model):
        return False
    cache = _temperature_cache(backend, create=False)
    return bool(cache is not None and model in cache.models)


def remember_temperature_rejection(backend: object, model: object) -> None:
    """Learn only after a typed rejection's repaired request has succeeded."""
    if not may_repair_temperature(backend, model) or type(model) is not str:
        return
    cache = _temperature_cache(backend, create=True)
    if cache is None:
        return
    if len(cache.models) >= _MAX_TEMPERATURE_ROUTES:
        cache.models.clear()
    cache.models.add(model)


def rejects_temperature(exc: BaseException) -> bool:
    """Recognize only a small structured HTTP 400 parameter rejection."""
    if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code != 400:
        return False
    response = exc.response
    try:
        if len(response.content) > 4096:
            return False
        body = response.json()
    except (ValueError, RuntimeError):
        return False
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return False
    error = body["error"]
    param = error.get("param")
    if param is not None and param != "temperature":
        return False
    code = error.get("code")
    if param == "temperature" and code == "unsupported_parameter":
        return True
    message = error.get("message")
    if not isinstance(message, str) or len(message) > 512:
        return False
    words = message.lower()
    marker = r"(?:unsupported|unknown|unrecognized)"
    field = r"(?:parameter|argument|setting|value)"
    return bool(
        re.search(rf"\b{marker}\s+{field}\s*[:=]?\s*['\"]?temperature\b", words)
        or re.search(rf"\b{field}\s*[:=]?\s*['\"]?temperature['\"]?\s+(?:is\s+)?{marker}\b", words)
        or re.search(rf"\btemperature\b\s+(?:is\s+)?(?:an?\s+)?{marker}\b", words)
    )


def may_repair_output_cap(backend: object, model: object) -> bool:
    """Permit a cap rung only on the current direct, guarded local auxiliary route."""
    if not may_repair_temperature(backend, model):
        return False
    state = _scope.get()
    if state is None or state.role not in _OUTPUT_CAP_ROLES or state.route is None:
        return False
    from .data_handling import _physical_guard
    from .direct_transport import require_direct_async_transport
    from .model_roles import public_local_origin, same_origin

    guard = _physical_guard.get()
    route = state.route
    if guard is None or not guard.active or guard.check is None:
        return False
    if (not public_local_origin(route.base_url)
            or not same_origin(route.base_url, route.client_base_url)):
        return False
    try:
        request_url = route.client.build_request("POST", "/v1/chat/completions").url
        require_direct_async_transport(route.client, request_url)
    except Exception:
        return False
    return True


def rejects_output_cap(exc: BaseException) -> bool:
    """Recognize only a bounded structured HTTP 400 naming unsupported max_tokens."""
    if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code != 400:
        return False
    try:
        if len(exc.response.content) > 4096:
            return False
        body = exc.response.json()
    except (ValueError, RuntimeError):
        return False
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return False
    error = body["error"]
    param = error.get("param")
    if param is not None and param != "max_tokens":
        return False
    code = error.get("code")
    if param == "max_tokens" and code in {
            "unsupported_parameter", "unknown_parameter", "unrecognized_parameter"}:
        return True
    message = error.get("message")
    if not isinstance(message, str) or len(message) > 512:
        return False
    words = message.lower()
    marker = r"(?:unsupported|unknown|unrecognized)"
    field = r"(?:parameter|argument|setting|value)"
    return bool(
        re.search(rf"\b{marker}\s+{field}\s*[:=]?\s*['\"]?max_tokens\b", words)
        or re.search(rf"\b{field}\s*[:=]?\s*['\"]?max_tokens['\"]?\s+(?:is\s+)?{marker}\b", words)
        or re.search(rf"\bmax_tokens\b\s+(?:is\s+)?(?:an?\s+)?{marker}\b", words)
    )


def note_output_cap_rejection(backend: object, model: object, exc: BaseException) -> bool:
    """Authorize omission only after this operation's actual typed rejection."""
    if not may_repair_output_cap(backend, model) or not rejects_output_cap(exc):
        return False
    state = _scope.get()
    if state is None:
        return False
    state.output_cap_rejected = True
    return True


def may_omit_rejected_output_cap(backend: object, model: object) -> bool:
    """The strict SOUL physical body guard's exact-operation omission flag."""
    state = _scope.get()
    return bool(state is not None and state.output_cap_rejected
                and may_repair_output_cap(backend, model))
