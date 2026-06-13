"""app_state.py — shared application-state accessors (CLN-3 shared kernel, layer 1).

The per-domain routers extracted from `agents/web.py` need the live orchestrator
(and, over time, the lazily-created singletons). Today they reach it via
`from agents import web; web.orch` inside each handler. This module gives them a
single sanctioned accessor instead, so a router can import from `core/` rather
than from `web`.

`get_orch()` deliberately **late-binds**: it reads `web.orch` at call time rather
than capturing it at import. That is load-bearing — the orchestrator global is
owned by `web.py` (it is set in `lifespan`), and the test suite rebinds it with
`monkeypatch.setattr(web, "orch", ...)` ~112×. Reading the attribute on each call
means those rebinds (and the lifespan set/clear) are always observed. The
`from agents import web` import lives *inside* the function so importing this
module never triggers the web app + lifespan (no import cycle) — the same pattern
already used by `core/cognition/api.py:_facade()` and `core/routers/*`.
"""

from __future__ import annotations

from typing import Optional


def get_orch() -> Optional[object]:
    """Return the live Orchestrator (or None before startup / after shutdown)."""
    from agents import web

    return getattr(web, "orch", None)
