"""G12 — the owner's switch and the per-key limits of the OpenAI-compatible API.

The API is off until the owner turns ``openai_api.enabled`` on (Settings, or
``nerva config set openai_api.enabled true``). It is an ordinary setting, so an administrator
can pin it either way in the managed ``config.yaml`` (G1, ``agents/core/managed_scope.py``) and
the owner's writers then refuse to move it. The switch is read on every request and fails
closed: a settings store that cannot be read keeps the API off.

Limits, each per key, read per request and clamped to sane bounds:

- ``rate_limit_per_min``: requests a key may start in a sliding minute (429 past it);
- ``max_concurrent``: turns one key may run at once (429 past it);
- ``max_request_kb``: the largest request body accepted (413 past it);
- ``max_input_chars``: the largest text one turn may hand Nerva after the client's system
  messages and history are folded in (413 past it).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger("nerva.openai_api")

CATEGORY = "openai_api"
WINDOW_SECONDS = 60.0
#: a concurrent-turn slot nothing released is dropped after this long (longer than any turn)
LEASE_SECONDS = 1800.0

#: name -> (default, minimum, maximum)
_BOUNDS = {
    "rate_limit_per_min": (20, 1, 600),
    "max_concurrent": (2, 1, 16),
    "max_request_kb": (256, 4, 4096),
    "max_input_chars": (16_000, 256, 200_000),
}


@dataclass(frozen=True)
class Limits:
    rate_limit_per_min: int
    max_concurrent: int
    max_request_bytes: int
    max_input_chars: int


def enabled() -> bool:
    """Whether the owner turned the API on (fails closed: unreadable settings mean off).

    Safe mode (``JARVIS_SAFE_MODE``, H275/H490) keeps it off whatever the setting says: like
    the inbound webhook receiver, it is a door the owner opened, and safe mode only takes away."""
    try:
        from agents.core import safe_mode

        if safe_mode.enabled():
            return False
    except Exception:
        return False
    try:
        from agents.core import settings_db

        found, value = settings_db.read_setting(CATEGORY, "enabled")
    except Exception:
        logger.warning("openai_api: settings unreadable; the API stays off")
        return False
    return found and value is True


def _bounded(name: str) -> int:
    default, low, high = _BOUNDS[name]
    try:
        from agents.core import settings_db

        value = settings_db.get_value(CATEGORY, name, default)
    except Exception:
        return default
    if type(value) is float and value.is_integer():
        value = int(value)
    if type(value) is not int:
        return default
    return max(low, min(high, value))


def limits() -> Limits:
    return Limits(
        rate_limit_per_min=_bounded("rate_limit_per_min"),
        max_concurrent=_bounded("max_concurrent"),
        max_request_bytes=_bounded("max_request_kb") * 1024,
        max_input_chars=_bounded("max_input_chars"),
    )


class KeyGate:
    """Per-key sliding-window rate limit and concurrent-turn cap (in memory, per process).

    A concurrent-turn slot is a lease: released when the turn ends, and dropped after
    :data:`LEASE_SECONDS` in any case, so a streamed response whose client vanished before
    the stream began (its generator never ran, so nothing released the slot) cannot lock the
    key out for good."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = {}
        self._running: dict[str, dict[int, float]] = {}
        self._next = 0

    def allow(self, key_id: str, per_minute: int, *, now: float | None = None) -> bool:
        """Count one request for ``key_id``; False once it is over ``per_minute``."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key_id, deque())
            while hits and hits[0] <= now - WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= per_minute:
                return False
            hits.append(now)
            return True

    def acquire(self, key_id: str, cap: int, *, now: float | None = None) -> int | None:
        """A slot token, or ``None`` when the key already runs ``cap`` turns."""
        now = time.monotonic() if now is None else now
        with self._lock:
            leases = self._running.setdefault(key_id, {})
            for token, started in list(leases.items()):
                if now - started > LEASE_SECONDS:
                    del leases[token]
            if len(leases) >= cap:
                return None
            self._next += 1
            leases[self._next] = now
            return self._next

    def release(self, key_id: str, token: int) -> None:
        with self._lock:
            leases = self._running.get(key_id)
            if leases is not None:
                leases.pop(token, None)
                if not leases:
                    self._running.pop(key_id, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._running.clear()


GATE = KeyGate()
