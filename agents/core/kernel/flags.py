"""flags.py — ORIZONT-24 Action Kernel feature gate.

The kernel ships **default-OFF**: every privileged action keeps its current path
until ``JARVIS_ACTION_KERNEL=1`` opts the process in. Mirrors the
``JARVIS_STRICT_EGRESS`` env-parse convention in ``http_client.py`` so the
migration is incremental and reversible (the H22.x kill-switch discipline).
"""

from __future__ import annotations

import os

_TRUE = ("1", "true", "yes", "on")


def kernel_enabled() -> bool:
    """True when the Action Kernel should mediate privileged actions.

    Default ``"0"`` → OFF. Brokers gate their kernel hook behind this so an unset
    env skips the hook entirely (structural default-off equivalence, not a no-op).
    """
    return os.environ.get("JARVIS_ACTION_KERNEL", "0").strip().lower() in _TRUE
