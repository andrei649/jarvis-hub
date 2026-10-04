"""Process-local capabilities for one authenticated smart-DENY owner reply.

These objects never belong in a Task, tool argument, model result or receipt.
The durable queue independently verifies every bound byte before use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from agents.core.approval_outcomes import ApprovalTurnContext


@dataclass(frozen=True, slots=True)
class OwnerOnceOwner:
    """Freshly authenticated sender and the exact delivered Telegram prompt."""

    principal_key: str
    channel: str
    chat_id: int
    user_id: int
    message_id: int
    generation: str


@dataclass(frozen=True, slots=True)
class OwnerOnceOffer:
    task_id: int
    nonce: str = field(repr=False)
    deadline_at: str
    _turn: ApprovalTurnContext = field(repr=False, compare=False)
    _queue_key: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class OwnerOnceClaim:
    task_id: int
    nonce: str = field(repr=False)
    decision_id: str
    _turn: ApprovalTurnContext = field(repr=False, compare=False)
    _owner: OwnerOnceOwner = field(repr=False, compare=False)
    _queue_key: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class OwnerOnceWaitOutcome:
    """An observed delivered wait ending; never a queue or execution capability."""

    state: Literal['timeout', 'withdrawn', 'denied', 'held']
    task_id: int
    nonce: str = field(repr=False)
    decision_id: str = field(default='', repr=False)


__all__ = ["OwnerOnceOwner", "OwnerOnceOffer", "OwnerOnceClaim", "OwnerOnceWaitOutcome"]
