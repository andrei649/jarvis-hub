"""Request-owned proof that a strict-local model call stays on this machine."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from .data_handling import DataHandlingRefused


class _Scope:
    active = True
    error: Exception | None = None


_SCOPE: ContextVar[_Scope | None] = ContextVar("physical_local_scope", default=None)
_OLLAMA_WIRE: ContextVar[str | None] = ContextVar("physical_local_ollama_wire", default=None)


@contextmanager
def physical_local_scope():
    state = _Scope()
    token = _SCOPE.set(state)
    try:
        yield
    finally:
        state.active = False
        _SCOPE.reset(token)
        if state.error is not None:
            raise state.error


def physical_local_required() -> bool:
    return _SCOPE.get() is not None


def check_physical_local_request(request, client, backend: str) -> None:
    """Final URL and selected transport, including a redirect's destination."""
    state = _SCOPE.get()
    if state is None:
        return
    if state.error is not None:
        raise state.error
    try:
        from .direct_transport import require_direct_async_transport
        from .model_roles import public_local_origin

        if not state.active or backend not in {"ollama", "lm-studio"}:
            raise DataHandlingRefused("strict-local model backend changed")
        if (request.method != "POST" or request.url.scheme not in {"http", "https"}
                or not public_local_origin(str(request.url))):
            raise DataHandlingRefused("strict-local model destination is not loopback")
        require_direct_async_transport(client, request.url)
        selector = _OLLAMA_WIRE.get()
        if backend == "ollama" and request.url.path in {"/api/generate", "/api/chat"}:
            if selector is None:
                raise DataHandlingRefused("strict-local Ollama selector is missing")
            try:
                sent_model = json.loads(request.content).get("model")
            except (ValueError, AttributeError, TypeError, RuntimeError):
                sent_model = None
            if sent_model != selector:
                raise DataHandlingRefused("strict-local Ollama model selector changed")
        elif backend == "ollama" and selector is not None:
            raise DataHandlingRefused("strict-local Ollama request path changed")
    except Exception as exc:
        state.error = exc
        raise


def ollama_local_selector(model: str) -> str:
    if not isinstance(model, str) or not model or len(model) > 113:
        raise DataHandlingRefused("strict-local Ollama model is invalid")
    tagged = model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"
    return tagged if tagged.endswith(":local") else f"{tagged}:local"


def ollama_wire_model(model: str) -> str:
    return _OLLAMA_WIRE.get() or model


def physical_local_ollama(method):
    """Keep logical routing identity while accounting for the exact wire selector."""
    @wraps(method)
    async def call(self, model, *args, **kwargs):
        if not physical_local_required():
            return await method(self, model, *args, **kwargs)
        from agents.core.turn_usage import wire_model_usage_scope

        selector = ollama_local_selector(model)
        token = _OLLAMA_WIRE.set(selector)
        try:
            with wire_model_usage_scope(model=selector, route="local"):
                return await method(self, model, *args, **kwargs)
        finally:
            _OLLAMA_WIRE.reset(token)
    return call


def hard_local_agent_call(method):
    @wraps(method)
    async def call(self, *args, **kwargs):
        from .hybrid_router import LOCAL_ONLY_AGENTS

        if getattr(self, "id", None) not in LOCAL_ONLY_AGENTS:
            return await method(self, *args, **kwargs)
        with physical_local_scope():
            return await method(self, *args, **kwargs)
    return call


def hard_local_synthesis(method):
    @wraps(method)
    async def call(self, responses, *args, **kwargs):
        if not self._strict_local_contributors(responses):
            return await method(self, responses, *args, **kwargs)
        with physical_local_scope():
            return await method(self, responses, *args, **kwargs)
    return call


def hard_local_moa_call(method):
    """Cover a committee called directly, outside Agent.generate_response."""
    @wraps(method)
    async def call(self, *args, **kwargs):
        from .hybrid_router import LOCAL_ONLY_AGENTS

        if self._agent_id not in LOCAL_ONLY_AGENTS or physical_local_required():
            return await method(self, *args, **kwargs)
        with physical_local_scope():
            return await method(self, *args, **kwargs)
    return call
