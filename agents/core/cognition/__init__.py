"""
cognition — H21 Living Memory & Human-Like Personality (skeleton, H21.0).

A single package behind a `CognitionFacade` (registered once via
ComponentRegistry) so the cognition subsystem grows WITHOUT inflating the
orchestrator/web god-objects (CLN-2/CLN-3). Transient per-request state lives on
a `TurnContext` (async-context-local, no mutation of shared instances); durable
state lives in locked, keyed `JsonStore`s.

**Master OFF = no-op.** Every sub-capability flag defaults to False, so this
skeleton changes zero behavior until later H21 items light a flag.
"""

from .facade import CognitionFacade
from .turn_context import TurnContext
from .store import KeyedStore

__all__ = ["CognitionFacade", "TurnContext", "KeyedStore"]
