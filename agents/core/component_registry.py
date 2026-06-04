"""
component_registry.py — A2: tame the Orchestrator god-object.

Replaces the ~14 near-identical ``try: import X; self.x = X(); except: warn;
self.x = None`` blocks in ``Orchestrator.__init__`` with a single registrar that:

* lazily imports + constructs each optional component,
* records init **status** (so a failure is visible, not a silent ``None`` —
  audit A8 startup health report),
* sets the attribute on the owner (``orch.arena`` etc.) so all existing
  ``getattr(orch, "x")`` / ``self.x`` access keeps working unchanged.

Behavior-preserving: a component that fails to construct still ends up as
``None`` on the owner, exactly as before — just logged once and tracked.
"""

from __future__ import annotations

import importlib
import logging
from typing import Callable, Iterable, Optional


class ComponentRegistry:
    def __init__(self, owner, logger: logging.Logger, package: str = "agents.core") -> None:
        self._owner = owner
        self._logger = logger
        self._package = package
        self.status: dict[str, str] = {}   # name -> "ok" | "failed"

    # ── registration ─────────────────────────────────────────────────────────

    def register(self, name: str, factory: Callable, label: Optional[str] = None):
        """Construct via *factory* (zero-arg); set owner.<name>; track status."""
        label = label or name
        try:
            instance = factory()
            self.status[name] = "ok"
        except Exception:
            self._logger.warning("%s init failed — disabled", label, exc_info=True)
            instance = None
            self.status[name] = "failed"
        setattr(self._owner, name, instance)
        return instance

    def add(self, name: str, module: str, attr: str, *args, label: Optional[str] = None, **kwargs):
        """Convenience: lazily import ``module:attr`` and construct with args."""
        def _factory():
            mod = importlib.import_module(module, self._package)
            return getattr(mod, attr)(*args, **kwargs)
        return self.register(name, _factory, label)

    def register_group(self, names: Iterable[str], factory: Callable, label: Optional[str] = None):
        """For an import that yields several components (factory → tuple). On
        failure, every name in the group is set to ``None``."""
        names = list(names)
        label = label or "/".join(names)
        try:
            values = factory()
            for n, v in zip(names, values):
                setattr(self._owner, n, v)
                self.status[n] = "ok"
        except Exception:
            self._logger.warning("%s init failed — disabled", label, exc_info=True)
            for n in names:
                setattr(self._owner, n, None)
                self.status[n] = "failed"

    # ── introspection ────────────────────────────────────────────────────────

    def health(self) -> dict[str, str]:
        return dict(self.status)

    def failed(self) -> list[str]:
        return [n for n, s in self.status.items() if s != "ok"]

    def summary(self) -> str:
        ok = sum(1 for s in self.status.values() if s == "ok")
        bad = self.failed()
        s = f"{ok}/{len(self.status)} components ok"
        return s + (f"; failed: {', '.join(bad)}" if bad else "")
