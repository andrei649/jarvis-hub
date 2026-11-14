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
inbound / guest    the names in ``llm.guest_tools`` (default ``echo``, ``time``, ``todo``), never
                   gated
internal / system  ungated tools; gated ones too when ``llm.internal_actuation`` is on
=================  ======================================================================

The **session-scoped** tools (:data:`SESSION_SCOPED_TOOLS`, today ``todo``, H315) keep
state per session. A turn that binds no session of its own runs on the shared default
session, the HUD's, so what they keep there is the owner's. On it, only an owner's turn
is offered them. A guest, a household member or a job there gets nothing (the resolver's
``shared_session``), and the tool refuses a call anyway. On a session of its own, a turn
is offered them by the rows above: ``todo`` is ungated, and it reaches an inbound guest
through the default ``llm.guest_tools``, so an owner who empties that list keeps guests
off the tool loop entirely. The rule for every tool the Hermes rows add (critic note 22):
a tool that acts on the owner's HUD, memory or skills (a canvas pointer, a memory write, a
skill body) stays off inbound/guest unless the owner names it in ``llm.guest_tools``;
``speak`` is gated and follows the gated rows of the table. The **owner-operator** tools
(:data:`OWNER_OPERATOR_TOOLS`: ``memory``, H314, and ``delegate_task``, H400) are stricter
still: they are offered to operator/owner only, whatever ``llm.guest_tools`` says.

A **third-party MCP tool** (a ``mcp__<server>__<tool>`` row the H557 bridge registers) is
ungated only on its server's own ``readOnlyHint``, which the MCP spec calls untrusted. So
off operator/owner it is never offered by default: an operator guest gets one only when
``llm.guest_tools`` names it (as an inbound guest already does), and a job only when
``llm.internal_actuation`` is on. Inbound/owner keeps the table's row: the owner is in the
turn.

A per-agent ``tools:`` list in ``agents.yaml`` (names or glob patterns; ``"*"`` = all)
narrows the posture further and never widens it. The resolved sets are snapshot-tested in
``tests/_snapshots/tool_profiles.json`` the way ``route_auth.json`` pins route guards, so a
tool quietly reaching a surface it should not is a failing test, not a surprise.

