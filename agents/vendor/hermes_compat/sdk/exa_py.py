"""``exa_py.Exa`` as the vendored Exa provider uses it: ``search`` and ``headers``.

``POST https://api.exa.ai/search`` with the key in ``x-api-key`` (Exa's documented REST
API); results expose ``url`` / ``title`` / ``highlights`` like the SDK's result objects.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agents.vendor.hermes_compat import httpx

API_BASE = "https://api.exa.ai"
TIMEOUT_SECONDS = 30


class Exa:
    def __init__(self, api_key: str) -> None:
        # Kept in ``headers`` as the SDK does (the vendored code adds its integration tag).
        self.headers: dict[str, str] = {"x-api-key": str(api_key or ""),
                                        "Content-Type": "application/json"}

    def __repr__(self) -> str:  # never show the key
        return "<Exa (compat)>"

    def search(self, query: str, *, num_results: int = 10, contents: Any = None,
               **_unused: Any) -> SimpleNamespace:
        body: dict[str, Any] = {"query": str(query), "numResults": int(num_results)}
        if contents:
            body["contents"] = contents
        resp = httpx.post(f"{API_BASE}/search", json=body, headers=dict(self.headers),
                          timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("results") if isinstance(data, dict) else None
        results = [
            SimpleNamespace(url=r.get("url"), title=r.get("title"),
                            highlights=list(r.get("highlights") or []), text=r.get("text"))
            for r in rows or [] if isinstance(r, dict)
        ]
        return SimpleNamespace(results=results)
