"""Tests for Signal Layer prompt grounding via plugin_gatherer."""

from types import SimpleNamespace

from agents.core import plugin_gatherer
from agents.core.plugin_gate import PermissionGate


class _SignalLayerStub:
    def __init__(self):
        self.calls = []

    async def ask_world(self, question, mode="general", country="", limit=8):
        self.calls.append({"question": question, "mode": mode, "country": country, "limit": limit})
        return {
            "status": "ok",
            "answer": "Replay-backed world brief",
            "mode": mode,
            "country": country,
            "freshness": {"stale": False},
        }


async def test_signal_layer_gatherer_triggers_for_overnight_world_brief():
    plugin = _SignalLayerStub()
    orch = SimpleNamespace(permission_gate=PermissionGate(), plugins={"signal-layer": plugin})
    intent = SimpleNamespace(target_agents=["jarvis"], context={"keywords_found": []})

    data = await plugin_gatherer.gather_plugin_data(orch, "What changed overnight that matters to me?", intent)

    assert "signal-layer" in data
    assert data["signal-layer"]["status"] == "ok"
    assert plugin.calls[0]["mode"] == "overnight_brief"
    assert plugin.calls[0]["limit"] == 8


async def test_signal_layer_gatherer_extracts_country_for_romania_risk():
    plugin = _SignalLayerStub()
    orch = SimpleNamespace(permission_gate=PermissionGate(), plugins={"signal-layer": plugin})
    intent = SimpleNamespace(target_agents=["argus"], context={"keywords_found": []})

    data = await plugin_gatherer.gather_plugin_data(orch, "What is the country risk for Romania?", intent)

    assert data["signal-layer"]["country"] == "RO"
    assert plugin.calls[0]["country"] == "RO"


def test_signal_layer_gatherer_formats_data_block():
    text = plugin_gatherer.format_plugin_data({"signal-layer": {"answer": "World brief"}})
    assert "REAL-TIME DATA" in text
    assert "SIGNAL-LAYER" in text
    assert "World brief" in text
