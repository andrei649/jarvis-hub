"""Request-owned, fail-closed observation of accepted generative HTTP attempts.

A dispatch is not an invoice. Provider counts and exact list prices are shown only
when every observed attempt has one complete, correlated usage publication.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agents.core.llm.cost_estimator import MODELS, PRICES_VERIFIED

_SCHEMA = "nerva.turn.usage.v1"
_MAX_CALLS = 1_000_000
_MAX_TOKENS = 1_000_000_000_000
_MAX_COST = 1_000_000_000
_MAX_BREAKDOWN = 16
_MAX_PAIRS = 64
_MAX_PENDING = 64
_MAX_SEEN_USAGE = 128
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]*\Z")
_CURRENT: ContextVar[TurnUsage | None] = ContextVar("turn_usage_collector", default=None)
_MODEL: ContextVar[_Generation | None] = ContextVar("turn_usage_model", default=None)


def _identity(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not (1 <= len(value) <= limit):
        return None
    return value if _IDENTITY.fullmatch(value) and "//" not in value else None


def _owner() -> object:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return task if task is not None else ("thread", threading.get_ident())


def _generation_request(request: Any) -> bool:
    """Known generative paths only; do not count /models, /api/show or embeddings."""
    if getattr(request, "method", "").upper() != "POST":
        return False
    path = getattr(getattr(request, "url", None), "path", "")
    return (path.endswith(("/chat/completions", "/responses", "/messages",
                           "/api/chat", "/api/generate", "/completions"))
            or path.endswith((":generateContent", ":streamGenerateContent"))
            or (path.startswith("/model/") and path.endswith(("/invoke", "/invoke-with-response-stream"))))


def _known_control_post(provider: str, request: Any) -> bool:
    """Exact non-inference POSTs used by owned model clients during preparation."""
    path = getattr(getattr(request, "url", None), "path", "")
    if provider == "ollama" and path in {"/api/show", "/api/embed", "/api/embeddings"}:
        return True
    if provider == "lm-studio" and path == "/v1/embeddings":
        return True
    if provider == "gemini":
        return (path in {"/v1/cachedContents", "/v1beta/cachedContents"}
                or (path.startswith(("/v1/models/", "/v1beta/models/"))
                    and path.endswith((":embedContent", ":batchEmbedContents"))))
    return False


def _wire_model(request: Any) -> str | None:
    """Use the physical request's model selector, never a final UI label."""
    path = getattr(getattr(request, "url", None), "path", "")
    if ":generateContent" in path or ":streamGenerateContent" in path:
        return _identity(path.rsplit("/models/", 1)[-1].split(":", 1)[0], 120)
    try:
        body = request.content
        if len(body) > 1_000_000:
            return None
        payload = json.loads(body)
        return _identity(payload.get("model"), 120) if isinstance(payload, dict) else None
    except (AttributeError, RuntimeError, TypeError, ValueError, UnicodeError):
        return None


def _local_proof(provider: str, request: Any, route: str) -> bool:
    if provider not in {"lm-studio", "ollama"} or route not in {
            "local", "local-fallback", "local-deep"}:
        return False
    from agents.core.http_client import host_is_local
    host = getattr(getattr(request, "url", None), "host", "") or ""
    try:
        return bool(host_is_local(host.lower().rstrip(".")))
    except Exception:
        return False


@dataclass(slots=True)
class _Generation:
    collector: TurnUsage
    model: str | None
    route: str
    parent: _Generation | None = None
    dispatches: int = 0
    active: bool = True


@dataclass(slots=True)
class _Pair:
    provider: str | None
    model: str | None
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    unknown_usage: bool = False
    unknown_cost: bool = False
    local_only: bool = True
    priced: bool = False


@dataclass(slots=True)
class _Pending:
    pair: _Pair
    local: bool


