"""send_rate_limit.py — 0.44 per-channel OUTBOUND send rate limits (opt-in).

A small sliding-window limiter for **outbound** sends on the external webhook
channels (WhatsApp / Signal / Matrix / Teams / Google Chat). It bounds how *much*
a channel can broadcast — the complement of CDX-11 (*who* may use a channel) and
the H23.16 egress monitor (*observing* the volume).

Deliberately scoped to the **webhook broadcast channels only**, NOT the interactive
reply path (telegram / web / voice go through ``ChannelManager.send`` and must
never have a user reply silently dropped). And **off by default**: with no env set
the limit is 0 = unlimited, so behavior is unchanged until an operator opts in —
useful for a multi-tenant / hardened deployment where a runaway or compromised
agent must not be able to flood a channel.

Config (read at check time, so it's live-tunable and test-friendly):
  * ``JARVIS_CHANNEL_SEND_RATE``  — global per-minute cap for every channel (int).
  * ``JARVIS_CHANNEL_SEND_RATES`` — per-channel overrides, e.g.
    ``"whatsapp:10,teams:30"`` (a listed channel overrides the global default).
  0 / unset / unparseable → unlimited (the default).
"""

from __future__ import annotations

import os
import threading
import time

WINDOW_SECONDS = 60.0


def _parse_rates(raw: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for pair in (raw or "").split(","):
        cid, sep, val = pair.strip().partition(":")
        if sep and cid.strip():
            try:
                out[cid.strip()] = int(val)
            except ValueError:
                continue
    return out


def limit_for(channel_id: str) -> int:
    """Per-minute cap for *channel_id* from the environment. 0 = unlimited (default).

    A per-channel ``JARVIS_CHANNEL_SEND_RATES`` entry wins over the global
    ``JARVIS_CHANNEL_SEND_RATE``.
    """
    rates = _parse_rates(os.environ.get("JARVIS_CHANNEL_SEND_RATES", ""))
    if channel_id in rates:
        return max(0, rates[channel_id])
    try:
        return max(0, int(os.environ.get("JARVIS_CHANNEL_SEND_RATE", "0")))
    except ValueError:
        return 0


class SendRateLimiter:
    """Thread-safe per-channel sliding-window send limiter."""

    def __init__(self, window: float = WINDOW_SECONDS) -> None:
        self._window = window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, channel_id: str, *, now: float | None = None) -> bool:
        """Record + permit a send, or refuse it when the window is full.

        Returns True (and counts the send) while under the per-minute cap; False
        when the cap is reached. With no configured limit it is a pure no-op pass
        (records nothing), so the default path stays allocation-free and unbounded.
        """
        cap = limit_for(channel_id)
        if cap <= 0:
            return True  # unlimited / disabled — the default
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = [t for t in self._hits.get(channel_id, ()) if now - t < self._window]
            if len(hits) >= cap:
                self._hits[channel_id] = hits   # prune even on refusal
                return False
            hits.append(now)
            self._hits[channel_id] = hits
            return True

    def reset(self, channel_id: str | None = None) -> None:
        with self._lock:
            if channel_id is None:
                self._hits.clear()
            else:
                self._hits.pop(channel_id, None)


# Process-wide limiter shared across all webhook-channel instances (state is keyed
# by channel_id, so the cap is genuinely per-channel, not per-instance).
_LIMITER = SendRateLimiter()


def allow_send(channel_id: str) -> bool:
    return _LIMITER.allow(channel_id)


def reset(channel_id: str | None = None) -> None:
    """Clear recorded send history (used by tests; harmless in production)."""
    _LIMITER.reset(channel_id)
