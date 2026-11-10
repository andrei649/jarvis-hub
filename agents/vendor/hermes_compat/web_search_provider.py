"""``agent.web_search_provider`` for vendored code: the base class and the key lookup.

:class:`WebSearchProvider` is the upstream ABC's surface (identity, picker schema,
``is_available`` / ``search`` / ``extract`` and the ``supports_*`` flags). The adapter in
``plugin_ctx`` maps an instance onto Nerva's ``SearchProvider``.

:func:`get_provider_env` replaces upstream's config-aware lookup (``os.environ``, then
``~/.hermes/.env``, with profile secret scopes). In Nerva a provider key is an env setting
read at call time through ``agents.core.env_config``, the path ``TAVILY_API_KEY`` takes,
and only for the names in :data:`PROVIDER_KEYS`: any other name reads as unset, so an
adopted file can never pick up another integration's key. Values are never logged.
"""

from __future__ import annotations

import abc
from typing import Any

from agents.core.env_config import env_str

#: Keys the adopted providers may read (documented in .env.example and docs/WEB_SEARCH.md).
PROVIDER_KEYS = frozenset({"EXA_API_KEY", "BRAVE_SEARCH_API_KEY", "PARALLEL_API_KEY"})


def get_provider_env(name: str) -> str:
    """The stripped value of an allowlisted provider key, or ``""``."""
    if name not in PROVIDER_KEYS:
        return ""
    return str(env_str(name, "") or "").strip()


class WebSearchProvider(abc.ABC):
    """Upstream's web search/extract provider ABC, with ``ProviderBase`` folded in."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable short identifier."""

    @property
    def display_name(self) -> str:
        return self.name

    def get_setup_schema(self) -> dict[str, Any]:
        return {"name": self.display_name, "badge": "", "tag": "", "env_vars": []}

    @abc.abstractmethod
    def is_available(self) -> bool:
        """True when the provider can answer (a cheap check, no network)."""

    def supports_search(self) -> bool:
        return True

    def is_keyless_available(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not support search")

    def extract(self, urls: list[str], **kwargs: Any) -> Any:
        raise NotImplementedError(f"{self.name} does not support extract")
