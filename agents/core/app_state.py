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
means those rebinds (and the lifespan set/clear) are always observed.

It looks the module up in `sys.modules` rather than `import`-ing it. `get_orch()`
is only ever called at request time, by which point `agents.web` is always loaded
(it owns the running app), so a dict lookup is equivalent to `from agents import
web` for every real call site — but it is *not* a static import edge, so this
module stays a leaf and never participates in an import cycle (CodeQL flagged the
`app_state → web → routers → app_state` cycle that the in-function import created).
Before startup / if web were somehow unloaded, it simply returns None.
"""

from __future__ import annotations

import sys
from typing import Optional


def get_orch() -> Optional[object]:
    """Return the live Orchestrator (or None before startup / after shutdown)."""
    web = sys.modules.get("agents.web")
    return getattr(web, "orch", None) if web is not None else None


def dev_mode() -> bool:
    """Return web.py's DEV_MODE flag, read at REQUEST time (CLN-3 unblock B).

    Same late-binding rationale as `get_orch`: `DEV_MODE` is a web.py
    module-global (and the skills test suite rebinds it with
    `monkeypatch.setattr(web, "DEV_MODE", ...)`), so the extracted skills router
    must read it through `sys.modules` on each call rather than capturing a bare
    `DEV_MODE` at import — that keeps the test's monkeypatch observed and avoids a
    static import edge back into `agents.web`.
    """
    web = sys.modules.get("agents.web")
    return bool(getattr(web, "DEV_MODE", False)) if web is not None else False
