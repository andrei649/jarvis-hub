"""lsp — language servers for code intelligence (Hermes H055, H564, H597).

* :mod:`.registry` — the servers Nerva knows and their pinned install recipes.
* :mod:`.trust` — the git workspaces the owner trusted; no server starts elsewhere.
* :mod:`.profiles` — each server's own runtime, and what a workspace can still influence.
* :mod:`.confine` — how a server (third-party code) is started: scrubbed env, an
  allowlist ``bwrap`` sandbox with no network (required by default), resource limits.
* :mod:`.client` — one server over JSON-RPC on stdio, bounded and narrow.
* :mod:`.manager` — discovery, lazy start, idle reaping, the broken set, and the
  before/after diagnostics of an edit (:func:`.manager.diagnose_write`).
* :mod:`.diff` — which diagnostics the edit introduced, re-anchored and bounded.
* :mod:`.install` — an ``lsp.install`` approval card, then the pinned install.

Surfaces: ``GET /api/codeintel/lsp/status`` and the start/stop/install routes
(``routers/codeintel.py``), the HUD Code Intel panel's language-server section and
``nerva lsp``. Off with ``JARVIS_LSP=0``.
"""

from __future__ import annotations

from .manager import LspManager, diagnose_write, enabled, get_manager, set_manager

__all__ = ["LspManager", "diagnose_write", "enabled", "get_manager", "set_manager"]
