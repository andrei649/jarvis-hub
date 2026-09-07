"""H12.15 — a backup nobody verified is a belief, not a backup.

`create_backup` has existed for a long time and nothing ever called it on a
schedule, and nothing ever pruned the directory it writes to. Those two gaps are
one gap: an automatic backup without a prune writes a full copy of the data root
every night forever, which turns a safety feature into the thing that fills the
owner's disk.

The tests are about the ways a backup can be worse than none:

  · one that has been failing quietly for a month, while the owner believes they
    have one — so health reports the AGE of the newest archive, not whether the
    directory has files in it;
  · one that grew without limit until the disk filled;
  · a prune failure that took the successful backup down with it;
  · an unencrypted archive of the entire data root that nobody knew was
    unencrypted.

Hermetic: a tmp_path backup directory with stamped files. Nothing is archived,
nothing is scheduled, and no real data root is touched.
"""

from __future__ import annotations

import os
import time

import pytest

from agents.core.backup import (
    _ARCHIVE_PREFIX,
    BACKUP_KEEP_DEFAULT,
    backup_health,
    list_backups,
    prune_backups,
)

DAY = 86_400.0


@pytest.fixture
def archives(tmp_path):
    """Ten archives, newest first, one day apart."""
    now = time.time()

    def _make(count: int = 10, *, encrypted: bool = False, start_days_ago: float = 0.0):
        made = []
        for i in range(count):
            suffix = ".tar.gz.enc" if encrypted else ".tar.gz"
            # Built from the module's own prefix rather than a literal: a fixture
            # that names files the real code would not produce tests nothing.
            path = tmp_path / f"{_ARCHIVE_PREFIX}2026010{i}T000000_000000Z_abc{i}{suffix}"
            path.write_bytes(b"x" * (100 + i))
            stamp = now - (start_days_ago + i) * DAY
            os.utime(path, (stamp, stamp))
            made.append(path)
        return made

    return _make


# ── retention ────────────────────────────────────────────────────────────────

def test_pruning_keeps_the_newest_and_removes_the_rest(tmp_path, archives):
    """Without this, a nightly backup writes a full copy of the data root every
    night and never stops."""
    archives(10)
    removed = prune_backups(3, str(tmp_path))
    assert len(removed) == 7
    assert len(list_backups(str(tmp_path))) == 3


def test_the_default_is_a_week_of_daily_snapshots(tmp_path, archives):
    """Long enough to notice a corruption that happened while you were away,
    short enough that a full copy of the data root does not fill a laptop."""
    assert BACKUP_KEEP_DEFAULT == 7
    archives(10)
    prune_backups(out_dir=str(tmp_path))
    assert len(list_backups(str(tmp_path))) == 7


def test_the_newest_archives_are_the_ones_kept(tmp_path, archives):
    made = archives(5)
    prune_backups(2, str(tmp_path))
    survivors = {row["name"] for row in list_backups(str(tmp_path))}
    # made[0] is the newest (0 days ago); made[4] the oldest
    assert made[0].name in survivors
    assert made[4].name not in survivors


def test_keeping_none_is_a_real_request_not_a_mistake(tmp_path, archives):
    """Someone turning backups off entirely may well want the archives gone too."""
    archives(4)
    assert len(prune_backups(0, str(tmp_path))) == 4
    assert list_backups(str(tmp_path)) == []


def test_a_negative_keep_is_treated_as_zero_rather_than_slicing_backwards(tmp_path, archives):
    archives(3)
    prune_backups(-5, str(tmp_path))
    assert list_backups(str(tmp_path)) == []


def test_pruning_a_directory_that_does_not_exist_is_not_an_error(tmp_path):
    assert prune_backups(3, str(tmp_path / "nope")) == []


def test_encrypted_archives_are_pruned_like_any_other(tmp_path, archives):
    """A retention rule that only saw plaintext archives would let an encrypted
    install grow forever."""
    archives(5, encrypted=True)
    prune_backups(2, str(tmp_path))
    assert len(list_backups(str(tmp_path))) == 2


# ── health: recency, not file count ──────────────────────────────────────────

def test_no_backup_ever_made_says_exactly_that(tmp_path):
    """"Nobody has ever backed up" and "the last backup is 40 days old" are
    different findings, and neither is an empty list."""
    health = backup_health(str(tmp_path))
    assert health["ok"] is False
    assert health["count"] == 0
    assert health["reason"] == "no backup has ever been made"
    assert health["age_seconds"] is None


def test_a_fresh_backup_reads_as_healthy(tmp_path, archives):
    archives(1)
    health = backup_health(str(tmp_path))
    assert health["ok"] is True
    assert health["count"] == 1
    assert health["reason"] == ""


def test_a_stale_backup_is_not_healthy_however_many_there_are(tmp_path, archives):
    """A backup failing quietly for a month is worse than none, because the owner
    believes they have one. Ten old archives are not ten reasons to relax."""
    archives(10, start_days_ago=30)
    health = backup_health(str(tmp_path))
    assert health["ok"] is False
    assert health["count"] == 10
    assert "day(s) old" in health["reason"]


