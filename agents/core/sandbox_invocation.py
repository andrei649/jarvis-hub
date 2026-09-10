"""K0: who a sandboxed script *is*, resolved by the host and fixed for its lifetime.

The sandbox bridge could already refuse a tool that is not on the allowlist, refuse
to execute a gated one, and scrub secrets out of every response. What it could not do
is say **on whose authority** a call from inside the sandbox was made. It called
``ToolRPCServer.handle({"tool": …, "args": …})`` with no actor, and the server falls
back to its own default agent — so an inner call was attributed to ``jarvis`` no
matter who started the run, and the inner reach was the whole registered allowlist
rather than the set the outer turn was actually offered.

That is a **missing contract, not a demonstrated bypass**. The only way in is
``POST /sandbox/execute``, which is behind ``user_guard`` and refuses unless
``DEV_MODE`` is on. Nothing here fixes a hole that was open to the world; it supplies
the authority binding that has to exist *before* `execute_code` can be offered to a
model at all, which is why K0 comes before K1.

The binding has four properties, and each one is a refusal the tests pin:

* **Server-resolved.** ``bind`` takes the live principal and origin and resolves the
  offered set itself, from the registry and the profile. A caller cannot pass in an
  identity or a wider tool set — there is no parameter for either. That is what makes
  a forged authority impossible rather than merely detected.
* **Immutable.** The dataclass is frozen. A run's authority is decided once, at the
  top, and no later call can widen it.
* **Bounded in time.** It expires. A sandbox process that outlives its authority
  cannot keep calling tools, and expiry is checked per call rather than at the start.
* **Intersecting, never widening.** An inner call must be in the offered set *and*
  still registered. The profile that narrowed the outer turn narrows the inner one by
  construction, so code cannot reach a tool the model itself was not shown.

Every refusal happens **before** ``handle`` runs — before a read executes and before
a gated call can enqueue an approval task. A gate that fires after the read is not a
gate, and an approval card the owner never asked for is its own harm.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from .tool_profiles import ProfileDecision, classify_turn, resolve_tools

#: A run's authority outlives a normal script but not a forgotten container.
DEFAULT_LIFETIME_SECONDS = 900.0
MAX_LIFETIME_SECONDS = 3600.0

AUTHORITY_MISSING = "authority_missing"
AUTHORITY_EXPIRED = "authority_expired"
AUTHORITY_REVOKED = "authority_revoked"
TOOL_NOT_OFFERED = "tool_not_offered"
TOOL_NOT_REGISTERED = "tool_not_registered"


class InvocationRefused(Exception):
    """A bounded reason code. Never carries the tool's arguments or a caller's text."""

    def __init__(self, reason: str, tool: str = "") -> None:
        self.reason = reason
        self.tool = tool
        super().__init__(reason)

    def as_response(self) -> dict:
        """The shape the sandbox shim already understands for a refusal."""
        return {"ok": False, "reason": self.reason, "tool": self.tool}


@dataclass(frozen=True, slots=True)
class SandboxInvocation:
    """One sandbox run's authority. Frozen: decided at the top, never widened."""

    agent: str
    surface: str
    principal: str
    session_id: str
    origin: str
    offered: frozenset[str]
    data_scope: frozenset[str] | None
    issued_at: float
    expires_at: float
    withheld: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict:
        """An owner-readable projection. Carries names and ids, never a tool's args."""
        return {
            "agent": self.agent, "surface": self.surface, "principal": self.principal,
            "session_id": self.session_id, "origin": self.origin,
            "offered_tools": sorted(self.offered),
            "withheld_tools": list(self.withheld),
            "data_scope": None if self.data_scope is None else sorted(self.data_scope),
            "issued_at": self.issued_at, "expires_at": self.expires_at,
        }

    def expired(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) >= self.expires_at

    def authorize(self, tool: str, *, registered: Callable[[str], bool] | None = None,
                  now: float | None = None, revoked: Callable[[], bool] | None = None) -> None:
        """Refuse before the call reaches the server, or return quietly.

        The order is the contract: lifetime first, then revocation, then the offer,
        then the live registry. A tool that was offered at bind time but has since
        been unregistered is refused too — the offer is a ceiling, not a promise.

        ``registered`` is a predicate (``ToolRPCServer.allows``) rather than a list,
        so the check costs a dict lookup instead of a copy of every tool schema on
        every call the sandbox makes.
        """
        if self.expired(now):
            raise InvocationRefused(AUTHORITY_EXPIRED, tool)
        if revoked is not None:
            try:
                gone = bool(revoked())
            except Exception:
                gone = True  # an unreadable revocation state is a revoked one
            if gone:
                raise InvocationRefused(AUTHORITY_REVOKED, tool)
        if tool not in self.offered:
            raise InvocationRefused(TOOL_NOT_OFFERED, tool)
        if registered is not None:
            try:
                live = bool(registered(tool))
            except Exception:
                live = False  # an unreadable registry offers nothing
            if not live:
                raise InvocationRefused(TOOL_NOT_REGISTERED, tool)


def bind(
    *,
    tools: Sequence[Mapping[str, object]],
    agent: str,
    principal: object = None,
    origin: str = "",
    session_id: str = "",
    settings: Callable[[str, object], object] = lambda key, default: default,
    agent_patterns: Sequence[str] | None = None,
    data_scope: Sequence[str] | None = None,
    lifetime_seconds: float = DEFAULT_LIFETIME_SECONDS,
    now: Callable[[], float] = time.time,
) -> tuple[SandboxInvocation, ProfileDecision]:
    """Resolve one run's authority from live host state.

    There is deliberately no parameter for "the offered set" or "the identity to act
    as": both are computed here from the principal the caller was already
    authenticated as, so a request body cannot name either. ``tools`` is the live
    registry metadata, and the posture narrows it exactly as it narrows a model turn.
    """
    posture = classify_turn(principal, origin)
    offered_rows, withheld = resolve_tools(
        tools, posture=posture, agent_patterns=agent_patterns, settings=settings,
    )
    offered = frozenset(str(row.get("name") or "") for row in offered_rows) - {""}
    issued = float(now())
    lifetime = max(1.0, min(float(lifetime_seconds), MAX_LIFETIME_SECONDS))
    invocation = SandboxInvocation(
        agent=str(agent or "").strip() or "jarvis",
        surface=posture.surface,
        principal=posture.principal,
        session_id=str(session_id or ""),
        origin=str(origin or ""),
        offered=offered,
        data_scope=None if data_scope is None else frozenset(str(s) for s in data_scope),
        issued_at=issued,
        expires_at=issued + lifetime,
        withheld=tuple(withheld),
    )
    return invocation, ProfileDecision(
        surface=posture.surface, principal=posture.principal,
        offered=tuple(sorted(offered)), withheld=tuple(withheld),
    )


__all__ = [
    "AUTHORITY_EXPIRED", "AUTHORITY_MISSING", "AUTHORITY_REVOKED",
    "DEFAULT_LIFETIME_SECONDS", "InvocationRefused", "MAX_LIFETIME_SECONDS",
    "SandboxInvocation", "TOOL_NOT_OFFERED", "TOOL_NOT_REGISTERED", "bind",
]
