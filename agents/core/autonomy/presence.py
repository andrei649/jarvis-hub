"""presence.py — owner desk-presence state (H34.2).

A tiny, pure, offline-testable tracker for **owner desk presence** — is the
owner *at the machine* right now, or away from it. This is deliberately NOT the
household room-occupancy inference in ``agents/core/house/presence.py`` (that is
per-room, per-occupant, consent-gated, household-sensitive). This one models a
single boolean-ish signal reported by an owner-side host daemon (a Windows
idle/lock watcher or the 0.64 Tauri host overlay) so the autonomy layer can
decide *where* a decision card should land:

  * **present / idle / unknown** → the HUD + Mission Control are enough; the
    existing Telegram decision-inbox path is unchanged (calm by default).
  * **away** → the owner isn't watching a screen, so finished-work / approval
    cards are *also* fanned out to the governed escalation channels
    (WhatsApp / Telegram / …) — see ``escalation.AwayNotifier`` — still inside
    the same ≤4/day interrupt budget.

**Default-off / fail-calm.** With no daemon reporting, the state is ``unknown``
and :meth:`OwnerPresence.is_away` is ``False`` — behavior is byte-identical to
before this module existed. A stale signal (older than the TTL) also reads as
*not away*, so a daemon that dies never silently starts (or keeps) escalating.
The host daemon is an owner-side install (``docs/OWNER_TASKS.md``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# Canonical states. ``idle`` sits between present and away: the owner is at the
# desk but hasn't touched input for a while — surfaced, but not "away" unless the
# tracker is configured to treat idle as away.
PRESENT = "present"
IDLE = "idle"
AWAY = "away"
UNKNOWN = "unknown"

# Aliases a host daemon might report (OS lock/idle vocab) → canonical state.
_ALIASES = {
    "present": PRESENT,
    "active": PRESENT,
    "home": PRESENT,
    "unlocked": PRESENT,
    "online": PRESENT,
    "idle": IDLE,
    "inactive": IDLE,
    "away": AWAY,
    "locked": AWAY,
    "lock": AWAY,
    "out": AWAY,
    "gone": AWAY,
    "offline": AWAY,
    "unknown": UNKNOWN,
    "": UNKNOWN,
}

_MAX_SOURCE_LEN = 64
_DEFAULT_TTL_SECONDS = 900.0  # 15 min — a signal older than this is "stale".


def normalize_state(state: object) -> str:
    """Map a reported state (canonical or alias) to a canonical state.

    Raises ``ValueError`` for anything unrecognized so a typo in a daemon's
    payload fails loudly at the edge instead of silently reading as ``unknown``.
    """
    if not isinstance(state, str):
        raise ValueError("presence state must be a string")
    key = state.strip().lower()
    canonical = _ALIASES.get(key)
    if canonical is None:
        raise ValueError(f"unsupported presence state: {state!r}")
    return canonical


@dataclass(frozen=True)
class PresenceSnapshot:
    """Immutable view of the owner's desk presence at one instant."""

    state: str
    source: str
    since: float
    updated_at: float
    idle_seconds: float | None
    ttl_seconds: float
    stale: bool
    away: bool
    ever_reported: bool

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "source": self.source,
            "since": self.since,
            "updated_at": self.updated_at,
            "idle_seconds": self.idle_seconds,
            "ttl_seconds": self.ttl_seconds,
            "stale": self.stale,
            "away": self.away,
            "ever_reported": self.ever_reported,
        }


class OwnerPresence:
    """Track the owner's desk-presence state from host-daemon signals.

    Single-process, event-loop-local: updates come from the presence route and
    reads from the autonomy notifier / swarm feed, all on the same loop — no lock
    needed. ``clock`` is injectable for deterministic tests.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        idle_is_away: bool = False,
        clock=time.time,
    ) -> None:
        self._ttl = max(0.0, float(ttl_seconds))
        self._idle_is_away = bool(idle_is_away)
        self._clock = clock
        self._state = UNKNOWN
        self._source = ""
        self._idle_seconds: float | None = None
        now = float(self._clock())
        self._since = now
        self._updated_at = now
        self._ever_reported = False

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    def update(
        self,
        state: object,
        *,
        source: str = "",
        idle_seconds: float | None = None,
        now: float | None = None,
    ) -> PresenceSnapshot:
        """Record a presence signal from the host daemon. Returns the new snapshot.

        ``state`` may be canonical or an OS alias (``locked``/``active``/…);
        an unrecognized value raises ``ValueError``. ``idle_seconds`` is an
        optional hint (seconds since last input) the daemon can attach.
        """
        canonical = normalize_state(state)
        ts = float(self._clock()) if now is None else float(now)
        clean_source = str(source or "").strip()[:_MAX_SOURCE_LEN]
        idle_val: float | None
        if idle_seconds is None:
            idle_val = None
        else:
            try:
                idle_val = max(0.0, float(idle_seconds))
            except (TypeError, ValueError):
                idle_val = None
        if canonical != self._state:
            self._since = ts
        self._state = canonical
        self._source = clean_source
        self._idle_seconds = idle_val
        self._updated_at = ts
        self._ever_reported = True
        return self.snapshot(now=ts)

    def _is_stale(self, now: float) -> bool:
        if not self._ever_reported:
            return True
        if self._ttl <= 0:
            return False
        return (now - self._updated_at) > self._ttl

    def snapshot(self, now: float | None = None) -> PresenceSnapshot:
        """A consistent read of the current presence state."""
        ts = float(self._clock()) if now is None else float(now)
        stale = self._is_stale(ts)
        away = self._compute_away(stale)
        return PresenceSnapshot(
            state=self._state,
            source=self._source,
            since=self._since,
            updated_at=self._updated_at,
            idle_seconds=self._idle_seconds,
            ttl_seconds=self._ttl,
            stale=stale,
            away=away,
            ever_reported=self._ever_reported,
        )

    def _compute_away(self, stale: bool) -> bool:
        # Fail calm: an unknown or stale signal is never "away", so a missing or
        # dead daemon can't trigger phone escalations on its own.
        if stale or self._state == UNKNOWN:
            return False
        if self._state == AWAY:
            return True
        if self._state == IDLE:
            return self._idle_is_away
        return False

    def is_away(self, now: float | None = None) -> bool:
        """True only when the owner is *known* to be away (fresh signal)."""
        ts = float(self._clock()) if now is None else float(now)
        return self._compute_away(self._is_stale(ts))
