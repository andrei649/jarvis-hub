"""backfill.py — catching up on what was sent while the hub was down, within bounds (H116).

Telegram keeps undelivered updates for a day and ntfy caches messages for hours, but the hub
kept its read position only in memory: after a restart Telegram re-sent whatever it had not
seen confirmed (including an update the hub had already answered, so a crash between the
answer and the next poll answered it twice), and ntfy subscribed from "now", losing every
message sent during the gap.

Now each channel persists its read position (Telegram's update offset, ntfy's last message
time and ids) in the reliability store and resumes from it. What comes back is a
**backfill**, and it is bounded and gated:

* It goes through exactly the path a live message takes — the channel's own update handler,
  then the gateway (pairing, rate limit, taint), the pending-input and approval paths and
  the orchestrator. There is no fast path: a stranger's backfilled message is held by
  pairing like a live one, and a backfilled command is judged like a live one.
* A message older than the window (``JARVIS_CHANNEL_BACKFILL_WINDOW_S``, 6 h by default)
  is skipped, not replayed; so is everything past the budget
  (``JARVIS_CHANNEL_BACKFILL_MAX``, 20 messages per channel start; Telegram keeps the
  newest of each fetched page, ntfy the earliest, since its cache streams in order).
  ``0`` for either turns backfill off: old messages are then all skipped.
* A button tap that waited in the queue (Telegram ``callback_query``) is never applied from
  a backfill: it is answered "not applied" and the owner taps again on a live card. An
  approval decided while Nerva was offline is not acted on hours later.
* Each message is processed once: the position is saved as each update is taken, and ntfy
  ids already seen are remembered across restarts.

What the catch-up did is counted on the channel's status row (``backfill``: processed,
skipped as too old, skipped over budget, taps refused) — counts only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..env_config import env_int

WINDOW_ENV = "JARVIS_CHANNEL_BACKFILL_WINDOW_S"
MAX_ENV = "JARVIS_CHANNEL_BACKFILL_MAX"
DEFAULT_WINDOW_S = 6 * 3600
DEFAULT_MAX = 20
#: Hard ceilings, whatever the environment says.
WINDOW_CEILING_S = 24 * 3600
MAX_CEILING = 200


def configured_window() -> int:
    return min(env_int(WINDOW_ENV, DEFAULT_WINDOW_S, minimum=0), WINDOW_CEILING_S)


def configured_max() -> int:
    return min(env_int(MAX_ENV, DEFAULT_MAX, minimum=0), MAX_CEILING)


@dataclass
class BackfillBudget:
    """One channel start's catch-up allowance and its tally."""

    window_s: int = field(default_factory=configured_window)
    limit: int = field(default_factory=configured_max)
    processed: int = 0
    skipped_stale: int = 0
    skipped_over_budget: int = 0
    refused_taps: int = 0

    def admit(self, sent_at, now: float) -> bool:
        """Whether one backfilled message (sent at *sent_at*, epoch seconds) is processed."""
        if (not isinstance(sent_at, (int, float)) or isinstance(sent_at, bool)
                or now - float(sent_at) > self.window_s or self.window_s <= 0):
            self.skipped_stale += 1
            return False
        if self.processed >= self.limit:
            self.skipped_over_budget += 1
            return False
        self.processed += 1
        return True

    def plan(self, sent_ats: list, now: float) -> list[bool]:
        """Admit a page of backfilled messages at once, keeping the newest within budget."""
        fresh = [i for i, sent_at in enumerate(sent_ats)
                 if self.window_s > 0 and isinstance(sent_at, (int, float))
                 and not isinstance(sent_at, bool) and now - float(sent_at) <= self.window_s]
        self.skipped_stale += len(sent_ats) - len(fresh)
        room = max(0, self.limit - self.processed)
        keep = set(fresh[len(fresh) - room:]) if room else set()
        self.skipped_over_budget += len(fresh) - len(keep)
        self.processed += len(keep)
        return [i in keep for i in range(len(sent_ats))]

    def counts(self) -> dict:
        return {"processed": self.processed, "skipped_stale": self.skipped_stale,
                "skipped_over_budget": self.skipped_over_budget,
                "refused_taps": self.refused_taps}


__all__ = ["BackfillBudget", "DEFAULT_MAX", "DEFAULT_WINDOW_S", "MAX_ENV", "WINDOW_ENV",
           "configured_max", "configured_window"]