def test_one_missed_night_is_a_hiccup_and_two_is_a_pattern(tmp_path, archives):
    archives(1, start_days_ago=1)
    assert backup_health(str(tmp_path))["ok"] is True
    archives(1, start_days_ago=3)
    assert backup_health(str(tmp_path))["ok"] is False


def test_health_reports_whether_the_archives_are_encrypted(tmp_path, archives):
    """An unencrypted local archive of the entire data root is a fact the owner
    should be able to see, not infer."""
    archives(2, encrypted=True)
    assert backup_health(str(tmp_path))["all_encrypted"] is True


def test_a_single_unencrypted_archive_makes_the_answer_no(tmp_path, archives):
    archives(2, encrypted=True)
    archives(1, encrypted=False)
    assert backup_health(str(tmp_path))["all_encrypted"] is False


def test_encryption_is_unknown_rather_than_false_when_there_is_nothing(tmp_path):
    """`False` would read as "your backups are unencrypted", which is a different
    and alarming claim from "there are no backups"."""
    assert backup_health(str(tmp_path))["all_encrypted"] is None


def test_health_reports_the_disk_it_is_using(tmp_path, archives):
    archives(3)
    assert backup_health(str(tmp_path))["total_bytes"] > 0


# ── the nightly job ──────────────────────────────────────────────────────────

class _Sched:
    def __init__(self):
        self.jobs = []

    def add_job(self, fn, trigger, **kw):
        self.jobs.append((getattr(fn, "__name__", str(fn)), trigger, kw.get("id")))


def _service(settings=None, sched=None):
    import types

    from agents.core.scheduler_service import SchedulerService

    values = dict(settings or {})
    orch = types.SimpleNamespace(
        heartbeat_scheduler=types.SimpleNamespace(scheduler=sched or _Sched()),
        get_setting=lambda key, default=None: values.get(key, default),
    )
    return SchedulerService(orch), orch


def test_the_nightly_job_is_registered(monkeypatch):
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    sched = _Sched()
    service, _ = _service(sched=sched)
    service.schedule_backups()
    assert [job[2] for job in sched.jobs] == ["backup-nightly"]


def test_it_is_on_by_default_unlike_every_other_scheduled_capability(monkeypatch, tmp_path):
    """Retention DELETES, so a wrong default loses data. A backup PRESERVES, so a
    wrong default costs disk — and the prune bounds that."""
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    service, _ = _service()
    calls = []
    monkeypatch.setattr(
        "agents.core.backup.create_backup",
        lambda **kw: calls.append(kw) or {"archive": str(tmp_path / "a.tar.gz"), "bytes": 1},
    )
    monkeypatch.setattr("agents.core.backup.prune_backups", lambda *a, **k: [])
    result = service.run_backup()
    assert result["ok"] is True
    assert calls == [{"label": "nightly"}]


def test_turning_it_off_skips_the_backup_with_a_named_reason(monkeypatch):
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    service, _ = _service({"backup.auto_enabled": False})
    monkeypatch.setattr(
        "agents.core.backup.create_backup",
        lambda **kw: pytest.fail("create_backup must not run when disabled"),
    )
    result = service.run_backup()
    assert result["ok"] is False
    assert "auto_enabled" in result["skipped"]


def test_a_failing_backup_is_reported_rather_than_swallowed(monkeypatch):
    """The whole point is that a silently-failing backup is worse than none."""
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    service, _ = _service()

    def _boom(**_kw):
        raise OSError("disk full")

    monkeypatch.setattr("agents.core.backup.create_backup", _boom)
    result = service.run_backup()
    assert result == {"ok": False, "error": "OSError"}


def test_a_prune_failure_does_not_fail_the_backup_that_succeeded(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    service, _ = _service()
    monkeypatch.setattr(
        "agents.core.backup.create_backup",
        lambda **kw: {"archive": str(tmp_path / "a.tar.gz"), "bytes": 1},
    )

    def _boom(*_a, **_k):
        raise OSError("cannot unlink")

    monkeypatch.setattr("agents.core.backup.prune_backups", _boom)
    result = service.run_backup()
    assert result["ok"] is True
    assert result["pruned"] == []


def test_the_configured_retention_is_honoured(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    service, _ = _service({"backup.keep": 3})
    seen = []
    monkeypatch.setattr(
        "agents.core.backup.create_backup",
        lambda **kw: {"archive": str(tmp_path / "a.tar.gz"), "bytes": 1},
    )
    monkeypatch.setattr(
        "agents.core.backup.prune_backups", lambda keep: seen.append(keep) or []
    )
    service.run_backup()
    assert seen == [3]


def test_the_settings_default_matches_the_module_default():
    """Two defaults that drift mean the UI says one thing and the job does
    another."""
    from agents.core.settings_db import DEFAULTS

    rows = {row["key"]: row["value"] for row in DEFAULTS if row["category"] == "memory"}
    assert rows["backup_auto_enabled"] is True
    assert rows["backup_keep"] == BACKUP_KEEP_DEFAULT
