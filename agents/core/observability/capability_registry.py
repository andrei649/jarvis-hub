"""capability_registry.py — V2: one queryable readiness state per capability.

ORIZONT 24 Track V (Verification Fabric). Today "is this capability real?" is answered
ad hoc, per-caller, by API-key presence — there is no central state, which is exactly
the "looks done, isn't wired" ambiguity the 2026-06-23 audit kept hitting. This module
**derives** a single ``CapabilityRecord`` per capability from the registries that already
exist — it does not add a parallel system:

    plugin_gate.BUILTIN_PLUGINS   → kind="plugin"
    orchestrator.components.status → kind="component"
    orchestrator.skills           → kind="skill"

Each record carries a readiness state on the lifecycle:

    SEAM      declared / not wired (disabled plugin, failed component, stub skill)
    WIRED     live path constructed and available (manual confidence)
    VERIFIED  a green reality-harness proved the *rail* in CI   ← V1, pending
    GA        VERIFIED and on the supported-version matrix

**No capability is VERIFIED/GA yet** — the reality harness (V1) is what promotes a record,
and it hasn't landed. That is intentional and honest: until then the board shows what is
merely *wired* vs *seam*, never a fabricated "verified". A human may **demote** a record
via an override (cap at WIRED); only the harness may promote to VERIFIED. Read-only at
``GET /api/metrics/capabilities`` (sibling of ``/api/metrics/north-star``).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

logger = logging.getLogger("jarvis.capabilities")

# Readiness lifecycle, low → high. Ordering matters: overrides may only DEMOTE
# (≤ WIRED), and the matrix gate (V3) keys off these names.
SEAM, WIRED, VERIFIED, GA = "seam", "wired", "verified", "ga"
_ORDER = (SEAM, WIRED, VERIFIED, GA)


def _rank(state: str) -> int:
    return _ORDER.index(state) if state in _ORDER else 0


# Manual demotions: capability id → state. Only SEAM/WIRED are honored (a human can
# demote, but only a green harness promotes to VERIFIED — Track V design §V2). Empty
# today; the audit can pin a known-stub capability here without code surgery.
_OVERRIDES: dict[str, str] = {}

# Harness verifications: capability id → {harness_id, last_verified}. Written ONLY by the
# V1 reality harness (`reality_harness.record_verification` → here); a green run promotes
# the derived state to VERIFIED. In-process (resets on boot) — durable cross-process
# promotion is V3's committed readiness snapshot, not this layer.
_VERIFICATIONS: dict[str, dict] = {}


def record_verification(cap_id: str, harness_id: str, ts: str, *, passed: bool) -> None:
    """Record a reality-harness verdict. A pass promotes to VERIFIED; a fail un-verifies.
    This is the ONLY promotion path to VERIFIED (set by the harness, never by hand)."""
    if passed:
        _VERIFICATIONS[cap_id] = {"harness_id": harness_id, "last_verified": ts}
    else:
        _VERIFICATIONS.pop(cap_id, None)


def clear_verifications() -> None:
    _VERIFICATIONS.clear()


@dataclass
class CapabilityRecord:
    id: str
    kind: str               # plugin | component | skill
    state: str              # SEAM | WIRED | VERIFIED | GA
    owner_agent: str = ""
    description: str = ""
    inputs: dict = field(default_factory=lambda: {"type": "object"})
    risk: str = "read_only"
    requires: tuple[str, ...] = ()
    supports: tuple[str, ...] = ()
    verification: str = ""
    rollback: str = ""
    confidence: float = 0.0
    implementation: str = ""
    contract_ref: str | None = None
    harness_id: str | None = None   # set by the V1 reality harness (none yet)
    last_verified: str | None = None
    detail: dict = field(default_factory=dict)


def set_override(cap_id: str, state: str) -> None:
    """Manually demote a capability. Refuses to set VERIFIED/GA — only the harness promotes."""
    if state not in (SEAM, WIRED):
        logger.warning("capability override ignored: %s=%s (only seam/wired allowed)", cap_id, state)
        return
    _OVERRIDES[cap_id] = state


def clear_override(cap_id: str) -> None:
    _OVERRIDES.pop(cap_id, None)


def _apply_verification(rec: CapabilityRecord) -> CapabilityRecord:
    """Promote to VERIFIED if a green harness verdict exists — but only for a rail that is
    at least WIRED (you can't verify a seam/absent capability)."""
    v = _VERIFICATIONS.get(rec.id)
    if v is not None and rec.state != SEAM:
        rec.state = VERIFIED
        rec.harness_id = v["harness_id"]
        rec.last_verified = v["last_verified"]
    return rec


def _apply_override(rec: CapabilityRecord) -> CapabilityRecord:
    """Manual demotion (applied last, so a human can pull a VERIFIED rail back down)."""
    ov = _OVERRIDES.get(rec.id)
    if ov is not None and _rank(ov) <= _rank(WIRED):
        rec.state = ov
    return rec


def _plugin_records() -> list[CapabilityRecord]:
    """Derive plugin capabilities from the static manifest registry (no orch needed)."""
    try:
        from agents.core.capability_manifests import plugin_capability_manifest
        from agents.core.plugin_gate import BUILTIN_PLUGINS
    except Exception:
        return []
    out = []
    for pid, m in sorted(BUILTIN_PLUGINS.items()):
        cap = plugin_capability_manifest(m)
        out.append(
            CapabilityRecord(
                id=f"plugin:{pid}",
                kind="plugin",
                state=WIRED if getattr(m, "enabled", True) else SEAM,
                owner_agent=(m.agents_served[0] if getattr(m, "agents_served", None) else ""),
                description=cap.description,
                inputs=cap.inputs,
                risk=cap.risk,
                requires=cap.requires,
                supports=cap.supports,
                verification=cap.verification,
                rollback=cap.rollback,
                confidence=cap.confidence,
                implementation=cap.implementation,
                detail={
                    "network_access": getattr(m.network_access, "value", str(m.network_access)),
                    "data_scope": getattr(m.data_scope, "value", str(m.data_scope)),
                    "agents_served": list(getattr(m, "agents_served", []) or []),
                },
            )
        )
    return out


def _action_records() -> list[CapabilityRecord]:
    """Derive executable action capabilities from the action-auth manifest layer."""
    from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS
    from agents.core.kernel.registry import ACTION_REGISTRY

    return [
        CapabilityRecord(
            id=manifest.id,
            kind="action",
            state=WIRED,
            description=manifest.description,
            inputs=manifest.inputs,
            risk=manifest.risk,
            requires=manifest.requires,
            supports=manifest.supports,
            verification=manifest.verification,
            rollback=manifest.rollback,
            confidence=manifest.confidence,
            implementation=manifest.implementation,
            contract_ref=manifest.contract_ref,
            detail={"action_kind": kind, "mediation": ACTION_REGISTRY[kind].value},
        )
        for kind, manifest in sorted(ACTION_CAPABILITY_MANIFESTS.items())
    ]


def _tool_records(orch) -> list[CapabilityRecord]:
    """Derive live ToolRPC capabilities only when registration declares identity."""
    server = getattr(orch, "tool_rpc", None)
    project = getattr(server, "tools", None)
    if not callable(project):
        return []
    from agents.core.capability_verification import tool_verification_ref

    out = []
    for tool in project():
        capability_id = tool.get("capability_id") if isinstance(tool, dict) else None
        if not isinstance(capability_id, str) or not capability_id:
            continue
        name = str(tool.get("name", ""))
        gated = bool(tool.get("gated"))
        out.append(
            CapabilityRecord(
                id=capability_id,
                kind="tool",
                state=WIRED,
                description=str(tool.get("description", "")),
                inputs=tool.get("input_schema") or {"type": "object"},
                risk="sensitive" if gated else "read_only",
                requires=("tool-rpc.registered", "action-kernel") if gated
                else ("tool-rpc.registered",),
                supports=("tool-rpc", "approval") if gated else ("tool-rpc", "inline"),
                verification=tool_verification_ref(name),
                rollback="tool-specific rollback required" if gated else "no mutation to roll back",
                confidence=0.0,
                implementation=f"agents.core.tool_rpc:{name}",
                detail={"tool": name, "gated": gated},
            )
        )
    return out


def _component_records(orch) -> list[CapabilityRecord]:
    """Derive component capabilities from the orchestrator's init-status registry."""
    reg = getattr(orch, "components", None)
    status = getattr(reg, "status", None) if reg is not None else None
    if not status:
        return []
    return [
        CapabilityRecord(
            id=f"component:{name}",
            kind="component",
            state=WIRED if s == "ok" else SEAM,
            description=f"Runtime component {name}.",
            risk="read_only",
            requires=("component.initialized",),
            supports=("readiness",),
            verification=f"reality-v1:component:{name}",
            rollback=f"disable component {name} and restart",
            confidence=0.0,
            implementation=f"orchestrator.components:{name}",
            detail={"init_status": s},
        )
        for name, s in sorted(status.items())
    ]


def _skill_records(orch) -> list[CapabilityRecord]:
    """Derive skill capabilities from the loaded skill set (loaded module ⇒ WIRED)."""
    loader = getattr(orch, "skills", None)
    skills = getattr(loader, "skills", None) if loader is not None else None
    if not skills:
        return []
    out = []
    for name, sk in sorted(skills.items()):
        agents = list(getattr(sk, "agents", []) or [])
        out.append(
            CapabilityRecord(
                id=f"skill:{name}",
                kind="skill",
                state=WIRED if getattr(sk, "module", None) is not None else SEAM,
                owner_agent=agents[0] if agents else "",
                description=f"Loaded skill {name}.",
                risk="sensitive",
                requires=("skill.loaded",),
                supports=("skill.invoke",),
                verification=f"reality-v1:skill:{name}",
                rollback=f"disable skill {name}",
                confidence=0.0,
                implementation=f"orchestrator.skills:{name}",
                detail={"trusted": bool(getattr(sk, "trusted", False)), "agents": agents},
            )
        )
    return out


def build_records(orch=None) -> list[CapabilityRecord]:
    """All capability records, overrides applied. Plugins derive statically; components
    and skills need a live orchestrator (omitted when *orch* is None). Each source is
    isolated so one failing registry can't blank the whole board."""
    records: list[CapabilityRecord] = []
    for source in (_plugin_records,
                   _action_records,
                   lambda: _tool_records(orch) if orch is not None else [],
                   lambda: _component_records(orch) if orch is not None else [],
                   lambda: _skill_records(orch) if orch is not None else []):
        try:
            records.extend(source())
        except Exception:  # pragma: no cover - a broken registry must not 500 the board
            logger.warning("capability source failed", exc_info=True)
    unique: dict[str, CapabilityRecord] = {}
    for record in records:
        if record.id in unique:
            logger.warning("duplicate capability id ignored: %s", record.id)
            continue
        unique[record.id] = record
    # Order matters: derive → promote-if-harness-verified → manual demote wins last.
    return [_apply_override(_apply_verification(r)) for r in unique.values()]


def snapshot(orch=None) -> dict:
    """Board-ready view: records + roll-ups + the honest ``harness_pending`` flag.

    ``by_state`` / ``by_kind`` are counts; ``harness_pending`` is True while no capability
    is VERIFIED (i.e. the V1 reality harness has yet to promote anything) — the board renders
    that as "wired, not yet proven" rather than implying verification we can't back."""
    records = build_records(orch)
    by_state: dict[str, int] = dict.fromkeys(_ORDER, 0)
    by_kind: dict[str, int] = {}
    for r in records:
        by_state[r.state] = by_state.get(r.state, 0) + 1
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
    return {
        "capabilities": [asdict(r) for r in records],
        "total": len(records),
        "by_state": by_state,
        "by_kind": by_kind,
        "harness_pending": by_state.get(VERIFIED, 0) == 0 and by_state.get(GA, 0) == 0,
    }
