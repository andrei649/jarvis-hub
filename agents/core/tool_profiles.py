"""tool_profiles.py — least privilege at the moment of *offering* (Hermes absorption 3b).

Mediation happened only at the moment of execution: every agent on every surface was
*offered* the whole ToolRPC allowlist, ``desktop_run`` and ``terminal_run`` included — a
Telegram guest's turn, a heartbeat's turn and the owner's HUD turn saw the same list. A
gated tool could not run without approval, but a guest could still make the model propose
it, and every proposal is a card in the owner's inbox. Least privilege means the tool is
not even on the table.

A profile is resolved before the tools are offered, keyed by **agent × surface ×
principal**, and a call to a tool outside it is refused as ``tool_not_allowed`` before it
reaches the server — the same refusal an unregistered tool gets.

Surfaces (from the channel the turn's principal was bound with, else from the action
origin):

* ``operator`` — the owner's own doors: the web HUD and the local voice loop;
* ``inbound`` — any external channel (Telegram, WhatsApp, email, the widget, …), or a turn
  whose action origin is already ``inbound``;
* ``internal`` — no human in the turn: heartbeats, jobs, workflows, evaluations.

Principals: ``owner`` (the turn's principal is admin), ``guest`` (a channel principal that
is not the owner — a household member with a user token, an unknown Telegram sender the
pairing gate admitted, a group member), ``system`` (no principal bound at all).

Default postures — the *gated* tools (``register_tool(gated=True)``: external or mutating,
approval-bound) are the actuation class:

=================  ======================================================================
operator / owner   every registered tool
operator / guest   ungated tools only
inbound / owner    ungated tools; gated ones too when ``llm.inbound_actuation`` is on
inbound / guest    the names in ``llm.guest_tools`` (default ``echo``, ``time``), never gated
internal / system  ungated tools; gated ones too when ``llm.internal_actuation`` is on
=================  ======================================================================

A per-agent ``tools:`` list in ``agents.yaml`` (names or glob patterns; ``"*"`` = all)
narrows the posture further and never widens it. The resolved sets are snapshot-tested in
``tests/_snapshots/tool_profiles.json`` the way ``route_auth.json`` pins route guards, so a
tool quietly reaching a surface it should not is a failing test, not a surprise.

Fails closed: an unreadable setting, an unknown surface or a resolver error offers nothing.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agents.core.action_origin import (
    INBOUND_ACTION_ORIGIN,
    OPERATOR_TURN_CHANNELS,
    TRUSTED_TURN_CHANNELS,
    current_action_origin,
)

SURFACE_OPERATOR = "operator"
SURFACE_INBOUND = "inbound"
SURFACE_INTERNAL = "internal"
PRINCIPAL_OWNER = "owner"
PRINCIPAL_GUEST = "guest"
PRINCIPAL_SYSTEM = "system"

GUEST_TOOLS_SETTING = "llm.guest_tools"
INBOUND_ACTUATION_SETTING = "llm.inbound_actuation"
INTERNAL_ACTUATION_SETTING = "llm.internal_actuation"
DEFAULT_GUEST_TOOLS: tuple[str, ...] = ("echo", "time")

# Every posture the resolver can produce, in snapshot order.
POSTURES: tuple[tuple[str, str], ...] = (
    (SURFACE_OPERATOR, PRINCIPAL_OWNER),
    (SURFACE_OPERATOR, PRINCIPAL_GUEST),
    (SURFACE_INBOUND, PRINCIPAL_OWNER),
    (SURFACE_INBOUND, PRINCIPAL_GUEST),
    (SURFACE_INTERNAL, PRINCIPAL_SYSTEM),
)

_UNBOUND_CHANNELS = frozenset({"", "unknown"})
MAX_AGENT_PATTERNS = 64
MAX_PATTERN_CHARS = 64


@dataclass(frozen=True)
class ToolPosture:
    surface: str
    principal: str

    @property
    def key(self) -> str:
        return f"{self.surface}/{self.principal}"


@dataclass(frozen=True)
class ProfileDecision:
    """What a resolution offered and withheld, for the event feed and the audit trail."""

    surface: str
    principal: str
    offered: tuple[str, ...]
    withheld: tuple[str, ...]


def classify_turn(principal: Any, origin: str | None = None) -> ToolPosture:
    """The posture of the current turn from its principal and its action origin.

    A principal bound with an external channel — or any turn whose origin is already
    ``inbound`` — is on the inbound surface, owner or not. A principal bound with ``web`` or
    ``voice`` is on the operator surface. No principal (a heartbeat, a job, a workflow) is
    the internal surface with the system principal. Anything a surface cannot place is a
    guest on it, never more.
    """
    channel = str(getattr(principal, "channel", "") or "").strip().lower()
    admin = bool(getattr(principal, "admin", False))
    bound = channel not in _UNBOUND_CHANNELS
    origin_text = str(origin or "").strip().lower()
    if origin_text == INBOUND_ACTION_ORIGIN or (bound and channel not in TRUSTED_TURN_CHANNELS):
        surface = SURFACE_INBOUND
    elif bound and channel in OPERATOR_TURN_CHANNELS:
        surface = SURFACE_OPERATOR
    else:
        surface = SURFACE_INTERNAL
    if surface == SURFACE_INTERNAL:
        # A bound principal on an internal channel (a builder or workflow turn started by
        # the owner) is still a turn without a human at the keyboard for the tool loop's
        # purposes: same posture as the heartbeat.
        kind = PRINCIPAL_SYSTEM
    elif admin:
        kind = PRINCIPAL_OWNER
    else:
        kind = PRINCIPAL_GUEST
    return ToolPosture(surface, kind)


def _flag(settings: Callable[[str, Any], Any], key: str) -> bool:
    try:
        return settings(key, False) is True
    except Exception:
        return False


def guest_tool_names(settings: Callable[[str, Any], Any]) -> tuple[str, ...]:
    """The bounded, string-only allowlist a guest may be offered (default ``echo``, ``time``)."""
    try:
        raw = settings(GUEST_TOOLS_SETTING, list(DEFAULT_GUEST_TOOLS))
    except Exception:
        return ()
    if not isinstance(raw, (list, tuple)):
        return ()
    names = tuple(
        item.strip() for item in raw
        if isinstance(item, str) and item.strip() and len(item) <= MAX_PATTERN_CHARS
    )
    return names[:MAX_AGENT_PATTERNS]


def _posture_allows(
    posture: ToolPosture, tool: Mapping[str, Any], settings: Callable[[str, Any], Any],
    guest_names: tuple[str, ...],
) -> bool:
    gated = bool(tool.get("gated"))
    name = str(tool.get("name") or "")
    if posture.surface == SURFACE_OPERATOR:
        if posture.principal == PRINCIPAL_OWNER:
            return True
        return not gated
    if posture.surface == SURFACE_INBOUND:
        if posture.principal == PRINCIPAL_OWNER:
            return (not gated) or _flag(settings, INBOUND_ACTUATION_SETTING)
        return (not gated) and name in guest_names
    if posture.surface == SURFACE_INTERNAL:
        return (not gated) or _flag(settings, INTERNAL_ACTUATION_SETTING)
    return False


def _clean_patterns(patterns: Sequence[str] | None) -> tuple[str, ...] | None:
    """``None`` means unrestricted; anything malformed narrows to nothing (fail closed)."""
    if patterns is None:
        return None
    if not isinstance(patterns, (list, tuple)):
        return ()
    out = [
        item.strip() for item in patterns
        if isinstance(item, str) and item.strip() and len(item) <= MAX_PATTERN_CHARS
    ]
    return tuple(out[:MAX_AGENT_PATTERNS])


def resolve_tools(
    tools: Sequence[Mapping[str, Any]],
    *,
    posture: ToolPosture,
    agent_patterns: Sequence[str] | None = None,
    settings: Callable[[str, Any], Any] = lambda key, default: default,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Split *tools* (ToolRPC metadata rows) into the ones this posture offers and the
    names it withholds. The agent's own patterns can only narrow the posture."""
    guest_names = guest_tool_names(settings)
    patterns = _clean_patterns(agent_patterns)
    offered: list[Mapping[str, Any]] = []
    withheld: list[str] = []
    for tool in tools:
        name = str(tool.get("name") or "")
        allowed = _posture_allows(posture, tool, settings, guest_names)
        if allowed and patterns is not None:
            allowed = any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
        if allowed:
            offered.append(tool)
        else:
            withheld.append(name)
    return offered, withheld


