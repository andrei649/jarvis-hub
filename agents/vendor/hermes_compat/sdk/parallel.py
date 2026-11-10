"""``parallel.Parallel`` as the vendored Parallel provider uses it: ``beta.search``.

``POST https://api.parallel.ai/v1beta/search`` with the key in ``x-api-key`` and the beta
header (Parallel's documented Search API); results expose ``url`` / ``title`` /
``excerpts`` like the SDK's result objects. ``AsyncParallel`` (extract) is not provided.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agents.vendor.hermes_compat import httpx

API_BASE = "https://api.parallel.ai"
BETA_HEADER = "search-extract-2025-10-10"
TIMEOUT_SECONDS = 60


class _Beta:
    def __init__(self, api_key: str) -> None:
        self._headers = {"x-api-key": str(api_key or ""), "parallel-beta": BETA_HEADER,
                         "Content-Type": "application/json"}

    def __repr__(self) -> str:  # never show the key
        return "<Parallel.beta (compat)>"

    def search(self, *, objective: str | None = None, search_queries: list[str] | None = None,
               mode: str | None = None, max_results: int | None = None,
               **_unused: Any) -> SimpleNamespace:
        body = {key: value for key, value in (
            ("objective", objective), ("search_queries", search_queries),
            ("mode", mode), ("max_results", max_results)) if value is not None}
        resp = httpx.post(f"{API_BASE}/v1beta/search", json=body, headers=dict(self._headers),
                          timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("results") if isinstance(data, dict) else None
        results = [
            SimpleNamespace(url=r.get("url"), title=r.get("title"),
                            excerpts=list(r.get("excerpts") or []))
            for r in rows or [] if isinstance(r, dict)
        ]
        return SimpleNamespace(results=results)


class Parallel:
    def __init__(self, api_key: str) -> None:
        self.beta = _Beta(api_key)

    def __repr__(self) -> str:
        return "<Parallel (compat)>"
