"""
auth_rotation.py — H12.20 Auth-profile rotation + failover for cloud LLM backends.

A provider (Anthropic, Gemini) can be given **several** API keys / accounts; the
pool rotates to the next healthy key when one fails with a rotatable error
(401/403 auth, 429 rate-limit/quota). A failed key goes into an exponential
cooldown and is retried later — so a single rate-limited or expired key no longer
takes the whole cloud tier down.

* **Backward compatible.** A pool built from a single key behaves exactly like the
  old single-key backend (one profile, no rotation).
* **Self-contained + offline-testable.** No network, no clock dependency (an
  injectable ``clock`` makes cooldown deterministic in tests).

Keys are read from the environment: a comma/whitespace-separated ``*_API_KEYS``
(multi) falling back to the single ``*_API_KEY``.
"""

from __future__ import annotations

import os
import re
import time
from typing import Callable, Optional

# Status codes that mean "this credential is the problem — try another one".
_ROTATABLE_STATUS = frozenset({401, 403, 429})

_BASE_COOLDOWN = 30.0      # seconds, first failure
_MAX_COOLDOWN = 900.0      # cap (15 min)


def is_rotatable_status(status: int) -> bool:
    """True for auth/quota/rate-limit statuses that warrant trying another key."""
    return status in _ROTATABLE_STATUS


def _split_keys(raw: str) -> list[str]:
    """Parse a multi-key env value (comma / whitespace / newline separated)."""
    return [k for k in re.split(r"[,\s]+", (raw or "").strip()) if k]


class AuthProfile:
    """One credential + its health (failure count, cooldown)."""

    __slots__ = ("id", "api_key", "failures", "cooldown_until")

    def __init__(self, profile_id: str, api_key: str) -> None:
        self.id = profile_id
        self.api_key = api_key
        self.failures = 0
        self.cooldown_until = 0.0


class AuthProfilePool:
    """Ordered credentials for one provider, with rotation + cooldown."""

    def __init__(self, keys: Optional[list[str]] = None, provider: str = "",
                 base_cooldown: float = _BASE_COOLDOWN, max_cooldown: float = _MAX_COOLDOWN,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.provider = provider
        self._base = base_cooldown
        self._max = max_cooldown
        self._clock = clock
        self._active = 0
        seen: set[str] = set()
        self._profiles: list[AuthProfile] = []
        for i, key in enumerate(keys or []):
            if not key or key in seen:        # skip empties + dedup
                continue
            seen.add(key)
            self._profiles.append(AuthProfile(f"{provider or 'key'}-{i+1}", key))

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, single_var: str, multi_var: str, provider: str = "",
                 clock: Callable[[], float] = time.monotonic) -> "AuthProfilePool":
        """Build from ``multi_var`` (preferred) or the single ``single_var``."""
        keys = _split_keys(os.environ.get(multi_var, ""))
        if not keys:
            single = os.environ.get(single_var, "").strip()
            keys = [single] if single else []
        return cls(keys, provider=provider, clock=clock)

    # ── state ─────────────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._profiles)

    def _is_healthy(self, p: AuthProfile, now: float) -> bool:
        return now >= p.cooldown_until

    def healthy_count(self) -> int:
        now = self._clock()
        return sum(1 for p in self._profiles if self._is_healthy(p, now))

    def current(self) -> Optional[AuthProfile]:
        """The active profile — prefer a healthy one, else fall back to any (so a
        single cooling key is still attempted rather than disabling the tier)."""
        if not self._profiles:
            return None
        now = self._clock()
        active = self._profiles[self._active]
        if self._is_healthy(active, now):
            return active
        for off in range(1, len(self._profiles)):
            idx = (self._active + off) % len(self._profiles)
            if self._is_healthy(self._profiles[idx], now):
                self._active = idx
                return self._profiles[idx]
        return active   # none healthy → last resort

    def current_key(self) -> Optional[str]:
        p = self.current()
        return p.api_key if p else None

    def _find(self, key: Optional[str]) -> Optional[AuthProfile]:
        if key is None:
            return self.current()
        for p in self._profiles:
            if p.api_key == key or p.id == key:
                return p
        return None

    # ── failover ──────────────────────────────────────────────────────────────

    def rotate(self) -> Optional[AuthProfile]:
        """Advance the active pointer to the next healthy profile (wrap)."""
        if not self._profiles:
            return None
        now = self._clock()
        for off in range(1, len(self._profiles) + 1):
            idx = (self._active + off) % len(self._profiles)
            if self._is_healthy(self._profiles[idx], now):
                self._active = idx
                return self._profiles[idx]
        # none healthy — still advance by one so we don't spin on the same key
        self._active = (self._active + 1) % len(self._profiles)
        return self._profiles[self._active]

    def report_failure(self, key: Optional[str] = None) -> Optional[AuthProfile]:
        """Mark a profile failed (exponential cooldown) and rotate away from it."""
        p = self._find(key)
        if p is None:
            return None
        p.failures += 1
        backoff = min(self._base * (2 ** (p.failures - 1)), self._max)
        p.cooldown_until = self._clock() + backoff
        return self.rotate()

    def report_success(self, key: Optional[str] = None) -> None:
        """Reset a profile's failure state after a good response."""
        p = self._find(key)
        if p is not None:
            p.failures = 0
            p.cooldown_until = 0.0

    # ── observability ─────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Masked snapshot for an admin endpoint (never exposes a full key)."""
        now = self._clock()
        return {
            "provider": self.provider,
            "size": self.size,
            "healthy": self.healthy_count(),
            "active": self._profiles[self._active].id if self._profiles else None,
            "profiles": [
                {"id": p.id, "key_hint": (p.api_key[:4] + "…") if p.api_key else "",
                 "failures": p.failures, "healthy": self._is_healthy(p, now)}
                for p in self._profiles
            ],
        }
