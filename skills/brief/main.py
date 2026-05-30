"""
brief/main.py — Friday's morning brief skill (H2.3).

Loader-pattern skill that consolidates weather + news (+ optional market) into
one briefing. Each source degrades independently: if any fails, the brief is
still returned with degraded_mode=True instead of crashing.

Commands (see get_commands):
  brief [location]   — generate the morning briefing
"""

import logging
import os

logger = logging.getLogger("jarvis.skills.brief")

_weather = None
_news = None


def _plugins():
    global _weather, _news
    if _weather is None or _news is None:
        try:
            from agents.core.plugins.weather import WeatherPlugin
            from agents.core.plugins.news import NewsPlugin
        except ImportError:
            from core.plugins.weather import WeatherPlugin
            from core.plugins.news import NewsPlugin
        _weather = _weather or WeatherPlugin()
        _news = _news or NewsPlugin()
    return _weather, _news


def get_commands() -> list[str]:
    return ["brief"]


async def generate_brief(location: str = "") -> dict:
    """Consolidate sources; degraded_mode=True if any source failed."""
    weather_plugin, news_plugin = _plugins()
    degraded = False

    weather = {}
    try:
        raw = await weather_plugin.get_weather(location)
        weather = {"summary": raw.strip()} if raw else {}
        if not weather:
            degraded = True
    except Exception as e:
        logger.warning(f"Brief weather failed: {e}")
        degraded = True

    news = []
    try:
        news = await news_plugin.get_headlines(limit=5)
    except Exception as e:
        logger.warning(f"Brief news failed: {e}")
        degraded = True

    # Market data needs an external API not configured here — left empty.
    market = {}

    return {
        "weather": weather,
        "news": news,
        "market": market,
        "degraded_mode": degraded,
    }


async def brief(args: str = "", context: dict = None) -> str:
    location = (args or "").strip()
    data = await generate_brief(location)
    lines = ["☀️ Brief de dimineață:"]
    w = data["weather"].get("summary") if data["weather"] else None
    lines.append(f"Vreme: {w}" if w else "Vreme: indisponibilă")
    news = data["news"]
    if news:
        lines.append(f"Știri ({len(news)}):")
        for item in news[:5]:
            title = item.get("title", "") if isinstance(item, dict) else str(item)
            if title:
                lines.append(f"- {title}")
    else:
        lines.append("Știri: indisponibile")
    if data["degraded_mode"]:
        lines.append("(unele surse au fost indisponibile)")
    return "\n".join(lines)


async def handle(cmd: str, args: str, context: dict = None) -> str:
    if cmd == "brief":
        return await brief(args, context)
    return f"[brief] comandă necunoscută: {cmd}"
