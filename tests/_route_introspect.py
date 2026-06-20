"""Shared route introspection for the parity / auth-matrix guards.

fastapi 0.137 stopped flattening `include_router` results into `app.routes`:
each included router is appended as one opaque `_IncludedRouter`, and its child
routes — with the merged prefix + include-time dependencies — are resolved
lazily. Iterating `app.routes` for flat `APIRoute` objects therefore misses
every router mounted via `include_router` (the route surface collapsed 296->83
under 0.137; the app itself was fine — routes still serve and appear in OpenAPI).

`iter_effective_routes` yields the *effective* route objects, each exposing
`.path`, `.methods` and a merged `.dependant` (include-time guards folded in),
by reusing fastapi's own `_iter_routes_with_context`. On fastapi <= 0.136 (no
wrapper) it degrades to iterating `app.routes` directly, so the guards behave
identically on both. Full context:
docs/research/2026-06-19-fastapi-0.137-include-router-regression.md
"""
from collections.abc import Iterator
from typing import Any


def iter_effective_routes(app: Any) -> Iterator[Any]:
    """Yield route-like objects with effective `.path` / `.methods` / `.dependant`.

    fastapi >= 0.137: descend into `_IncludedRouter` wrappers via the same helper
    fastapi uses for OpenAPI/runtime, so included routes (and their merged guards)
    are seen. fastapi <= 0.136: `app.routes` is already flat — yield it as-is.
    """
    try:
        from fastapi.routing import _iter_routes_with_context  # fastapi >= 0.137
    except ImportError:
        yield from app.routes
        return
    for route, ctx in _iter_routes_with_context(app.routes):
        # Included routes -> ctx is an _EffectiveRouteContext exposing the merged
        # .path/.methods/.dependant; top-level routes -> ctx is None, use route.
        yield ctx if ctx is not None else route
