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

from fastapi.responses import JSONResponse


def nocache_json(content: dict, status_code: int = 200) -> JSONResponse:
    """A JSONResponse with no-store cache headers (the ubiquitous API responder)."""
    return JSONResponse(
        content=content,
        status_code=status_code,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def mask_secret(value: str) -> str:
    """Mask a secret-ish env value for display (e.g. in /api/admin/env)."""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-2:]}"