class ToolProfileResolver:
    """The hook the tool runtime calls with ``(agent_id, tools)`` before offering tools.

    ``principal`` and ``origin`` are read per call so the posture is the *current* turn's;
    ``agent_patterns`` maps an agent id to its ``tools:`` list (``None`` = unrestricted).
    """

    def __init__(
        self,
        *,
        settings: Callable[[str, Any], Any],
        agent_patterns: Callable[[str], Sequence[str] | None] = lambda agent_id: None,
        principal: Callable[[], Any] = lambda: None,
        origin: Callable[[], str] = current_action_origin,
    ) -> None:
        self._settings = settings
        self._agent_patterns = agent_patterns
        self._principal = principal
        self._origin = origin

    def posture(self) -> ToolPosture:
        try:
            principal = self._principal()
        except Exception:
            principal = None
        try:
            origin = self._origin()
        except Exception:
            origin = INBOUND_ACTION_ORIGIN
        return classify_turn(principal, origin)

    def __call__(
        self, agent_id: str, tools: Sequence[Mapping[str, Any]],
    ) -> tuple[list[Mapping[str, Any]], ProfileDecision]:
        posture = self.posture()
        try:
            patterns = self._agent_patterns(agent_id)
        except Exception:
            patterns = ()
        offered, withheld = resolve_tools(
            tools, posture=posture, agent_patterns=patterns, settings=self._settings,
        )
        return offered, ProfileDecision(
            surface=posture.surface,
            principal=posture.principal,
            offered=tuple(str(tool.get("name") or "") for tool in offered),
            withheld=tuple(withheld),
        )


__all__ = [
    "DEFAULT_GUEST_TOOLS", "GUEST_TOOLS_SETTING", "INBOUND_ACTUATION_SETTING",
    "INTERNAL_ACTUATION_SETTING", "POSTURES", "PRINCIPAL_GUEST", "PRINCIPAL_OWNER",
    "PRINCIPAL_SYSTEM", "ProfileDecision", "SURFACE_INBOUND", "SURFACE_INTERNAL",
    "SURFACE_OPERATOR", "ToolPosture", "ToolProfileResolver", "classify_turn",
    "guest_tool_names", "resolve_tools",
]
