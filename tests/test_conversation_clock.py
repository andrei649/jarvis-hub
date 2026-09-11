"""H671 — a long-lived conversation knows what day it is now.

Nerva is built to run forever on one box. A forever-session that silently
believes it is still its birth date schedules "tomorrow" against the wrong day,
files an episode under the wrong date, and misreads every relative thing the
owner says. Wall-clock assumptions rot silently and only at the boundary — which
is exactly how this sprint's other midnight bug hid for months.
"""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from agents.core.conversation_clock import clock_block, parse_started_at, with_clock

BUCHAREST = ZoneInfo("Europe/Bucharest")
BORN = datetime(2026, 9, 8, 10, 0, tzinfo=BUCHAREST)


# ── the off-by-one-day this exists to remove ─────────────────────────────────

def test_an_aware_moment_keeps_its_own_zone_and_therefore_its_own_date():
    """The regression that showed up in this module's first smoke test: converting
    an already-aware moment into the host's zone turns 00:01 in +03:00 into 21:01
    the PREVIOUS day, and the block then confidently names yesterday."""
    block = clock_block(BORN, datetime(2026, 9, 11, 0, 1, tzinfo=BUCHAREST))
    assert "Friday, September 11, 2026" in block
    assert "September 10" not in block


def test_a_moment_one_minute_before_local_midnight_is_still_today():
    block = clock_block(BORN, datetime(2026, 9, 10, 23, 59, tzinfo=BUCHAREST))
    assert "Thursday, September 10, 2026" in block


def test_an_explicit_zone_converts_rather_than_being_ignored():
    block = clock_block(
        datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        datetime(2026, 9, 10, 22, 30, tzinfo=UTC),   # 01:30 on the 11th local
        zone=BUCHAREST,
    )
    assert "Friday, September 11, 2026" in block


# ── the cache property ───────────────────────────────────────────────────────

def test_a_same_day_session_gets_exactly_one_line():
    """The system prompt is one of the two things marked as the cacheable stable
    prefix (H363). A "today" line on every same-day turn would be a cache miss
    bought for no information at all."""
    block = clock_block(BORN, BORN + timedelta(hours=5))
    assert block.count("\n") == 0
    assert "Today's date" not in block


def test_the_refresh_line_appears_only_once_the_day_actually_differs():
    same = clock_block(BORN, BORN + timedelta(hours=13))
    later = clock_block(BORN, BORN + timedelta(days=3))
    assert "Today's date" not in same
    assert "Today's date" in later


def test_the_start_line_is_byte_identical_across_the_day_boundary():
    """Only the second line may appear; the first must not move, or every session
    alive at midnight re-pays for its whole cached prefix."""
    before = clock_block(BORN, datetime(2026, 9, 8, 23, 59, tzinfo=BUCHAREST))
    after = clock_block(BORN, datetime(2026, 9, 9, 0, 1, tzinfo=BUCHAREST))
    assert after.startswith(before)


# ── what it refuses to invent ────────────────────────────────────────────────

def test_an_unknown_birth_date_produces_nothing_at_all():
    """An invented start date is worse than a missing one: the model reasons from
    it confidently."""
    assert clock_block(None) == ""
    assert with_clock("SOUL BODY", None) == "SOUL BODY"


def test_a_prompt_with_no_clock_is_returned_unchanged_not_padded():
    """A prompt that gained an empty section would be a different cache key for
    nothing."""
    assert with_clock("SOUL", None) == "SOUL"


def test_the_block_follows_the_identity_block_rather_than_replacing_it():
    out = with_clock("SOUL BODY", BORN, BORN + timedelta(days=1))
    assert out.startswith("SOUL BODY")
    assert "Conversation started:" in out


# ── legibility ───────────────────────────────────────────────────────────────

def test_the_date_is_spelled_out_because_09_11_is_two_different_days():
    block = clock_block(BORN, BORN + timedelta(days=3))
    assert "September" in block and "Friday" in block
    assert "09/11" not in block and "11/09" not in block


def test_the_zone_carries_the_offset_because_an_abbreviation_is_ambiguous():
    """`EST` is two different offsets depending on the country, so the offset —
    which is always knowable — is what carries the meaning."""
    block = clock_block(BORN, BORN)
    assert "UTC+03:00" in block
    assert "Europe/Bucharest" in block


def test_a_fixed_offset_zone_still_renders_an_offset():
    """A tzinfo with no IANA name must not produce a half-written parenthesis."""
    fixed = timezone(timedelta(hours=-5))
    block = clock_block(datetime(2026, 9, 8, 10, 0, tzinfo=fixed), None, zone=fixed)
    assert "UTC-05:00" in block and "(" in block and ")" in block


def test_the_refresh_line_tells_the_model_which_date_to_trust():
    block = clock_block(BORN, BORN + timedelta(days=2))
    assert "trust this over the start date" in block


# ── reading the birth date back off the store ────────────────────────────────

def test_an_iso_timestamp_from_the_session_store_is_read_back():
    parsed = parse_started_at("2026-09-08T10:00:00+03:00")
    assert parsed is not None and parsed.year == 2026 and parsed.day == 8


def test_a_zulu_timestamp_is_understood():
    assert parse_started_at("2026-09-08T07:00:00Z") is not None


def test_a_row_with_no_start_reads_as_unknown_rather_than_the_epoch():
    """A session row predating the column must not be dated 1970 — that is a
    confident wrong answer, which is the failure mode this row is about."""
    for value in ("", None, "not a date", 0):
        assert parse_started_at(value) is None


def test_a_datetime_is_passed_through():
    assert parse_started_at(BORN) == BORN


# ── the wiring: a forever-session keeps its birthday ─────────────────────────

def _orch(session_id="s1"):
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch._session_born = {}
    orch.session_id = session_id
    return orch


def test_the_birth_date_is_seeded_once_and_never_refreshed():
    """The whole point. Recomputing it at rebuild time would quietly reset a
    forever-session's birthday to today, every single rebuild."""
    orch = _orch()
    first = orch._session_birth()
    assert orch._session_birth() is first
    assert orch._session_born["s1"] is first


def test_a_rotation_to_a_new_session_gets_its_own_birthday():
    orch = _orch()
    born_a = orch._session_birth()
    orch.session_id = "s2"
    assert orch._session_birth() is not born_a


def test_returning_to_an_earlier_session_restores_its_original_birthday():
    """A checkpoint restore or a rotation back must not re-date the conversation."""
    orch = _orch()
    born_a = orch._session_birth()
    orch.session_id = "s2"
    orch._session_birth()
    orch.session_id = "s1"
    assert orch._session_birth() is born_a


def test_no_session_id_means_no_invented_birthday():
    orch = _orch(session_id="")
    assert orch._session_birth() is None


def test_the_system_prompt_carries_the_clock_after_the_soul():
    from agents.core.conversation_clock import with_clock

    orch = _orch()
    out = with_clock("SOUL BODY", orch._session_birth())
    assert out.startswith("SOUL BODY")
    assert "Conversation started:" in out
