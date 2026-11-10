"""The ``os`` name vendored code sees (rewrite rule ``os-env``): ``getenv`` and ``environ.get``.

Reads go through ``agents.core.env_config.env_str`` at call time, and only for the names in
:data:`ALLOWED` for the provider the adapter is running (``provider_scope``): documented,
non-secret settings of that provider. Any other name, or a read outside a provider scope,
reads as unset. Every other ``os`` attribute is absent on purpose: an AttributeError is a
loud failure the tests catch, not an unreviewed side effect.
"""

from __future__ import annotations

from agents.core.env_config import env_str
from agents.vendor.hermes_compat.web_search_provider import current_provider

#: Non-secret settings each adopted provider may read (see docs/hermes/ADOPT_LANE.md).
ALLOWED: dict[str, frozenset[str]] = {"parallel": frozenset({"PARALLEL_SEARCH_MODE"})}


def getenv(name: str, default: str | None = None) -> str | None:
    if name not in ALLOWED.get(current_provider(), frozenset()):
        return default
    value = env_str(name, "")
    return value if value else default


class _Environ:
    """``os.environ`` reduced to ``get`` under the same allowlist as :func:`getenv` (G19:
    the FAL video plugin reads ``os.environ.get("FAL_VIDEO_MODEL")``, which is not allowed,
    so it reads as unset and the family the owner approved is the one used)."""

    def get(self, name: str, default: str | None = None) -> str | None:
        return getenv(name, default)

    def __repr__(self) -> str:
        return "<os.environ (compat, allowlisted get only)>"


environ = _Environ()