Fails closed: an unreadable setting, an unknown surface or a resolver error offers nothing.
"""

from __future__ import annotations

import fnmatch
import os
import threading
import time
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
DEFAULT_GUEST_TOOLS: tuple[str, ...] = ("echo", "time", "todo")
#: H400 — the model's sub-agent tool and the switch it is offered under (read per offer).
DELEGATE_TOOL = "delegate_task"
DELEGATE_SETTING = "llm.delegate_task"
#: The model-facing prefix of a bridged third-party MCP tool (H557).
MCP_TOOL_PREFIX = "mcp__"

# Every posture the resolver can produce, in snapshot order.
POSTURES: tuple[tuple[str, str], ...] = (
    (SURFACE_OPERATOR, PRINCIPAL_OWNER),
    (SURFACE_OPERATOR, PRINCIPAL_GUEST),
    (SURFACE_INBOUND, PRINCIPAL_OWNER),
    (SURFACE_INBOUND, PRINCIPAL_GUEST),
    (SURFACE_INTERNAL, PRINCIPAL_SYSTEM),
)

_UNBOUND_CHANNELS = frozenset({"", "unknown"})
#: Tools that keep state per session (H315). On the shared default session that state is
#: the owner's, so there they are offered to an owner's turn only (see the docstring).
SESSION_SCOPED_TOOLS: frozenset[str] = frozenset({"todo"})
#: Tools that write what the owner keeps (H314: ``memory``) or start further model runs on
#: the owner's hub (H400: ``delegate_task``). Offered to the owner at the operator surface
#: only: not to a guest, not to an inbound turn (a channel message is untrusted input), not
#: to a job, and not through ``llm.guest_tools`` either.
OWNER_OPERATOR_TOOLS: frozenset[str] = frozenset({"memory", "delegate_task"})
MAX_AGENT_PATTERNS = 64
MAX_PATTERN_CHARS = 64

#: H295 — per-tool backend availability probe TTL and transient-failure grace window.
CHECK_FN_TTL_SECONDS = 30.0
LAST_KNOWN_GOOD_GRACE_SECONDS = 60.0


def no_cache_check_fn(fn: Callable[[], bool]) -> Callable[[], bool]:
    """Mark a per-tool ``check_fn`` as uncached so every offer re-evaluates it live."""
    fn._no_cache_check_fn = True  # type: ignore[attr-defined]
    return fn


def _check_scope_key(env: Mapping[str, str] | None = None) -> str:
    environ = env if env is not None else os.environ
    home = (
        environ.get("NERVA_HOME")
        or environ.get("JARVIS_HOME")
        or environ.get("HERMES_HOME")
        or environ.get("JARVIS_MEMORY_DIR")
        or ""
    )
    profile = environ.get("NERVA_PROFILE") or environ.get("JARVIS_PROFILE") or "default"
    return f"{home}::{profile}"


@dataclass
class _CheckCacheEntry:
    value: bool
    checked_at: float
    last_good_at: float | None = None


class CheckFnCache:
    """TTL + last-known-good cache for per-tool backend availability probes (H295).

    * Positive/negative probe verdicts are cached for ``ttl_seconds`` (~30 s) per
      ``(scope_key, tool_name)`` so per-turn tool resolution never hammers Docker/CLI
      subprocesses.
    * When a tool was previously observed healthy (``last_good_at``), a transient probe
      failure or exception after TTL expiry continues offering the tool during
      ``grace_seconds`` (~60 s from ``last_good_at``) so an in-flight multi-turn session
      does not lose its tool mid-task on a brief daemon hiccup.
    * Tools that have *never* probed healthy (e.g. ``execute_code`` on a host without
      Docker or WASM) immediately withhold on ``False``, disappearing from the turn's
      offer rather than failing at call time with ``sandbox_not_isolated``.
    * Callables decorated with :func:`no_cache_check_fn` or calls with ``bypass=True``
      evaluate live without reading or populating the TTL cache.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = CHECK_FN_TTL_SECONDS,
        grace_seconds: float = LAST_KNOWN_GOOD_GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        scope: Callable[[], str] = _check_scope_key,
    ) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.grace_seconds = max(0.0, float(grace_seconds))
        self._clock = clock
        self._scope = scope
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], _CheckCacheEntry] = {}

    @staticmethod
    def _probe(fn: Callable[[], bool]) -> bool:
        try:
            return bool(fn())
        except Exception:
            return False

    def check(self, tool_name: str, fn: Callable[[], bool], *, bypass: bool = False) -> bool:
        if bypass or bool(getattr(fn, "_no_cache_check_fn", False)):
            return self._probe(fn)
        now = float(self._clock())
        key = (self._scope(), str(tool_name))
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and (now - entry.checked_at) < self.ttl_seconds:
                if entry.value:
                    return True
                return (
                    entry.last_good_at is not None
                    and (now - entry.last_good_at) < self.grace_seconds
                )

        # Probe outside the lock so a slow backend check never blocks other turns.
        ok = self._probe(fn)
        now_after = float(self._clock())
        with self._lock:
            prev = self._entries.get(key)
            if ok:
                self._entries[key] = _CheckCacheEntry(
                    value=True, checked_at=now_after, last_good_at=now_after
                )
                return True
            last_good = prev.last_good_at if prev is not None else None
            self._entries[key] = _CheckCacheEntry(
                value=False, checked_at=now_after, last_good_at=last_good
            )
            return bool(last_good is not None and (now_after - last_good) < self.grace_seconds)

    def invalidate(self, tool_name: str | None = None) -> None:
        with self._lock:
            if tool_name is None:
                self._entries.clear()
                return
            target = str(tool_name)
            self._entries = {k: v for k, v in self._entries.items() if k[1] != target}


