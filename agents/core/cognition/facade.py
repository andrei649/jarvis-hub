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
_SUB_FLAGS = ("honesty_enabled", "affect_enabled", "memory_enabled",
              "learning_enabled", "personality_enabled")


class CognitionFacade:
    """Cognition subsystem entry point (H21). Master OFF = no-op."""

    def __init__(self, get_setting: Optional[Callable] = None) -> None:
        # get_setting(key, default) — defaults to "everything OFF".
        self._get = get_setting or (lambda k, d=None: d)

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
            "modules": [],   # submodules register here in later H21 items
        }

    def new_turn(self, session_id: str = "", agent: str = "", user: str = "") -> TurnContext:
        """Create a per-request TurnContext (caller binds it via TurnContext.bind)."""
        return TurnContext(session_id=session_id, agent=agent, user=user)
