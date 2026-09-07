"""LVP-hestia-wiring — Hestia's reads and proposals bound onto the House Brain.

Until now ``agents/hestia`` was a persona with no code behind it: ORIZONT 30
shipped ``agents/core/house/**`` (adapter, graph, presence, actuation) and the
router, but no agent *owned* the building. This module is that binding. It
adds no second policy layer and no parallel device path:

- :meth:`HestiaBridge.observe` reads ONE snapshot through the strict-local
  adapter, projects it into the shared :class:`HouseGraph` (same instance the
  router serves), optionally feeds the presence writer, and returns a bounded,
  non-sensitive observation: rooms, device counts, lights on, stale and
  unavailable devices, and an *aggregate* occupancy word (``occupied`` /
  ``empty`` / ``unknown``) — never who, never which room (SOUL rule 3).
- :meth:`HestiaBridge.propose` applies explicit local rules to that
  observation and turns each hit into a house task **through
  ``HouseActuator.request_*``** — the existing rail that runs the kernel
  intake gate, the ask-until-earned floor and ``govern_enqueue``. Hestia never
  touches a device and never enqueues around the actuator; a proposal is a
  proposal until the owner accepts it (SOUL rule 4).
- :meth:`HestiaBridge.ambient` forwards the assistant's orb state to the
  optional :class:`WLEDBridge` (H30.8), whose every write crosses
  ``house.control``.

Default-off behind ``JARVIS_HESTIA_BRIDGE``: with the flag unset both
``observe`` and ``propose`` answer ``hestia_bridge_disabled`` and touch
nothing. Proposals are additionally bounded per cycle, per entity (cooldown)
and per day, so a quiet house stays quiet.
"""

from __future__ import annotations

import inspect
import logging
import time
from collections import Counter
from collections.abc import Callable

from agents.core.env_config import env_flag

from .contracts import HouseSnapshot
from .graph import HouseGraph

logger = logging.getLogger(__name__)

HESTIA_BRIDGE_ENV = "JARVIS_HESTIA_BRIDGE"
HESTIA_AGENT = "hestia"
STALE_AFTER_SECONDS = 15 * 60.0
_MAX_LISTED = 64
_MAX_ROOMS = 128
_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})
_HOME_STATES = frozenset({"home", "on"})
_AWAY_STATES = frozenset({"not_home", "away", "off"})
RULE_LIGHTS_ON_IN_EMPTY_HOUSE = "lights_on_in_empty_house"


def hestia_bridge_enabled() -> bool:
    """Default-off master switch for Hestia's observe/propose loop."""
    return env_flag(HESTIA_BRIDGE_ENV)


def _disabled(reason: str) -> dict:
    return {"status": "disabled", "reason": reason, "proposals": [], "notes": []}


def _occupancy(snapshot: HouseSnapshot) -> str:
    """Aggregate occupancy from identity-bearing HA domains; no identity leaves."""
    seen = False
    for entity in snapshot.entities:
        if entity.domain not in {"person", "device_tracker"}:
            continue
        state = entity.state.strip().lower()
        if state in _HOME_STATES:
            return "occupied"
        if state in _AWAY_STATES:
            seen = True
    return "empty" if seen else "unknown"