DEFAULT_CHECK_FN_CACHE = CheckFnCache()


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
    """The bounded, string-only allowlist a guest may be offered (default ``echo``, ``time``,
    ``todo``)."""
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
    third_party = name.startswith(MCP_TOOL_PREFIX)
    if posture.surface == SURFACE_OPERATOR:
        if posture.principal == PRINCIPAL_OWNER:
            return True
        if third_party:
            # "Ungated" rests on the server's own readOnlyHint: a guest gets it only
            # when the owner names it.
            return (not gated) and name in guest_names
        return not gated
    if posture.surface == SURFACE_INBOUND:
        if posture.principal == PRINCIPAL_OWNER:
            return (not gated) or _flag(settings, INBOUND_ACTUATION_SETTING)
        return (not gated) and name in guest_names
    if posture.surface == SURFACE_INTERNAL:
        if third_party:
            return _flag(settings, INTERNAL_ACTUATION_SETTING)
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
    shared_session: bool = False,
    check_fns: Mapping[str, Callable[[], bool]] | None = None,
    check_cache: CheckFnCache | None = None,
    bypass_check_cache: bool = False,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Split *tools* (ToolRPC metadata rows) into the ones this posture offers and the
    names it withholds. The agent's own patterns can only narrow the posture.
    ``shared_session`` says the turn runs on the shared default session: there the
    session-scoped tools are the owner's, so a turn that is not the owner's is not offered
    them. ``check_fns`` (H295) probes per-tool backend availability with ~30 s TTL caching
    and a ~60 s last-known-good grace window."""
    from .job_toolsets import allows
    guest_names = guest_tool_names(settings)
    patterns = _clean_patterns(agent_patterns)
    owners_only = shared_session and posture.principal != PRINCIPAL_OWNER
    cache = check_cache if check_cache is not None else DEFAULT_CHECK_FN_CACHE
    offered: list[Mapping[str, Any]] = []
    withheld: list[str] = []
    for tool in tools:
        name = str(tool.get("name") or "")
        allowed = allows(name) and _posture_allows(posture, tool, settings, guest_names)
        if allowed and name == DELEGATE_TOOL:
            # H400 (M1): the owner's switch is read at every offer, not only at boot.
            allowed = _flag(settings, DELEGATE_SETTING)
        if allowed and name.startswith("kanban_"):
            from .kanban.runtime import offer_allowed
            allowed = offer_allowed(
                name, posture.key, _flag(settings, "llm.kanban"),
                network_enabled=_flag(settings, "llm.kanban_network_attachments"),
            )
        if allowed and owners_only and name in SESSION_SCOPED_TOOLS:
            allowed = False
        if allowed and name in OWNER_OPERATOR_TOOLS and posture.key != f"{SURFACE_OPERATOR}/{PRINCIPAL_OWNER}":
            allowed = False
        if allowed and patterns is not None:
            allowed = any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
        if allowed and check_fns is not None and name in check_fns:
            probe_fn = check_fns[name]
            if callable(probe_fn):
                allowed = cache.check(name, probe_fn, bypass=bypass_check_cache)
            else:
                allowed = False
        if allowed:
            offered.append(tool)
        else:
            withheld.append(name)
    return offered, withheld


class ToolProfileResolver:
    """The hook the tool runtime calls with ``(agent_id, tools)`` before offering tools.

    ``principal`` and ``origin`` are read per call so the posture is the *current* turn's;
    ``agent_patterns`` maps an agent id to its ``tools:`` list (``None`` = unrestricted);
    ``shared_session`` says whether the turn runs on the shared default session (read per
    call; a getter that fails counts as yes, and so does a resolver built without one).
    """

    def __init__(
        self,
        *,
        settings: Callable[[str, Any], Any],
        agent_patterns: Callable[[str], Sequence[str] | None] = lambda agent_id: None,
        principal: Callable[[], Any] = lambda: None,
        origin: Callable[[], str] = current_action_origin,
        shared_session: Callable[[], bool] = lambda: True,
        check_fns: Mapping[str, Callable[[], bool]] | None = None,
        check_cache: CheckFnCache | None = None,
        bypass_check_cache: Callable[[], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._agent_patterns = agent_patterns
        self._principal = principal
        self._origin = origin
        self._shared_session = shared_session
        self._check_fns = dict(check_fns) if check_fns is not None else None
        self._check_cache = check_cache if check_cache is not None else CheckFnCache()
        self._bypass_check_cache = bypass_check_cache

    @property
    def check_cache(self) -> CheckFnCache:
        return self._check_cache

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
        try:
            shared = bool(self._shared_session())
        except Exception:
            shared = True
        bypass = False
        if self._bypass_check_cache is not None:
            try:
                bypass = bool(self._bypass_check_cache())
            except Exception:
                bypass = False
        offered, withheld = resolve_tools(
            tools, posture=posture, agent_patterns=patterns, settings=self._settings,
            shared_session=shared, check_fns=self._check_fns,
            check_cache=self._check_cache, bypass_check_cache=bypass,
        )
        return offered, ProfileDecision(
            surface=posture.surface,
            principal=posture.principal,
            offered=tuple(str(tool.get("name") or "") for tool in offered),
            withheld=tuple(withheld),
        )


__all__ = [
    "CHECK_FN_TTL_SECONDS", "CheckFnCache", "DEFAULT_CHECK_FN_CACHE",
    "DEFAULT_GUEST_TOOLS", "GUEST_TOOLS_SETTING", "INBOUND_ACTUATION_SETTING",
    "INTERNAL_ACTUATION_SETTING", "LAST_KNOWN_GOOD_GRACE_SECONDS",
    "POSTURES", "PRINCIPAL_GUEST", "PRINCIPAL_OWNER",
    "OWNER_OPERATOR_TOOLS", "PRINCIPAL_SYSTEM", "ProfileDecision", "SESSION_SCOPED_TOOLS", "SURFACE_INBOUND",
    "SURFACE_INTERNAL", "SURFACE_OPERATOR", "ToolPosture", "ToolProfileResolver", "classify_turn",
    "guest_tool_names", "no_cache_check_fn", "resolve_tools",
]
