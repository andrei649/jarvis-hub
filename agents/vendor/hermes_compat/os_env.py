"""The ``os`` name vendored code sees (rewrite rule ``os-env``): ``getenv`` only.

Reads go through ``agents.core.env_config.env_str`` at call time, and only for the names in
:data:`ALLOWED` (documented settings of the adopted providers). Any other name reads as
unset, so a vendored file cannot read a key it was not adopted for. Every other ``os``
attribute is absent on purpose: an AttributeError is a loud failure the tests catch, not
an unreviewed side effect.
"""

from __future__ import annotations

from agents.core.env_config import env_str

#: Non-secret settings vendored code may read (see docs/hermes/ADOPT_LANE.md).
ALLOWED = frozenset({"PARALLEL_SEARCH_MODE"})


def getenv(name: str, default: str | None = None) -> str | None:
    if name not in ALLOWED:
        return default
    value = env_str(name, "")
    return value if value else default
