"""web_helpers.py — pure, stateless web helpers (CLN-3 shared kernel, layer 0).

Extracted from the agents/web.py god-object so the per-domain routers in
`core/routers/` can import them directly instead of reaching back into `web`
(`from agents import web; web._nocache_json(...)`). These functions hold no app
or orchestrator state, so this module imports nothing from `web` and can be
imported by any router with no cycle.

`web.py` re-exports these under their original private names
(`_nocache_json`/`_mask_secret`) for backward compatibility, so every existing
call site — and any test that references them — keeps working unchanged.
"""

from __future__ import annotations

import html
import logging
import re

from fastapi.responses import JSONResponse

logger = logging.getLogger("jarvis.web")


def nocache_json(content: dict, status_code: int = 200) -> JSONResponse:
    """A JSONResponse with no-store cache headers (the ubiquitous API responder)."""
    return JSONResponse(
        content=content,
        status_code=status_code,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def error_json(exc, status_code: int, public_message: str, *, extra: dict | None = None, log=None) -> JSONResponse:
    """CWE-209-safe error response.

    Logs the *full* exception detail server-side and returns ONLY a controlled,
    static `public_message` to the client — never the raw exception text, which
    can carry stack traces, filesystem paths, or other internal detail. `extra`
    preserves any additional response keys the endpoint's contract requires
    (e.g. ``{"ok": False}`` or ``{"results": []}``); it must not contain
    exception-derived values.
    """
    (log or logger).warning("request error [%s] (%s): %s", public_message, status_code, exc)
    body = dict(extra or {})
    body["error"] = public_message
    return nocache_json(body, status_code=status_code)


# Anything outside this conservative identifier charset is dropped before a
# user-supplied value is echoed back into a response body.
_REFLECT_UNSAFE = re.compile(r"[^A-Za-z0-9._:@/-]")


def safe_reflect(value, *, max_len: int = 100) -> str:
    """Sanitize a user-supplied identifier for safe echo into a response.

    Endpoints sometimes reflect a path/query value back ("trace '<id>' not
    found", or a correlation key in a success body). Echoing raw input is a
    reflected-XSS / response-splitting taint sink (CWE-79/-116). This truncates,
    strips anything outside a conservative identifier charset, then HTML-escapes
    — the escape both clears the taint and neutralizes any residual markup,
    while valid identifiers (the realistic inputs) pass through unchanged.
    """
    cleaned = _REFLECT_UNSAFE.sub("", str(value)[:max_len])
    return html.escape(cleaned, quote=True)


def logsafe(value: object) -> str:
    """Neutralize newlines so untrusted values can't forge log records (CWE-117).

    A value containing CR/LF logged verbatim could inject fake log lines;
    stripping the line breaks is the standard log-injection remediation. Use at
    every log site that interpolates request-controlled data.
    """
    return str(value).replace("\r", " ").replace("\n", " ")


def mask_secret(value: str) -> str:
    """Mask a secret-ish env value for display (e.g. in /api/admin/env)."""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-2:]}"


# ── Bounded backend reads on the request path (NEW-4) ─────────────────────────
#
# A manual QA run against a live box found four HUD routes that hung INDEFINITELY
# when the memory/graph backends (Qdrant, Neo4j) were down: the handler awaited a
# backend call with no deadline, the backend never answered, and the request never
# returned. The HUD spinner span forever with no error — the worst failure mode,
# because it is indistinguishable from "still loading".
#
# Two rules follow, and the helpers below exist to make both cheap:
#   1. Every backend reach on a request path gets a deadline.
#   2. A timeout is REPORTED, never absorbed into a plausible-looking zero. A
#      handler that catches the timeout and returns `{"entities": 0}` has turned a
#      dead backend into a confident wrong answer — the fabrication this codebase
#      keeps having to root out. Use `degraded()` so the body says it does not know.

# Default deadline for a backend read on the request path. Long enough that a
# healthy local Qdrant/Neo4j/sqlite call never trips it, short enough that a HUD
# panel reports a problem instead of hanging.
BACKEND_TIMEOUT_S = 5.0


class BackendTimeout(Exception):
    """A backend on the request path did not answer within its budget.

    Carries `what` so the handler can name the backend in its degraded response
    without interpolating anything request-controlled.
    """

    def __init__(self, what: str, seconds: float):
        self.what = what
        self.seconds = seconds
        super().__init__(f"{what} did not answer within {seconds}s")


async def bounded(awaitable, *, what: str, seconds: float = BACKEND_TIMEOUT_S):
    """Await `awaitable` with a hard deadline, raising `BackendTimeout` past it.

    Prefer this over a bare `await` for anything that leaves the process: a memory
    store, a graph, a model server, a subprocess. `asyncio.wait_for` cancels the
    inner task on expiry, so a wedged backend cannot keep the handler's slot.

    Raises `BackendTimeout` (not `asyncio.TimeoutError`) so a caller's existing
    broad `except Exception` cannot silently reclassify a dead backend as an empty
    one — the distinction has to reach the response body.
    """
    import asyncio

    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except TimeoutError as exc:  # asyncio.TimeoutError is an alias of this on 3.11+
        logger.warning("backend read timed out after %.1fs: %s", seconds, logsafe(what))
        raise BackendTimeout(what, seconds) from exc


def degraded(body: dict, *, what: str, reason: str, status_code: int = 200) -> JSONResponse:
    """A response whose values could not be measured, and which says so.

    The keys the client expects are still present (so a panel does not crash on a
    missing field), but `available: false` and `degraded` tell it these are
    placeholders, not readings. Render them as unknown — never as zero.
    """
    return nocache_json(
        {
            **body,
            "available": False,
            "degraded": {"source": what, "reason": reason},
        },
        status_code=status_code,
    )
