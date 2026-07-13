"""Final execution-time revocation and compensation for ambient silent work."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .policy import DecisionRung, LadderContext, LadderPolicy
from .registry import MonitorRegistry

_HASH = re.compile(r"^[a-f0-9]{64}$")
_PAYLOAD_FIELDS = {
    "ambient_generation",
    "consent_generation",
    "event_fingerprint",
    "monitor_hash",
    "monitor_id",
    "monitor_version",
    "rung",
    "source",
}


@dataclass(frozen=True, slots=True)
class SilentActionBinding:
    monitor_id: str
    capability_id: str
    rollbackable: bool
    postcondition_bound: bool

    def __post_init__(self) -> None:
        if not self.monitor_id or len(self.monitor_id) > 128:
            raise ValueError("ambient action monitor binding is invalid")
        if not self.capability_id or len(self.capability_id) > 128:
            raise ValueError("ambient capability binding is invalid")
        if not isinstance(self.rollbackable, bool) or not isinstance(
            self.postcondition_bound, bool
        ):
            raise ValueError("ambient action proofs must be boolean")


class AmbientTaskExecutor:
    """Revalidate immutable provenance twice before entering Action API."""

    def __init__(
        self,
        *,
        enabled_provider: Callable[[], bool],
        generation_provider: Callable[[], int],
        registry: MonitorRegistry,
        ownership_provider: Callable[[str], bool],
        kill_switch: Callable[[], bool] | object,
        binding_resolver: Callable[[str], SilentActionBinding | None],
        action_api: Callable[[SilentActionBinding, object], Awaitable[dict]],
        rollback: Callable[[SilentActionBinding, object, dict], Awaitable[dict]],
        policy: LadderPolicy | None = None,
    ) -> None:
        providers = (
            enabled_provider,
            generation_provider,
            ownership_provider,
            binding_resolver,
            action_api,
            rollback,
        )
        if any(not callable(item) for item in providers) or not isinstance(
            registry, MonitorRegistry
        ):
            raise ValueError("ambient executor dependencies are invalid")
        self._enabled = enabled_provider
        self._generation = generation_provider
        self._registry = registry
        self._ownership = ownership_provider
        self._kill_switch = kill_switch
        self._binding = binding_resolver
        self._action_api = action_api
        self._rollback = rollback
        self._policy = policy or LadderPolicy()

    def _halted(self) -> bool:
        if callable(self._kill_switch):
            try:
                return self._kill_switch() is True
            except Exception:
                return True
        checker = getattr(self._kill_switch, "is_halted", None)
        try:
            return checker() is True if callable(checker) else True
        except Exception:
            return True

    def _guard(self, task: object) -> tuple[SilentActionBinding | None, str]:
        payload = getattr(task, "payload", None)
        if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
            return None, "ambient_payload_invalid"
        try:
            enabled = self._enabled()
        except Exception:
            enabled = False
        if enabled is not True:
            return None, "ambient_disabled"
        generation = payload.get("ambient_generation")
        try:
            current_generation = self._generation()
        except Exception:
            return None, "ambient_generation_revoked"
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation != current_generation
        ):
            return None, "ambient_generation_revoked"
        source = payload.get("source")
        if not isinstance(source, str) or self._ownership(source) is not True:
            return None, "source_ownership_revoked"
        if self._halted():
            return None, "kill_switch_halted"
        monitor_id = payload.get("monitor_id")
        definition = self._registry.get(monitor_id) if isinstance(monitor_id, str) else None
        if (
            definition is None
            or definition.enabled is not True
            or definition.version != payload.get("monitor_version")
            or definition.definition_hash != payload.get("monitor_hash")
            or definition.source != source
            or payload.get("rung") != "act_silently"
            or _HASH.fullmatch(str(payload.get("event_fingerprint") or "")) is None
        ):
            return None, "monitor_version_revoked"
        binding = self._binding(monitor_id)
        if not isinstance(binding, SilentActionBinding) or binding.monitor_id != monitor_id:
            return None, "silent_binding_revoked"
        policy = self._policy.decide(
            LadderContext(
                requested_rung="act_silently",
                capability_id=binding.capability_id,
                silent_eligible=True,
                rollbackable=binding.rollbackable,
                postcondition_bound=binding.postcondition_bound,
            )
        )
        if policy.rung is not DecisionRung.ACT_SILENTLY:
            return None, policy.reason
        return binding, ""

    async def execute(self, task: object) -> dict:
        binding, reason = self._guard(task)
        if binding is None:
            return {"status": "revoked", "reason": reason}
        # Deliberately re-read all mutable safety state at the last instruction
        # before the governed Action API call.
        binding, reason = self._guard(task)
        if binding is None:
            return {"status": "revoked", "reason": reason}
        try:
            result = await self._action_api(binding, task)
        except Exception:
            result = {"status": "failed", "verified": False}
        if isinstance(result, dict) and result.get("verified") is True:
            return result
        failed = result if isinstance(result, dict) else {"status": "failed"}
        # Compensation is explicitly allowed after ambient disable/revocation.
        try:
            compensation = await self._rollback(binding, task, failed)
        except Exception:
            compensation = {"status": "failed", "verified": False}
        return {
            "status": "failed",
            "reason": "postcondition_failed",
            "compensation": (
                "verified"
                if isinstance(compensation, dict) and compensation.get("verified") is True
                else "manual_recovery_required"
            ),
        }


def register_ambient_handlers(executor, ambient: AmbientTaskExecutor):
    if not isinstance(ambient, AmbientTaskExecutor):
        raise ValueError("ambient task executor is required")
    return executor.register("ambient.action", ambient.execute)


__all__ = ["AmbientTaskExecutor", "SilentActionBinding", "register_ambient_handlers"]
