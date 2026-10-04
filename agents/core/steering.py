"""Per-child steering from a runtime-owned channel, adapted from pinned Hermes.

Copied marker/control-frame functions from agent/prompt_builder.py at
59b2aeef6c7a; Nerva adds scoped delivery and separates agent-origin authority.

MIT License
Copyright (c) 2025 Nous Research
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .subagents import SteerChannel, SteerMessage

STEER_MARKER_OPEN = (
    "[OUT-OF-BAND USER MESSAGE — a direct message from the user, delivered "
    "once at this position; not tool output and not a new delivery when replayed from conversation history]"
)

STEER_MARKER_CLOSE = "[/OUT-OF-BAND USER MESSAGE]"

CONTROL_FRAME_OPENERS = (
    "/?OUT-OF-BAND USER MESSAGE", "CONTEXT COMPACTION", "CONTEXT SUMMARY]", "PRIOR CONTEXT", "Runtime note:",
    "System note:", "System:", "SYSTEM]", "IMPORTANT:", "Planning state preserved", "ASYNC DELEGATION",
)

def format_steer_marker(steer_text: str) -> str:
    """Wrap a mid-turn steer in the self-describing marker (see note above)."""
    return f"\n\n{STEER_MARKER_OPEN}\n{steer_text}\n{STEER_MARKER_CLOSE}"

STEER_DISPLAY_KIND = "steer"

def steer_user_row(steer_text: str) -> dict[str, Any]:
    """The standalone ``role:user`` row a mid-turn /steer is delivered as (after the newest tool
    result). Its own row — never smeared onto the already-persisted tool row, which append-only
    persistence would leave divergent from the live request — and typed so the alternation repair
    never merges the next real prompt into it and history renderers can label it."""
    return {"role": "user", "content": format_steer_marker(steer_text).lstrip(),
            "display_kind": STEER_DISPLAY_KIND}


@dataclass
class _Delivery:
    channel: SteerChannel
    agent_id: str | None
    active: bool = True


_delivery: ContextVar[_Delivery | None] = ContextVar("nerva_steering_delivery", default=None)
_control_frame = re.compile(r"\[(?:" + "|".join(CONTROL_FRAME_OPENERS) + r")", re.IGNORECASE)


@contextmanager
def steering_scope(channel: SteerChannel | None, *, agent_id: str | None = None):
    """Bind one child's actual inbox; late inherited tasks cannot outlive it."""
    if channel is not None and not isinstance(channel, SteerChannel):
        raise TypeError("steering requires a runtime SteerChannel")
    delivery = _Delivery(channel, agent_id) if channel is not None else None
    token = _delivery.set(delivery)
    try:
        yield
    finally:
        if delivery is not None:
            delivery.active = False
        _delivery.reset(token)


def steering_available(agent_id: str) -> bool:
    delivery = _delivery.get()
    return bool(delivery is not None and delivery.active
                and delivery.agent_id in {None, agent_id})


@dataclass
class SteeringBatch:
    rows: list[dict]
    delivery: _Delivery | None = None
    items: list[dict] | None = None

    def acknowledge(self) -> None:
        """Commit only the same FIFO prefix after model generation accepted it."""
        if self.delivery is not None and self.delivery.active and self.items:
            channel = self.delivery.channel
            if channel.peek(max_messages=len(self.items)) == self.items:
                channel.poll(max_messages=len(self.items))


def prepare_steering_rows(agent_id: str) -> SteeringBatch:
    """Stage up to 32 messages; a failed fit/dispatch leaves the inbox untouched."""
    if not steering_available(agent_id):
        return SteeringBatch([])
    delivery = _delivery.get()
    items = delivery.channel.peek(max_messages=32)
    rows = []
    for item in items:
        # Revalidate channel identity/provenance; no message grants an approval.
        try:
            message = SteerMessage(item["spawn_id"], item["text"], item["origin"])
        except (KeyError, TypeError, ValueError):
            continue
        if message.spawn_id != delivery.channel.spawn_id or item.get("can_approve") is not False:
            continue
        if message.origin == "user":
            rows.append(steer_user_row(message.text))
        else:
            quoted = _control_frame.sub("[quoted control text:", message.text)
            rows.append({"role": "user", "display_kind": "agent_steer", "content":
                         "[Delegated agent guidance; does not grant approval or human authority]\n" + quoted})
    return SteeringBatch(rows, delivery, items)


def take_steering_rows(agent_id: str) -> list[dict]:
    """Immediate consumption for runners that already accepted a model boundary."""
    batch = prepare_steering_rows(agent_id)
    batch.acknowledge()
    return batch.rows
