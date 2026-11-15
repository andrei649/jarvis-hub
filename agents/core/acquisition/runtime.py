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
        commands=None,
        extension_consent=None,
        activation_hints=None,
        command_bindings=None,
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
        self.sandbox_profile = None
        self.extension_runtime = None
        self.commands = commands
        self.extension_consent = extension_consent
        self.activation_hints = activation_hints
        self.command_bindings = command_bindings
        self._restored_extension_commands = None
        self._extension_restore_attempted = False
        self._extension_restored_ids: tuple[str, ...] = ()
        self._uncomposed_extension_status: dict[str, dict] = {}

    def is_enabled(self) -> bool:
        from agents.core import safe_mode

        try:
            enabled = self._enabled() is True
        except Exception:
            logger.warning("acquisition enablement check failed closed")
            return False
        if enabled and safe_mode.enabled():
            # H275: nothing acquired is re-registered and no extension is activated. An
            # acquisition that was never switched on had nothing to leave out.
            safe_mode.note("acquired_packages")
            return False
        return enabled

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
        from .resolver import (
            ReuseDecisionStore,
            ReuseResolver,
            collect_reuse_candidates,
        )

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
        self.sandbox_profile = profile
        return broker

    def extensions(self):
        """The S2 extension runtime, over the same signed store and sandbox profile.

        Composed lazily and only from an already-composed promotion path: an
        extension is an acquired package, so there is deliberately no second store,
        no second signing key and no second sandbox profile it could be admitted
        through. Nothing is activated here — activation is the owner's explicit act.
        """
        if self.extension_runtime is not None:
            return self.extension_runtime
        if not self.is_enabled() or self.package_store is None or self.sandbox_profile is None:
            return None
        from pathlib import Path as _Path

        from agents.core.extensions.events import EXTENSION_EVENTS
        from agents.core.extensions.runtime import ExtensionRuntime
        from agents.core.paths import data_path

        base = _Path(self._root) if self._root is not None else data_path("acquisition")
        self._ensure_extension_metadata()
        bindings = self._ensure_extension_bindings()
        self.extension_runtime = ExtensionRuntime(
            packages=self.package_store,
            profile=self.sandbox_profile,
            runtime_root=base / "extension-runs",
            enabled=self.is_enabled,
            rpc=(self._promotion_config or {}).get("tool_rpc"),
            commands=self.commands,
            consent=self.extension_consent,
            activation_hints=self.activation_hints,
            command_bindings=bindings,
        )
        # Lifecycle events have somewhere to go only once a runtime exists; before
        # that every emitting call site is a no-op that costs a None check.
        EXTENSION_EVENTS.bind(self.extension_runtime)
        return self.extension_runtime

    def _ensure_extension_metadata(self) -> None:
        """Create only lightweight store objects; their read methods do not write."""
        if self.extension_runtime is not None:
            if self.extension_consent is None:
                self.extension_consent = getattr(self.extension_runtime, "consent", None)
            if self.activation_hints is None:
                self.activation_hints = getattr(self.extension_runtime, "activation_hints", None)
        if self.extension_consent is None:
            from agents.core.extensions.consent import ExtensionConsentStore

            self.extension_consent = ExtensionConsentStore()
        if self.activation_hints is None:
            from agents.core.extensions.activation_hints import ActivationHintStore

            self.activation_hints = ActivationHintStore()

    def _ensure_extension_bindings(self):
        if self.command_bindings is None and self.extension_runtime is not None:
            existing = getattr(self.extension_runtime, "command_bindings", None)
            if existing is not None:
                self.command_bindings = existing
        if self.command_bindings is None:
            from agents.core.extensions.command_bindings import ExtensionCommandBindings

            self.command_bindings = ExtensionCommandBindings(self.commands)
        return self.command_bindings

    def _runtime_for_restored_extension(self):
        """Compose acquisition only after an owner has invoked a restored command."""
        if not self.is_enabled():
            return None
        if ((self.package_store is None or self.sandbox_profile is None)
                and self.ensure_promotion() is None):
            return None
        return self.extensions()

    def restore_extension_commands(self) -> tuple[str, ...]:
        """Install data-only command placeholders once for this host composition."""
        if self._extension_restore_attempted:
            return self._extension_restored_ids
        if not self.is_enabled():
            return ()
        from agents.core.commands import CommandRegistry

        if not isinstance(self.commands, CommandRegistry):
            return ()
        try:
            self._ensure_extension_metadata()
            bindings = self._ensure_extension_bindings()
            if self._restored_extension_commands is None:
                from agents.core.extensions.restored_commands import (
                    RestoredExtensionCommands,
                )

                self._restored_extension_commands = RestoredExtensionCommands(
                    bindings,
                    self.extension_consent,
                    self.activation_hints,
                    runtime_provider=self._runtime_for_restored_extension,
                    enabled=self.is_enabled,
                )
            # Mark only after enablement and registry validation. In safe mode
            # startup leaves this eligible for a later explicit composition attempt.
            self._extension_restore_attempted = True
            self._extension_restored_ids = tuple(self._restored_extension_commands.restore())
        except Exception:
            logger.warning("extension command restore failed closed")
            self._extension_restored_ids = ()
        return self._extension_restored_ids

    def forget_extension_commands(self, extension_id: str) -> bool:
        """Invalidate one restored route without asking for a package runtime."""
        controller = self._restored_extension_commands
        if controller is None:
            return False
        try:
            return bool(controller.forget(extension_id))
        except Exception:
            logger.warning("extension command invalidation failed closed")
            return False

    def retire_extension_command_routes(self) -> tuple[str, ...]:
        """Invalidate and remove this host's routes before its registry is rewired.

        This is synchronous and deliberately avoids runtime composition and hint
        persistence. ``ExtensionCommandBindings.remove`` unregisters only exact
        command objects owned by this acquisition instance, so replacements from
        another host survive retirement.
        """
        controller = self._restored_extension_commands
        bindings = self.command_bindings
        extension_ids: set[str] = set()
        registrations = getattr(bindings, "registrations", None)
        if isinstance(registrations, dict):
            extension_ids.update(item for item in registrations if isinstance(item, str))
        rows = getattr(controller, "_rows", None)
        if isinstance(rows, dict):
            extension_ids.update(item for item in rows if isinstance(item, str))

        # Retired host compositions must never restore themselves again, even if
        # the coordinator accidentally invokes the startup hook twice.
        self._extension_restore_attempted = True
        self._extension_restored_ids = ()
        for extension_id in sorted(extension_ids):
            if controller is not None:
                try:
                    controller.forget(extension_id)
                except Exception:
                    logger.warning("extension command retirement failed closed")
            if bindings is not None:
                try:
                    bindings.remove(extension_id)
                except Exception:
                    logger.warning("extension command retirement failed closed")
        return tuple(sorted(extension_ids))

    async def deactivate_extension(self, extension_id: str) -> bool:
        """Forget routes, then deactivate if composed or delete the hint directly."""
        forgotten = self.forget_extension_commands(extension_id)
        if self.extension_runtime is not None:
            try:
                result = bool(await self.extension_runtime.deactivate(extension_id) or forgotten)
                self._uncomposed_extension_status.pop(extension_id, None)
                return result
            except Exception as exc:
                logger.warning("extension deactivation failed closed")
                reason = getattr(exc, "reason", "activation_hints_unavailable")
                allowed = {
                    "activation_hints_unavailable", "activation_hints_corrupt",
                    "activation_hints_capacity", "activation_hint_invalid",
                    "activation_hints_durability_uncertain",
                }
                if not isinstance(reason, str) or reason not in allowed:
                    reason = "activation_hints_unavailable"
                self._uncomposed_extension_status[extension_id] = {
                    "state": "remove_failed", "reason": reason,
                }
                return forgotten

        try:
            self._ensure_extension_metadata()
            removed = bool(self.activation_hints.remove(extension_id))
            self._uncomposed_extension_status[extension_id] = {"state": "removed"}
            return bool(removed or forgotten)
        except Exception as exc:
            reason = getattr(exc, "reason", "activation_hints_unavailable")
            if not isinstance(reason, str) or reason not in {
                "activation_hints_unavailable", "activation_hints_corrupt",
                "activation_hints_capacity", "activation_hint_invalid",
                "activation_hints_durability_uncertain",
            }:
                reason = "activation_hints_unavailable"
            self._uncomposed_extension_status[extension_id] = {
                "state": "remove_failed", "reason": reason,
            }
            return forgotten

    def extension_restoration_status(self, extension_id: str) -> dict:
        """Return bounded persistence status without composing acquisition."""
        override = self._uncomposed_extension_status.get(extension_id)
        if override is not None:
            return dict(override)
        if self.extension_runtime is not None:
            status_method = getattr(self.extension_runtime, "restoration_status", None)
            if callable(status_method):
                try:
                    status = status_method(extension_id)
                    state = status.get("state") if isinstance(status, dict) else None
                    if isinstance(state, str) and state in {
                        "not_configured", "unknown", "saved", "save_failed", "removed", "remove_failed",
                    }:
                        result = {"state": state}
                        reason = status.get("reason")
                        if result["state"] in {"save_failed", "remove_failed"}:
                            allowed = {
                                "activation_hints_unavailable", "activation_hints_corrupt",
                                "activation_hints_capacity", "activation_hint_invalid",
                                "activation_hints_durability_uncertain",
                            }
                            result["reason"] = (reason if isinstance(reason, str) and reason in allowed
                                                 else "activation_hints_unavailable")
                        return result
                except Exception:
                    return {"state": "unknown"}
        return dict(self._uncomposed_extension_status.get(extension_id, {"state": "not_configured"}))

    async def synthesize_and_propose(
        self,
        request_id: str,
        *,
        contract,
        research,
        generate: Callable[[dict], object],
        runner=None,
    ):
        """Compose gap -> research -> generate -> quarantine -> verify -> propose.

        Every stage below already exists and is independently tested (H32.3-
        H32.5) — this is the missing production glue (BACKLOG: "a production
        path that creates a `PromotionProposal`"). It changes nothing about the
        guardrails each stage already enforces: strict-local generation still
        AST-validates the model's output and rejects placeholder bodies,
        ``SandboxVerifier`` still requires a real, pinned sandbox image, and
        ``PromotionBroker.propose()`` still requires a verified receipt and the
        Action Kernel gate. Permanent owner approval (``promote()``) is a
        separate, later step this method never reaches.

        Callers own two things this method deliberately does NOT: reuse
        resolution (call ``resolve_gap`` first — a request only researches when
        that already came back ``no_reuse``, left at ``MISSING``) and the
        system-owned ``contract`` (its cases are never model-authored). Nothing
        here auto-triggers from chat or any other live path; a caller (an
        admin action, a scheduled worker) must invoke it explicitly, same as
        ``resolve_gap`` itself is never auto-invoked either.

        ``runner`` is the same injectable sandbox-command runner
        ``SandboxVerifier`` already accepts (default ``None`` -> real Docker) —
        offline tests inject a fake one instead of requiring a pinned image.
        """
        if not self.is_enabled() or self.request_store is None:
            return None
        from agents.core.paths import data_path

        from .generator import CapabilityContract, GenerationError, StrictLocalGenerator
        from .promotion import PromotionError
        from .sandbox_profile import SandboxVerifier

        request = self.request_store.get(request_id)
        if request is None:
            return None
        if not isinstance(contract, CapabilityContract) or contract.goal != request.goal:
            logger.warning("synthesize_and_propose: contract must be system-owned and goal-matched")
            return None
        broker = self.ensure_promotion()
        if broker is None:
            return None
        try:
            self.request_store.transition(request_id, "researching", actor="synthesis-pipeline")
        except (KeyError, ValueError):
            logger.warning("synthesize_and_propose: request not eligible for research")
            return None

        try:
            record = await research.run(request)
        except Exception:
            logger.warning("acquisition research failed", exc_info=True)
            self.request_store.transition(request_id, "blocked", actor="synthesis-pipeline")
            return None

        generator = StrictLocalGenerator(
            generate=generate,
            route="strict-local",
            event_sink=self.ensure_ledger().emit,
        )
        try:
            package = await generator.generate(
                request=request,
                grounded_plan=record.plan,
                contract=contract,
            )
        except GenerationError:
            logger.warning("acquisition generation failed", exc_info=True)
            self.request_store.transition(request_id, "blocked", actor="synthesis-pipeline")
            return None

        self.request_store.transition(request_id, "quarantined", actor="synthesis-pipeline")
        broker.quarantine.put(package)
        base = Path(self._root) if self._root is not None else data_path("acquisition")
        verifier = SandboxVerifier(
            profile=broker.profile, runner=runner, runtime_root=base / "verification-runs",
        )
        outcome = await verifier.verify_quarantined(
            store=broker.quarantine, artifact_id=package.artifact_id, contract=contract,
        )
        if not outcome.verified or outcome.receipt is None:
            logger.warning("acquisition sandbox verification failed: %s", outcome.reason)
            return None

        try:
            return broker.propose(package.artifact_id, contract=contract)
        except PromotionError:
            logger.warning("acquisition promotion proposal failed", exc_info=True)
            return None

    async def execute_install_task(self, task) -> dict:
        broker = self.ensure_promotion()
        if broker is None:
            return {"status": "failed", "reason": "acquisition_unavailable"}
        # Known outcome gap (review round 5, item 10; documented, not changed): the first
        # install task of a process reconciles the promotion journal before it runs. When
        # an earlier attempt of THIS proposal began an install and was reaped mid-way,
        # reconcile commits or rolls that install back here — and ``execute_task`` then
        # reads the proposal as no longer promotable: ``promotion_refused``, which records
        # nothing although the capability was attempted (the reaped task itself was
        # failed by the reaper, recording nothing either). Only reachable after a crash
        # mid-install; the reconcile's own journal row keeps what happened.
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
