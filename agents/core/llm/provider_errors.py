"""Secret-safe provider failure reporting shared by cloud LLM clients."""

from __future__ import annotations

import logging
from typing import Final

GEMINI_DEGRADED_REPLY: Final[str] = "[Gemini error: provider request failed]"


def provider_http_status(exc: BaseException) -> int | None:
    """Return an HTTP status without inspecting exception text or response data."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def log_provider_failure(
    logger: logging.Logger,
    *,
    provider: str,
    operation: str,
    exc: BaseException,
    level: int = logging.WARNING,
) -> None:
    """Log only provider-safe diagnostics: operation, type, and numeric status."""
    status = provider_http_status(exc)
    logger.log(
        level,
        "%s %s failed (type=%s, status=%s)",
        provider,
        operation,
        type(exc).__name__,
        status if status is not None else "none",
    )
