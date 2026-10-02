"""Reviewed native video provider and transport failure categories."""
from __future__ import annotations

import json
import re

import httpx

_MAX_ERROR_BODY_BYTES = 512_000
_PAYMENT_CODES = frozenset({
    "balance_depleted", "budget_limit_exceeded", "insufficient_funds",
    "insufficient_quota", "key_limit_exceeded", "payment_required",
    "quota_exceeded", "resource_exhausted",
})
_PAYMENT_PHRASES = (
    "insufficient funds", "insufficient credits", "credits exhausted",
    "no usable credits", "payment required", "budget limit exceeded",
    "key limit exceeded", "quota exceeded", "daily quota", "daily limit",
    "weekly limit", "weekly usage limit", "too many tokens per day",
    "quota_exceeded", "resource exhausted", "resource_exhausted",
    "resource-exhausted", "resourceexhausted", "out of funds",
    "balance depleted", "requires a subscription", "upgrade for access",
    "not available on the free tier", "isn't available on the free tier",
)
_MODEL_CODES = frozenset({"model_not_supported", "unsupported_model"})
_MODEL_PHRASES = (
    "is not supported when using", "model is not supported",
    "not supported with this", "not supported for this account",
    "does not support this model", "unsupported model",
)
_MODEL_EXCLUSIONS = (
    "model not found", "model_not_found", "no such model", "does not exist",
    "unknown model", "is not a valid model", "openrouter catalog",
    "credits", "insufficient funds", "billing", "out of funds",
    "balance_depleted", "no usable credits", "payment required",
    "free tier", "free-tier", "model_not_supported_on_free_tier", "quota",
)


def _has_phrase(value: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", value)
               for phrase in phrases)


def _error_fields(body: bytes) -> tuple[str, str, str] | None:
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("error"), dict):
        return None
    error = parsed["error"]
    fields = tuple(error.get(field, "") for field in ("code", "type", "message"))
    if not all(isinstance(value, str) for value in fields):
        return None
    return tuple(value.strip().lower() for value in fields)


def provider_failure_category(status: int, body: bytes) -> str | None:
    """Classify only a bounded HTTP failure and its structured error fields."""
    if len(body) > _MAX_ERROR_BODY_BYTES:
        return None
    if status == 401:
        return "auth"
    if status == 402:
        return "payment"
    if status not in {400, 403, 404, 429}:
        return None

    fields = _error_fields(body)
    if status == 429 and fields is None:
        return "rate_limit"
    if fields is None:
        return None
    code, error_type, message = fields

    if status == 403 and (
        code in {"bad-credentials", "unauthenticated:bad-credentials"}
        or error_type in {"bad-credentials", "unauthenticated:bad-credentials"}
        or message in {"bad-credentials", "unauthenticated:bad-credentials"}
    ):
        return "auth"
    if status in {403, 404, 429} and (
        code in _PAYMENT_CODES or error_type in _PAYMENT_CODES
        or _has_phrase(message, _PAYMENT_PHRASES)
    ):
        return "payment"
    if status == 429:
        return "rate_limit"
    if (status == 400
            and not any(_has_phrase(value, _MODEL_EXCLUSIONS) or "the model `" in value
                        for value in fields)
            and (code in _MODEL_CODES or error_type in _MODEL_CODES
                 or _has_phrase(message, _MODEL_PHRASES))):
        return "model_incompatible"
    return None


def transport_failure_category(exc: BaseException) -> str | None:
    """Classify request-boundary HTTPX errors only; caller must wrap guard failures."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, (httpx.NetworkError, httpx.RemoteProtocolError)):
        return "connection"
    return None
