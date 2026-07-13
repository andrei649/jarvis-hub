"""Dependency-neutral types shared by the generic and operator reality harnesses."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from agents.core.capability_verification import HARNESS_ID

ProbeResult = bool | Mapping[str, object]
Probe = Callable[[], Awaitable[ProbeResult]]


@dataclass
class RealityCase:
    """One capability contract and the async probe that supplies its evidence."""

    capability_id: str
    name: str
    contract: str
    probe: Probe
    live: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{HARNESS_ID}:{self.name}"
