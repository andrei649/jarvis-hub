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


def mask_secret(value: str) -> str:
    """Mask a secret-ish env value for display (e.g. in /api/admin/env)."""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-2:]}"
