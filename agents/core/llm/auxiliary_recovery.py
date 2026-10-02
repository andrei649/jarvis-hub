"""Operation-bound permission for one local auxiliary parameter repair."""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx


@dataclass
class _RecoveryScope:
    backend: object
    model: str
    active: bool = True


_scope: ContextVar[_RecoveryScope | None] = ContextVar("auxiliary_parameter_recovery", default=None)


@contextmanager
def auxiliary_temperature_recovery_scope(backend: object, model: str):
    """Permit recovery only while this exact backend/model operation is active."""
    state = _RecoveryScope(backend, model)
    token = _scope.set(state)
    try:
        yield
    finally:
        state.active = False
        _scope.reset(token)


def may_repair_temperature(backend: object, model: object) -> bool:
    state = _scope.get()
    return bool(state is not None and state.active and state.backend is backend
                and state.model == model)


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
