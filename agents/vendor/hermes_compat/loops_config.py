"""``hermes_cli.config`` for the vendored ``hermes_cli/loops.py`` (rule ``hermes-cli-config``).

The loop module reads one section, ``loops`` (``min_interval_seconds``, ``max_ticks``,
``self_paced_floor_seconds``, ``self_paced_ceiling_seconds``), and clamps every value
itself. Nerva has no ``config.yaml``: the section is empty, so the upstream defaults
apply (a 30 s floor for a fixed cadence, a 100-tick backstop, self-paced 60 s → 15 min).
Nerva's driver (``agents/core/session_loops.py``) may narrow them for one process with
:func:`set_loops_overrides`; nothing here can widen a floor below upstream's own clamp,
because ``loops.py`` clamps after reading.
"""

from __future__ import annotations

from typing import Any

_ALLOWED = frozenset({"min_interval_seconds", "max_ticks", "self_paced_floor_seconds",
                      "self_paced_ceiling_seconds"})
_overrides: dict[str, int] = {}


def set_loops_overrides(values: dict[str, int] | None) -> None:
    """Replace the process-wide ``loops`` section (tests and the driver; ints only)."""
    _overrides.clear()
    for key, value in (values or {}).items():
        if key in _ALLOWED and type(value) is int:
            _overrides[key] = value


def load_config() -> dict[str, Any]:
    return {"loops": dict(_overrides)}
