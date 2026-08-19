"""registry.py — the action-auth mediation registry (ORIZONT-24 Gate K seed).

Routes have a runtime registry (``app.routes``) that ``test_route_auth_matrix``
introspects; privileged **actions** do not, and AST-scanning call sites is
fragile. So we mirror the route-auth pattern with a registry whose *enumeration*
is runtime-derived (broker ``KIND`` constants) and whose *classification* is
curated + snapshotted:

  * ``known_broker_action_kinds()`` reads the brokers' own ``KIND`` / ``KIND_PREFIX``
    — a new broker surfaces here automatically, so it can't be added unclassified.
  * ``ACTION_REGISTRY`` pins each kind to a ``Mediation`` state, snapshotted in
    ``tests/_snapshots/action_auth.json`` and gated by ``tests/test_action_auth_matrix.py``.

As waves K1→K4 land, entries move ``PENDING_KERNEL → KERNEL``; the honest-pending
test makes that shrinkage CI-visible (the SEC-3 → empty-``PENDING_GUARD`` discipline).
"""

from __future__ import annotations

from enum import StrEnum


class Mediation(StrEnum):
    KERNEL = "kernel"                  # routed through kernel.authorize
    INTENTIONALLY_DIRECT = "direct"    # safe by design — never needs the kernel
    PENDING_KERNEL = "pending"         # not-yet-migrated; the shrinking debt set


# Curated classification. Wave-1 wires the 4 TaskQueue-backed brokers below;
# everything else is PENDING_KERNEL until its wave lands (see the design spec's
# migration order: brokers → plugin egress → MCP+KG → admin routes).
ACTION_REGISTRY: dict[str, Mediation] = {
    # Wave 1 — kernel-mediated.
    "node.dispatch": Mediation.KERNEL,
    "call.outbound": Mediation.KERNEL,
    "social.*": Mediation.KERNEL,
    "writeback.*": Mediation.KERNEL,
    # Payment micro-wave — admissible requests routed through kernel.authorize
    # (a DENY blocks before the payment becomes pending; PaymentBroker carries a
    # `kernel` hook, bound in web.py via kernel.binding.make_action_kernel).
    "payment": Mediation.KERNEL,
    # Wave 2 — policy-passing plugin egress is mediated by the kernel via an injected
    # hook in http_client (a DENY blocks otherwise-allowed egress: kill-switch / budget /
    # loop). The B3 strict-egress-downgrade audit landed earlier; this is the routing half.
    "plugin.egress": Mediation.KERNEL,
    # Wave 3 (in progress) — MCP mutating tools route through kernel.authorize after
    # the per-identity gate (a DENY blocks the write: kill-switch / budget / loop).
    "mcp.mutating": Mediation.KERNEL,
    # Owner-authorized local-model autonomy. Chat/MCP start-load-unload requests
    # fail closed unless the kernel is enabled and explicitly GRANTs this
    # reversible host effect; identity/contract/audit gates wrap the same call.
    "host.control": Mediation.KERNEL,
    # Wave 3 — a gated Tool-RPC call is mediated by the kernel before it can enqueue
    # an approval task (a DENY blocks it: kill-switch / budget / loop).
    "tool.rpc": Mediation.KERNEL,
    # R1 residual hardening — an external GitHub trigger asking Oracle to pull/rebase
    # and run tests is host execution. It is default-refused when the kernel is off,
    # and when enabled it crosses kernel.authorize before any git/pytest subprocess.
    "repo.sync": Mediation.KERNEL,
    # Wave 4a/4b — admin escalations cross the kernel front door (in addition to admin_guard):
    # engaging a halt and minting a capability are mediated; a capability token is now
    # MANDATORY (kernel.TOKEN_MANDATORY_KINDS) — the router mints one for an already-
    # admin_guard-authenticated caller when none is presented, so the kernel's real
    # capability nucleus runs instead of tolerating an empty token. (Disengage is NOT
    # mediated — it must always be able to release a halt.)
    "admin.kill_switch": Mediation.KERNEL,
    "admin.capability_issue": Mediation.KERNEL,
    # Wave 3/4b — externally-driven KG writes (the /api/kg/* mutating HTTP handlers) are
    # mediated with a MANDATORY capability token (kernel.TOKEN_MANDATORY_KINDS); the
    # high-frequency *internal* ingestion path (incremental.ingest from
    # _record_interactions, seed_graph, reflection) writes graph methods directly and is
    # NOT gated (a halt must not freeze per-turn memory). Memory.remember (vector write),
    # /consolidate (plan-only) and /decay/forget (ACT-R op) are not KG writes → out of scope.
    "kg.write": Mediation.KERNEL,
    # ORIZONT 29 wave 1 — the Media Director's present() capability is mediated at
    # the CapabilityActionAPI facade (reversible tier; contract-gated before the
    # kernel; NullMediaDriver default until the owner wires real device drivers).
    "media.present": Mediation.KERNEL,
    # Restore can stop playback or replay a previous session, so it is a distinct
    # privileged action and crosses the same facade/kernel boundary as present().
    "media.restore": Mediation.KERNEL,
    # ORIZONT 28 — any optional real desktop host driver crosses the unified
    # action facade immediately before actuation. Null/manual offline drivers
    # keep their legacy direct path; a requires_kernel driver cannot use it.
    "desktop.step": Mediation.KERNEL,
    # ORIZONT 30 — every Home Assistant mutation crosses the unified facade.
    # Security control retains an owner-confirmation floor; recovery is separate
    # so a halt or policy change can refuse compensation honestly.
    "house.control": Mediation.KERNEL,
    "house.security_control": Mediation.KERNEL,
    "house.recovery": Mediation.KERNEL,
    # Safe Comms — a governed reply to a live channel inbox thread crosses the
    # kernel at request time (ChannelReplyBroker); a GRANT lifts the draft from
    # ask→act, a DENY refuses before the approval queue sees it (GAP-3).
    "channel.reply": Mediation.KERNEL,
    # ORIZONT 32 — installing an acquired capability crosses the kernel before a
    # PromotionProposal exists (make_skill_install_kernel_gate); even a kernel
    # GRANT cannot bypass the permanent owner-approval floor (GAP-3).
    "skill.install": Mediation.KERNEL,
}


