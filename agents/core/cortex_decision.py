"""Typed, replayable shadow records for the existing intent router.

This module is deliberately advisory.  It observes the route chosen by the
current router and emits ``nerva.decision.v1`` evidence without changing that
route, authorizing an action, or marking work complete.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Literal, Mapping, Protocol

logger = logging.getLogger("nerva.cortex.shadow")

EvidenceStatus = Literal["measured", "unknown", "not_measured", "not_applicable"]


@dataclass(frozen=True)
class EvidenceValue:
    """One explicitly qualified evidence value.

    Missing data is never converted into a guessed number.  ``value`` is only
    populated for measured evidence; the status remains visible in serialized
    records and fingerprints.
    """

    status: EvidenceStatus
    value: Any = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.status != "measured" and self.value is not None:
            raise ValueError("unmeasured evidence cannot carry a value")
        if self.status == "measured" and self.source is None:
            raise ValueError("measured evidence requires a source")


@dataclass(frozen=True)
class DecisionRejection:
    """A hard constraint that excluded a route.

    Rejections are non-overridable by construction.  A future scored Cortex may
    rank eligible routes, but it must never outvote policy or privacy constraints.
    """

    route_id: str
    code: str
    category: Literal["policy", "privacy", "availability", "compatibility"]
    source: str
    non_overridable: bool = field(default=True, init=False)


@dataclass(frozen=True)
class DecisionRequest:
    """Privacy-minimised request identity used for deterministic replay."""

    text_digest: str
    text_length: int
    available_agents: tuple[str, ...]
    privacy_class: str = "unknown"

    @classmethod
    def from_input(cls, text: str, agents: Mapping[str, Any]) -> "DecisionRequest":
        normalized = _normalize_for_digest(text)
        return cls(
            text_digest=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            text_length=len(text or ""),
            available_agents=tuple(sorted(str(agent_id) for agent_id in agents)),
        )


@dataclass(frozen=True)
class DecisionCandidate:
    route_id: str
    rank: int
    selected: bool
    score: EvidenceValue
    quality: EvidenceValue = field(
        default_factory=lambda: EvidenceValue("not_measured")
    )
    risk: EvidenceValue = field(
        default_factory=lambda: EvidenceValue("not_measured")
    )
    privacy: EvidenceValue = field(
        default_factory=lambda: EvidenceValue("not_measured")
    )
    latency: EvidenceValue = field(
        default_factory=lambda: EvidenceValue("not_measured")
    )
    cost: EvidenceValue = field(
        default_factory=lambda: EvidenceValue("not_measured")
    )


@dataclass(frozen=True)
class DecisionRecord:
    """Replayable observation of an already-made routing decision."""

    request: DecisionRequest
    source: str
    candidates: tuple[DecisionCandidate, ...]
    selected_route: str
    fallbacks: tuple[str, ...]
    confidence: EvidenceValue
    hard_constraint_rejections: tuple[DecisionRejection, ...] = ()
    schema: str = field(default="nerva.decision.v1", init=False)
    authority: str = field(default="route_selection_only", init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def canonical_payload(self) -> dict[str, Any]:
        """Return the stable payload used for serialization and replay hashing."""

        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def replay_fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_intent(
        cls,
        *,
        text: str,
        agents: Mapping[str, Any],
        intent: Any,
    ) -> "DecisionRecord":
        context = dict(getattr(intent, "context", {}) or {})
        target_agents = tuple(getattr(intent, "target_agents", None) or ("jarvis",))
        raw_scores = context.get("scores") if isinstance(context.get("scores"), dict) else {}

        candidates: list[DecisionCandidate] = []
        for rank, route_id in enumerate(target_agents):
            raw_score = raw_scores.get(route_id)
            score = (
                EvidenceValue("measured", float(raw_score), "router.context.scores")
                if isinstance(raw_score, (int, float))
                else EvidenceValue("not_measured")
            )
            candidates.append(
                DecisionCandidate(
                    route_id=str(route_id),
                    rank=rank,
                    selected=rank == 0,
                    score=score,
                )
            )

        confidence_raw = getattr(intent, "confidence", None)
        confidence = (
            EvidenceValue("measured", float(confidence_raw), "router.intent.confidence")
            if isinstance(confidence_raw, (int, float))
            else EvidenceValue("unknown")
        )

        rejections = tuple(_parse_rejections(context.get("hard_constraint_rejections")))
        return cls(
            request=DecisionRequest.from_input(text, agents),
            source=str(context.get("source") or "unknown"),
            candidates=tuple(candidates),
            selected_route=str(target_agents[0]),
            fallbacks=tuple(str(route_id) for route_id in target_agents[1:]),
            confidence=confidence,
            hard_constraint_rejections=rejections,
        )


class RouterProtocol(Protocol):
    async def classify(self, text: str, agents: dict[str, Any]) -> Any: ...


ShadowWriter = Callable[[DecisionRecord], None | Awaitable[None]]


class ShadowDecisionRouter:
    """Transparent wrapper that records current router output in shadow mode.

    The wrapped ``Intent`` object is returned unchanged.  Writer failure is
    isolated and logged, so enabling observation cannot alter routing behavior.
    Unknown attributes are delegated to preserve mutable routing-table and
    promotion behavior used by the orchestrator.
    """

    def __init__(self, router: RouterProtocol, writer: ShadowWriter):
        self._router = router
        self._writer = writer

    async def classify(self, text: str, agents: dict[str, Any]) -> Any:
        intent = await self._router.classify(text, agents)
        try:
            record = DecisionRecord.from_intent(text=text, agents=agents, intent=intent)
            result = self._writer(record)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # shadow evidence must never break routing
            logger.warning("Cortex shadow writer failed: %s", exc)
        return intent

    def __getattr__(self, name: str) -> Any:
        return getattr(self._router, name)


def _parse_rejections(raw: Any) -> list[DecisionRejection]:
    if not isinstance(raw, (list, tuple)):
        return []
    parsed: list[DecisionRejection] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        route_id = item.get("route_id")
        code = item.get("code")
        category = item.get("category")
        source = item.get("source")
        if (
            isinstance(route_id, str)
            and isinstance(code, str)
            and category in {"policy", "privacy", "availability", "compatibility"}
            and isinstance(source, str)
        ):
            parsed.append(
                DecisionRejection(
                    route_id=route_id,
                    code=code,
                    category=category,
                    source=source,
                )
            )
    return parsed


def _normalize_for_digest(text: str) -> str:
    folded = unicodedata.normalize("NFKC", (text or "").strip().lower())
    return " ".join(folded.split())
