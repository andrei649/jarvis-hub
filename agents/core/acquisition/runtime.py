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
        self.package_store = None
        self.promotion_broker = None
        self._promotion_config: dict | None = None
        self._reconciled = False

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

    def bind_promotion(
        self,
        *,
        tool_rpc,
        marketplace,
        kernel_gate=None,
        profile=None,
    ) -> None:
        """Bind live seams without creating any acquisition files while disabled."""
        self._promotion_config = {
            "tool_rpc": tool_rpc,
            "marketplace": marketplace,
            "kernel_gate": kernel_gate,
            "profile": profile,
        }

    def ensure_promotion(self):
        if not self.is_enabled():
            return None
        if self.promotion_broker is not None:
            return self.promotion_broker
        if self._promotion_config is None:
            logger.warning("acquisition promotion seams are not bound")
            return None
        if self._promotion_config.get("tool_rpc") is None or self._promotion_config.get("marketplace") is None:
            logger.warning("acquisition promotion host seams are incomplete")
            return None
        import os

        from agents.core.paths import data_path

        from .acquired_runner import AcquiredSandboxRunner
        from .managed_signing import ManagedSigningKeyStore
        from .package_store import AcquiredPackageStore
        from .promotion import PromotionBroker, PromotionJournal, PromotionStore
        from .quarantine import QuarantineStore
        from .sandbox_profile import AcquisitionSandboxProfile, SandboxProfileError

        base = Path(self._root) if self._root is not None else data_path("acquisition")
        profile = self._promotion_config.get("profile")
        if profile is None:
            try:
                profile = AcquisitionSandboxProfile(
                    image=os.environ.get("JARVIS_ACQUISITION_SANDBOX_IMAGE", "")
                )
            except SandboxProfileError:
                logger.warning("acquisition sandbox image is not pinned; promotion unavailable")
                return None
        signing = ManagedSigningKeyStore(root=base / "signing")
        packages = AcquiredPackageStore(root=base / "packages", signing=signing)
        if self.request_store is None:
            self.request_store = self._store_factory(root=base)
        runtime = AcquiredSandboxRunner(
            packages=packages,
            profile=profile,
            runtime_root=base / "runs",
            enabled=self.is_enabled,
        )
        broker = PromotionBroker(
            enabled=self.is_enabled,
            quarantine=QuarantineStore(root=base / "quarantine"),
            requests=self.request_store,
            proposals=PromotionStore(root=base / "proposals"),
            packages=packages,
            journal=PromotionJournal(root=base / "journal"),
            tool_rpc=self._promotion_config["tool_rpc"],
            runtime=runtime,
            marketplace=self._promotion_config["marketplace"],
            profile=profile,
            kernel_gate=self._promotion_config.get("kernel_gate"),
        )
        broker.restore_registrations()
        self.package_store = packages
        self.promotion_broker = broker
        return broker

    async def execute_install_task(self, task) -> dict:
        broker = self.ensure_promotion()
        if broker is None:
            return {"status": "failed", "reason": "acquisition_unavailable"}
        if not self._reconciled:
            await broker.reconcile()
            self._reconciled = True
        return await broker.execute_task(task)
