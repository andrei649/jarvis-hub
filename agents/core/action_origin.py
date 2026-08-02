"""Per-turn provenance for kernel-mediated actions.

The Action Kernel cannot infer whether an LLM-produced action came from trusted
operator input or an inbound external channel after the model has processed the
text. This module carries that declared provenance in a ContextVar so brokers
can tag ``Action.origin`` without importing the orchestrator.
"""

from __future__ import annotations

from contextvars import ContextVar

OPERATOR_TURN_CHANNELS = frozenset({"web", "voice"})
INTERNAL_TURN_CHANNELS = frozenset({
    "eval",
    "notes",
    "builder",
    "room",
    "arena",
    "workflow",
    "internal",
})
# NOTE (Q10 / ch11 CHN-061): `widget` is deliberately NOT internal. The embed
# endpoint is tier `open` — the text comes from an anonymous visitor on someone
# else's website, so it classifies `inbound` like any other external door.
TRUSTED_TURN_CHANNELS = OPERATOR_TURN_CHANNELS | INTERNAL_TURN_CHANNELS
DEFAULT_ACTION_ORIGIN = "generated"
INBOUND_ACTION_ORIGIN = "inbound"

_active_action_origin: ContextVar[str] = ContextVar(
    "jarvis_action_origin",
    default=DEFAULT_ACTION_ORIGIN,
)


def origin_for_channel(channel: str | None) -> str:
    """Classify the inbound turn's channel into a kernel Action.origin value."""
    channel_id = str(channel or "").strip().lower()
    if channel_id in TRUSTED_TURN_CHANNELS:
        return DEFAULT_ACTION_ORIGIN
    return INBOUND_ACTION_ORIGIN


def bind_action_origin(origin: str | None):
    """Bind origin for the current async context; return the reset token."""
    return _active_action_origin.set(str(origin or DEFAULT_ACTION_ORIGIN))


def bind_turn_action_origin(channel: str | None):
    """Bind the declared turn origin without downgrading an inbound parent context."""
    origin = origin_for_channel(channel)
    if current_action_origin() == INBOUND_ACTION_ORIGIN:
        origin = INBOUND_ACTION_ORIGIN
    return bind_action_origin(origin)


def reset_action_origin(token) -> None:
    _active_action_origin.reset(token)


def current_action_origin(default: str = DEFAULT_ACTION_ORIGIN) -> str:
    return _active_action_origin.get() or default
