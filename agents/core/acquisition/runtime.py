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
        self.ledger = None

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
            self.request_store = self._make_request_store()
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
            ledger = self.ensure_ledger()
            if ledger is None:
                return None
            self.decision_store = ReuseDecisionStore(
                root=self._root,
                event_sink=ledger.emit,
            )
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
        ledger = self.ensure_ledger()
        if ledger is None:
            logger.warning("acquisition was disabled during promotion composition")
            return None
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
        packages = AcquiredPackageStore(
            root=base / "packages",
            signing=signing,
            event_sink=ledger.emit,
        )
        if self.request_store is None:
            self.request_store = self._make_request_store()
        runtime = AcquiredSandboxRunner(
            packages=packages,
            profile=profile,
            runtime_root=base / "runs",
            enabled=self.is_enabled,
            event_sink=ledger.emit,
        )
        broker = PromotionBroker(
            enabled=self.is_enabled,
            quarantine=QuarantineStore(root=base / "quarantine", event_sink=ledger.emit),
            requests=self.request_store,
            proposals=PromotionStore(root=base / "proposals", event_sink=ledger.emit),
            packages=packages,
            journal=PromotionJournal(root=base / "journal"),
            tool_rpc=self._promotion_config["tool_rpc"],
            runtime=runtime,
            marketplace=self._promotion_config["marketplace"],
            profile=profile,
            kernel_gate=self._promotion_config.get("kernel_gate"),
            event_sink=ledger.emit,
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

    def ensure_ledger(self):
        if not self.is_enabled():
            return None
        if self.ledger is None:
            from agents.core.paths import data_path

            from .audit import AcquisitionLedger

            base = Path(self._root) if self._root is not None else data_path("acquisition")
            self.ledger = AcquisitionLedger(root=base / "ledger")
        return self.ledger

    def status_snapshot(self) -> dict:
        empty_reuse = {
            "reused": 0,
            "generated": 0,
            "blocked": 0,
            "abandoned": 0,
            "reuse_rate": 0.0,
        }
        if not self.is_enabled():
            existing = self._ledger_if_present()
            audit = (
                existing.health()
                if existing is not None
                else {
                    "status": "disabled",
                    "events": 0,
                    "summarized_events": 0,
                    "chain_valid": True,
                }
            )
            return {
                "enabled": False,
                "status": "disabled",
                "reason": "acquisition_disabled",
                "states": {},
                "reuse": empty_reuse,
                "packages": [],
                "audit": audit,
            }
        try:
            ledger = self.ensure_ledger()
            audit = ledger.health()
            broker = self.ensure_promotion()
            requests = self.request_store.list() if self.request_store is not None else []
            states: dict[str, int] = {}
            for request in requests:
                states[request.status.value] = states.get(request.status.value, 0) + 1
            reuse = self.decision_store.metrics() if self.decision_store is not None else empty_reuse
            package_rows = self.package_store.list_records() if self.package_store is not None else []
            packages = [
                {
                    "name": row.name,
                    "version": row.version,
                    "status": row.status,
                    "confidence": float(row.outcomes.get("confidence", 0.0)),
                }
                for row in package_rows[:256]
            ]
            if broker is None:
                status, reason = "blocked", "promotion_runtime_unavailable"
            else:
                try:
                    broker.packages.signing.active_identity()
                    status, reason = "ready", None
                except Exception:
                    status, reason = "blocked", "managed_signing_key_required"
            return {
                "enabled": True,
                "status": status,
                "reason": reason,
                "states": states,
                "reuse": reuse,
                "packages": packages,
                "audit": audit,
            }
        except Exception:
            logger.warning("acquisition status projection failed closed", exc_info=True)
            return {
                "enabled": True,
                "status": "degraded",
                "reason": "acquisition_state_unavailable",
                "states": {},
                "reuse": empty_reuse,
                "packages": [],
                "audit": {
                    "status": "degraded",
                    "events": 0,
                    "summarized_events": 0,
                    "chain_valid": False,
                },
            }

    def list_audit_events(self, *, limit: int = 100) -> list[dict]:
        ledger = self.ensure_ledger() if self.is_enabled() else self._ledger_if_present()
        return ledger.list_public(limit=limit) if ledger is not None else []

    def export_audit(self) -> dict:
        ledger = self.ensure_ledger() if self.is_enabled() else self._ledger_if_present()
        if ledger is None:
            return {"schema": 1, "summary": {}, "events": []}
        return ledger.export_public()

    def purge_audit(self, *, actor: str) -> dict[str, int]:
        ledger = self.ensure_ledger() if self.is_enabled() else self._ledger_if_present()
        if ledger is None:
            return {"purged": 0, "summarized_events": 0}
        return ledger.purge_details(actor=actor)

    async def revoke(self, name: str) -> dict:
        broker = self.ensure_promotion()
        if broker is None:
            return {"status": "refused", "reason": "acquisition_unavailable"}
        return await broker.revoke(name)

    async def rollback(self, name: str) -> dict:
        broker = self.ensure_promotion()
        if broker is None:
            return {"status": "refused", "reason": "acquisition_unavailable"}
        return await broker.rollback(name)

    def _make_request_store(self):
        ledger = self.ensure_ledger()
        try:
            return self._store_factory(
                root=self._root,
                event_sink=ledger.emit if ledger is not None else None,
            )
        except TypeError:
            return self._store_factory(root=self._root)

    def _ledger_if_present(self):
        if self.ledger is not None:
            return self.ledger
        from agents.core.paths import data_path

        base = Path(self._root) if self._root is not None else data_path("acquisition")
        if not (base / "ledger" / "ledger.enc").is_file():
            return None
        from .audit import AcquisitionLedger

        self.ledger = AcquisitionLedger(root=base / "ledger")
        return self.ledger
