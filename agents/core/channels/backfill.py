"""backfill.py — catching up on what was sent while the hub was not listening, within bounds (H116).

Telegram keeps undelivered updates for a day and ntfy caches messages for hours, but the hub
kept its read position only in memory: after a restart Telegram re-sent whatever it had not
seen confirmed (including an update the hub had already answered, so a crash between the
answer and the next poll answered it twice), and ntfy subscribed from "now", losing every
message sent during the gap.

Now each channel persists its read position (Telegram's update offset, ntfy's last message
time and ids) in the reliability store and resumes from it. What comes back — after a
restart, and after an outage while running — is a **backfill**: messages dated before the
moment the channel was reading again (the *cutoff*, compared at whole-second precision, the
precision the platforms date messages with). A backfill is bounded and gated:

* A plain message goes through exactly the path a live one takes — the channel's own update
  handler, then the gateway (pairing, rate limit, taint) and the orchestrator. There is no
  fast path: a stranger's backfilled message is held by pairing like a live one. It never
  answers a pending question or a decision-reason prompt (it is marked ineligible for pending
  input), so an old message cannot answer a prompt raised after the restart.
* A typed command (anything starting with ``/``) is **never** dispatched from a backfill: an
  old ``/resume`` must not lift a newer emergency stop, an old ``/approve`` must not approve.
  The sender, when it is one Nerva already answers (paired or allowlisted), is told
  "sent while Nerva was offline — send it again"; anyone else hears nothing.
* A button tap that waited in the queue (Telegram ``callback_query``) is answered "not
  applied" and the owner taps again on a live card.
* A message older than the window (``JARVIS_CHANNEL_BACKFILL_WINDOW_S``, 6 h by default)
  is skipped; so is everything past the budget (``JARVIS_CHANNEL_BACKFILL_MAX``, 20
  messages per catch-up). Telegram reads the whole backlog first and keeps the **newest**
  20 overall; ntfy streams its cache in order and keeps the **earliest** 20 of each
  connection. ``0`` for either turns backfill off: old messages are then all skipped.
* Inbound is **at most once**: the position is saved as each update is taken, before it is
  handled, and ntfy ids already taken are remembered across restarts. A message whose turn
  was still queued when the process died is not re-run (an action is never replayed); the
  owner sends it again.

What a catch-up did is counted on the channel's status row (``backfill``: processed,
skipped as too old, skipped over budget, commands and taps refused) — counts only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..env_config import env_int

WINDOW_ENV = "JARVIS_CHANNEL_BACKFILL_WINDOW_S"
MAX_ENV = "JARVIS_CHANNEL_BACKFILL_MAX"
DEFAULT_WINDOW_S = 6 * 3600
DEFAULT_MAX = 20
#: Hard ceilings, whatever the environment says.
WINDOW_CEILING_S = 24 * 3600
MAX_CEILING = 200
#: What the sender of a refused backfilled command is told.
COMMAND_REFUSED = ("This command was sent while Nerva was offline, so it was not run. "
                   "Send it again if you still want it.")
TAP_REFUSED = "Not applied: this was tapped while Nerva was offline. Tap again."

#: H120 — a message that reaches a running channel long after it was sent (a stuck
#: delivery queue on the platform's side) is held to the backfill rules too: a command in
#: it is refused, it never answers a pending prompt. ``0`` turns the guard off.
LATE_ENV = "JARVIS_CHANNEL_LATE_DELIVERY_S"
DEFAULT_LATE_S = 900
#: Dates before 2020-01-01 are not a delivery delay, they are a broken or hostile date.
_PLAUSIBLE_EPOCH = 1_577_836_800
LATE_COMMAND_REFUSED = ("This command reached Nerva late (several minutes after you sent it), "
                        "so it was not run. Send it again if you still want it.")


def configured_window() -> int:
    return min(env_int(WINDOW_ENV, DEFAULT_WINDOW_S, minimum=0), WINDOW_CEILING_S)


def configured_max() -> int:
    return min(env_int(MAX_ENV, DEFAULT_MAX, minimum=0), MAX_CEILING)


def configured_late_threshold() -> int:
    return min(env_int(LATE_ENV, DEFAULT_LATE_S, minimum=0), WINDOW_CEILING_S)


def delivered_late(sent_at, now, threshold: int | None = None) -> bool:
    """Whether a message dated *sent_at* reached a running channel more than *threshold*
    seconds after it was sent. A threshold of 0 is off. Only a plausible date on a readable
    clock counts: an undated message, a date before :data:`_PLAUSIBLE_EPOCH`, an
    unreadable or non-finite clock, or a number too large for a float is never "late"
    (and never raises), so a hostile date cannot use this guard to drop a message."""
    try:
        limit = configured_late_threshold() if threshold is None else threshold
        if (limit <= 0 or type(sent_at) not in (int, float) or type(now) not in (int, float)
                or not math.isfinite(sent_at) or not math.isfinite(now)
                or sent_at < _PLAUSIBLE_EPOCH):
            return False
        return float(now) - float(sent_at) > limit
    except (OverflowError, ValueError, TypeError):
        return False


def is_backlog(sent_at, cutoff) -> bool:
    """Whether a message dated *sent_at* (whole seconds) was sent before *cutoff*."""
    if (not isinstance(sent_at, (int, float)) or isinstance(sent_at, bool)
            or not isinstance(cutoff, (int, float))):
        return False
    return sent_at < math.floor(cutoff)


def looks_like_command(text) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("/")


@dataclass
class BackfillBudget:
    """One catch-up's allowance and its tally."""

    window_s: int = field(default_factory=configured_window)
    limit: int = field(default_factory=configured_max)
    processed: int = 0
    skipped_stale: int = 0
    skipped_over_budget: int = 0
    refused_commands: int = 0
    refused_taps: int = 0

    def fresh(self, sent_at, now: float) -> bool:
        """Within the window; counts a stale one."""
        if (self.window_s <= 0 or not isinstance(sent_at, (int, float)) or isinstance(sent_at, bool)
                or now - float(sent_at) > self.window_s):
            self.skipped_stale += 1
            return False
        return True

    def admit(self, sent_at, now: float) -> bool:
        """In order (ntfy): within the window and the budget; counts what it refuses."""
        if not self.fresh(sent_at, now):
            return False
        if self.processed >= self.limit:
            self.skipped_over_budget += 1
            return False
        self.processed += 1
        return True

    def counts(self) -> dict:
        return {"processed": self.processed, "skipped_stale": self.skipped_stale,
                "skipped_over_budget": self.skipped_over_budget,
                "refused_commands": self.refused_commands, "refused_taps": self.refused_taps}


__all__ = ["BackfillBudget", "COMMAND_REFUSED", "DEFAULT_LATE_S", "DEFAULT_MAX", "DEFAULT_WINDOW_S",
           "LATE_COMMAND_REFUSED", "LATE_ENV", "MAX_ENV", "TAP_REFUSED", "WINDOW_ENV",
           "configured_late_threshold", "configured_max", "configured_window", "delivered_late",
           "is_backlog", "looks_like_command"]
