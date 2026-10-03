"""Private contracts joining trusted H487 producers, owner decisions and execution.

These objects are constructed by server integrations; request bodies and model
payloads are never deserialized into authority-bearing objects.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from .consent_ledger import ConsentCategory, ConsentContext

if TYPE_CHECKING:
    from .queue import Task


@dataclass(frozen=True, slots=True)
class ConsentDescriptor:
    context: ConsentContext
    categories: tuple[ConsentCategory, ...]
    registration_epoch: str


@dataclass(frozen=True, slots=True)
class OwnerConsentActor:
    label: Literal["admin", "owner"]
    decided_by: Literal["admin", "telegram"]
    live: Callable[[], bool] = field(repr=False, compare=False)
    principal_key: str | None = None
    authority: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ConsentOffer:
    task_id: int
    revision: str
    member_ids: tuple[int, ...]
    categories: tuple[ConsentCategory, ...]


@dataclass(frozen=True, slots=True)
class ConsentDecisionResult:
    tasks: tuple[Task, ...]
    group_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConsentClaim:
    task_id: int
    nonce: str
    execution_id: str
    _queue_key: object = field(repr=False, compare=False)
