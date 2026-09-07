"""LVP-hestia-wiring — Hestia observes the house and proposes through the rail.

Hermetic: a fake Home Assistant adapter serves snapshots, the real HouseGraph
projects into an in-memory generic graph, a recording actuator (and, once, the
real HouseActuator over a fake govern_enqueue) receives proposals. Pins:
default-off, non-sensitive observation (aggregate occupancy only), proposals
only when the house is empty, every proposal tagged agent=hestia and routed
through the actuator, cooldown/daily/cycle caps, and the WLED hand-off.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parents[1]
for entry in (str(repo_root), str(repo_root / "agents")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agents.core.house.actuation import HOUSE_CONTROL_KIND, HouseActuator  # noqa: E402
from agents.core.house.contracts import HouseArea, HouseEntity, HouseSnapshot  # noqa: E402
from agents.core.house.graph import HouseGraph  # noqa: E402
from agents.core.house.hestia_bridge import (  # noqa: E402
    HESTIA_BRIDGE_ENV,
    RULE_LIGHTS_ON_IN_EMPTY_HOUSE,
    HestiaBridge,
)
from agents.core.memory.graph import InMemoryGraph  # noqa: E402

NOW = 1_800_000_000.0


def _entity(entity_id, state, *, area="living", updated_at=NOW, attrs=(), name=""):
    domain = entity_id.split(".", 1)[0]
    return HouseEntity(
        entity_id=entity_id,
        domain=domain,
        name=name or entity_id,
        state=state,
        area_id=area,
        updated_at=updated_at,
        attributes=tuple(attrs),
    )


def _snapshot(entities, *, status="live", observed_at=NOW, reason=""):
    return HouseSnapshot(
        enabled=status != "disabled",
        status=status,
        observed_at=observed_at,
        areas=(HouseArea("living", "Living room"), HouseArea("bedroom", "Bedroom")),
        entities=tuple(entities),
        reason=reason,
    )


def _empty_house(*, lights=("light.living", "light.bedroom")):
    return _snapshot(
        [
            _entity("person.owner", "not_home", area="", name="Owner"),
            *[_entity(light, "on", area=light.split(".")[1]) for light in lights],
            _entity("light.hall", "off", area="living"),
            _entity("sensor.temp", "21.5", area="bedroom", updated_at=NOW - 3600),
            _entity("switch.garage", "unavailable", area="living"),
        ]
    )


class _Adapter:
    def __init__(self, snapshot):
        self.snapshot_value = snapshot
        self.calls = 0

    async def snapshot(self):
        self.calls += 1
        if isinstance(self.snapshot_value, Exception):
            raise self.snapshot_value
        return self.snapshot_value


class _Actuator:
    def __init__(self, *, queued=True):
        self.calls = []
        self.queued = queued
        self.next_id = 100

    async def request_light(self, entity_id, *, state, brightness_pct=None, agent="jarvis"):
        self.calls.append((entity_id, state, agent))
        if not self.queued:
            return {"ok": False, "queued": False, "reason": "house_state_stale"}
        self.next_id += 1
        return {"ok": True, "queued": True, "task_id": self.next_id}


class _Ingestor:
    def __init__(self):
        self.snapshots = []

    def ingest(self, snapshot):
        self.snapshots.append(snapshot)
        return 0


def _runtime(snapshot, *, actuator=None, ingestor=None):
    return SimpleNamespace(
        adapter=_Adapter(snapshot),
        graph=HouseGraph(InMemoryGraph()),
        actuator=_Actuator() if actuator is None else actuator,
        presence_ingestor=ingestor,
    )


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(HESTIA_BRIDGE_ENV, "1")


# ── default-off ──────────────────────────────────────────────────────────────


async def test_bridge_is_off_by_default_and_touches_nothing(monkeypatch):
    monkeypatch.delenv(HESTIA_BRIDGE_ENV, raising=False)
    runtime = _runtime(_empty_house())
    bridge = HestiaBridge(runtime)

    observed = await bridge.observe()
    proposed = await bridge.propose()

    assert observed["status"] == "disabled"
    assert observed["reason"] == "hestia_bridge_disabled"
    assert proposed["proposals"] == []
    assert runtime.adapter.calls == 0
    assert runtime.actuator.calls == []
    assert bridge.status()["enabled"] is False


def test_bridge_requires_a_house_brain():
    with pytest.raises(ValueError):
        HestiaBridge(None)


# ── observe ──────────────────────────────────────────────────────────────────


async def test_observe_is_bounded_and_carries_no_identity(on):
    ingestor = _Ingestor()
    runtime = _runtime(_empty_house(), ingestor=ingestor)
    bridge = HestiaBridge(runtime, clock=lambda: NOW + 1)

    observation = await bridge.observe()

    assert observation["status"] == "live"
    assert observation["occupancy"] == "empty"
    assert observation["lights_on"] == ["light.bedroom", "light.living"]
    assert observation["unavailable"] == ["switch.garage"]
    assert [item["entity_id"] for item in observation["stale"]] == ["sensor.temp"]
    assert observation["stale"][0]["age_seconds"] == pytest.approx(3601.0)
    assert observation["devices"]["total"] == 6
    assert observation["devices"]["by_domain"]["light"] == 3
    rooms = {room["room_id"]: room for room in observation["rooms"]}
    assert rooms["living"]["lights_on"] == 1 and rooms["living"]["devices"] == 3
    assert observation["projection"]["status"] == "projected"
    assert ingestor.snapshots == [runtime.adapter.snapshot_value]
    # The identity-bearing entity is aggregated away, never listed.
    flat = repr(observation)
    assert "person.owner" not in flat and "Owner" not in flat


async def test_observe_reports_occupied_and_unknown_honestly(on):
    occupied = _snapshot([_entity("device_tracker.phone", "home", area=""), _entity("light.living", "on")])
    unknown = _snapshot([_entity("light.living", "on")])

    assert (await HestiaBridge(_runtime(occupied)).observe())["occupancy"] == "occupied"
    assert (await HestiaBridge(_runtime(unknown)).observe())["occupancy"] == "unknown"


async def test_observe_passes_a_non_live_snapshot_through(on):
    degraded = _snapshot([], status="degraded", reason="ha_unreachable")
    bridge = HestiaBridge(_runtime(degraded))

    observation = await bridge.observe()

    assert observation["status"] == "degraded"
    assert observation["reason"] == "ha_unreachable"
    assert (await bridge.propose())["proposals"] == []


async def test_observe_survives_an_adapter_failure(on):
    bridge = HestiaBridge(_runtime(RuntimeError("boom")))

    assert await bridge.observe() == {"status": "degraded", "reason": "house_state_unavailable"}


async def test_house_brain_may_be_an_async_provider(on):
    runtime = _runtime(_empty_house())

    async def provider():
        return runtime

    observation = await HestiaBridge(provider).observe()

    assert observation["status"] == "live"
    assert runtime.adapter.calls == 1


# ── propose ──────────────────────────────────────────────────────────────────


async def test_lights_on_in_an_empty_house_become_hestia_proposals(on):
    runtime = _runtime(_empty_house())
    bridge = HestiaBridge(runtime, clock=lambda: NOW + 1)

    result = await bridge.propose()

    assert result["status"] == "live"
    assert runtime.actuator.calls == [
        ("light.bedroom", "off", "hestia"),
        ("light.living", "off", "hestia"),
    ]
    assert [p["rule"] for p in result["proposals"]] == [RULE_LIGHTS_ON_IN_EMPTY_HOUSE] * 2
    assert all(p["queued"] and p["task_id"] for p in result["proposals"])
    assert {n["note"] for n in result["notes"]} == {"device_unavailable", "reading_stale"}
    assert bridge.status()["proposals_today"] == 2


async def test_an_occupied_house_gets_no_proposal(on):
    occupied = _snapshot([_entity("person.owner", "home", area=""), _entity("light.living", "on")])
    runtime = _runtime(occupied)

    result = await HestiaBridge(runtime).propose()

    assert result["proposals"] == []
    assert runtime.actuator.calls == []


async def test_unknown_occupancy_never_guesses_empty(on):
    runtime = _runtime(_snapshot([_entity("light.living", "on")]))

    result = await HestiaBridge(runtime).propose()

    assert result["occupancy"] == "unknown"
    assert runtime.actuator.calls == []


async def test_cooldown_offers_each_light_once(on):
    clock = [NOW]
    runtime = _runtime(_empty_house(lights=("light.living",)))
    bridge = HestiaBridge(runtime, clock=lambda: clock[0], proposal_cooldown_seconds=600)

    first = await bridge.propose()
    second = await bridge.propose()
    clock[0] += 601
    third = await bridge.propose()

    assert len(first["proposals"]) == 1
    assert second["proposals"] == []
    assert second["skipped"] == [{"entity_id": "light.living", "reason": "proposal_cooldown"}]
    assert len(third["proposals"]) == 1
    assert len(runtime.actuator.calls) == 2


async def test_cycle_and_daily_caps_keep_hestia_quiet(on):
    runtime = _runtime(_empty_house(lights=("light.a", "light.b", "light.c")))
    bridge = HestiaBridge(runtime, max_proposals_per_cycle=2, daily_proposal_cap=3,
                          proposal_cooldown_seconds=0)

    first = await bridge.propose()
    second = await bridge.propose()

    assert len(first["proposals"]) == 2
    assert first["skipped"] == [{"entity_id": "light.c", "reason": "cycle_cap"}]
    assert len(second["proposals"]) == 1
    assert {s["reason"] for s in second["skipped"]} == {"daily_proposal_cap"}
    assert len(runtime.actuator.calls) == 3


async def test_a_refused_proposal_does_not_spend_the_budget(on):
    runtime = _runtime(_empty_house(lights=("light.living",)), actuator=_Actuator(queued=False))
    bridge = HestiaBridge(runtime)

    result = await bridge.propose()

    assert result["proposals"][0]["queued"] is False
    assert result["proposals"][0]["reason"] == "house_state_stale"
    assert bridge.status()["proposals_today"] == 0


async def test_missing_actuator_is_an_honest_skip(on):
    runtime = _runtime(_empty_house(lights=("light.living",)))
    runtime.actuator = None

    result = await HestiaBridge(runtime).propose()

    assert result["proposals"] == []
    assert result["skipped"] == [
        {"entity_id": "light.living", "reason": "house_actuation_unavailable"}
    ]


async def test_proposals_reach_govern_enqueue_as_house_control_from_hestia(on, tmp_path):
    """End-to-end over the REAL HouseActuator: the task lands via govern_enqueue."""
    enqueued = []

    def govern_enqueue(agent, kind, title, **kwargs):
        enqueued.append((agent, kind, title, kwargs))
        return 42

    class _Driver:
        async def apply(self, _command):
            raise AssertionError("a proposal must never actuate")

    adapter = _Adapter(_empty_house(lights=("light.living",)))
    actuator = HouseActuator(
        state_reader=adapter,
        driver=_Driver(),
        enqueue=govern_enqueue,
        ledger_path=tmp_path / "actuation.db",
        clock=lambda: NOW + 1,
    )
    runtime = SimpleNamespace(adapter=adapter, graph=None, actuator=actuator)

    result = await HestiaBridge(runtime, clock=lambda: NOW + 1).propose()

    assert result["proposals"] == [
        {
            "rule": RULE_LIGHTS_ON_IN_EMPTY_HOUSE,
            "entity_id": "light.living",
            "title": "Turn off light.living — nobody is home",
            "agent": "hestia",
            "queued": True,
            "task_id": 42,
            "reason": "",
        }
    ]
    agent, kind, _title, kwargs = enqueued[0]
    assert agent == "hestia"
    assert kind == HOUSE_CONTROL_KIND
    assert kwargs["autonomy_level"] == "ask"
    assert kwargs["payload"]["entity_id"] == "light.living"
    assert kwargs["payload"]["action"] == "off"


# ── ambient hand-off ─────────────────────────────────────────────────────────


async def test_ambient_without_a_strip_refuses_honestly(on):
    bridge = HestiaBridge(_runtime(_empty_house()))

    assert await bridge.ambient("listening") == {"ok": False, "reason": "wled_not_configured"}
    assert bridge.status()["wled"] is None


async def test_ambient_delegates_to_the_wled_bridge(on):
    class _WLED:
        def __init__(self):
            self.scenes = []

        async def set_scene(self, state):
            self.scenes.append(state)
            return {"ok": True, "scene": state, "verified": True}

        def status(self):
            return {"configured": True, "scene": self.scenes[-1] if self.scenes else None}

    wled = _WLED()
    bridge = HestiaBridge(_runtime(_empty_house()), wled=wled)

    result = await bridge.ambient("speaking")

    assert result["ok"] is True
    assert wled.scenes == ["speaking"]
    assert bridge.status()["wled"]["scene"] == "speaking"


async def test_from_orchestrator_binds_a_default_off_wled(monkeypatch, on):
    monkeypatch.delenv("JARVIS_WLED_URL", raising=False)
    runtime = _runtime(_empty_house())

    bridge = HestiaBridge.from_orchestrator(None, runtime_provider=lambda: runtime)

    assert bridge.wled.configured is False
    assert (await bridge.ambient("idle")) == {"ok": False, "reason": "wled_not_configured"}
    assert (await bridge.observe())["status"] == "live"
