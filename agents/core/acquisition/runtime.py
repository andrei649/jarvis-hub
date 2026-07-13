"""Default-off runtime composition for the acquisition plane."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from .models import CapabilityRequest
from .store import CapabilityRequestStore

logger = logging.getLogger("jarvis.acquisition")


class AcquisitionRuntime:
    def __init__(
        self,
        *,
        enabled: Callable[[], bool] = lambda: False,
        root: str | Path | None = None,
        store_factory: Callable[..., CapabilityRequestStore] = CapabilityRequestStore,
    ) -> None:
        self._enabled = enabled
        self._root = root
        self._store_factory = store_factory
        self.request_store: CapabilityRequestStore | None = None
        self.decision_store = None

    def is_enabled(self) -> bool:
        try:
            return self._enabled() is True
        except Exception:
            logger.warning("acquisition enablement check failed closed")
            return False

    def capture_gap(self, payload: dict) -> CapabilityRequest | None:
        """Persist only the Agent Runtime's explicit governed-capability refusal."""
        if not self.is_enabled():
            return None
        if not isinstance(payload, dict):
            return None
        if self.request_store is None:
            self.request_store = self._store_factory(root=self._root)
        try:
            return self.request_store.capture(
                payload.get("goal", ""),
                agent_id=payload.get("agent_id", ""),
                reason=payload.get("reason", ""),
            )
        except (TypeError, ValueError):
            logger.warning("invalid capability gap refused")
            return None

    def resolve_gap(self, request_id: str, orch, *, candidates=None):
        """Run the deterministic local reuse phase; never starts research/generation."""
        if not self.is_enabled() or self.request_store is None:
            return None
        request = self.request_store.get(request_id)
        if request is None:
            return None
        from .resolver import ReuseDecisionStore, ReuseResolver, collect_reuse_candidates

        if self.decision_store is None:
            self.decision_store = ReuseDecisionStore(root=self._root)
        return ReuseResolver(decision_store=self.decision_store).resolve(
            request,
            collect_reuse_candidates(orch) if candidates is None else candidates,
            request_store=self.request_store,
        )
