"""
facade.py — CognitionFacade (H21.0).

The single entry point for the cognition subsystem. Registered once in the
orchestrator via ComponentRegistry. Until a sub-flag is enabled, every method is
inert — the skeleton adds zero behavior.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .turn_context import TurnContext

logger = logging.getLogger("jarvis.cognition")

# Sub-capabilities, all master-gated. Each defaults OFF → master OFF = no-op.
# Later H21 items implement the modules behind these flags.
# review_enabled (H20 learning loop): the per-turn background review distiller
# + nightly skill curator — requires memory_enabled to be useful.
_SUB_FLAGS = ("honesty_enabled", "affect_enabled", "memory_enabled",
              "learning_enabled", "personality_enabled", "review_enabled")


class CognitionFacade:
    """Cognition subsystem entry point (H21). Master OFF = no-op."""

    def __init__(self, get_setting: Optional[Callable] = None) -> None:
        # get_setting(key, default) — defaults to "everything OFF".
        self._get = get_setting or (lambda k, d=None: d)
        self._modules: dict = {}

    def register_module(self, name: str, module) -> None:
        """Submodules (honesty, affect, memory, …) register here as H21 grows."""
        self._modules[name] = module

    def module(self, name: str):
        return self._modules.get(name)

    def flag(self, name: str) -> bool:
        return bool(self._get(f"cognition.{name}", False))

    def enabled(self) -> bool:
        """Master switch — when False the whole subsystem is inert."""
        return self.flag("enabled")

    def sub_enabled(self, name: str) -> bool:
        """A sub-capability is on only if the master AND its own flag are on."""
        return self.enabled() and self.flag(name)

    def status(self) -> dict:
        master = self.enabled()
        return {
            "enabled": master,
            "available": True,
            "flags": {f: (master and self.flag(f)) for f in _SUB_FLAGS},
            "modules": sorted(self._modules.keys()),
        }

    def new_turn(self, session_id: str = "", agent: str = "", user: str = "") -> TurnContext:
        """Create a per-request TurnContext (caller binds it via TurnContext.bind)."""
        return TurnContext(session_id=session_id, agent=agent, user=user)
