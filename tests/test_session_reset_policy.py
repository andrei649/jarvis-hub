"""Synthetic H063 reset policy and persistent route-index contracts."""

import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from agents.core.channels.session_reset import (
    ResetPolicy,
    RouteState,
    SessionResetError,
    SessionResetStore,
    generation_key,
    resolve_policy,
    should_reset,
)


def settings(values):
    return lambda key, default=None: values.get(key, default)


def test_policy_defaults_and_override_precedence():
    assert resolve_policy(settings({}), "telegram", "dm") == ResetPolicy()
    values = {
        "sessions.reset_mode": "idle",
        "sessions.idle_minutes": 60,
        "sessions.daily_hour": 3,
        "sessions.reset_by_type": {"dm": {"mode": "daily", "daily_hour": 5}},
        "sessions.reset_by_channel": {
            "telegram": {"mode": "both", "idle_minutes": 20,
                         "types": {"dm": {"idle_minutes": 7}}},
        },
        "general.timezone": "UTC",
    }
    assert resolve_policy(settings(values), "telegram", "dm") == ResetPolicy(
        mode="both", idle_minutes=7, daily_hour=5, timezone="UTC"
    )
    assert resolve_policy(settings(values), "telegram", "group") == ResetPolicy(
        mode="both", idle_minutes=20, daily_hour=3, timezone="UTC"
    )
    assert resolve_policy(settings(values), "discord", "dm") == ResetPolicy(
        mode="daily", idle_minutes=60, daily_hour=5, timezone="UTC"
    )


@pytest.mark.parametrize("bad", [
    {"sessions.reset_mode": "weekly"},
    {"sessions.idle_minutes": 0},
    {"sessions.idle_minutes": float("inf")},
    {"sessions.daily_hour": 24},
    {"general.timezone": "not/a/zone"},
    {"sessions.reset_by_type": ["dm"]},
    {"sessions.reset_by_channel": {"telegram": {"types": []}}},
    {"sessions.reset_by_type": {"group": {"mode": "weekly"}}},
    {"sessions.reset_mode": []},
    {"sessions.idle_minutes": 10**100},
])
def test_invalid_policy_configuration_fails_closed(bad):
    with pytest.raises(SessionResetError):
        resolve_policy(settings(bad), "telegram", "dm")


def test_idle_daily_both_and_backward_clocks():
    last = datetime(2026, 10, 5, 3, 30, tzinfo=UTC)
    assert not should_reset(last, last + timedelta(minutes=9), ResetPolicy("idle", 10))
    assert should_reset(last, last + timedelta(minutes=10), ResetPolicy("idle", 10))
    assert not should_reset(last, last - timedelta(seconds=1), ResetPolicy("both", 10))
    assert not should_reset(last, last + timedelta(days=3), ResetPolicy("none"))
    daily = ResetPolicy("daily", daily_hour=4, timezone="UTC")
    assert not should_reset(last, datetime(2026, 10, 5, 3, 59, tzinfo=UTC), daily)
    assert should_reset(last, datetime(2026, 10, 5, 4, tzinfo=UTC), daily)
    assert should_reset(last, datetime(2026, 10, 6, 3, 59, tzinfo=UTC), daily)


def test_daily_boundary_obeys_bucharest_dst_and_aware_instants():
    zone = ZoneInfo("Europe/Bucharest")
    policy = ResetPolicy("daily")
    # DST starts on 2026-03-29; 04:00 local is 01:00 UTC.
    last = datetime(2026, 3, 29, 2, 30, tzinfo=zone)
    before = datetime(2026, 3, 29, 2, 59, tzinfo=zone)
    boundary = datetime(2026, 3, 29, 4, 0, tzinfo=zone)
    assert not should_reset(last, before, policy)
    assert should_reset(last, boundary, policy)
    assert not should_reset(boundary, boundary, policy)
    # During fall-back, repeating 03:xx never crosses the 04:00 boundary.
    first = datetime(2026, 10, 25, 3, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 10, 25, 3, 30, tzinfo=zone, fold=1)
    assert not should_reset(first, second, policy)


@pytest.mark.parametrize("clock", [datetime(2026, 1, 1), float("nan"), float("inf"), "bad"])
def test_invalid_clocks_fail_closed(clock):
    with pytest.raises(SessionResetError):
        should_reset(datetime(2026, 1, 1, tzinfo=UTC), clock, ResetPolicy())


