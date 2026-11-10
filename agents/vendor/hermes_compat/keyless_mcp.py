"""``plugins.web.keyless_mcp`` for vendored code: the keyless ring stays off.

Upstream Exa and Parallel can answer without a key through public MCP endpoints. In Nerva
a search goes only to a backend the owner configured (``web_providers``: a keyless provider
is never "configured" for unattended callers), so the adopted providers are keyed only and
the ring is never entered.
"""

from __future__ import annotations

from typing import Any


def use_keyless(name: str, api_key: str) -> bool:
    return False


def keyless_enabled() -> bool:
    return False


def provider_tier(name: str) -> str:
    return "paid"


def search_with_failover(name: str, query: str, limit: int) -> dict[str, Any]:
    return {"success": False, "error": "keyless search is not available in Nerva"}


def extract_with_failover(name: str, urls: list[str]) -> list[dict[str, Any]]:
    return [{"url": u, "title": "", "content": "",
             "error": "keyless extract is not available in Nerva"} for u in urls]
