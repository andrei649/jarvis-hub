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


def iter_websocket_routes(app: Any) -> Iterator[Any]:
    """Yield every WebSocket route with its effective `.path` / `.dependant` (H511).

    `iter_effective_routes` callers filter on `.methods`, which a WebSocket route
    has none of — and on fastapi >= 0.137 an included WebSocket route's context
    carries an empty `.path` and no `.dependant`; the prefixed route fastapi
    actually serves lives on `ctx.starlette_route`. Without this the auth matrix
    never saw `/api/kanban/events` or `/api/hermes/ws`, so a new unguarded upgrade
    endpoint passed CI.

    A `Mount` or `Host` whose app has its own routes (a mounted or host-dispatched
    FastAPI/Starlette sub-app) is descended into, and its upgrade routes are yielded
    under the mount prefix (`//<host>` for a Host), so a WebSocket endpoint on a
    sub-app is classified too. A mount with no route table
    (StaticFiles, an opaque ASGI callable) cannot be introspected here — those are
    pinned by `iter_mounts` + test_every_mount_is_pinned instead.
    """
    yield from _walk_websockets(app.routes, "")


def _served(routes: Any) -> Iterator[Any]:
    """Each route as fastapi actually serves it: an included route is resolved to
    `ctx.starlette_route` (fastapi >= 0.137), anything else is yielded as-is."""
    try:
        from fastapi.routing import _iter_routes_with_context  # fastapi >= 0.137
    except ImportError:
        yield from routes
        return
    for route, ctx in _iter_routes_with_context(routes):
        starlette_route = getattr(ctx, "starlette_route", None) if ctx is not None else None
        yield starlette_route if starlette_route is not None else route


def _sub_app_path(served: Any, prefix: str) -> "str | None":
    """The served-path key of a route that dispatches to a whole ASGI sub-app, or None.

    `Mount` -> its path under `prefix`. starlette's `Host` is a sibling of `Mount`, not
    a subclass (H511 round 3): it matches every path on its host, so it is keyed
    `//<host>` under `prefix`. Any other non-endpoint route carrying an `.app` is keyed
    by its path tagged with its class, so an unknown dispatcher is reported, not skipped.
    """
    from starlette.routing import Host, Mount, Route, WebSocketRoute

    if isinstance(served, Mount):
        return prefix + served.path
    if isinstance(served, Host):
        return prefix + "//" + served.host
    if isinstance(served, (Route, WebSocketRoute)) or getattr(served, "app", None) is None:
        return None
    return f"{prefix}{getattr(served, 'path', '')}[{type(served).__name__}]"


def _walk_websockets(routes: Any, prefix: str) -> Iterator[Any]:
    from types import SimpleNamespace

    from starlette.routing import WebSocketRoute

    for served in _served(routes):
        if isinstance(served, WebSocketRoute):
            if not prefix:
                yield served
            else:
                yield SimpleNamespace(path=prefix + served.path,
                                      dependant=getattr(served, "dependant", None))
            continue
        sub = _sub_app_path(served, prefix)
        if sub is not None:
            yield from _walk_websockets(_inner_routes(served), sub)


def _inner_routes(served: Any) -> Any:
    # Mount/Host expose `.routes` (Mount reads it off the app under any middleware).
    return getattr(served, "routes", None) or getattr(served.app, "routes", None) or []


def iter_mounts(app: Any) -> Iterator[Any]:
    """Yield every `Mount` and `Host` at any depth (H511) — an ASGI sub-application
    the HTTP route matrix cannot see inside (a Host is keyed `//<host>`).

    Each item exposes `.path` (the path the mount is actually served under) and
    `.app` (the mounted application). A mount inside an included APIRouter is found
    too: on fastapi >= 0.137 it sits behind an opaque `_IncludedRouter`, and the
    `Mount` fastapi serves is `ctx.starlette_route` — whose path is the one that
    answers (fastapi 0.142 does not apply the router prefix to a router-level mount,
    so `APIRouter(prefix="/api").mount("/inner", ...)` serves `/inner/...`). A mount
    with its own route table is descended into, so a mount nested in a mounted
    sub-app is reported under its full served path.
    """
    yield from _walk_mounts(app.routes, "")


def _walk_mounts(routes: Any, prefix: str) -> Iterator[Any]:
    from types import SimpleNamespace

    for served in _served(routes):
        path = _sub_app_path(served, prefix)
        if path is None:
            continue
        yield SimpleNamespace(path=path, app=served.app, mount=served)
        inner = _inner_routes(served)
        if inner:
            yield from _walk_mounts(inner, path)
