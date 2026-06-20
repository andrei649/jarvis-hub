"""plugin_gatherer.py — live-plugin data gathering extracted from the Orchestrator (CLN-2).

Owns the keyword-triggered fan-out to the real-time plugins (weather, news,
calendar, gmail, websearch, worldview, signal-layer), the small location heuristic,
the prompt block formatter, and the two routing helpers it depends on. Every
function takes the orchestrator as an explicit collaborator and reads its live state
(``plugins``, ``permission_gate``) at call time — the same delegation pattern as
SchedulerService / ChannelManager.

``gather_plugin_data`` stays reachable as a bound entrypoint on the orchestrator
(``Orchestrator._gather_plugin_data`` delegates here) because the request
lifecycle calls ``self._gather_plugin_data(...)`` and tests replace it as a bound
method. ``any_agent_can`` / ``first_target_agent`` are likewise re-exposed as thin
orchestrator wrappers (called directly in test_routing).
"""

from __future__ import annotations

import logging

from .log import log_error
from .errors import E_PLUGIN_BLOCKED

logger = logging.getLogger("jarvis.orchestrator")


def first_target_agent(orch, intent) -> str:
    return intent.target_agents[0] if intent.target_agents and len(intent.target_agents) > 0 else "jarvis"


def any_agent_can(orch, plugin: str, intent) -> bool:
    agents = intent.target_agents if intent.target_agents else ["jarvis"]
    return any(orch.permission_gate.check_call(plugin, a) for a in agents)


def wants_signal_layer(text_lower: str, keywords: list[str]) -> bool:
    return (
        "worldview" in keywords
        or "news" in keywords
        or any(w in text_lower for w in [
            "world brief", "global brief", "world intelligence", "signal layer",
            "what changed overnight", "changed overnight", "overnight",
            "geopolitic", "country risk", "risk for romania", "risk for uae",
            "romania risk", "uae risk", "external world", "world today",
            "global status", "global risk", "osint", "chokepoint", "suez",
        ])
    )


async def _signal_layer_answer(orch, text: str, text_lower: str) -> dict:
    """Ask the local Signal Layer for an evidence-backed world answer.

    The orchestrator may not have registered the plugin yet on older branches, so
    this function lazily instantiates the read-only client. Failure is returned as
    structured plugin data and never fabricated into a world-intel answer.
    """
    plugin = orch.plugins.get("signal-layer")
    if plugin is None:
        try:
            from .plugins.signal_layer import SignalLayerPlugin
            plugin = SignalLayerPlugin()
            orch.plugins["signal-layer"] = plugin
        except Exception as e:
            return {"status": "unavailable", "error": f"SignalLayerPlugin unavailable: {e}"}

    mode = "overnight_brief" if "overnight" in text_lower else "general"
    country = "RO" if "romania" in text_lower else "AE" if "uae" in text_lower or "emirates" in text_lower else ""
    try:
        return await plugin.ask_world(text, mode=mode, country=country, limit=8)
    except Exception as e:
        return {"status": "unavailable", "error": str(e), "provider": "signal-layer"}


async def gather_plugin_data(orch, text: str, intent) -> dict:
    data = {}
    keywords = intent.context.get("keywords_found", [])
    text_lower = text.lower()

    if "weather" in keywords or any(w in text_lower for w in ["weather", "vremea", "temperature", "ploaie", "temperatura"]):
        if any_agent_can(orch, "weather", intent):
            wp = orch.plugins.get("weather")
            if wp:
                location = extract_location(text)
                data["weather"] = await wp.get_weather(location)
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="weather")

    if "news" in keywords or any(w in text_lower for w in ["news", "stiri", "headlines", "noutati"]):
        if any_agent_can(orch, "news", intent):
            np = orch.plugins.get("news")
            if np:
                category = "general"
                if any(w in text_lower for w in ["tech", "technology", "tehnologie"]):
                    category = "technology"
                elif any(w in text_lower for w in ["business", "afaceri"]):
                    category = "business"
                data["news"] = await np.summarize(category)
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="news")

    if "calendar" in keywords or any(w in text_lower for w in ["calendar", "agenda", "program", "sedin", "meeting", "eveniment"]):
        if any_agent_can(orch, "google-calendar", intent):
            gp = orch.plugins.get("google-calendar")
            if gp and gp.access_token:
                data["calendar"] = await gp.get_today_events()

    if "email" in keywords or any(w in text_lower for w in ["email", "mail", "inbox", "mesaj", "hangup", "prim"]):
        if any_agent_can(orch, "gmail", intent):
            gp = orch.plugins.get("gmail")
            if gp and gp.access_token:
                data["email"] = await gp.list_messages(max_results=5)

    if "research" in keywords or "search" in keywords or any(w in text_lower for w in ["research", "caut", "search", "find", "gaseste", "investigheaza"]):
        if any_agent_can(orch, "websearch", intent):
            wp = orch.plugins.get("websearch")
            if wp:
                data["websearch"] = await wp.search(text, max_results=5)

    if "worldview" in keywords or any(w in text_lower for w in [
        "satellite", "satelit", "recon", "overflight", "overpass", "satpass",
        "geospatial", "osint", "hormuz", "strait", "dark vessel",
        "jamming", "bruiaj", "footprint", "overhead pass",
    ]):
        if any_agent_can(orch, "worldview", intent):
            wv = orch.plugins.get("worldview")
            if wv:
                data["worldview"] = await wv.recon_overview()
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="worldview")

    if wants_signal_layer(text_lower, keywords):
        if any_agent_can(orch, "signal-layer", intent):
            data["signal-layer"] = await _signal_layer_answer(orch, text, text_lower)
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="signal-layer")

    return data


def extract_location(text: str) -> str:
    text_lower = text.lower()
    for kw in ["in ", "la ", "pentru ", "din "]:
        if kw in text_lower:
            idx = text_lower.index(kw) + len(kw)
            rest = text[idx:].strip().rstrip("?.!")
            if rest and not rest.startswith(("the", "a", "an", "my")):
                return rest
    return ""


def format_plugin_data(data: dict) -> str:
    if not data:
        return ""
    blocks = []
    for key, value in data.items():
        if value:
            blocks.append(f"[REAL-TIME DATA — {key.upper()}]:\n{value}")
    return "\n\n".join(blocks) + "\n\n" if blocks else ""