def known_broker_action_kinds() -> set[str]:
    """The privileged action kinds owned by the in-process brokers, read from
    their own ``KIND`` / ``KIND_PREFIX`` constants. A new broker added without a
    classification in ``ACTION_REGISTRY`` makes ``test_action_auth_matrix`` fail.

    Imports are lazy so the registry module stays cheap and cycle-free.
    """
    kinds: set[str] = set()
    from ..node_mesh import KIND as NODE_KIND
    kinds.add(NODE_KIND)
    from ..autonomy.call_broker import CallBroker
    kinds.add(CallBroker.KIND)
    from ..social import SocialBroker
    kinds.add(SocialBroker.KIND_PREFIX + "*")
    from ..writeback import WriteBackBroker
    kinds.add(WriteBackBroker.KIND_PREFIX + "*")
    from ..payments import PaymentBroker
    kinds.add(getattr(PaymentBroker, "KIND", "payment"))
    from ..channel_reply import CHANNEL_REPLY_TASK_KIND
    kinds.add(CHANNEL_REPLY_TASK_KIND)
    from ..skills.marketplace import SKILL_INSTALL_CONTRACT_KIND
    kinds.add(SKILL_INSTALL_CONTRACT_KIND)
    return kinds


def classify(kind: str) -> Mediation | None:
    """Classify a concrete action kind: exact match, else a ``prefix.*`` pattern."""
    if kind in ACTION_REGISTRY:
        return ACTION_REGISTRY[kind]
    for pat, med in ACTION_REGISTRY.items():
        if pat.endswith(".*") and kind.startswith(pat[:-1]):
            return med
    return None