class TurnUsage:
    """One request's mutable accounting state; snapshots are immutable copies."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._api_calls = 0
        self._unattributed = False
        self._pairs: dict[tuple[str | None, str | None], _Pair] = {}
        self._pending: dict[object, _Pending] = {}
        # Strong references prevent id reuse while the bounded turn is open.
        self._seen_usage: dict[int, Any] = {}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            for attempt in self._pending.values():
                attempt.pair.unknown_usage = True
                attempt.pair.unknown_cost = True
            self._pending.clear()
            self._seen_usage.clear()
            self._closed = True

    def _dispatch(self, provider: str | None, model: str | None, route: str,
                  request: Any, owner: object) -> None:
        with self._lock:
            if self._closed:
                return
            if self._api_calls >= _MAX_CALLS:
                self._unattributed = True
                return
            self._api_calls += 1
            key = (provider, model)
            if key not in self._pairs:
                if len(self._pairs) >= _MAX_PAIRS:
                    self._unattributed = True
                    return
                self._pairs[key] = _Pair(provider, model)
            pair = self._pairs[key]
            pair.api_calls += 1
            old = self._pending.pop(owner, None)
            if old is not None:
                old.pair.unknown_usage = True
                old.pair.unknown_cost = True
            if owner not in self._pending and len(self._pending) >= _MAX_PENDING:
                pair.unknown_usage = pair.unknown_cost = True
                self._unattributed = True
                return
            local = _local_proof(provider or "", request, route)
            pair.local_only &= local
            self._pending[owner] = _Pending(pair, local)

    def _usage(self, usage: Any, owner: object) -> None:
        with self._lock:
            if self._closed:
                return
            if self._seen_usage.get(id(usage)) is usage:
                return
            attempt = self._pending.pop(owner, None)
            if attempt is None:
                return  # duplicate, unrelated task, or no accepted dispatch
            if len(self._seen_usage) >= _MAX_SEEN_USAGE:
                self._unattributed = True
            else:
                self._seen_usage[id(usage)] = usage
            pair = attempt.pair
            fields = [getattr(usage, key, None) for key in
                      ("input_tokens", "output_tokens", "cache_read", "cache_write")]
            if (getattr(usage, "counts_complete", None) is not True
                    or any(type(value) is not int or not 0 <= value <= _MAX_TOKENS
                           for value in fields)
                    or sum(fields) > _MAX_TOKENS):
                pair.unknown_usage = pair.unknown_cost = True
                return
            inputs, outputs, cache_read, cache_write = fields
            pair.input_tokens += inputs + cache_read + cache_write
            pair.output_tokens += outputs
            if pair.input_tokens > _MAX_TOKENS or pair.output_tokens > _MAX_TOKENS:
                pair.unknown_usage = pair.unknown_cost = True
                return
            if attempt.local:
                return
            if pair.model is None or cache_write or (
                    pair.model.startswith("gemini-") and "pro" in pair.model
                    and inputs + cache_read + cache_write > 200_000):
                pair.unknown_cost = True
                return
            price = MODELS.get(pair.model)
            if (price is None or (price["input"] == price["output"] == 0)
                    or (cache_read and price.get("cached") is None)):
                pair.unknown_cost = True
                return
            rate = price.get("cached") or 0
            amount = (inputs * price["input"] + outputs * price["output"]
                      + cache_read * rate) / 1_000_000
            if not math.isfinite(amount) or not 0 <= amount <= _MAX_COST:
                pair.unknown_cost = True
                return
            pair.estimated_cost_usd += amount
            pair.priced = True
            if pair.estimated_cost_usd > _MAX_COST:
                pair.unknown_cost = True

    def snapshot(self) -> dict:
        with self._lock:
            pairs = list(self._pairs.values())
            pending = {id(item.pair) for item in self._pending.values()}
            bad_usage = self._unattributed or any(
                pair.unknown_usage or id(pair) in pending for pair in pairs)
            bad_cost = bad_usage or any(pair.unknown_cost for pair in pairs)
            bad_calls = self._unattributed
            if not pairs and not bad_calls:
                usage_basis = cost_basis = "measured_zero"
            else:
                usage_basis = "unknown" if bad_usage else "provider_complete"
                cost_basis = ("unknown" if bad_cost else
                              "local_zero" if all(pair.local_only for pair in pairs) else
                              "price_table")
            breakdown = []
            for pair in pairs[:_MAX_BREAKDOWN]:
                pair_bad_usage = pair.unknown_usage or id(pair) in pending
                pair_bad_cost = pair_bad_usage or pair.unknown_cost
                breakdown.append({
                    "provider": pair.provider, "model": pair.model,
                    "api_calls": pair.api_calls,
                    "input_tokens": None if pair_bad_usage else pair.input_tokens,
                    "output_tokens": None if pair_bad_usage else pair.output_tokens,
                    "estimated_cost_usd": None if pair_bad_cost else
                    (0.0 if pair.local_only else round(pair.estimated_cost_usd, 10)),
                    "usage_basis": "unknown" if pair_bad_usage else "provider_complete",
                    "cost_basis": ("unknown" if pair_bad_cost else
                                   "local_zero" if pair.local_only else "price_table"),
                })
            one = pairs[0] if len(pairs) == 1 and not bad_calls else None
            result = {
                "schema": _SCHEMA,
                "api_calls": None if bad_calls else self._api_calls,
                "input_tokens": None if bad_usage else sum(pair.input_tokens for pair in pairs),
                "output_tokens": None if bad_usage else sum(pair.output_tokens for pair in pairs),
                "estimated_cost_usd": None if bad_cost else
                (0.0 if not pairs else round(sum(pair.estimated_cost_usd for pair in pairs), 10)),
                "model": one.model if one else None,
                "provider": one.provider if one else None,
                "usage_basis": usage_basis,
                "cost_basis": cost_basis,
                "breakdown": breakdown,
                "breakdown_truncated": len(pairs) > _MAX_BREAKDOWN,
            }
            if cost_basis == "price_table":
                result["price_verified_at"] = PRICES_VERIFIED
            return result


@contextmanager
def turn_usage_scope():
    """Bind and close one collector; inherited children cannot mutate it later."""
    collector = TurnUsage()
    token = _CURRENT.set(collector)
    try:
        yield collector
    finally:
        collector.close()
        _CURRENT.reset(token)


@contextmanager
def model_usage_scope(*, model: str, route: str = ""):
    """Mark real generation intent and carry routed model provenance to egress."""
    collector = _CURRENT.get()
    parent = _MODEL.get()
    selected_route = route or (parent.route if parent is not None and parent.active else "")
    generation = _Generation(collector, _identity(model, 120), selected_route,
                             parent if parent is not None and parent.active and
                             parent.collector is collector else None) if collector else None
    token = _MODEL.set(generation)
    try:
        yield
    finally:
        if generation is not None:
            generation.active = False
            if generation.dispatches == 0:
                with collector._lock:
                    if not collector._closed:
                        collector._unattributed = True
        _MODEL.reset(token)


@contextmanager
def detached_turn_usage():
    """Keep background work outside the active request's spend receipt."""
    from .turn_stops import detached_turn_stops
    current = _CURRENT.set(None)
    model = _MODEL.set(None)
    try:
        with detached_turn_stops():
            yield
    finally:
        _MODEL.reset(model)
        _CURRENT.reset(current)


def record_dispatch(provider: str, request: Any) -> None:
    """Observe accepted inference and refuse confident totals for unknown POSTs."""
    collector, generation = _CURRENT.get(), _MODEL.get()
    if collector is None or getattr(request, "method", "").upper() != "POST":
        return
    # An inherited but exited scope cannot authenticate a model or route. The
    # request still belongs to an open collector and must not disappear.
    if generation is not None and (not generation.active or generation.collector is not collector):
        generation = None
    if not _generation_request(request):
        if generation is not None and not _known_control_post(provider, request):
            with collector._lock:
                if not collector._closed:
                    collector._unattributed = True
        return
    if generation is not None:
        scope = generation
        while scope is not None and scope.active and scope.collector is collector:
            scope.dispatches += 1
            scope = scope.parent
    wire_model = _wire_model(request)
    expected_model = generation.model if generation is not None else None
    selected_model = expected_model if expected_model is not None and expected_model == wire_model else None
    collector._dispatch(_identity(provider, 64), selected_model,
                        generation.route if generation is not None else "",
                        request, _owner())


def record_usage(usage: Any) -> None:
    """Publish one provider-certified response to this task's last dispatch."""
    collector = _CURRENT.get()
    if collector is not None:
        collector._usage(usage, _owner())
