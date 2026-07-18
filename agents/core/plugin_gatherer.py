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

import asyncio
import logging
from collections.abc import Callable

from .log import log_error
from .errors import E_PLUGIN_BLOCKED, E_PLUGIN_EXEC_FAIL

logger = logging.getLogger("jarvis.orchestrator")

# Live-plugin fan-out tuning. The eligibility checks (keyword match + permission
# gate) are cheap and synchronous; only the awaitable plugin calls run
# concurrently, so a query that triggers several plugins (weather + news +
# calendar …) no longer pays serial network round-trips, and one slow API can't
# stall the whole turn.
PLUGIN_TIMEOUT_S = 8.0
PLUGIN_CONCURRENCY = 6


def first_target_agent(orch, intent) -> str:
    return intent.target_agents[0] if intent.target_agents and len(intent.target_agents) > 0 else "jarvis"


def any_agent_can(orch, plugin: str, intent) -> bool:
    agents = intent.target_agents if intent.target_agents else ["jarvis"]
    return any(orch.permission_gate.check_call(plugin, a) for a in agents)


def wants_signal_layer(text_lower: str, keywords: list[str]) -> bool:
    # Only ground on world-intelligence intent. A bare "news" keyword used to
    # trigger this, which fired a Signal Layer fan-out on any news query and added
    # latency to unrelated requests — require explicit world/global signals instead.
    return (
        "worldview" in keywords
        or any(w in text_lower for w in [
            "world brief", "global brief", "world intelligence", "signal layer",
            "what changed overnight", "changed overnight", "overnight",
            "geopolitic", "country risk", "risk for romania", "risk for uae",
            "romania risk", "uae risk", "external world", "world today",
            "global status", "global risk", "osint", "chokepoint", "suez",
        ])
    )


# Country name/alias → ISO-2 for the watchlist set (the countries that have
# committed replay assessments, so ``country_risk`` resolves real fixture data).
_COUNTRY_ISO2 = {
    "romania": "RO", "uae": "AE", "emirates": "AE", "united states": "US",
    "u.s.": "US", "america": "US", "ukraine": "UA", "israel": "IL",
    "china": "CN", "turkey": "TR", "türkiye": "TR", "india": "IN",
}

# Query-shape vocabularies that route a world-intel ask to the right facade
# method. ``" risk"`` (leading space) catches "<country> risk" without matching
# unrelated substrings; "global risk"/"world today" stay brief-shaped below.
_RISK_PHRASES = ("country risk", "risk for", "risk assessment", "assessment", " risk")
_BRIEF_PHRASES = (
    "world brief", "global brief", "world today", "global status",
    "global risk", "what changed overnight", "changed overnight",
)
_SIGNAL_PHRASES = ("alert", "critical", "chokepoint", "jamming", "dark vessel", "osint")


def _resolve_country_iso2(text_lower: str) -> str:
    """First watchlist country named in the text, as an ISO-2 code (or "")."""
    for name, iso2 in _COUNTRY_ISO2.items():
        if name in text_lower:
            return iso2
    return ""


def _argus(orch):
    """The orchestrator's governed Argus facade, built on demand if absent.

    On ``main`` the orchestrator wires ``orch.argus`` at startup; older branches
    and lightweight test orchestrators may not, so fall back to constructing one
    from the orchestrator's ``permission_gate`` + ``plugins``.
    """
    argus = getattr(orch, "argus", None)
    if argus is None:
        from .argus import ArgusInterface
        argus = ArgusInterface.from_orchestrator(orch)
    return argus


async def _signal_layer_answer(orch, text: str, text_lower: str) -> dict:
    """Route a world-intelligence query through the governed Argus facade.

    Picks the facade method by query intent — country risk, global brief, signal
    feed, or the general World Analyst answer — instead of always calling
    ``ask_world``. Every call passes the egress permission gate inside the facade
    and returns structured ``{"status": ...}`` data; failure is never fabricated
    into a world-intel answer.
    """
    argus = _argus(orch)
    iso2 = _resolve_country_iso2(text_lower)

    # 1. Country risk — a watchlist country plus a risk/assessment-shaped ask.
    if iso2 and any(p in text_lower for p in _RISK_PHRASES):
        return await argus.country_risk(iso2)

    # 2. Global brief — a world-wide ask with no specific country in focus.
    if not iso2 and any(p in text_lower for p in _BRIEF_PHRASES):
        return await argus.world_brief()

    # 3. Signal feed — alert / severity / OSINT-shaped asks.
    if any(p in text_lower for p in _SIGNAL_PHRASES):
        min_sev = "high" if ("critical" in text_lower or "high" in text_lower) else ""
        return await argus.signals(relevant_only=True, country=iso2, min_severity=min_sev)

    # 4. Default — the general World Analyst answer (preserves overnight mode).
    mode = "overnight_brief" if "overnight" in text_lower else "general"
    return await argus.ask_world(text, mode=mode, country=iso2, limit=8)


