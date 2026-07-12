"""Default-off unified action facade for registry-addressed capabilities."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS, CapabilityManifest
from agents.core.env_config import env_flag
from agents.core.kernel import Action, Capability, Decision, Verdict, kernel_enabled

UNIFIED_ACTION_ENV = "JARVIS_UNIFIED_ACTION_API"


@dataclass(frozen=True)
class PerformContext:
    agent: str = "jarvis"
    title: str = ""
    origin: str = "generated"
    scope: str = "global"
    capability_token: str = ""
    capability_name: str = ""


@dataclass(frozen=True)
class PerformResult:
    status: str
    capability_id: str
    action_kind: str = ""
    reason: str = ""
    tier: int | None = None
    card: dict | None = None
    output: Any = None


@dataclass(frozen=True)
class _Binding:
    handler: Callable[[dict[str, Any], PerformContext], Any]
    mediation: str = "facade"


class CapabilityActionAPI:
    """Resolve a capability id, mediate it once, then invoke its implementation."""

    def __init__(
        self,
        *,
        authorizer: Callable | None = None,
        manifests: Iterable[CapabilityManifest] | None = None,
    ) -> None:
        self._authorizer = authorizer
        source = manifests if manifests is not None else ACTION_CAPABILITY_MANIFESTS.values()
        self._manifests = {manifest.id: manifest for manifest in source}
        self._bindings: dict[str, _Binding] = {}

    def register(
        self,
        capability_id: str,
        handler: Callable[[dict[str, Any], PerformContext], Any],
    ) -> CapabilityActionAPI:
        return self._bind(capability_id, handler, mediation="facade")

    def _bind(
        self,
        capability_id: str,
        handler: Callable[[dict[str, Any], PerformContext], Any],
        *,
        mediation: str,
    ) -> CapabilityActionAPI:
        if capability_id not in self._manifests:
            raise ValueError(f"unknown action capability: {capability_id}")
        if not callable(handler):
            raise TypeError("capability handler must be callable")
        if mediation == "delegated":
            from agents.core.kernel.registry import Mediation, classify

            action_kind = self._manifests[capability_id].action_kind or ""
            if classify(action_kind) is not Mediation.KERNEL:
                raise ValueError("delegated capability must already be kernel-mediated")
        self._bindings[capability_id] = _Binding(handler=handler, mediation=mediation)
        return self

    def register_broker(
        self,
        capability_id: str,
        broker: Any,
        handler: Callable[[dict[str, Any], PerformContext], Any],
    ) -> CapabilityActionAPI:
        """Bind a broker that already owns its kernel mediation point."""
        self._validate_delegated_capability(capability_id)
        if not callable(getattr(broker, "_kernel", None)):
            raise ValueError("delegated broker must have a bound kernel")
        if getattr(handler, "__self__", None) is not broker:
            raise ValueError("delegated broker handler must be a bound method of that broker")
        return self._bind(capability_id, handler, mediation="delegated")

    def register_tool_rpc(self, capability_id: str, server: Any) -> CapabilityActionAPI:
        """Bind ToolRPC's existing mediated handle path without authorizing twice."""
        self._validate_delegated_capability(capability_id)
        if not callable(getattr(server, "handle", None)):
            raise TypeError("ToolRPC server must expose an async handle method")
        if not callable(getattr(server, "_kernel", None)):
            raise ValueError("delegated ToolRPC server must have a bound kernel")

        async def _handle(params: dict[str, Any], context: PerformContext) -> Any:
            tool_name = str(params.get("tool", ""))
            spec = next((item for item in server.tools() if item.get("name") == tool_name), None)
            if spec is not None and not spec.get("gated"):
                return {"ok": False, "reason": "capability_requires_gated_tool", "tool": tool_name}
            return await server.handle(params, actor=context.agent)

        return self._bind(capability_id, _handle, mediation="delegated")

    async def perform(
        self,
        capability_id: str,
        params: Mapping[str, Any],
        context: PerformContext | None = None,
    ) -> PerformResult:
        context = PerformContext() if context is None else context
        manifest = self._manifests.get(capability_id)
        action_kind = manifest.action_kind if manifest is not None and manifest.action_kind else ""

        if not env_flag(UNIFIED_ACTION_ENV):
            return PerformResult("disabled", capability_id, action_kind, "unified_action_api_disabled")
        if not kernel_enabled():
            return PerformResult("disabled", capability_id, action_kind, "action_kernel_disabled")
        if manifest is None:
            return PerformResult("refused", capability_id, reason="unknown_capability")
        if not isinstance(context, PerformContext):
            return PerformResult("refused", capability_id, action_kind, "invalid_context")
        if not isinstance(params, Mapping):
            return PerformResult("refused", capability_id, action_kind, "invalid_params")
        missing = self._missing_inputs(manifest, params)
        if missing:
            return PerformResult(
                "refused", capability_id, action_kind, f"missing_inputs:{','.join(missing)}"
            )
        binding = self._bindings.get(capability_id)
        if binding is None:
            return PerformResult("refused", capability_id, action_kind, "implementation_unbound")
        if context.capability_name and context.capability_name != action_kind:
            return PerformResult("refused", capability_id, action_kind, "capability_mismatch")
        if binding.mediation == "delegated":
            return await self._invoke(binding, capability_id, action_kind, dict(params), context)
        if self._authorizer is None:
            return PerformResult("refused", capability_id, action_kind, "kernel_unavailable")

        payload = dict(params)
        action = Action(
            kind=action_kind,
            agent=context.agent,
            title=context.title,
            payload=payload,
            scope=context.scope,
            origin=context.origin,
        )
        capability = Capability(
            token_id=context.capability_token,
            name=action_kind,
        )
        try:
            decision = self._authorizer(action, capability=capability)
            if inspect.isawaitable(decision):
                decision = await decision
        except Exception:
            return PerformResult("refused", capability_id, action_kind, "kernel_error")
        if not isinstance(decision, Decision):
            return PerformResult("refused", capability_id, action_kind, "kernel_error")
        if decision.verdict is Verdict.DENY:
            return PerformResult(
                "refused", capability_id, action_kind, decision.reason, decision.tier, decision.card
            )
        if decision.verdict is Verdict.QUEUE:
            return PerformResult(
                "queued", capability_id, action_kind, decision.reason, decision.tier, decision.card
            )

        return await self._invoke(
            binding,
            capability_id,
            action_kind,
            payload,
            context,
            reason=decision.reason,
            tier=decision.tier,
        )

    @staticmethod
    def _missing_inputs(manifest: CapabilityManifest, params: Mapping[str, Any]) -> list[str]:
        required = manifest.inputs.get("required", ())
        return sorted(str(key) for key in required if key not in params)

    def _validate_delegated_capability(self, capability_id: str) -> None:
        manifest = self._manifests.get(capability_id)
        if manifest is None:
            raise ValueError(f"unknown action capability: {capability_id}")
        from agents.core.kernel.registry import Mediation, classify

        if classify(manifest.action_kind or "") is not Mediation.KERNEL:
            raise ValueError("delegated capability must already be kernel-mediated")

    @staticmethod
    async def _invoke(
        binding: _Binding,
        capability_id: str,
        action_kind: str,
        payload: dict[str, Any],
        context: PerformContext,
        *,
        reason: str = "",
        tier: int | None = None,
    ) -> PerformResult:
        try:
            output = binding.handler(payload, context)
            if inspect.isawaitable(output):
                output = await output
        except Exception:
            return PerformResult("failed", capability_id, action_kind, "implementation_error")
        if isinstance(output, Mapping) and output.get("reason") == "approval_required":
            return PerformResult(
                "queued", capability_id, action_kind, "approval_required", tier, output=output
            )
        if isinstance(output, Mapping) and output.get("reason") == "kernel_denied":
            return PerformResult(
                "refused", capability_id, action_kind, "kernel_denied", tier, output=output
            )
        if isinstance(output, Mapping) and output.get("reason") == "capability_requires_gated_tool":
            return PerformResult(
                "refused",
                capability_id,
                action_kind,
                "capability_requires_gated_tool",
                tier,
            )
        return PerformResult(
            "completed", capability_id, action_kind, reason, tier, output=output
        )