def test_generation_keys_remain_safe_and_never_truncate():
    assert generation_key("ch_telegram_sender_ab", 0) == "ch_telegram_sender_ab"
    assert generation_key("ch_telegram_sender_ab", 12) == "ch_telegram_sender_ab_g12"
    for base, generation in [("../secret", 0), ("a" * 128, 1), ("safe", -1)]:
        with pytest.raises(SessionResetError):
            generation_key(base, generation)


def test_store_reopens_and_retirement_keeps_generation_fence(tmp_path):
    path = tmp_path / "routes.db"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = SessionResetStore(path)
    assert store.state("ch_telegram_sender_ab") == RouteState(
        "ch_telegram_sender_ab", 0, None, None, None, False
    )
    assert store.touch("ch_telegram_sender_ab", now, " Telegram ", "DM").generation == 0
    assert store.rotate("ch_telegram_sender_ab", now, "telegram", "dm").generation == 1
    assert SessionResetStore(path).state("ch_telegram_sender_ab").generation == 1
    retired = SessionResetStore(path).retire("ch_telegram_sender_ab")
    assert retired == RouteState("ch_telegram_sender_ab", 2, None, None, None, False)
    revived = store.touch("ch_telegram_sender_ab", now + timedelta(days=1), "telegram", "dm")
    assert revived.generation == 2 and revived.active
    assert SessionResetStore(path).entries() == [revived]


def test_two_instances_rotate_without_lost_updates(tmp_path):
    path = tmp_path / "routes.db"
    one, two = SessionResetStore(path), SessionResetStore(path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert one.rotate("route", now, "web", "dm").generation == 1
    assert two.rotate("route", now, "web", "dm").generation == 2
    assert one.state("route").generation == 2


def test_failed_mutation_keeps_prior_state_and_store_rejects_corruption(tmp_path):
    path = tmp_path / "routes.db"
    store = SessionResetStore(path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    old = store.touch("route", now, "web", "dm")
    with pytest.raises(SessionResetError):
        store.rotate("route", datetime(2025, 1, 1), "web", "dm")
    with pytest.raises(SessionResetError):
        store.touch("route", now - timedelta(seconds=1), "web", "dm")
    assert SessionResetStore(path).state("route") == old
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not sqlite")
    with pytest.raises(SessionResetError):
        SessionResetStore(broken)


def test_invalid_persisted_row_fails_closed_on_read(tmp_path):
    path = tmp_path / "routes.db"
    store = SessionResetStore(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO routes VALUES (?, ?, ?, ?, ?, ?)",
                   ("route", 1, float("nan"), "web", "dm", 1))
    with pytest.raises(SessionResetError):
        store.state("route")


def test_mismatched_schema_is_refused_even_when_column_names_match(tmp_path):
    path = tmp_path / "forged.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE routes (base TEXT, generation TEXT, last_activity TEXT, "
                   "channel TEXT, kind TEXT, active TEXT)")
        db.execute("PRAGMA user_version=1")
    with pytest.raises(SessionResetError):
        SessionResetStore(path)


def test_database_write_failure_does_not_advance_generation(tmp_path):
    path = tmp_path / "routes.db"
    store = SessionResetStore(path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    old = store.touch("route", now, "web", "dm")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER deny_route_update BEFORE UPDATE ON routes "
                   "BEGIN SELECT RAISE(ABORT, 'synthetic write refusal'); END")
    with pytest.raises(SessionResetError):
        store.rotate("route", now, "web", "dm")
    assert SessionResetStore(path).state("route") == old


def test_store_rejects_path_replaced_with_symlink(tmp_path):
    path = tmp_path / "routes.db"
    store = SessionResetStore(path)
    other = tmp_path / "other.db"
    SessionResetStore(other)
    path.unlink()
    try:
        path.symlink_to(other)
    except OSError:
        pytest.skip("creating a symlink requires a Windows privilege")
    with pytest.raises(SessionResetError):
        store.state("route")


def test_store_capacity_and_unsafe_inputs_fail_closed(tmp_path):
    store = SessionResetStore(tmp_path / "routes.db", max_entries=2)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for n in range(2):
        store.retire(f"route_{n}")
    with pytest.raises(SessionResetError):
        store.touch("one_more", now, "web", "dm")
    with pytest.raises(SessionResetError):
        store.touch("../escape", now, "web", "dm")
    assert len(store.entries()) == 2
