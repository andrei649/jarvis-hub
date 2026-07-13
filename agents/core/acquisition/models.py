"""Bounded data contracts for the H32 acquisition lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RequestStatus(StrEnum):
    MISSING = "missing"
    RESEARCHING = "researching"
    QUARANTINED = "quarantined"
    APPROVAL_PENDING = "approval_pending"
    INSTALLED = "installed"
    REUSED = "reused"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class RequestEvent:
    status: RequestStatus
    at: float
    actor: str

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status.value, "at": self.at, "actor": self.actor}

    @classmethod
    def from_dict(cls, value: dict) -> RequestEvent:
        return cls(
            status=RequestStatus(value["status"]),
            at=float(value["at"]),
            actor=str(value["actor"]),
        )


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    request_id: str
    fingerprint: str
    goal: str
    agent_id: str
    reason: str
    status: RequestStatus
    created_at: float
    updated_at: float
    occurrences: int = 1
    history: tuple[RequestEvent, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "fingerprint": self.fingerprint,
            "goal": self.goal,
            "agent_id": self.agent_id,
            "reason": self.reason,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "occurrences": self.occurrences,
            "history": [event.to_dict() for event in self.history],
        }

    @classmethod
    def from_dict(cls, value: dict) -> CapabilityRequest:
        request_id = str(value["request_id"])
        fingerprint = str(value["fingerprint"])
        goal = str(value.get("goal", ""))
        agent_id = str(value["agent_id"])
        reason = str(value["reason"])
        if len(request_id) != 32 or len(fingerprint) != 64:
            raise ValueError("invalid acquisition request identity")
        if len(goal) > 4096 or len(agent_id) > 128 or len(reason) > 64:
            raise ValueError("invalid acquisition request bounds")
        history_raw = value.get("history", [])
        if not isinstance(history_raw, list) or len(history_raw) > 64:
            raise ValueError("invalid acquisition request history")
        return cls(
            request_id=request_id,
            fingerprint=fingerprint,
            goal=goal,
            agent_id=agent_id,
            reason=reason,
            status=RequestStatus(value["status"]),
            created_at=float(value["created_at"]),
            updated_at=float(value["updated_at"]),
            occurrences=int(value.get("occurrences", 1)),
            history=tuple(RequestEvent.from_dict(event) for event in history_raw),
        )
