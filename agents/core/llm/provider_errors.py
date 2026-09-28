"""Secret-safe provider failure reporting shared by cloud LLM clients."""

from __future__ import annotations

import contextlib
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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
    model: str | None = None,
) -> None:
    """Log only provider-safe diagnostics: operation, type, and numeric status. With
    *model*, the failure is also noted for the request (H681)."""
    if model is not None:
        note_provider_failure(provider.lower(), model, exc)
    status = provider_http_status(exc)
    logger.log(
        level,
        "%s %s failed (type=%s, status=%s)",
        provider,
        operation,
        type(exc).__name__,
        status if status is not None else "none",
    )


# ── H681: what a failed call was, for the request that made it ──────────────────────
#
# A backend answers a failed call with a degraded reply, never an exception, so the
# caller only sees "[OpenRouter error]". A caller that must say *why* (a batch of
# sub-agents that all hit a model the provider does not know) opens a
# ``provider_failure_scope`` and reads what the backends noted: the provider, the model
# they asked for, the HTTP status and one fixed kind. The provider's own text is read
# only to choose the kind and is never kept: it can echo a key, a prompt or a URL.

FAILURE_KINDS: Final = ("model_not_found", "not_found", "auth", "rate_limited", "unreachable",
                        "server_error", "rejected", "error")

_MODEL_MISSING = re.compile(
    r"\bmodels?\b[^\n]{0,80}?\b(?:not found|does not exist|doesn't exist|unknown|not a valid|is invalid"
    r"|not available)"
    r"|\b(?:unknown|invalid|no such) model\b"
    r"|\bnot a valid model\b|model_not_found"
    r"|not_found_error[^\n]{0,40}\bmodel\b",
    re.IGNORECASE,
)
_FAILURES: ContextVar[list | None] = ContextVar("provider_failures", default=None)


@dataclass(frozen=True)
class ProviderFailure:
    provider: str
    model: str | None
    status: int | None
    kind: str

    def message(self) -> str:
        """A line composed from the fields alone (no provider text)."""
        what = {"model_not_found": "not found", "not_found": "not found", "auth": "authentication failed",
                "rate_limited": "rate limited", "unreachable": "unreachable", "server_error": "server error",
                "rejected": "request rejected", "error": "request failed"}.get(self.kind, "request failed")
        head = f"{self.provider}: model '{self.model}' {what}" if self.model else f"{self.provider}: {what}"
        return f"{head} (HTTP {self.status})" if self.status is not None else head

    def as_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model, "status": self.status, "kind": self.kind,
                "message": self.message()}


ERROR_HEAD_BYTES: Final = 8192


async def read_error_head(response) -> None:
    """Read at most ``ERROR_HEAD_BYTES`` of a streamed error response's body onto it
    (``nerva_error_head``), so its failure can be classified; the rest is never read."""
    head = bytearray()
    try:
        async for chunk in response.aiter_bytes():
            head.extend(chunk)
            if len(head) >= ERROR_HEAD_BYTES:
                break
    except Exception:  # noqa: BLE001 — classification is best-effort
        logging.getLogger(__name__).debug("error body not readable for classification", exc_info=True)
    with contextlib.suppress(Exception):
        response.nerva_error_head = bytes(head[:ERROR_HEAD_BYTES]).decode("utf-8", "replace")


def _error_text(exc: BaseException) -> str:
    """The provider's own words, for classifying only; empty when unreadable."""
    parts = [str(exc)]
    response = getattr(exc, "response", None)
    if response is not None:
        head = getattr(response, "nerva_error_head", None)
        if isinstance(head, str):
            parts.append(head)
        else:
            with contextlib.suppress(Exception):   # a streamed body that was never read
                parts.append(response.text or "")
    return " ".join(parts)[:4000]


def classify_failure(exc: BaseException | None) -> tuple[int | None, str]:
    """``(status, kind)`` for a failed provider call."""
    if exc is None:
        return None, "error"
    status = provider_http_status(exc)
    if status is None:
        try:
            import httpx

            if isinstance(exc, (httpx.TransportError, ConnectionError, TimeoutError)):
                return None, "unreachable"
        except ImportError:  # pragma: no cover
            pass
        return None, "model_not_found" if _MODEL_MISSING.search(_error_text(exc)) else "error"
    if status in (401, 403):
        return status, "auth"
    if status == 429:
        return status, "rate_limited"
    if status >= 500:
        return status, "server_error"
    if status in (400, 404, 422) and _MODEL_MISSING.search(_error_text(exc)):
        return status, "model_not_found"
    return status, "not_found" if status == 404 else "rejected"


@contextmanager
def provider_failure_scope():
    """Collect the failures noted while the block runs (and in tasks it starts)."""
    notes: list = []
    token = _FAILURES.set(notes)
    try:
        yield notes
    finally:
        _FAILURES.reset(token)


def note_provider_failure(provider: str, model: str | None, exc: BaseException | None = None, *,
                          kind: str | None = None, status: int | None = None) -> None:
    """Record a failed call for the open scope; a no-op outside one. Never raises."""
    notes = _FAILURES.get()
    if notes is None:
        return
    try:
        found_status, found_kind = classify_failure(exc)
        notes.append(ProviderFailure(
            provider=str(provider or "unknown"), model=str(model) if model else None,
            status=status if status is not None else found_status,
            kind=kind if kind in FAILURE_KINDS else found_kind))
    except Exception:  # noqa: BLE001 — a note is never worth a failed reply
        logging.getLogger(__name__).debug("provider failure not noted", exc_info=True)
