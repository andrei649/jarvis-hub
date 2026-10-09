"""Owner-bound empty-result budget and active native vision request scope."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

RETRY_NOTICE = (
    "May retry once with the same images and model after an empty response "
    "(at most two model calls)."
)


class VisionRetryConfigError(ValueError):
    """The owner-controlled vision retry setting is invalid."""


def resolve_vision_empty_retries(env: Mapping[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    raw = source.get("JARVIS_ROLE_VISION_EMPTY_RETRIES", "")
    if not isinstance(raw, str) or len(raw) > 16:
        raise VisionRetryConfigError("invalid vision empty retry setting")
    value = raw.strip(" ")
    if value in {"", "0"}:
        return 0
    if value == "1":
        return 1
    raise VisionRetryConfigError("invalid vision empty retry setting")


@dataclass
class VisionRetryScope:
    backend: object
    model: str
    check: object
    active: bool = True
    started: bool = False
    expected_digest: bytes | None = None
    prepared_json: str | None = None
    attempts: int = 0
    sent: bool = False
    max_attempts: int = 2

    def _alive(self):
        if not self.active or _current.get() is not self:
            raise RuntimeError("vision retry scope is closed")

    def begin(self, payload: dict):
        self._alive()
        if self.started:
            raise RuntimeError("vision retry operation already started")
        self.started = True
        self.prepared_json = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False)
        self.expected_digest = hashlib.sha256(self.prepared_json.encode()).digest()

    def next_attempt(self):
        self._alive()
        if not self.started or self.attempts >= self.max_attempts:
            raise RuntimeError("vision retry limit exceeded")
        self.attempts += 1
        self.sent = False
        self.check()
        return json.loads(self.prepared_json)

    def validate(self, request, *, marked: bool = False):
        self._alive()
        try:
            actual = hashlib.sha256(json.dumps(
                json.loads(request.content), sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False).encode()).digest()
        except (TypeError, ValueError, UnicodeError):
            actual = b""
        if (self.expected_digest is None or self.attempts < 1 or self.sent != marked
                or not hmac.compare_digest(actual, self.expected_digest)):
            raise RuntimeError("vision physical request changed")
        if not marked:
            self.sent = True


_current: ContextVar[VisionRetryScope | None] = ContextVar("vision_empty_retry_scope", default=None)


@contextmanager
def vision_retry_scope(backend: object, model: str, check, *, max_attempts: int = 2):
    if max_attempts not in (1, 2):
        raise ValueError("invalid vision attempt budget")
    state = VisionRetryScope(backend, model, check, max_attempts=max_attempts)
    token = _current.set(state)
    try:
        yield state
    finally:
        state.active = False
        _current.reset(token)


def current_vision_retry(backend: object, model: str) -> VisionRetryScope | None:
    state = _current.get()
    if state is not None and state.active and state.backend is backend and state.model == model:
        return state
    return None
