"""
web_research/main.py — Vision's web research skill (H2.9).

Loader-pattern skill that searches the web, extracts content, and returns a
structured report with source citations. Uses WebSearchPlugin under the hood
with Tavily / SearXNG / DuckDuckGo fallback.

Commands (see get_commands):
  research [query]  — web research with cited sources
"""

import logging

logger = logging.getLogger("jarvis.skills.web_research")


def _get_plugin():
    try:
        from agents.core.plugins.websearch import WebSearchPlugin
    except ImportError:
        from core.plugins.websearch import WebSearchPlugin
    return WebSearchPlugin()


def get_commands() -> list[str]:
    return ["research"]


async def research(args: str = "", context: dict = None) -> str:
    query = (args or "").strip()
    if not query:
        return (
            "Folosire: research <interogare>\n"
            "Exemplu: research piața MarTech CEE"
        )

    plugin = None
    try:
        plugin = _get_plugin()
    except Exception as e:
        logger.error(f"WebSearchPlugin indisponibil: {e}")
        return "Eroare: pluginul de căutare web este indisponibil."

    try:
        results = await plugin.search(query, max_results=8)
    except Exception as e:
        logger.error(f"Căutare eșuată: {e}")
        return f"Eroare la căutarea web: {e}"

    if not results:
        return (
            f"Niciun rezultat găsit pentru: „{query}”.\n"
            "Verifică termenii de căutare sau încearcă din nou."
        )

    lines = [f'🔍 Rezultate cercetare: "{query}"', "─" * 60]

    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        snippet = r.get("snippet", "").strip()
        url = r.get("url", "").strip()

        lines.append(f"{i}. {title or '[fără titlu]'}")

        if snippet:
            lines.append(f"   {snippet[:500]}")

        if url:
            lines.append(f"   🔗 {url}")

        lines.append("")

    lines.append("─" * 60)
    lines.append(f"S-au găsit {len(results)} rezultate.")
    return "\n".join(lines)


async def handle(cmd: str, args: str, context: dict = None) -> str:
    if cmd == "research":
        return await research(args, context)
    return f"[web_research] comandă necunoscută: {cmd}"
