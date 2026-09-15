"""H671 — a long-lived conversation knows what day it is now.

Nerva is built to run forever on one box: a house brain, ambient capture,
heartbeats, 24/7 autonomy. A forever-session that silently believes it is still
its birth date will schedule "tomorrow" against the wrong day, file a memory
episode under the wrong date, and reason wrongly about anything the owner says
relatively — "move it to Friday", "same time next week", "yesterday's run".

That is not hypothetical. This sprint hit the same class of fault from the other
side: a test seeded a row "an hour ago" and the report counted a local-day
window, so between 00:00 and 01:00 the row landed in yesterday and the count read
zero. Wall-clock assumptions rot silently and only at the boundary.

Two lines, and the second one only when it is actually needed:

    Conversation started: Monday, September 08, 2026 (Europe/Bucharest, EEST, UTC+03:00)
    Today's date (as of the last context rebuild): Friday, September 11, 2026 — trust this over the start date

**A same-day session renders byte-identically to a session with no clock block at
all except the first line**, which is the property that keeps the prompt cache
intact: the system prompt is one of the two things H363 marks as the stable
cacheable prefix, and a string that changes every turn would throw that discount
away on every request. The refresh line appears only once the rebuild day differs
from the start day, and it is written at the compaction boundary — where the
cached prefix is already being invalidated and the rebuild costs nothing extra.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo

_START_LABEL = "Conversation started:"
_TODAY_LABEL = "Today's date (as of the last context rebuild):"
_TRUST = "trust this over the start date"


def _local(moment: datetime, zone: tzinfo | None = None) -> datetime:
    """A timezone-aware moment in the zone the owner actually lives in.

    A naive datetime is read as local rather than UTC: it came off this box's own
    clock, and calling it UTC would shift the date by the offset — reintroducing
    the very off-by-one-day this row exists to remove.
    """
    if zone is not None:
        # An explicit zone wins: convert into it (or adopt it, if naive).
        return (moment.replace(tzinfo=zone) if moment.tzinfo is None
                else moment.astimezone(zone))
    if moment.tzinfo is None:
        return moment.astimezone()          # this box's clock, read as local
    # Already aware and no zone asked for: LEAVE IT ALONE. Converting it to this
    # box's zone is the off-by-one-day above, from the other direction — a moment
    # stamped 00:01 in +03:00 becomes 21:01 the previous day in UTC and the block
    # confidently names yesterday.
    return moment


def _zone_name(moment: datetime) -> str:
    """``Europe/Bucharest, EEST, UTC+03:00`` — or as much of it as is knowable.

    The IANA name is not always recoverable from an aware datetime (a fixed-offset
    tzinfo has no name), so the offset — which always is — carries the meaning and
    the name is added when it exists. Printing a bare abbreviation would be worse
    than printing none: ``EST`` is two different offsets depending on the country.
    """
    parts: list[str] = []
    key = getattr(moment.tzinfo, "key", None)          # zoneinfo carries .key
    if key:
        parts.append(str(key))
    abbrev = moment.tzname() or ""
    if abbrev and abbrev != key and not abbrev.startswith(("UTC+", "UTC-")):
        parts.append(abbrev)
    offset = moment.utcoffset()
    if offset is None:
        parts.append("UTC+00:00")
    else:
        total = int(offset.total_seconds())
        sign = "+" if total >= 0 else "-"
        total = abs(total)
        parts.append(f"UTC{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}")
    return ", ".join(parts)


def _long_date(moment: datetime) -> str:
    """``Friday, September 11, 2026`` — spelled out, never numeric.

    09/11 is two different days depending on which side of the Atlantic the model
    learned its formats on, and a date the model can misread is worse than none.
    """
    return f"{moment:%A}, {moment:%B} {moment.day:02d}, {moment.year}"


def clock_block(
    started_at: datetime | None,
    now: datetime | None = None,
    *,
    zone: tzinfo | None = None,
) -> str:
    """The clock lines for a session born at *started_at*, rebuilt at *now*.

    Returns ``""`` when the birth date is unknown — an invented start date is
    worse than a missing one, because the model would reason from it confidently.
    """
    if started_at is None:
        return ""
    start = _local(started_at, zone)
    lines = [f"{_START_LABEL} {_long_date(start)} ({_zone_name(start)})"]
    current = now or datetime.now(UTC)
    if zone is None and not getattr(start.tzinfo, "key", None) and start.tzinfo == start.astimezone().tzinfo:
        # astimezone() stores an instant's fixed offset, not DST rules. When
        # birth came from this host, resolve today's local offset independently.
        moment = current.astimezone()
    else:
        moment = _local(current, zone or start.tzinfo)
    if moment.date() != start.date():
        # Only on a day boundary. A same-day session keeps the byte-identical
        # prefix the cache is built on (H363); adding an always-present "today"
        # line would change the system prompt every midnight *and* make every
        # same-day session a cache miss for no information gained.
        lines.append(f"{_TODAY_LABEL} {_long_date(moment)} — {_TRUST}")
    return "\n".join(lines)


def with_clock(
    system_prompt: str,
    started_at: datetime | None,
    now: datetime | None = None,
    *,
    zone: tzinfo | None = None,
) -> str:
    """Put the clock block after the identity block, or return the prompt unchanged.

    Unchanged is the honest answer when there is no birth date: a system prompt
    that gained an empty section would be a different cache key for nothing.
    """
    block = clock_block(started_at, now, zone=zone)
    if not block:
        return system_prompt
    body = system_prompt or ""
    # Replace only our trailing structured block, not a phrase in the soul.
    body = re.sub(
        r"(?:\n\n|^)Conversation started: [A-Za-z]+, [A-Za-z]+ \d{2}, \d{4} \([^\n]+\)"
        r"(?:\nToday's date \(as of the last context rebuild\): [^\n]+)?$",
        "", body,
    )
    return f"{body}\n\n{block}" if body else block


def parse_started_at(value: object) -> datetime | None:
    """Read a session's ``started_at`` back off the store, or None.

    The checkpoint store writes ISO text; a row that predates the column, or one
    written by something else, must read as "unknown" rather than as an epoch.
    """
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


__all__ = ["clock_block", "parse_started_at", "with_clock"]


# Request-owned values: a tool runtime child task inherits a frozen snapshot, not
# a mutable manager-wide clock. No session ancestry is implied.


@dataclass(frozen=True)
class ClockSnapshot:
    session_id: str
    started_at: datetime
    rebuilt_at: datetime
    revision: int


CONTEXT_REFUSED_REPLY = "I stopped this turn because its context compaction could not be safely committed. Please retry."


class CompactionClockRefused(RuntimeError):
    """An unaccepted compaction must not become an oversized model request."""


@dataclass
class ClockLifetime:
    active: bool = True
    parent: ClockLifetime | None = None

    def is_active(self):
        return self.active and (self.parent is None or self.parent.is_active())


@dataclass(frozen=True)
class ClockFrame:
    manager: object
    snapshot: ClockSnapshot | None
    lifetime: ClockLifetime

    @property
    def active(self):
        return self.lifetime.is_active()


CLOCK_UNSET = object()
prompt_clock: ContextVar[ClockSnapshot | None] = ContextVar('prompt_clock', default=None)
_active_clock: ContextVar[ClockFrame | None] = ContextVar('active_compaction_clock', default=None)


def capture_clock(manager, session_id: str, *, agent_id: str | None = None) -> ClockSnapshot | None:
    if not session_id or manager is None or not hasattr(manager, 'clock_snapshot'):
        return None
    try:
        manager.create_session_record(session_id, agent_id=agent_id)
        return manager.clock_snapshot(session_id)
    except Exception:
        return None


@contextmanager
def clock_scope(manager, snapshot):
    parent = _active_clock.get()
    if parent is not None and not parent.active:
        raise CompactionClockRefused(CONTEXT_REFUSED_REPLY)
    if parent is None and snapshot is None:
        # No durable clock authority exists to revoke. Preserve legacy background
        # generation, but never use this branch to shed a managed ancestor.
        yield
        return
    frame = ClockFrame(manager, snapshot, ClockLifetime(parent=parent.lifetime if parent else None))
    token = _active_clock.set(frame)
    try:
        yield
    finally:
        frame.lifetime.active = False
        _active_clock.reset(token)


def active_clock():
    return _active_clock.get()


def render_snapshot(system: str, snapshot: ClockSnapshot | None) -> str:
    if snapshot is None:
        return system
    return with_clock(system, snapshot.started_at.astimezone(), snapshot.rebuilt_at)
