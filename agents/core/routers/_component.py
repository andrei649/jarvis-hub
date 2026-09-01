"""Shared `orch.<component>` → 503 guard for the extracted routers (AUDIT A5/Q2).

`docs/AUDIT.md` A5 (repeated as Q2) flagged the four-line preamble that every
component-backed endpoint copy-pasted::

    orch = get_orch()
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return JSONResponse({"error": "arena not available"}, status_code=503)

§7 parked it as "Deferred to post-manual-testing … many endpoints intentionally
degrade gracefully (return empty) rather than 503, and a blanket migration would
change that". That caveat still holds and is why this module offers a *helper*
that individual 503 sites opt into, rather than anything that sweeps whole
routers: an endpoint that answers `{"rooms": []}` when the store is missing is
making a deliberate product choice, not repeating boilerplate, and it is left
exactly as it is.

**Why this is not a `Depends(...)`.** AUDIT A5 sketched it as a FastAPI
dependency. It cannot be one without changing behaviour: FastAPI's
`solve_dependencies` runs the dependency graph *before* `request_body_to_args`,
so a dependency-shaped guard answers 503 on a request whose body is malformed —
where the handler-shaped guard lets validation answer 422 first. Verified on
fastapi 0.141.1; `tests/test_require_component_sweep.py::
test_body_validation_still_wins_over_the_guard` pins it. Resolving at the top of
the handler keeps status, body, response class and ordering byte-for-byte what
they were, which is the whole point of a refactor.

`require_component` returns the orchestrator too: seven of the migrated handlers
(`arena_run`, `kg_add_fact`, `kg_ingest`, `notes_set`, `notes_rewrite`,
`capabilities_issue`, `kill_switch_set`, `audit_anchor`) keep using `orch` after
the guard, and re-reading the global would be a second, needless late-bind.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from fastapi.responses import JSONResponse

from agents.core.app_state import get_orch


class ResolvedComponent(NamedTuple):
    """`(orch, value, error)` — `error` is None exactly when `value` is not."""

    orch: object | None
    value: Any
    error: JSONResponse | None


def component_unavailable(message: str) -> JSONResponse:
    """The one 503 body the routers agreed on: `{"error": "<what is missing>"}`.

    Exposed on its own for the handful of guards that cannot use
    `require_component` verbatim — `capabilities_check` tests two components
    against a single message, `sandbox_execute` checks mid-handler after an
    earlier gate — so the *shape* of the refusal is still defined in one place
    even where the test around it stays hand-written.
    """
    return JSONResponse({"error": message}, status_code=503)


def require_component(name: str, message: str) -> ResolvedComponent:
    """Resolve `orch.<name>`, or produce the 503 the endpoint returned before.

    `message` is passed rather than derived from `name`: the wording is part of
    each endpoint's published contract ("kill-switch not available",
    "e2e sync unavailable", "bi-temporal KG not available") and clients read it.
    Deriving it would silently rewrite ~45 response bodies.

    The `if orch else None` short-circuit is deliberate and load-bearing: a
    falsy-but-present orchestrator refused under the old preamble even when the
    attribute existed, and two handlers (`notes_rewrite`, `rooms_message`) spelled
    that out a second time as `x is None or not orch`.
    """
    orch = get_orch()
    value = getattr(orch, name, None) if orch else None
    if value is None:
        return ResolvedComponent(orch, None, component_unavailable(message))
    return ResolvedComponent(orch, value, None)
