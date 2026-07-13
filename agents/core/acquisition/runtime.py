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