async def gather_plugin_data(orch, text: str, intent) -> dict:
    """Run every eligible live plugin concurrently and collect their data.

    Eligibility (keyword match + permission gate) is resolved synchronously by
    ``_eligible_plugins``; the awaitable calls then run together under a bounded
    semaphore with a per-plugin deadline. A plugin that times out or raises is
    logged and omitted — it never fails the turn or blocks the others. The
    result dict preserves the original plugin order so the prompt block is
    deterministic.
    """
    specs = _eligible_plugins(orch, text, intent)
    if not specs:
        return {}

    sem = asyncio.Semaphore(PLUGIN_CONCURRENCY)

    async def _run(make_coro: Callable[[], object]):
        async with sem:
            return await asyncio.wait_for(make_coro(), timeout=PLUGIN_TIMEOUT_S)

    results = await asyncio.gather(
        *(_run(make_coro) for _, make_coro in specs),
        return_exceptions=True,
    )

    data: dict = {}
    for (key, _), result in zip(specs, results):
        if isinstance(result, BaseException):
            log_error(logger, E_PLUGIN_EXEC_FAIL, name=key, detail=repr(result))
            continue
        data[key] = result
    return data


def _eligible_plugins(orch, text: str, intent) -> list[tuple[str, Callable[[], object]]]:
    """Keyword + permission gating (cheap, synchronous).

    Returns ordered ``(result_key, coroutine_factory)`` specs for every plugin
    that should run this turn. Each factory, when called, returns the plugin's
    coroutine — deferred so ``gather_plugin_data`` can await them concurrently.
    Permission-blocked plugins are logged here, exactly as before.
    """
    keywords = intent.context.get("keywords_found", [])
    text_lower = text.lower()
    specs: list[tuple[str, Callable[[], object]]] = []

    if "weather" in keywords or any(w in text_lower for w in ["weather", "vremea", "temperature", "ploaie", "temperatura"]):
        if any_agent_can(orch, "weather", intent):
            wp = orch.plugins.get("weather")
            if wp:
                location = extract_location(text)
                specs.append(("weather", lambda wp=wp, loc=location: wp.get_weather(loc)))
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
                specs.append(("news", lambda np=np, cat=category: np.summarize(cat)))
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="news")

    if "calendar" in keywords or any(w in text_lower for w in ["calendar", "agenda", "program", "sedin", "meeting", "eveniment"]):
        if any_agent_can(orch, "google-calendar", intent):
            gp = orch.plugins.get("google-calendar")
            if gp and gp.access_token:
                specs.append(("calendar", lambda gp=gp: gp.get_today_events()))

    if "email" in keywords or any(w in text_lower for w in ["email", "mail", "inbox", "mesaj", "hangup", "prim"]):
        if any_agent_can(orch, "gmail", intent):
            gp = orch.plugins.get("gmail")
            if gp and gp.access_token:
                specs.append(("email", lambda gp=gp: gp.list_messages(max_results=5)))

    if "research" in keywords or "search" in keywords or any(w in text_lower for w in ["research", "caut", "search", "find", "gaseste", "investigheaza"]):
        if any_agent_can(orch, "websearch", intent):
            wp = orch.plugins.get("websearch")
            if wp:
                specs.append(("websearch", lambda wp=wp: wp.search(text, max_results=5)))

    if "worldview" in keywords or any(w in text_lower for w in [
        "satellite", "satelit", "recon", "overflight", "overpass", "satpass",
        "geospatial", "osint", "hormuz", "strait", "dark vessel",
        "jamming", "bruiaj", "footprint", "overhead pass",
    ]):
        if any_agent_can(orch, "worldview", intent):
            wv = orch.plugins.get("worldview")
            if wv:
                # Route through the governed facade so the WorldView recon shares
                # one gated path with the rest of world-intel (recon_overview
                # accepts the facade's optional ``lead`` arg).
                specs.append(("worldview", lambda: _argus(orch).recon_overview()))
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="worldview")

    if any(w in text_lower for w in ["revenue", "mrr", "subscription", "subscriptions",
                                     "venituri", "abonament", "abonamente", "revenuecat"]):
        if any_agent_can(orch, "revenuecat", intent):
            rc = orch.plugins.get("revenuecat")
            if rc and rc.available():
                specs.append(("revenue", lambda rc=rc: rc.overview_text()))
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="revenuecat")

    if any(w in text_lower for w in ["ad spend", "meta ads", "facebook ads", "advertising",
                                     "campaign", "campaigns", "campanii", "reclame"]):
        if any_agent_can(orch, "meta-ads", intent):
            ma = orch.plugins.get("meta-ads")
            if ma and ma.available():
                specs.append(("ads", lambda ma=ma: ma.insights_text()))
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="meta-ads")

    if any(w in text_lower for w in ["scheduled posts", "social queue", "content calendar",
                                     "postari programate", "calendar de continut", "postiz"]):
        if any_agent_can(orch, "postiz", intent):
            pz = orch.plugins.get("postiz")
            if pz and pz.available():
                specs.append(("social-schedule", lambda pz=pz: pz.queue_text()))
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="postiz")

    if wants_signal_layer(text_lower, keywords):
        if any_agent_can(orch, "signal-layer", intent):
            # Runs in the concurrent fan-out like every other plugin; the call
            # itself never raises (it returns structured {"status": ...} on error).
            specs.append(("signal-layer", lambda: _signal_layer_answer(orch, text, text_lower)))
        else:
            log_error(logger, E_PLUGIN_BLOCKED, name="signal-layer")

    return specs


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
