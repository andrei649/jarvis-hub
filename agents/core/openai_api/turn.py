"""G12 — one Nerva turn started by an OpenAI-compatible client.

The turn is an ordinary orchestrator turn (``Orchestrator.handle_input`` /
``handle_input_stream``): the same memory, tools, kernel, approval queue, turn lease and usage
accounting as a HUD message. What the API decides is only *who is speaking*:

- an **owner key** speaks as the owner at the HUD (``Principal(channel="web", admin=True)``,
  the operator surface): its turns are trusted like the owner's own typing;
- any **other key** speaks on the ``openai_api`` channel as a guest
  (``Principal(channel="openai_api", sender="apikey:<id>", admin=False)``). That channel is not
  a trusted turn channel (``agents/core/action_origin.py``), so the turn's action origin is
  ``inbound`` — bound here at the boundary *and* by the orchestrator's own chokepoint, which
  never downgrades it — and the kernel escalates every mutating action it proposes to the
  owner's approval queue. The guest tool posture (``agents/core/tool_profiles.py``) applies.

Nothing a client sends (system prompt, model name, metadata) changes that classification.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from .store import ApiKey

logger = logging.getLogger("nerva.openai_api")

#: The channel a non-owner key's turns arrive on (an inbound, untrusted channel).
CHANNEL = "openai_api"


class TurnBusy(Exception):
    """Another turn holds this conversation's lease."""


class TurnIncomplete(Exception):
    """The turn ended without an answer (an error, a refusal, an empty reply).

    ``approvals`` names what the turn queued before it failed: those cards are still waiting."""

    def __init__(self, reason: str = "turn_failed") -> None:
        super().__init__(reason)
        self.reason = reason
        self.approvals: list[int] = []


class NoModel(Exception):
    """No language model is loaded, so the turn could not run."""


@dataclass(frozen=True)
class Speaker:
    """Who the key makes the speaker of this turn."""

    channel: str
    admin: bool
    sender: str | None

    @property
    def inbound(self) -> bool:
        from agents.core.action_origin import INBOUND_ACTION_ORIGIN, origin_for_channel

        return origin_for_channel(self.channel) == INBOUND_ACTION_ORIGIN


def speaker_for(key: ApiKey) -> Speaker:
    if key.owner:
        return Speaker(channel="web", admin=True, sender=None)
    return Speaker(channel=CHANNEL, admin=False, sender=f"apikey:{key.key_id}")


@dataclass
class TurnOutcome:
    text: str
    approvals: list[int] = field(default_factory=list)
    usage: dict[str, Any] | None = None


@asynccontextmanager
async def _lease(orch, session_id: str):
    lease = getattr(orch, "turn_lease", None)
    if lease is None:
        yield True
        return
    async with lease(session_id) as acquired:
        yield acquired


async def _load_session(orch, session_id: str) -> None:
    """Bring a conversation this API already spoke in back into memory, as a chat channel does
    for its own route (``memory.resume_session``: a no-op while it is loaded, a read of its
    snapshot after a restart). Its history identity, rewind and foreign-history fences are the
    memory layer's own; a session it cannot vouch for ends the turn instead of starting over."""
    resume = getattr(getattr(orch, "memory", None), "resume_session", None)
    if not callable(resume):
        return                                   # a stand-in hub without session memory
    try:
        await resume(session_id)
    except Exception as exc:  # noqa: BLE001 — e.g. an unverified rewind: refuse, never guess
        raise TurnIncomplete("session_unavailable") from exc


async def run_turn(orch, key: ApiKey, text: str, *, session_id: str, agent_override: str | None,
                   known_session: bool,
                   on_token: Callable[[str], Awaitable[None]] | None = None) -> TurnOutcome:
    """Run the turn as the key's speaker; raise :class:`TurnBusy`, :class:`NoModel` or
    :class:`TurnIncomplete` instead of returning a failure as if it were the answer."""
    from agents.core.action_origin import (
        INBOUND_ACTION_ORIGIN,
        bind_action_origin,
        reset_action_origin,
    )
    from agents.core.commands import Principal
    from agents.core.orchestrator import (
        NO_MODEL_REPLY,
        TURN_BUSY_REPLY,
        bind_turn_principal,
        reset_turn_principal,
    )
    from agents.core.turn_approvals import open_turn_approvals, reset_turn_approvals
    from agents.core.turn_usage import turn_usage_scope

    speaker = speaker_for(key)
    principal_token = bind_turn_principal(Principal(channel=speaker.channel, sender=speaker.sender,
                                                    admin=speaker.admin))
    # Taint at the boundary: a guest key's turn is inbound before the orchestrator sees it.
    origin_token = bind_action_origin(INBOUND_ACTION_ORIGIN) if speaker.inbound else None
    sink, approvals_token = open_turn_approvals()
    usage = None
    try:
        with turn_usage_scope() as collector:
            async with _lease(orch, session_id) as acquired:
                if not acquired:
                    raise TurnBusy()
                if known_session:
                    await _load_session(orch, session_id)
                kwargs = {"channel": speaker.channel, "agent_override": agent_override, "session_id": session_id}
                try:
                    if on_token is not None:
                        reply = await orch.handle_input_stream(text, on_token=on_token, **kwargs)
                    else:
                        reply = await orch.handle_input(text, **kwargs)
                except (asyncio.CancelledError, TurnBusy, TurnIncomplete):
                    raise
                except Exception as exc:
                    logger.exception("openai_api: turn failed")
                    raise TurnIncomplete("turn_failed") from exc
            usage = collector.snapshot()
    except TurnIncomplete as exc:
        exc.approvals = list(sink)
        raise
    finally:
        approvals = list(sink)
        reset_turn_approvals(approvals_token)
        if origin_token is not None:
            reset_action_origin(origin_token)
        reset_turn_principal(principal_token)
    if reply == TURN_BUSY_REPLY:
        raise TurnBusy()
    if reply == NO_MODEL_REPLY:
        raise NoModel()
    if not isinstance(reply, str) or not reply.strip():
        raise TurnIncomplete("empty_reply")
    return TurnOutcome(text=reply, approvals=approvals, usage=usage)


__all__ = ["CHANNEL", "NoModel", "Speaker", "TurnBusy", "TurnIncomplete", "TurnOutcome", "run_turn",
           "speaker_for"]
