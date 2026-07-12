"""Machine-readable capability manifests for the Nerva action plane.

The action-auth registry remains the source of truth for mediation.  This module
adds the product metadata an agent needs to reason about those actions without
introducing another authorization registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.core.capability_verification import (
    action_verification_ref,
    plugin_verification_ref,
)

RISK_LEVELS = frozenset({"read_only", "reversible", "sensitive", "irreversible_or_money"})
ROLLBACK_MODES = frozenset({
    "none",
    "cancel",
    "compensate",
    "restore",
    "revoke",
    "disable",
    "implementation_specific",
})


@dataclass(frozen=True)
class RollbackContract:
    """Bounded rollback promise exposed to planners and approval clients."""

    mode: str
    description: str
    automatic: bool = False
    handler_ref: str | None = None
    limitations: str = ""

    def __post_init__(self) -> None:
        if self.mode not in ROLLBACK_MODES:
            raise ValueError(f"unsupported rollback mode: {self.mode}")
        if not self.description.strip():
            raise ValueError("rollback description is required")
        if self.automatic and not self.handler_ref:
            raise ValueError("automatic rollback requires a handler reference")
        if self.mode == "none" and (self.automatic or self.handler_ref):
            raise ValueError("rollback mode none cannot declare a handler")


@dataclass(frozen=True)
class CapabilityManifest:
    id: str
    description: str
    inputs: dict[str, Any]
    risk: str
    requires: tuple[str, ...]
    supports: tuple[str, ...]
    verification: str
    rollback: RollbackContract
    confidence: float
    implementation: str
    action_kind: str | None = None
    contract_ref: str | None = None

    def __post_init__(self) -> None:
        validate_manifest(self)


def validate_manifest(manifest: CapabilityManifest) -> CapabilityManifest:
    """Validate the stable fields shared by action and derived manifests."""
    if not manifest.id or not manifest.description.strip():
        raise ValueError("capability id and description are required")
    if not isinstance(manifest.inputs, dict) or manifest.inputs.get("type") != "object":
        raise ValueError("capability inputs must be an object schema")
    if manifest.risk not in RISK_LEVELS:
        raise ValueError(f"unsupported capability risk: {manifest.risk}")
    if isinstance(manifest.confidence, bool) or not isinstance(manifest.confidence, (int, float)):
        raise ValueError("capability confidence must be numeric")
    if not 0.0 <= float(manifest.confidence) <= 1.0:
        raise ValueError("capability confidence must be between 0 and 1")
    if not manifest.requires or not manifest.supports:
        raise ValueError("capability requires and supports must be non-empty")
    if (not manifest.verification or not isinstance(manifest.rollback, RollbackContract)
            or ":" not in manifest.implementation):
        raise ValueError("capability verification, rollback and implementation are required")
    return manifest


def _action(
    kind: str,
    description: str,
    *,
    required: tuple[str, ...] = (),
    risk: str = "sensitive",
    supports: tuple[str, ...] = ("execute",),
    rollback: RollbackContract,
    implementation: str,
    contract_ref: str | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        id=f"action:{kind}",
        description=description,
        inputs={"type": "object", "required": list(required), "additionalProperties": True},
        risk=risk,
        requires=("action-kernel",),
        supports=supports,
        verification=action_verification_ref(kind),
        rollback=rollback,
        confidence=0.0,
        implementation=implementation,
        action_kind=kind,
        contract_ref=contract_ref,
    )


# Explicit product decisions.  A drift test pins this key set to ACTION_REGISTRY.
ACTION_CAPABILITY_MANIFESTS: dict[str, CapabilityManifest] = {
    "node.dispatch": _action(
        "node.dispatch",
        "Dispatch an allowlisted operation to a registered execution node.",
        required=("node_id", "operation"),
        rollback=RollbackContract(
            mode="cancel",
            description="Cancel the dispatch while it is still queued.",
            limitations="After remote acceptance, rollback is implementation-specific.",
        ),
        implementation="agents.core.node_mesh:NodeMesh.dispatch",
    ),
    "call.outbound": _action(
        "call.outbound",
        "Place a governed outbound call through a configured provider.",
        required=("to", "message"),
        rollback=RollbackContract(
            mode="cancel",
            description="Cancel before the provider accepts the call.",
            limitations="An accepted call cannot be undone.",
        ),
        implementation="agents.core.autonomy.call_broker:CallBroker.request",
    ),
    "social.*": _action(
        "social.*",
        "Publish or mutate content through a governed social provider.",
        required=("provider", "action"),
        risk="irreversible_or_money",
        supports=("publish", "mutate"),
        rollback=RollbackContract(
            mode="compensate",
            description="Delete the remote item when the provider supports deletion.",
            limitations="Deletion support and retention are provider-specific.",
        ),
        implementation="agents.core.social:SocialBroker.request",
    ),
    "writeback.*": _action(
        "writeback.*",
        "Write an attributed update to an allowlisted external target.",
        required=("target", "action"),
        risk="reversible",
        supports=("create", "update"),
        rollback=RollbackContract(
            mode="restore",
            description="Restore the previous target value from the audit snapshot.",
            limitations="Requires a complete pre-write audit snapshot and a writable target.",
        ),
        implementation="agents.core.writeback:WriteBackBroker.request",
    ),
    "payment": _action(
        "payment",
        "Request a payment within an active mandate and hard spending caps.",
        required=("mandate_id", "payee", "amount", "currency"),
        risk="irreversible_or_money",
        supports=("request", "approve"),
        rollback=RollbackContract(
            mode="cancel",
            description="Cancel the payment before settlement.",
            limitations="A settled payment cannot be undone.",
        ),
        implementation="agents.core.payments:PaymentBroker.request_payment",
        contract_ref="agents.core.payments:PAYMENT_CONTRACT",
    ),
    "plugin.egress": _action(
        "plugin.egress",
        "Send a policy-admitted outbound request for a governed plugin.",
        required=("plugin", "method", "url"),
        supports=("http",),
        rollback=RollbackContract(
            mode="cancel",
            description="Abort the request before transmission.",
            limitations="A transmitted external request may already have side effects.",
        ),
        implementation="agents.core.http_client:PluginHTTPClient.request",
        contract_ref="agents.core.plugin_gate:PLUGIN_CALL_CONTRACT",
    ),
    "mcp.mutating": _action(
        "mcp.mutating",
        "Invoke an identity-checked mutating MCP route tool.",
        required=("tool", "args"),
        supports=("tool-rpc", "mutate"),
        rollback=RollbackContract(
            mode="implementation_specific",
            description="Use the adapter rollback declared by the route specification.",
            limitations="Unavailable when the adapter declares no compensating operation.",
        ),
        implementation="agents.core.mcp.route_tools:MutatingRouteTool.call",
    ),
    "tool.rpc": _action(
        "tool.rpc",
        "Invoke a gated ToolRPC tool through its approval and sandbox boundary.",
        required=("tool", "args"),
        supports=("tool-rpc",),
        rollback=RollbackContract(
            mode="implementation_specific",
            description="Use the rollback declared by the selected tool.",
            limitations="The action is not reversible when the tool declares no rollback.",
        ),
        implementation="agents.core.tool_rpc:ToolRPCServer.handle",
    ),
    "repo.sync": _action(
        "repo.sync",
        "Pull and validate an externally triggered repository update.",
        required=("commit",),
        supports=("git", "test"),
        rollback=RollbackContract(
            mode="restore",
            description="Restore the recorded pre-sync commit.",
            limitations="Local changes after the sync require a separate reconciliation.",
        ),
        implementation="agents.core.plugins.oracle_bridge:OracleBridgePlugin._process_claude_commit",
    ),
    "admin.kill_switch": _action(
        "admin.kill_switch",
        "Engage the persisted action kill-switch for an authenticated scope.",
        required=("scope",),
        supports=("halt",),
        rollback=RollbackContract(
            mode="restore",
            description="Disengage through the admin-only recovery path.",
            limitations="Recovery requires an authenticated administrator.",
        ),
        implementation="agents.core.routers.security:kill_switch_set",
    ),
    "admin.capability_issue": _action(
        "admin.capability_issue",
        "Issue a bounded capability token to an authenticated operator.",
        required=("capabilities",),
        supports=("issue",),
        rollback=RollbackContract(
            mode="revoke",
            description="Revoke the issued capability token.",
            limitations="Already completed operations are not reversed by token revocation.",
        ),
        implementation="agents.core.routers.security:capabilities_issue",
    ),
    "kg.write": _action(
        "kg.write",
        "Apply an externally requested mutation to the governed knowledge graph.",
        required=("operation",),
        risk="reversible",
        supports=("create", "update", "delete"),
        rollback=RollbackContract(
            mode="restore",
            description="Restore the entity or relation from the audit snapshot.",
            limitations="Requires a complete pre-write audit snapshot.",
        ),
        implementation="agents.core.routers.memory_kg:kg_upsert_entity",
    ),
}


def manifest_for_action(kind: str) -> CapabilityManifest | None:
    """Resolve a concrete action kind using the action-auth exact/wildcard rules."""
    exact = ACTION_CAPABILITY_MANIFESTS.get(kind)
    if exact is not None:
        return exact
    for pattern, manifest in ACTION_CAPABILITY_MANIFESTS.items():
        if pattern.endswith(".*") and kind.startswith(pattern[:-1]):
            return manifest
    return None


def plugin_capability_manifest(plugin: Any) -> CapabilityManifest:
    """Derive executable metadata without duplicating plugin network policy."""
    network = getattr(getattr(plugin, "network_access", None), "value", "none")
    data_scope = getattr(getattr(plugin, "data_scope", None), "value", "local_only")
    plugin_id = str(getattr(plugin, "id", "")).strip()
    # Network/data scope cannot prove an operation is read-only: a NONE/LAN plugin
    # may still restart a service or actuate a device.  Stay conservative until a
    # future native manifest explicitly earns a lower tier.
    risk = "sensitive"
    domains = tuple(str(item) for item in (getattr(plugin, "allowed_domains", None) or ()))
    requires = ("plugin.enabled", f"network:{network}", f"data:{data_scope}") + tuple(
        f"domain:{domain}" for domain in domains
    )
    return CapabilityManifest(
        id=f"plugin:{plugin_id}",
        description=str(getattr(plugin, "description", "")).strip(),
        inputs={"type": "object", "additionalProperties": True},
        risk=risk,
        requires=requires,
        supports=("plugin-call", f"egress:{network}"),
        verification=plugin_verification_ref(plugin_id),
        rollback=RollbackContract(
            mode="disable",
            description=f"Disable plugin {plugin_id}.",
            limitations="Disabling prevents future calls but cannot undo completed external effects.",
        ),
        confidence=0.0,
        implementation=f"agents.core.plugin_gate:BUILTIN_PLUGINS[{plugin_id}]",
    )
