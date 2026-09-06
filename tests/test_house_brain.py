"""House Brain package surface — Hestia's binding sits beside the ORIZONT 30 modules.

Pins that ``agents.core.house`` exports the Hestia/WLED binding next to the
adapter/graph/actuation substrate it wires onto, and that the orchestrator
binding path (``HestiaBridge.from_orchestrator``) is default-off end to end:
with the flag unset nothing is read, and with the flag on but the House Brain
itself disabled the answer is the house's own ``disabled`` reason — never a
fabricated picture of the building.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[1]
for entry in (str(repo_root), str(repo_root / "agents")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agents.core import house  # noqa: E402
from agents.core.house.contracts import HouseSnapshot  # noqa: E402


def test_package_exports_the_hestia_binding_next_to_the_substrate():
    for name in (
        "HouseActuator",
        "HouseGraph",
        "HomeAssistantAdapter",
        "HestiaBridge",
        "WLEDBridge",
        "WLEDConfigError",
        "WLED_SCENES",
        "WLED_URL_ENV",
        "HESTIA_BRIDGE_ENV",
        "hestia_bridge_enabled",
    ):
        assert name in house.__all__, name
        assert getattr(house, name) is not None
    assert house.HESTIA_BRIDGE_ENV == "JARVIS_HESTIA_BRIDGE"
    assert house.WLED_URL_ENV == "JARVIS_WLED_URL"


class _DisabledAdapter:
    def __init__(self):
        self.calls = 0

    async def snapshot(self):
        self.calls += 1
        return HouseSnapshot(
            enabled=False, status="disabled", observed_at=0.0, reason="house_brain_disabled"
        )


async def test_orchestrator_binding_is_default_off(monkeypatch):
    monkeypatch.delenv(house.HESTIA_BRIDGE_ENV, raising=False)
    monkeypatch.delenv(house.WLED_URL_ENV, raising=False)
    adapter = _DisabledAdapter()
    runtime = SimpleNamespace(adapter=adapter, graph=None, actuator=None)

    bridge = house.HestiaBridge.from_orchestrator(None, runtime_provider=lambda: runtime)
    observed = await bridge.observe()

    assert observed["status"] == "disabled"
    assert observed["reason"] == "hestia_bridge_disabled"
    assert adapter.calls == 0
    assert bridge.wled.configured is False


async def test_binding_reports_a_disabled_house_as_disabled(monkeypatch):
    monkeypatch.setenv(house.HESTIA_BRIDGE_ENV, "1")
    adapter = _DisabledAdapter()
    runtime = SimpleNamespace(adapter=adapter, graph=None, actuator=None)

    bridge = house.HestiaBridge.from_orchestrator(None, runtime_provider=lambda: runtime)
    observed = await bridge.observe()
    proposed = await bridge.propose()

    assert observed == {"status": "disabled", "reason": "house_brain_disabled", "observed_at": 0.0}
    assert proposed["status"] == "disabled"
    assert proposed["proposals"] == []
    assert adapter.calls == 2
