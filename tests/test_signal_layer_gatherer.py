"""Tests for Signal Layer prompt grounding via plugin_gatherer.

The gatherer routes world-intelligence queries through the governed Argus facade
(``orch.argus``) and picks the facade method by query intent — country risk,
global brief, signal feed, or the general World Analyst answer — instead of
always calling ``ask_world``.
"""

from types import SimpleNamespace

from agents.core import plugin_gatherer
from agents.core.plugin_gate import PermissionGate


class _SignalLayerStub:
    """Records which facade-backed method the gatherer routed to."""

    def __init__(self):
        self.calls = []

    async def ask_world(self, question, mode="general", country="", limit=8):
        self.calls.append({"method": "ask_world", "question": question,
                           "mode": mode, "country": country, "limit": limit})
        return {"status": "ok", "answer": "World analyst answer",
                "mode": mode, "country": country, "freshness": {"stale": False}}

    async def world_brief(self):
        self.calls.append({"method": "world_brief"})
        return {"status": "ok", "brief": {"summary": "Replay-backed world brief"}}

    async def country_assessment(self, iso2):
        self.calls.append({"method": "country_assessment", "iso2": iso2})
        return {"status": "ok", "assessment": {"subject": iso2, "score": 42}}

    async def signals(self, limit=20, relevant_only=True, signal_type="",
                      country="", min_severity=""):
        self.calls.append({"method": "signals", "relevant_only": relevant_only,
                           "country": country, "min_severity": min_severity})
        return {"status": "ok", "count": 0, "signals": []}


def _orch(plugin, *, agents=("jarvis",)):
    # No ``argus`` attr → the gatherer builds the facade from gate + plugins.
    orch = SimpleNamespace(permission_gate=PermissionGate(),
                           plugins={"signal-layer": plugin})
    intent = SimpleNamespace(target_agents=list(agents), context={"keywords_found": []})
    return orch, intent


async def test_overnight_world_brief_routes_to_world_brief():
    plugin = _SignalLayerStub()
    orch, intent = _orch(plugin)

    data = await plugin_gatherer.gather_plugin_data(
        orch, "What changed overnight that matters to me?", intent)

    assert data["signal-layer"]["status"] == "ok"
    assert plugin.calls[0]["method"] == "world_brief"


async def test_country_risk_routes_to_country_assessment():
    plugin = _SignalLayerStub()
    orch, intent = _orch(plugin, agents=("argus",))

    data = await plugin_gatherer.gather_plugin_data(
        orch, "What is the country risk for Romania?", intent)

    assert data["signal-layer"]["status"] == "ok"
    assert plugin.calls[0] == {"method": "country_assessment", "iso2": "RO"}


async def test_country_risk_resolves_extended_watchlist():
    plugin = _SignalLayerStub()
    orch, intent = _orch(plugin, agents=("argus",))

    await plugin_gatherer.gather_plugin_data(
        orch, "what is the country risk for Ukraine?", intent)

    assert plugin.calls[0] == {"method": "country_assessment", "iso2": "UA"}


async def test_alert_query_routes_to_signals_feed():
    plugin = _SignalLayerStub()
    orch, intent = _orch(plugin)

    await plugin_gatherer.gather_plugin_data(
        orch, "any critical chokepoint signals right now?", intent)

    assert plugin.calls[0]["method"] == "signals"
    assert plugin.calls[0]["relevant_only"] is True
    assert plugin.calls[0]["min_severity"] == "high"


async def test_generic_world_intent_falls_back_to_ask_world():
    plugin = _SignalLayerStub()
    orch, intent = _orch(plugin)

    # "geopolitic" triggers the world-intel fan-out but matches no
    # risk/brief/signal shape, so it defaults to the World Analyst answer.
    await plugin_gatherer.gather_plugin_data(
        orch, "what's the geopolitical picture?", intent)

    assert plugin.calls[0]["method"] == "ask_world"
    assert plugin.calls[0]["mode"] == "general"
    assert plugin.calls[0]["limit"] == 8


def test_signal_layer_gatherer_formats_data_block():
    text = plugin_gatherer.format_plugin_data({"signal-layer": {"answer": "World brief"}})
    assert "REAL-TIME DATA" in text
    assert "SIGNAL-LAYER" in text
    assert "World brief" in text


def test_wants_signal_layer_ignores_generic_news():
    # A plain news query must NOT fan out to the Signal Layer.
    assert plugin_gatherer.wants_signal_layer("any local news today", ["news"]) is False
    assert plugin_gatherer.wants_signal_layer("what's the latest celebrity news", []) is False


def test_wants_signal_layer_triggers_on_world_intent():
    assert plugin_gatherer.wants_signal_layer("give me a world brief", []) is True
    assert plugin_gatherer.wants_signal_layer("what is the country risk for romania", []) is True
    assert plugin_gatherer.wants_signal_layer("what changed overnight", []) is True
    # WorldView OSINT surface keyword stays an explicit trigger.
    assert plugin_gatherer.wants_signal_layer("open the map", ["worldview"]) is True


def test_resolve_country_iso2_covers_watchlist():
    assert plugin_gatherer._resolve_country_iso2("risk for romania") == "RO"
    assert plugin_gatherer._resolve_country_iso2("united states outlook") == "US"
    assert plugin_gatherer._resolve_country_iso2("israel assessment") == "IL"
    assert plugin_gatherer._resolve_country_iso2("no country here") == ""