class HestiaBridge:
    """Hestia's code: observe the house, propose through the governed rail."""

    def __init__(
        self,
        house_brain,
        *,
        wled=None,
        enabled: bool | None = None,
        clock: Callable[[], float] | None = None,
        agent: str = HESTIA_AGENT,
        max_proposals_per_cycle: int = 3,
        proposal_cooldown_seconds: float = 3600.0,
        daily_proposal_cap: int = 12,
        stale_after_seconds: float = STALE_AFTER_SECONDS,
    ) -> None:
        if house_brain is None:
            raise ValueError("house_brain is required")
        self._brain = house_brain
        self._wled = wled
        self._enabled = enabled
        self._clock = clock or time.time
        self._agent = agent
        self._per_cycle = max(0, int(max_proposals_per_cycle))
        self._cooldown = max(0.0, float(proposal_cooldown_seconds))
        self._daily_cap = max(0, int(daily_proposal_cap))
        self._stale_after = max(0.0, float(stale_after_seconds))
        self._last_proposed: dict[str, float] = {}
        self._day_bucket = ""
        self._day_count = 0
        self._last_observation: dict = {}

    @classmethod
    def from_orchestrator(
        cls, orch, *, runtime_provider: Callable | None = None, wled=None
    ) -> HestiaBridge:
        """Bind onto the router's cached :class:`HouseRuntime` (shared stores).

        The provider defaults to ``routers.house._get_runtime`` so Hestia sees
        the SAME graph/private-store/actuator instances the API serves — a
        second runtime on the same paths would be invisible to the router
        (the GAP-9 lesson). WLED gets the same bound kernel the house uses.
        """
        if runtime_provider is None:
            from agents.core.routers.house import _get_runtime

            runtime_provider = _get_runtime
        if wled is None:
            from agents.core.kernel.binding import make_action_kernel

            from .wled import WLEDBridge

            try:
                authorizer = make_action_kernel(orch) if orch is not None else None
            except Exception:
                logger.debug("hestia: action kernel unavailable for WLED", exc_info=True)
                authorizer = None
            wled = WLEDBridge(authorizer=authorizer)
        return cls(runtime_provider, wled=wled)

    # ── plumbing ─────────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return hestia_bridge_enabled() if self._enabled is None else bool(self._enabled)

    @property
    def wled(self):
        return self._wled

    async def _runtime(self):
        brain = self._brain
        if callable(brain) and not hasattr(brain, "adapter"):
            brain = brain()
            if inspect.isawaitable(brain):
                brain = await brain
        return brain

    @staticmethod
    async def _snapshot(runtime) -> HouseSnapshot | None:
        reader = getattr(runtime, "adapter", None)
        snapshot = getattr(reader, "snapshot", None)
        if not callable(snapshot):
            return None
        try:
            result = snapshot()
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            logger.debug("hestia: snapshot unavailable", exc_info=True)
            return None
        return result if isinstance(result, HouseSnapshot) else None

    # ── observe ──────────────────────────────────────────────────────────────
    async def observe(self) -> dict:
        """One bounded, non-sensitive picture of the house right now."""
        if not self.enabled:
            return _disabled("hestia_bridge_disabled")
        runtime = await self._runtime()
        snapshot = await self._snapshot(runtime)
        if snapshot is None:
            return {"status": "degraded", "reason": "house_state_unavailable"}
        if snapshot.status != "live":
            return {
                "status": snapshot.status,
                "reason": snapshot.reason or f"house_{snapshot.status}",
                "observed_at": snapshot.observed_at,
            }

        projection = None
        graph = getattr(runtime, "graph", None)
        if isinstance(graph, HouseGraph):
            try:
                projection = graph.project_snapshot(snapshot)
            except Exception:
                logger.debug("hestia: graph projection failed", exc_info=True)
                projection = {"status": "degraded", "reason": "graph_projection_failed"}
        ingestor = getattr(runtime, "presence_ingestor", None)
        if ingestor is not None and callable(getattr(ingestor, "ingest", None)):
            try:
                ingestor.ingest(snapshot)
            except Exception:
                logger.debug("hestia: presence ingest failed", exc_info=True)

        now = float(self._clock())
        rooms = {area.area_id: {"room_id": area.area_id, "name": area.name, "devices": 0,
                                "lights_on": 0} for area in snapshot.areas[:_MAX_ROOMS]}
        by_domain: Counter[str] = Counter()
        lights_on: list[str] = []
        stale: list[dict] = []
        unavailable: list[str] = []
        for entity in snapshot.entities:
            by_domain[entity.domain] += 1
            room = rooms.get(entity.area_id)
            if room is not None:
                room["devices"] += 1
            state = entity.state.strip().lower()
            if state in _UNAVAILABLE_STATES:
                unavailable.append(entity.entity_id)
                continue
            if entity.domain == "light" and state == "on":
                lights_on.append(entity.entity_id)
                if room is not None:
                    room["lights_on"] += 1
            age = now - entity.updated_at if entity.updated_at else None
            if age is not None and age > self._stale_after:
                stale.append({"entity_id": entity.entity_id, "age_seconds": round(age, 1)})
        stale.sort(key=lambda item: -item["age_seconds"])
        observation = {
            "status": "live",
            "reason": "",
            "observed_at": snapshot.observed_at,
            "occupancy": _occupancy(snapshot),
            "rooms": sorted(rooms.values(), key=lambda item: item["room_id"]),
            "devices": {"total": len(snapshot.entities), "by_domain": dict(sorted(by_domain.items()))},
            "lights_on": sorted(lights_on)[:_MAX_LISTED],
            "stale": stale[:_MAX_LISTED],
            "unavailable": sorted(unavailable)[:_MAX_LISTED],
            "projection": projection,
        }
        self._last_observation = observation
        return observation

    # ── propose ──────────────────────────────────────────────────────────────
    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(float(self._clock())))

    def _budget_allows(self, entity_id: str) -> str:
        """'' when a proposal for *entity_id* may go out now, else the reason."""
        now = float(self._clock())
        day = self._day()
        if day != self._day_bucket:
            self._day_bucket = day
            self._day_count = 0
        if self._day_count >= self._daily_cap:
            return "daily_proposal_cap"
        last = self._last_proposed.get(entity_id)
        if last is not None and now - last < self._cooldown:
            return "proposal_cooldown"
        return ""

    def _record_proposal(self, entity_id: str) -> None:
        self._last_proposed[entity_id] = float(self._clock())
        self._day_count += 1

    async def propose(self, observation: dict | None = None) -> dict:
        """Turn the observation into governed house tasks (ask-floor, capped)."""
        if not self.enabled:
            return _disabled("hestia_bridge_disabled")
        if observation is None:
            observation = await self.observe()
        if observation.get("status") != "live":
            return {
                "status": observation.get("status", "degraded"),
                "reason": observation.get("reason", ""),
                "proposals": [],
                "notes": [],
            }
        runtime = await self._runtime()
        actuator = getattr(runtime, "actuator", None)
        request_light = getattr(actuator, "request_light", None)

        notes = [
            {"note": "device_unavailable", "entity_id": entity_id}
            for entity_id in observation.get("unavailable", [])[:_MAX_LISTED]
        ]
        notes.extend(
            {"note": "reading_stale", **item} for item in observation.get("stale", [])[:_MAX_LISTED]
        )
        proposals: list[dict] = []
        skipped: list[dict] = []
        if observation.get("occupancy") == "empty":
            for entity_id in observation.get("lights_on", []):
                if len(proposals) >= self._per_cycle:
                    skipped.append({"entity_id": entity_id, "reason": "cycle_cap"})
                    continue
                blocked = self._budget_allows(entity_id)
                if blocked:
                    skipped.append({"entity_id": entity_id, "reason": blocked})
                    continue
                if not callable(request_light):
                    skipped.append({"entity_id": entity_id, "reason": "house_actuation_unavailable"})
                    continue
                try:
                    result = await request_light(entity_id, state="off", agent=self._agent)
                except Exception:
                    logger.debug("hestia: proposal refused by the actuator", exc_info=True)
                    result = {"ok": False, "queued": False, "reason": "house_actuation_error"}
                if not isinstance(result, dict):
                    result = {"ok": False, "queued": False, "reason": "invalid_actuator_result"}
                if result.get("queued"):
                    self._record_proposal(entity_id)
                proposals.append(
                    {
                        "rule": RULE_LIGHTS_ON_IN_EMPTY_HOUSE,
                        "entity_id": entity_id,
                        "title": f"Turn off {entity_id} — nobody is home",
                        "agent": self._agent,
                        "queued": bool(result.get("queued")),
                        "task_id": result.get("task_id"),
                        "reason": result.get("reason", ""),
                    }
                )
        return {
            "status": "live",
            "reason": "",
            "occupancy": observation.get("occupancy", "unknown"),
            "proposals": proposals,
            "skipped": skipped,
            "notes": notes,
        }

    # ── ambient (H30.8) ──────────────────────────────────────────────────────
    async def ambient(self, state: str) -> dict:
        """Mirror the orb state onto the strip; honest refusal without a bridge."""
        if self._wled is None:
            return {"ok": False, "reason": "wled_not_configured"}
        return await self._wled.set_scene(state)

    def status(self) -> dict:
        wled_status = self._wled.status() if self._wled is not None else None
        return {
            "enabled": self.enabled,
            "agent": self._agent,
            "proposals_today": self._day_count if self._day_bucket == self._day() else 0,
            "daily_cap": self._daily_cap,
            "last_observed_at": self._last_observation.get("observed_at"),
            "wled": wled_status,
        }


__all__ = [
    "HESTIA_AGENT",
    "HESTIA_BRIDGE_ENV",
    "RULE_LIGHTS_ON_IN_EMPTY_HOUSE",
    "STALE_AFTER_SECONDS",
    "HestiaBridge",
    "hestia_bridge_enabled",
]
