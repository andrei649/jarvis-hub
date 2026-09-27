"""H262 — the data lifecycle sweep: archive, then retention, then VACUUM, once per interval.

One hourly job (``data-retention-sweep``) claims the sweep through a compare-and-set row in
checkpoints.db, so only one process runs it per ``retention.min_interval_hours``. The
archive phase stamps idle chats archived on ``memory.auto_archive_days`` (never a pinned
one, never one a chat is on). The retention phase deletes only archived, unpinned chats
idle past the horizon, through H218's backup-first delete, and never deeper than the last
approved horizon (no approval yet: nothing is deleted). A database whose rows a prune
deleted is VACUUMed, at most every ``retention.min_vacuum_interval_days``.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import lifecycle_sweep, retention, settings_db
from agents.core import session_archive as sa
from agents.core.checkpoint import CheckpointManager
from agents.core.security.audit import AuditLogger
from agents.core.security.types import SecurityEvent, SecurityEventType

_DAY = 86400
NOW = time.time()
MOMENT = datetime.fromtimestamp(NOW, UTC)


def _iso(days_ago: float) -> str:
    return (MOMENT - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def env(tmp_path, monkeypatch):
    from agents.core.memory import persistence

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(tmp_path / "bk"))
    monkeypatch.delenv("JARVIS_SESSION_BACKUP_KEEP", raising=False)
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    monkeypatch.setattr(persistence, "MEMORY_DIR", None)
    cp = CheckpointManager(str(home / "checkpoints.db"))
    cp.initialize()
    yield SimpleNamespace(root=home, cp=cp, backup=tmp_path / "bk" / "sessions", tmp=tmp_path)
    cp.close()


def _settings(**over) -> dict:
    base = {"retention.enabled": True, "memory.auto_archive_days": 100,
            "retention.conversation_ttl_days": 60, "retention.audit_ttl_days": 0,
            "retention.ingestion_ttl_days": 0, "retention.artifact_ttl_days": 0}
    base.update({k.replace("__", "."): v for k, v in over.items()})
    return base


def _approve(cp, settings: dict) -> None:
    cp.put_state(retention.APPROVED_STATE, {"values": {k: settings.get(k) for k in retention.RETENTION_KEYS}})


def _orch(env, settings: dict, *, audit=None, live="live", channels=None):
    from agents.core.memory.conversation import ConversationMemory
    from agents.core.notes import NotesStore
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = live
    orch.checkpoints, orch.memory = env.cp, ConversationMemory(persist=False)
    orch.notes = NotesStore(env.tmp / "notes.json")
    orch._channel_sessions = dict(channels or {})
    orch._turn_lease_max_wait = 0.05
    orch._runtime_settings = settings
    orch.audit, orch.ingestion_watcher = audit, None
    return orch


def _chat(env, sid, idle_days, *, archived=True, pinned=False, files=True):
    from agents.core.memory.precompress import TranscriptArchive

    env.cp.create_session_record(sid, "jarvis", {"title": sid})
    with env.cp._lock:
        env.cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?",
                             (_iso(idle_days + 1), _iso(idle_days), sid))
        env.cp._conn.commit()
    if archived:
        assert env.cp.set_archived(sid, True, at=_iso(idle_days)) is True
    if pinned:
        assert env.cp.set_pinned(sid, True) is True
    if files:
        (env.root / f"{sid}.json").write_text(json.dumps({"session_id": sid, "turns": [
            {"role": "user", "content": f"{sid} secret"}]}), encoding="utf-8")
        (env.root / f"{sid}.jsonl").write_text('{"role": "user", "content": "hi"}\n', encoding="utf-8")
        arch = TranscriptArchive().path_for(sid)
        arch.parent.mkdir(parents=True, exist_ok=True)
        arch.write_text('{"role": "assistant", "text": "old"}\n', encoding="utf-8")


def _meta(cp, sid):
    return json.loads(cp.session_row(sid)["metadata"] or "{}")


async def _sweep(orch, *, at=NOW):
    return await lifecycle_sweep.run_sweep(orch, now=at)


# ── 1. the settings ──────────────────────────────────────────────────────────────

def test_the_settings_rows_and_their_defaults():
    rows = {(r["category"], r["key"]): r for r in settings_db.DEFAULTS}
    want = {("retention", "enabled"): (False, "toggle"), ("retention", "conversation_ttl_days"): (90, "number"),
            ("retention", "audit_ttl_days"): (365, "number"), ("retention", "ingestion_ttl_days"): (0, "number"),
            ("retention", "artifact_ttl_days"): (0, "number"), ("retention", "min_interval_hours"): (24, "number"),
            ("retention", "vacuum_after_prune"): (True, "toggle"),
            ("retention", "min_vacuum_interval_days"): (30, "number"), ("memory", "auto_archive_days"): (0, "number")}
    for key, (value, kind) in want.items():
        assert (rows[key]["value"], rows[key]["kind"]) == (value, kind), key
    assert "archived, unpinned" in rows[("retention", "conversation_ttl_days")]["label"]
    assert "pinned chats are never archived" in rows[("memory", "auto_archive_days")]["label"]
    assert not any(r["key"] in {"auto_archive", "archive_after_days"} for r in settings_db.DEFAULTS
                   if r["category"] == "retention")                       # one archive setting only


@pytest.mark.parametrize("cat,key,bad,good", [
    ("retention", "conversation_ttl_days", [-1, 36501, 1.5, True], [0, 36500]),
    ("retention", "audit_ttl_days", [-1, 36501, 2.5, False], [0, 365]),
    ("retention", "ingestion_ttl_days", [-1, 36501, 0.5], [0, 30]),
    ("retention", "min_interval_hours", [0, 721, 1.5, True], [1, 720]),
    ("retention", "min_vacuum_interval_days", [-1, 366, 7.5], [0, 365]),
    ("retention", "vacuum_after_prune", [1, "yes"], [True, False]),
    ("memory", "auto_archive_days", [3651, True, 1.5, -1], [0, 3650]),
])
def test_out_of_range_values_are_refused(cat, key, bad, good):
    for value in bad:
        assert settings_db.validate_category(cat, {key: value}), (key, value)
    for value in good:
        assert settings_db.validate_category(cat, {key: value}) == [], (key, value)


async def test_the_settings_route_answers_422_for_an_out_of_range_value():
    from agents.core.routers import admin

    got = await admin.admin_put_category("memory", admin.AdminPutBody(values={"auto_archive_days": 3651}))
    assert got.status_code == 422 and "auto_archive_days" in json.loads(got.body)["details"][0]


# ── 2. the claim ─────────────────────────────────────────────────────────────────

def test_the_claim_is_taken_once_per_interval(env):
    cp = env.cp
    assert cp.claim_sweep("lifecycle_sweep", NOW, 3600) is True
    assert cp.claim_sweep("lifecycle_sweep", NOW + 3599, 3600) is False
    assert cp.claim_sweep("lifecycle_sweep", NOW + 3600, 3600) is True
    assert cp.get_state("lifecycle_sweep")["last_run_at"] == NOW + 3600
    assert cp.claim_sweep("other", NOW, 3600) is True                  # one row per name


def test_a_claim_from_the_future_is_due_again(env):
    assert env.cp.claim_sweep("lifecycle_sweep", NOW + 10 * _DAY, 3600) is True
    assert env.cp.claim_sweep("lifecycle_sweep", NOW, 3600) is True       # the clock went back


def test_two_stores_on_one_file_claim_it_exactly_once(env):
    other = CheckpointManager(env.cp.db_path)
    other.initialize()
    barrier, got = threading.Barrier(2), []

    def claim(cp):
        barrier.wait()
        got.append(cp.claim_sweep("lifecycle_sweep", NOW, 3600))
    threads = [threading.Thread(target=claim, args=(cp,)) for cp in (env.cp, other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    other.close()
    assert sorted(got) == [False, True]


def test_the_state_rows(env, tmp_path):
    cp = env.cp
    assert cp.get_state("lifecycle_sweep") is None
    assert cp.put_state("lifecycle_sweep", {"a": 1}) is True
    assert cp.get_state("lifecycle_sweep") == {"last_run_at": None, "value": {"a": 1}}
    cp.claim_sweep("lifecycle_sweep", NOW, 3600)
    assert cp.put_state("lifecycle_sweep", {"b": 2}) is True
    assert cp.get_state("lifecycle_sweep") == {"last_run_at": NOW, "value": {"b": 2}}   # the claim is kept
    cold = CheckpointManager(str(tmp_path / "cold.db"))
    assert cold.claim_sweep("x", NOW, 1) is None and cold.get_state("x") is None and cold.put_state("x", {}) is None
    with cp._lock:
        cp._conn.execute("UPDATE maintenance_state SET value='not json' WHERE name='lifecycle_sweep'")
        cp._conn.commit()
    assert cp.get_state("lifecycle_sweep") == {"last_run_at": NOW, "value": {}}


# ── 3. when the sweep runs ───────────────────────────────────────────────────────

async def test_with_both_features_off_the_sweep_is_skipped_and_claims_nothing(env):
    orch = _orch(env, _settings(retention__enabled=False, memory__auto_archive_days=0))
    assert await _sweep(orch) == {"_scheduler_status": "skipped"}
    assert env.cp.get_state("lifecycle_sweep") is None


async def test_a_second_sweep_inside_the_interval_is_not_due(env):
    orch = _orch(env, _settings(retention__min_interval_hours=24))
    first = await _sweep(orch)
    assert "_scheduler_status" not in first
    assert await _sweep(orch, at=NOW + 23 * 3600) == {"_scheduler_status": "skipped", "reason": "not_due"}
    assert "_scheduler_status" not in await _sweep(orch, at=NOW + 24 * 3600)


async def test_a_missing_store_is_skipped_not_failed(env, tmp_path):
    orch = _orch(env, _settings())
    orch.checkpoints = CheckpointManager(str(tmp_path / "never-opened.db"))
    assert await _sweep(orch) == {"_scheduler_status": "skipped", "reason": "state_unavailable"}
    orch.checkpoints = None
    assert await _sweep(orch) == {"_scheduler_status": "skipped", "reason": "state_unavailable"}


async def test_the_scheduled_job_runs_the_sweep_and_reports_a_failure(env, monkeypatch):
    from agents.core.scheduler_service import SchedulerService

    orch = _orch(env, _settings())
    _approve(env.cp, _settings())
    svc = SchedulerService(orch)
    got = await svc.run_retention_purge()
    assert "archived" in got and got["retention"]["conversations"]["deleted"] == []

    async def boom(*args, **kwargs):
        raise RuntimeError("private")
    monkeypatch.setattr(lifecycle_sweep, "run_sweep", boom)
    assert await svc.run_retention_purge() == {"_scheduler_status": "failed"}


async def test_the_sweep_state_records_the_last_report(env):
    orch = _orch(env, _settings(retention__enabled=False, memory__auto_archive_days=30))
    _chat(env, "idle", 40, archived=False)
    report = await _sweep(orch)
    state = env.cp.get_state("lifecycle_sweep")
    assert state["last_run_at"] == NOW and state["value"]["last_report"] == report
    assert report["archived"] == ["idle"] and report["retention"] == "off"


# ── 4. the archive phase ─────────────────────────────────────────────────────────

async def test_the_archive_phase_spares_pinned_and_live_chats(env):
    orch = _orch(env, _settings(retention__enabled=False, memory__auto_archive_days=30),
                 channels={"telegram:1": "tg"})
    for sid in ("idle", "pinned", "live", "tg"):
        _chat(env, sid, 40, archived=False, pinned=sid == "pinned")
    _chat(env, "recent", 10, archived=False)
    assert orch.live_session_ids() == {"live", "tg"}
    report = await _sweep(orch)
    assert report["archived"] == ["idle"]
    assert _meta(env.cp, "idle")["archived_at"] == MOMENT.isoformat()
    for sid in ("pinned", "live", "tg", "recent"):
        assert "archived_at" not in _meta(env.cp, sid), sid
    assert env.cp.stale_sessions(_iso(30)) == ["live", "tg"]                # pinned is never stale


def test_live_session_ids_tolerates_a_bare_orchestrator():
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    assert orch.live_session_ids() == set()
    orch.session_id = "s"
    orch._channel_sessions = {"a": "x", "b": None}
    assert orch.live_session_ids() == {"s", "x"}


def test_the_archiver_takes_several_live_ids(env):
    for sid in ("a", "b", "c"):
        _chat(env, sid, 40, archived=False, files=False)
    assert sa.run_auto_archive(env.cp, 30, active={"a", "b"}, now=MOMENT) == ["c"]
    assert sa.run_auto_archive(env.cp, 30, active="a", now=MOMENT) == ["b"]


# ── 5–6. what retention deletes ──────────────────────────────────────────────────

async def test_retention_deletes_only_archived_unpinned_chats_past_the_horizon(env):
    from agents.core import todo_tool
    from agents.core.memory.precompress import TranscriptArchive

    settings = _settings()                        # horizon = max(60, 100) = 100 days
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    _chat(env, "expired", 120)
    _chat(env, "unarchived", 95, archived=False)
    _chat(env, "pinned", 120, pinned=True)
    _chat(env, "fresh", 70)
    todo_tool.TODOS.apply("expired", [{"id": "1", "content": "x", "status": "pending"}], False)
    orch.notes.set("expired", "call the bank")
    report = await _sweep(orch)
    conv = report["retention"]["conversations"]
    assert conv["deleted"] == ["expired"] and conv["skipped"] == {} and conv["remaining"] is False
    assert report["retention"]["horizons"]["conversations"] == 100
    assert env.cp.session_row("expired") is None
    assert not (env.root / "expired.json").exists() and not (env.root / "expired.jsonl").exists()
    assert not TranscriptArchive().path_for("expired").exists()
    assert todo_tool.TODOS.read("expired")["todos"] == [] and orch.notes.get("expired") == ""
    [backup] = list(env.backup.glob("expired-*.json.enc"))
    assert sa.read_backup(backup)["snapshot"]["turns"][0]["content"] == "expired secret"
    for sid in ("unarchived", "pinned", "fresh"):
        assert env.cp.session_row(sid) is not None and (env.root / f"{sid}.jsonl").exists(), sid


async def test_the_database_clock_decides_never_the_file_mtime(env):
    import os

    settings = _settings(memory__auto_archive_days=30, retention__conversation_ttl_days=30)
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    _chat(env, "recent-db-old-files", 10)
    _chat(env, "old-db-new-files", 45)
    old = NOW - 400 * _DAY
    for name in ("recent-db-old-files.json", "recent-db-old-files.jsonl"):
        os.utime(env.root / name, (old, old))
    report = await _sweep(orch)
    assert report["retention"]["conversations"]["deleted"] == ["old-db-new-files"]
    assert (env.root / "recent-db-old-files.jsonl").exists()


async def test_orphan_transcripts_are_counted_not_deleted(env):
    settings = _settings()
    _approve(env.cp, settings)
    (env.root / "orphan.jsonl").write_text('{"role": "user"}\n', encoding="utf-8")
    (env.root / "orphan2.json").write_text(json.dumps({"session_id": "orphan2", "turns": []}), encoding="utf-8")
    (env.root / "notes.json").write_text('{"x": {"content": "keep"}}', encoding="utf-8")
    (env.root / "autonomy_journal.jsonl").write_text('{"event": "x"}\n', encoding="utf-8")
    report = await _sweep(_orch(env, settings))
    assert report["retention"]["orphans"] == 2
    for name in ("orphan.jsonl", "orphan2.json", "notes.json", "autonomy_journal.jsonl"):
        assert (env.root / name).exists(), name


def test_orphan_compaction_archives_go_once_old_and_a_database_session_keeps_its_own(tmp_path):
    import os

    from agents.core.memory.precompress import TranscriptArchive

    archive, old = TranscriptArchive(tmp_path / "compaction_archive"), NOW - 120 * _DAY
    for sid in ("with-file", "db-only", "gone", "new-orphan"):
        archive.on_pre_compress([{"role": "user", "content": f"{sid}: my bank PIN is 4242"}], session_id=sid)
    (tmp_path / "with-file.jsonl").write_text('{"role": "user"}\n', encoding="utf-8")
    for sid in ("with-file", "db-only", "gone"):
        os.utime(archive.path_for(sid), (old, old))
    assert retention.purge_orphan_compaction_archives(tmp_path, NOW - 30 * _DAY, live_ids={"db-only"}) == 1
    assert archive.read("gone") == []
    for sid in ("with-file", "db-only", "new-orphan"):
        assert len(archive.read(sid)) == 1, sid


# ── 7. continuations ─────────────────────────────────────────────────────────────

def _continue(cp, source, request="00000000-0000-4000-8000-000000000001"):
    from agents.core.session_continuation import ContinuationStore

    seed = [{"role": "user", "content": "carried", "agent_id": None,
             "timestamp": "2026-01-01T10:00:00+00:00", "token_count": 1}]
    return ContinuationStore(cp).create(source, request, seed, cp.clock_snapshot(source))["session_id"]


def _age(cp, sid, idle_days, *, archived=True):
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?",
                         (_iso(idle_days + 1), _iso(idle_days), sid))
        cp._conn.commit()
    if archived:
        cp.set_archived(sid, True, at=_iso(idle_days))


async def test_an_expired_parent_and_child_both_go_child_first(env):
    settings = _settings()
    _approve(env.cp, settings)
    _chat(env, "parent", 130)
    child = _continue(env.cp, "parent")
    _age(env.cp, child, 120)
    report = await _sweep(_orch(env, settings))
    assert report["retention"]["conversations"]["deleted"] == [child, "parent"]
    assert env.cp.session_row("parent") is None and env.cp.session_row(child) is None


async def test_a_parent_whose_child_lives_is_skipped_not_failed(env):
    settings = _settings()
    _approve(env.cp, settings)
    _chat(env, "parent", 130)
    child = _continue(env.cp, "parent")
    _age(env.cp, child, 5, archived=False)
    report = await _sweep(_orch(env, settings))
    conv = report["retention"]["conversations"]
    assert conv["deleted"] == [] and conv["skipped"] == {"parent": "has_continuations"}
    assert env.cp.session_row("parent") is not None


async def test_a_parent_checked_before_its_child_is_retried_after_it(env):
    settings = _settings()
    _approve(env.cp, settings)
    _chat(env, "parent", 110)                    # the parent's last turn is newer than the child's
    child = _continue(env.cp, "parent")
    _age(env.cp, child, 120)
    report = await _sweep(_orch(env, settings))
    assert sorted(report["retention"]["conversations"]["deleted"]) == sorted([child, "parent"])
    assert report["retention"]["conversations"]["skipped"] == {}


# ── 8. a turn racing the sweep ───────────────────────────────────────────────────

async def test_a_turn_after_the_candidate_query_keeps_the_chat(env, monkeypatch):
    settings = _settings()
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    _chat(env, "racing", 120)
    real = env.cp.expired_sessions

    def then_a_turn(before, **kw):
        found = real(before, **kw)
        env.cp.update_session("racing", turn_count=2)          # a turn lands: ended_at is now
        return found
    monkeypatch.setattr(env.cp, "expired_sessions", then_a_turn)
    report = await _sweep(orch)
    assert report["retention"]["conversations"]["skipped"] == {"racing": "no_longer_expired"}
    assert env.cp.session_row("racing") is not None and not env.backup.exists()


async def test_delete_expired_rechecks_inside_the_lease(env):
    settings = _settings()
    orch = _orch(env, settings)
    _chat(env, "s", 120)
    env.cp.set_pinned("s", True)
    with pytest.raises(sa.SessionDeleteError) as err:
        await sa.delete_expired(orch, "s", _iso(100))
    assert err.value.reason == "no_longer_expired"
    with pytest.raises(sa.SessionDeleteError) as err:
        await sa.delete_expired(orch, "live", _iso(100))
    assert err.value.reason == "active_session"


async def test_a_held_turn_lease_is_a_skip(env):
    settings = _settings()
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    _chat(env, "busy", 120)
    held, done = asyncio.Event(), asyncio.Event()

    async def turn():
        async with orch.turn_lease("busy"):
            held.set()
            await done.wait()
    running = asyncio.create_task(turn())
    await held.wait()
    report = await _sweep(orch)
    done.set()
    await running
    assert report["retention"]["conversations"]["skipped"] == {"busy": "session_busy"}
    assert env.cp.session_row("busy") is not None


async def test_a_channel_bound_chat_is_never_deleted_by_the_sweep(env):
    settings = _settings()
    _approve(env.cp, settings)
    _chat(env, "tg", 120)
    report = await _sweep(_orch(env, settings, channels={"telegram:1": "tg"}))
    assert report["retention"]["conversations"]["skipped"] == {"tg": "active_session"}


# ── 9. the sweep's own backups ───────────────────────────────────────────────────

async def test_a_bulk_sweep_keeps_every_backup_it_wrote(env):
    settings = _settings()
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    for i in range(15):
        _chat(env, f"old{i:02d}", 120 + i, files=i < 2)
    report = await _sweep(orch)
    assert len(report["retention"]["conversations"]["deleted"]) == 15
    assert len(list(env.backup.glob("*.json.enc"))) == 15
    _chat(env, "later", 120, files=False)
    report = await _sweep(orch, at=NOW + 25 * 3600)
    assert report["retention"]["conversations"]["deleted"] == ["later"]
    assert len(list(env.backup.glob("*.json.enc"))) == sa.BACKUP_KEEP_DEFAULT + 1


def test_delete_session_can_leave_the_backups_unpruned(env, monkeypatch):
    monkeypatch.setenv("JARVIS_SESSION_BACKUP_KEEP", "1")
    for sid in ("a", "b"):
        _chat(env, sid, 1, files=False)
        got = asyncio.run(sa.delete_session(sid, checkpoints=env.cp, prune=False))
        assert got["pruned"] == []
    assert len(list(env.backup.glob("*.json.enc"))) == 2


# ── 10–11. the approved horizon ──────────────────────────────────────────────────

def _seed_audit(path, ages_days, *, blob=""):
    audit = AuditLogger(db_path=str(path))
    for age in ages_days:
        audit.log(SecurityEvent(event_type=SecurityEventType.AUDIT_LOG, timestamp=NOW - age * _DAY,
                                content_preview=f"event {age}d {blob}", action_taken="logged"))
    return audit


async def test_without_an_approval_retention_deletes_nothing(env):
    settings = _settings(retention__audit_ttl_days=30)
    audit = _seed_audit(env.tmp / "audit.db", [400, 1])
    _chat(env, "expired", 120)
    report = await _sweep(_orch(env, settings, audit=audit))
    assert report["retention"] == "awaiting_approval"
    assert env.cp.session_row("expired") is not None and audit.count() == 2
    assert report["vacuum"]["done"] == [] and report["vacuum"]["pending"] == []


async def test_the_sweep_never_deletes_past_the_approved_horizon(env):
    settings = _settings(memory__auto_archive_days=30, retention__conversation_ttl_days=30,
                         retention__audit_ttl_days=30)
    _approve(env.cp, _settings(memory__auto_archive_days=30, retention__conversation_ttl_days=90,
                               retention__audit_ttl_days=365))
    audit = _seed_audit(env.tmp / "audit.db", [400, 100, 1])
    _chat(env, "sixty", 60)
    _chat(env, "old", 120)
    report = await _sweep(_orch(env, settings, audit=audit))
    assert report["retention"]["horizons"] == {"conversations": 90, "audit": 365, "ingestion": None,
                                               "artifacts": None}
    assert report["retention"]["conversations"]["deleted"] == ["old"]
    assert env.cp.session_row("sixty") is not None
    assert report["retention"]["audit"]["deleted"] == 1 and audit.count() == 2


async def test_an_approval_of_retention_off_deletes_nothing(env):
    settings = _settings()
    _approve(env.cp, _settings(retention__enabled=False))
    _chat(env, "expired", 120)
    report = await _sweep(_orch(env, settings))
    assert report["retention"]["conversations"]["deleted"] == [] and env.cp.session_row("expired") is not None


def _h(**over):
    return retention.horizons(_settings(**over))


def test_the_horizon_math():
    inf = float("inf")
    assert _h() == {"conversations": 100, "audit": inf, "ingestion": inf, "artifacts": inf}
    assert _h(memory__auto_archive_days=0)["conversations"] == inf            # needs chat archiving on
    assert _h(retention__conversation_ttl_days=0)["conversations"] == inf     # 0 = keep forever
    assert _h(retention__conversation_ttl_days=200)["conversations"] == 200
    got = _h(retention__audit_ttl_days=30, retention__ingestion_ttl_days=7, retention__artifact_ttl_days=1)
    assert (got["audit"], got["ingestion"], got["artifacts"]) == (30, 7, 1)
    assert set(_h(retention__enabled=False).values()) == {inf}
    assert _h(retention__audit_ttl_days=True)["audit"] == inf                 # a bool is no number of days
    assert _h(retention__audit_ttl_days="bad")["audit"] == inf
    assert _h(retention__audit_ttl_days=-5)["audit"] == inf


def test_the_effective_horizon_is_the_wider_one_and_a_write_that_narrows_it_widens_deletion():
    inf = float("inf")
    current = {"conversations": 30, "audit": inf, "ingestion": 7, "artifacts": 400}
    approved = {"conversations": 90, "audit": 365, "ingestion": 7, "artifacts": 1}
    assert retention.effective_horizons(current, approved) == {"conversations": 90, "audit": inf,
                                                               "ingestion": 7, "artifacts": 400}
    assert retention.effective_horizons(current, None) is None
    assert retention.widening(current, approved) == ["conversations"]
    assert retention.widening(approved, approved) == []
    assert retention.widening({**approved, "audit": inf}, approved) == []
    assert retention.widening(approved, None) == ["conversations", "audit", "ingestion", "artifacts"]
    assert retention.widening(dict.fromkeys(approved, inf), None) == []


def test_the_approved_values_are_read_from_the_state_row(env):
    assert retention.approved_horizons(env.cp) is None
    assert retention.approved_horizons(None) is None
    env.cp.put_state(retention.APPROVED_STATE, {"values": "garbage"})
    assert retention.approved_horizons(env.cp) is None
    _approve(env.cp, _settings())
    assert retention.approved_horizons(env.cp)["conversations"] == 100
    assert set(retention.RETENTION_KEYS) == {
        "retention.enabled", "retention.conversation_ttl_days", "retention.audit_ttl_days",
        "retention.ingestion_ttl_days", "retention.artifact_ttl_days", "memory.auto_archive_days"}


# ── 12–13. VACUUM ────────────────────────────────────────────────────────────────

def _size(path: Path) -> int:
    wal = path.with_name(path.name + "-wal")
    return path.stat().st_size + (wal.stat().st_size if wal.exists() else 0)


def _checkpointed(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


async def test_a_deleting_prune_vacuums_the_audit_database_and_the_chain_holds(env):
    settings = _settings(retention__audit_ttl_days=30)
    _approve(env.cp, settings)
    path = env.tmp / "audit.db"
    audit = _seed_audit(path, [400] * 1500 + [1], blob="x" * 60)
    _checkpointed(path)
    before = _size(path)
    report = await _sweep(_orch(env, settings, audit=audit))
    assert report["retention"]["audit"]["deleted"] == 1500
    assert "audit" in report["vacuum"]["done"] and report["vacuum"]["pending"] == []
    assert _size(path) < before / 2
    assert audit.verify_chain() == (True, None)
    audit.log(SecurityEvent(event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(),
                            content_preview="after vacuum", action_taken="logged"))
    assert audit.verify_chain() == (True, None) and audit.count() == 2
    state = env.cp.get_state("lifecycle_sweep")["value"]
    assert state["last_vacuum_at"] == NOW and state["vacuum_pending"] == []


async def test_no_vacuum_when_switched_off_or_nothing_was_deleted(env, monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle_sweep, "_VACUUMS", {name: (lambda orch, root, name=name: calls.append(name))
                                                      for name in lifecycle_sweep._VACUUMS})
    settings = _settings(retention__vacuum_after_prune=False)
    _approve(env.cp, settings)
    _chat(env, "old", 120, files=False)
    orch = _orch(env, settings)
    report = await _sweep(orch)
    assert report["retention"]["conversations"]["deleted"] == ["old"]
    assert calls == [] and report["vacuum"]["pending"] == ["checkpoints"]
    settings["retention.vacuum_after_prune"] = True
    settings["retention.min_interval_hours"] = 1
    env.cp.put_state("lifecycle_sweep", {})                  # nothing pending: nothing deleted since
    report = await _sweep(orch, at=NOW + 2 * 3600)
    assert calls == [] and report["vacuum"] == {"done": [], "pending": [], "failed": {}}


async def test_a_vacuum_inside_the_interval_waits_for_the_next_due_sweep(env, monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle_sweep, "_VACUUMS", {name: (lambda orch, root, name=name: calls.append(name))
                                                      for name in lifecycle_sweep._VACUUMS})
    settings = _settings(retention__min_interval_hours=1)
    _approve(env.cp, settings)
    env.cp.put_state("lifecycle_sweep", {"last_vacuum_at": NOW - _DAY, "vacuum_pending": []})
    _chat(env, "old", 120, files=False)
    orch = _orch(env, settings)
    report = await _sweep(orch)
    assert calls == [] and report["vacuum"]["pending"] == ["checkpoints"]
    report = await _sweep(orch, at=NOW + 2 * 3600)                     # still inside 30 days
    assert calls == [] and report["vacuum"]["pending"] == ["checkpoints"]
    report = await _sweep(orch, at=NOW + 30 * _DAY)                     # due: vacuumed though nothing was deleted
    assert calls == ["checkpoints"] and report["vacuum"]["done"] == ["checkpoints"]
    assert env.cp.get_state("lifecycle_sweep")["value"]["vacuum_pending"] == []


def test_the_audit_logger_still_has_what_the_vacuum_borrows(tmp_path):
    audit = AuditLogger(db_path=str(tmp_path / "a.db"))
    assert isinstance(audit._lock, type(threading.Lock())) and Path(audit._db_path).is_file()


def test_the_audit_vacuum_fails_closed_without_them():
    assert retention.vacuum_audit(SimpleNamespace()) == "audit_vacuum_unavailable"
    assert retention.vacuum_audit(None) == "audit_vacuum_unavailable"


def test_the_audit_vacuum_waits_for_the_loggers_own_lock(tmp_path):
    """The VACUUM takes the logger's ``_lock``, so it never runs across one of this
    process's writes (it waits for the write, and a write waits for it)."""
    audit = _seed_audit(tmp_path / "a.db", [400] * 50, blob="y" * 60)
    done: list = []
    with audit._lock:
        worker = threading.Thread(target=lambda: done.append(retention.vacuum_audit(audit)))
        worker.start()
        worker.join(0.5)
        assert worker.is_alive() and done == []          # waiting on the held lock
    worker.join(30)
    assert done == [None]


def test_a_log_during_the_audit_vacuum_waits_and_lands(tmp_path):
    audit = _seed_audit(tmp_path / "a.db", [400] * 500, blob="y" * 60)
    audit.prune_before(NOW - 30 * _DAY)
    errors, started = [], threading.Event()

    def vacuum():
        started.set()
        try:
            assert retention.vacuum_audit(audit) is None
        except Exception as exc:          # pragma: no cover - the failure is the assertion below
            errors.append(exc)
    worker = threading.Thread(target=vacuum)
    worker.start()
    started.wait()
    for i in range(20):
        audit.log(SecurityEvent(event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(),
                                content_preview=f"during {i}", action_taken="logged"))
    worker.join()
    assert errors == [] and audit.count() == 20 and audit.verify_chain() == (True, None)


def test_the_checkpoints_database_is_vacuumed(env):
    for i in range(300):
        env.cp.create_session_record(f"s{i}", "jarvis", {"title": "x" * 400})
    with env.cp._lock:
        env.cp._conn.execute("DELETE FROM sessions")
        env.cp._conn.commit()
    path = Path(env.cp.db_path)
    _checkpointed(path)
    before = _size(path)
    assert env.cp.vacuum() is True
    assert _size(path) < before / 2
    assert CheckpointManager(str(env.tmp / "cold.db")).vacuum() is False


def test_the_artifact_database_is_vacuumed_unless_an_upload_holds_it(tmp_path):
    from agents.core.artifact_store import BinaryArtifactStore

    store = BinaryArtifactStore(tmp_path / "root")
    assert store.vacuum() is True                        # no index yet: nothing to do
    with store._db() as db:
        for i in range(300):
            db.execute("INSERT INTO artifacts VALUES (?, 'k', 'm', 1, 's', 'a', 1, 0)", (f"id{i}" + "z" * 400,))
    with store._db() as db:
        db.execute("DELETE FROM artifacts")
    before = store.index.stat().st_size
    assert store.vacuum() is True and store.index.stat().st_size < before / 2
    with store._upload_lock(), pytest.raises(ValueError, match="artifact_store_busy"):
        store.vacuum()


async def test_a_busy_artifact_store_stays_pending(env, monkeypatch):
    from agents.core.artifact_store import BinaryArtifactStore

    settings = _settings(retention__artifact_ttl_days=1)
    _approve(env.cp, settings)
    store = BinaryArtifactStore(env.root)
    with store._db() as db:
        db.execute("INSERT INTO artifacts VALUES ('old', 'k', 'm', 1, 's', 'a', ?, 0)", (NOW - 10 * _DAY,))
    monkeypatch.setattr(BinaryArtifactStore, "_path", lambda self, item_id: self.directory / item_id)
    orch = _orch(env, settings)
    with store._upload_lock():
        report = await _sweep(orch)
    assert report["retention"]["artifacts"]["deleted"] == ["old"]
    assert report["vacuum"]["pending"] == ["artifacts"]
    assert report["vacuum"]["failed"] == {"artifacts": "artifact_store_busy"}
    assert env.cp.get_state("lifecycle_sweep")["value"]["last_vacuum_at"] is None


# ── 14. the schedule ─────────────────────────────────────────────────────────────

def test_one_hourly_job_and_no_separate_archiver():
    from agents.core.scheduler_service import SchedulerService

    jobs = []
    sched = SimpleNamespace(add_job=lambda func, trigger, **kw: jobs.append((func, trigger, kw)))
    svc = SchedulerService(SimpleNamespace(heartbeat_scheduler=SimpleNamespace(scheduler=sched)))
    for name in dir(SchedulerService):
        if name.startswith("schedule_") and name not in {"schedule_all", "schedule_retention"}:
            setattr(svc, name, lambda: None)
    svc.schedule_all()
    assert jobs == [(svc.run_retention_purge, "interval",
                     {"hours": 1, "id": "data-retention-sweep", "replace_existing": True})]
    assert not hasattr(SchedulerService, "schedule_auto_archive")


# ── pin (§4) ─────────────────────────────────────────────────────────────────────

def test_the_pin_stamp(env):
    _chat(env, "s", 1, archived=False, files=False)
    assert env.cp.set_pinned("s", True, at="p") is True and _meta(env.cp, "s")["pinned_at"] == "p"
    assert env.cp.set_archived("s", True, at="a") is True
    assert env.cp.set_archived("s", False) is True and _meta(env.cp, "s")["pinned_at"] == "p"
    assert env.cp.set_pinned("s", False) is True and "pinned_at" not in _meta(env.cp, "s")
    assert env.cp.set_pinned("nope", True) is False


def test_expired_sessions_are_archived_unpinned_and_newest_first(env):
    for sid, idle, pinned, archived in (("a", 200, False, True), ("b", 150, False, True), ("c", 150, True, True),
                                        ("d", 150, False, False), ("e", 10, False, True)):
        _chat(env, sid, idle, archived=archived, pinned=pinned, files=False)
    assert env.cp.expired_sessions(_iso(100)) == ["b", "a"]
    assert env.cp.expired_sessions(_iso(100), limit=1) == ["b"]
    assert env.cp.is_expired("a", _iso(100)) is True
    assert env.cp.is_expired("c", _iso(100)) is False and env.cp.is_expired("e", _iso(100)) is False
    assert env.cp.is_expired("nope", _iso(100)) is False
    assert env.cp.session_ids() == {"a", "b", "c", "d", "e"}


def _client(monkeypatch, orch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions as route

    monkeypatch.setattr(route, "get_orch", lambda: orch)
    return TestClient(web.app)


def test_the_pin_routes(env, monkeypatch):
    _chat(env, "s", 1, archived=False, files=False)
    client = _client(monkeypatch, SimpleNamespace(checkpoints=env.cp))
    got = client.post("/sessions/s/pin")
    assert got.status_code == 200 and got.json() == {"ok": True, "session": "s", "pinned": True}
    assert "no-store" in got.headers["Cache-Control"]
    row = client.get("/sessions").json()["sessions"][0]
    assert row["pinned_at"] == _meta(env.cp, "s")["pinned_at"] and row["archived_at"] is None
    assert client.post("/sessions/s/unpin").json()["pinned"] is False and "pinned_at" not in _meta(env.cp, "s")
    assert client.get("/sessions").json()["sessions"][0]["pinned_at"] is None
    assert client.post("/sessions/nope/pin").status_code == 404
    assert client.post("/sessions/bad%20id/pin").status_code == 400
    assert _client(monkeypatch, None).post("/sessions/s/pin").status_code == 503
    env.cp._conn.close()
    got = _client(monkeypatch, SimpleNamespace(checkpoints=env.cp)).post("/sessions/s/unpin")
    assert got.status_code == 503 and got.json()["reason"] == "store_unavailable"
    env.cp._conn = None


def test_a_pinned_archived_chat_can_be_unarchived_and_resume_keeps_the_pin(env, monkeypatch):
    _chat(env, "s", 1, pinned=True, files=False)

    async def resume(sid):
        return True

    async def history(sid):
        return []
    client = _client(monkeypatch, SimpleNamespace(checkpoints=env.cp, memory=SimpleNamespace(
        resume_session=resume, get_history=history)))
    assert client.get("/sessions", params={"archived": "true"}).json()["sessions"][0]["pinned_at"]
    assert client.post("/sessions/resume", json={"session_id": "s"}).status_code == 200
    assert "archived_at" not in _meta(env.cp, "s") and "pinned_at" in _meta(env.cp, "s")
    env.cp.set_archived("s", True)
    assert client.post("/sessions/s/unarchive").status_code == 200 and "pinned_at" in _meta(env.cp, "s")


def test_the_pin_routes_are_the_owners():
    from agents.core.routers import sessions as route

    routes = {(r.path, tuple(sorted(r.methods))): r for r in route.router.routes}
    names = lambda r: [d.call.__name__ for d in r.dependant.dependencies]  # noqa: E731
    assert names(routes[("/sessions/{session_id}/pin", ("POST",))]) == ["user_guard"]
    assert names(routes[("/sessions/{session_id}/unpin", ("POST",))]) == ["user_guard"]


# ── the shared delete (§5) ───────────────────────────────────────────────────────

async def test_the_delete_route_goes_through_the_shared_helper(env, monkeypatch):
    from agents.core.routers import sessions as route

    seen = []

    async def spy(orch, sid, **kw):
        seen.append((sid, kw))
        return {"ok": True, "session": sid}
    monkeypatch.setattr(sa, "delete_leased", spy)
    monkeypatch.setattr(route, "get_orch", lambda: SimpleNamespace(session_id="live"))
    got = await route.delete_session("gone", confirm="DELETE")
    assert got.status_code == 200 and seen == [("gone", {})]


# ── review round (H262) ──────────────────────────────────────────────────────────

def _resume_client(env, monkeypatch):
    async def resume(sid):
        return True

    async def history(sid):
        return []
    orch = SimpleNamespace(checkpoints=env.cp, session_id=None,
                           memory=SimpleNamespace(resume_session=resume, get_history=history))
    return _client(monkeypatch, orch)


async def test_f0_a_never_archived_idle_chat_survives_the_sweep_that_archives_it(env):
    settings = _settings()                        # horizon = max(60, 100) = 100 days
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    _chat(env, "idle", 120, archived=False)
    report = await _sweep(orch)
    assert report["archived"] == ["idle"] and report["retention"]["conversations"]["deleted"] == []
    assert env.cp.session_row("idle") is not None
    later = await _sweep(orch, at=NOW + 6 * _DAY)                # inside the week in the Archived view
    assert later["retention"]["conversations"]["deleted"] == [] and env.cp.session_row("idle") is not None
    week = await _sweep(orch, at=NOW + retention.DELETE_GRACE_DAYS * _DAY)
    assert week["retention"]["conversations"]["deleted"] == ["idle"] and env.cp.session_row("idle") is None


async def test_f0_an_unarchived_chat_is_not_archived_again_by_the_next_sweep(env, monkeypatch):
    settings = _settings()
    _approve(env.cp, settings)
    _chat(env, "kept", 120)                                     # archived 120 days ago
    got = _client(monkeypatch, SimpleNamespace(checkpoints=env.cp)).post("/sessions/kept/unarchive")
    assert got.status_code == 200 and "archived_at" not in _meta(env.cp, "kept")
    assert _meta(env.cp, "kept")["kept_at"]
    report = await _sweep(_orch(env, settings), at=time.time())
    assert report["archived"] == [] and report["retention"]["conversations"]["deleted"] == []
    assert env.cp.session_row("kept") is not None and "archived_at" not in _meta(env.cp, "kept")


async def test_f0_a_resumed_chat_is_not_archived_again_by_the_next_sweep(env, monkeypatch):
    settings = _settings()
    _approve(env.cp, settings)
    _chat(env, "back", 120)
    assert _resume_client(env, monkeypatch).post("/sessions/resume", json={"session_id": "back"}).status_code == 200
    assert "archived_at" not in _meta(env.cp, "back") and _meta(env.cp, "back")["kept_at"]
    report = await _sweep(_orch(env, settings), at=time.time())
    assert report["archived"] == [] and env.cp.session_row("back") is not None


def test_f0_the_grace_is_in_the_expired_query(env):
    _chat(env, "just-archived", 120, archived=False, files=False)
    env.cp.set_archived("just-archived", True, at=MOMENT.isoformat())
    _chat(env, "long-archived", 120, files=False)
    grace = (MOMENT - timedelta(days=retention.DELETE_GRACE_DAYS)).isoformat()
    assert env.cp.expired_sessions(_iso(100), archived_before=grace) == ["long-archived"]
    assert env.cp.is_expired("just-archived", _iso(100), archived_before=grace) is False
    assert env.cp.is_expired("long-archived", _iso(100), archived_before=grace) is True
    assert env.cp.expired_sessions(_iso(100)) == ["long-archived"]            # the grace by default
    assert "7" in next(r for r in settings_db.DEFAULTS if r["key"] == "conversation_ttl_days")["label"]


async def test_f2_failed_attempts_after_their_backup_never_prune_a_deleted_chats_backup(env, monkeypatch):
    monkeypatch.setenv("JARVIS_SESSION_BACKUP_KEEP", "1")
    settings = _settings()
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    for i, sid in enumerate(("ok1", "ok2", "bad1", "bad2", "bad3", "bad4")):
        _chat(env, sid, 110 + i, files=False)             # newest first: ok1, ok2, then the failures
    calls = []

    async def forget(sid):
        calls.append(sid)
        if sid.startswith("bad"):
            raise RuntimeError("database is locked")
        return 0
    orch.memory.forget_session_embeddings = forget
    report = await _sweep(orch)
    conv = report["retention"]["conversations"]
    assert conv["deleted"] == ["ok1", "ok2"] and conv["backups_pruned"] == []
    left = {p.name.split("-")[0] for p in env.backup.glob("*.json.enc")}
    assert {"ok1", "ok2"} <= left


async def _pin_during_delete(env, monkeypatch, act):
    settings = _settings()
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    _chat(env, "late", 120)
    real = sa._write_backup

    def backup_then_act(record, target):
        out = real(record, target)
        act()                                                   # lands after the in-lease re-check
        return out
    monkeypatch.setattr(sa, "_write_backup", backup_then_act)
    report = await _sweep(orch)
    return report


@pytest.mark.parametrize("act", ["pin", "unarchive", "resume"])
async def test_f3_a_pin_unarchive_or_resume_after_the_recheck_keeps_the_chat(env, monkeypatch, act):
    from agents.core.memory.precompress import TranscriptArchive

    def landing():
        if act == "pin":
            env.cp.set_pinned("late", True)
        else:
            env.cp.unarchive("late")
    report = await _pin_during_delete(env, monkeypatch, landing)
    conv = report["retention"]["conversations"]
    assert conv["deleted"] == [] and conv["skipped"] == {"late": "no_longer_expired"}
    assert env.cp.session_row("late") is not None
    assert (env.root / "late.json").exists() and (env.root / "late.jsonl").exists()
    assert TranscriptArchive().path_for("late").exists()


def test_f3_the_guarded_row_delete_removes_nothing_when_no_longer_expired(env):
    _chat(env, "s", 120, files=False)
    env.cp.set_pinned("s", True)
    grace = (MOMENT - timedelta(days=7)).isoformat()
    assert env.cp.delete_session_rows("s", expired=(_iso(100), grace)) is None
    assert env.cp.session_row("s") is not None
    env.cp.set_pinned("s", False)
    assert env.cp.delete_session_rows("s", expired=(_iso(100), grace))["sessions"] == 1


def test_f8_an_earlier_clock_read_committed_later_never_claims_twice(env):
    other = CheckpointManager(env.cp.db_path)
    other.initialize()
    try:
        assert env.cp.claim_sweep("lifecycle_sweep", 1000.0, 3600) is True
        assert other.claim_sweep("lifecycle_sweep", 999.9, 3600) is False
    finally:
        other.close()


def test_f9_the_checkpoint_connection_waits_out_a_vacuum(env):
    assert env.cp._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    assert "30 s" in CheckpointManager.vacuum.__doc__


def _other_process():
    """A live process that is not this one: a hub, as far as ``hub.lock`` says."""
    import subprocess
    import sys

    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


def _stop(proc) -> int:
    """Stop *proc* by its handle and reap it: its pid is then a dead one."""
    proc.kill()
    proc.wait(timeout=30)
    return proc.pid


def _write_hub_lock(root, text: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "hub.lock").write_text(text, encoding="ascii")


async def test_f7_a_process_without_the_hub_lock_skips_while_a_hub_holds_it(env, monkeypatch):
    from agents.core import install_identity

    settings = _settings()
    _approve(env.cp, settings)
    _chat(env, "idle", 120, archived=False)
    monkeypatch.setattr(install_identity, "_hub_handle", None)
    hub = _other_process()                                # the hub: its pid in hub.lock, alive
    try:
        _write_hub_lock(env.root, str(hub.pid))
        assert install_identity.holds_hub_lock() is False
        assert install_identity.hub_lock_held_elsewhere(env.root) is True
        got = await lifecycle_sweep.run_sweep(_orch(env, settings), now=NOW, root=env.root)
        assert got == {"_scheduler_status": "skipped", "reason": "hub_runs_it"}
        assert env.cp.get_state("lifecycle_sweep") is None and "archived_at" not in _meta(env.cp, "idle")
    finally:
        _stop(hub)
    assert install_identity.hub_lock_held_elsewhere(env.root) is False     # the hub is gone: a coordinator runs it
    got = await lifecycle_sweep.run_sweep(_orch(env, settings), now=NOW, root=env.root)
    assert got["archived"] == ["idle"]


@pytest.mark.skipif(__import__("os").name == "nt", reason="flock")
async def test_f7_the_hub_lock_holder_runs_it(env, monkeypatch):
    from agents.core import install_identity

    settings = _settings()
    _approve(env.cp, settings)
    monkeypatch.setattr(install_identity, "_hub_handle", None)
    install_identity.acquire_hub_lock(env.root)
    try:
        assert install_identity.holds_hub_lock() is True
        assert install_identity.hub_lock_held_elsewhere(env.root) is False
        got = await lifecycle_sweep.run_sweep(_orch(env, settings), now=NOW, root=env.root)
        assert "_scheduler_status" not in got
    finally:
        install_identity.release_hub_lock()


def test_f7_the_probe_never_creates_the_data_root(tmp_path, monkeypatch):
    from agents.core import install_identity

    monkeypatch.setattr(install_identity, "_hub_handle", None)
    missing = tmp_path / "nowhere"
    assert install_identity.hub_lock_held_elsewhere(missing) is False and not missing.exists()


async def test_f3_a_pin_after_the_last_check_is_caught_by_the_guarded_row_delete(env):
    settings = _settings()
    _approve(env.cp, settings)
    orch = _orch(env, settings)
    _chat(env, "late", 120)

    async def forget(sid):
        env.cp.set_pinned(sid, True)                  # between every Python-side check and the delete
        return 0
    orch.memory.forget_session_embeddings = forget
    report = await _sweep(orch)
    assert report["retention"]["conversations"]["skipped"] == {"late": "no_longer_expired"}
    assert env.cp.session_row("late") is not None and (env.root / "late.jsonl").exists()


# ── review round 2 (H262) ─────────────────────────────────────────────────────────

async def test_n1_the_card_counts_every_archived_chat_the_next_weeks_sweeps_delete(env):
    """Archiving turned on while retention is off (not gated) archives the whole history;
    retention enabled two days later with chats at 90 days: the card counts every old
    archived chat, and the sweeps of the next week delete exactly those."""
    off = _settings(retention__enabled=False, memory__auto_archive_days=30, retention__conversation_ttl_days=90)
    for i in range(20):
        _chat(env, f"old{i}", 200, archived=False)
    _chat(env, "recent", 10, archived=False)
    first = await _sweep(_orch(env, off))
    assert len(first["archived"]) == 20 and first["retention"] == "off"
    on = {**off, "retention.enabled": True}
    gone = retention.approval_preview(on, None, env.cp, None, now=NOW + 2 * _DAY)["would_delete"]
    assert gone["chats_to_archive"] == {"count": 0, "more": False}
    assert gone["archived_chats"] == {"count": 20, "more": False}
    _approve(env.cp, on)
    week = await _sweep(_orch(env, on), at=NOW + retention.DELETE_GRACE_DAYS * _DAY)
    assert len(week["retention"]["conversations"]["deleted"]) == gone["archived_chats"]["count"]


def test_n5_a_live_pid_in_the_lock_file_is_a_hub_and_the_probe_never_takes_the_lock(tmp_path, monkeypatch):
    from agents.core import install_identity

    def no_lock(*_a, **_k):
        raise AssertionError("the probe took hub.lock")

    monkeypatch.setattr(install_identity, "_hub_handle", None)
    monkeypatch.setattr(install_identity, "_file_lock", no_lock)
    monkeypatch.setattr(install_identity, "_file_unlock", no_lock)
    hub = _other_process()
    try:
        _write_hub_lock(tmp_path, f"{hub.pid}\n")
        assert install_identity.hub_lock_held_elsewhere(tmp_path) is True
    finally:
        _stop(hub)


def test_n5_a_dead_hubs_stale_pid_is_no_hub(tmp_path, monkeypatch):
    from agents.core import install_identity

    monkeypatch.setattr(install_identity, "_hub_handle", None)
    _write_hub_lock(tmp_path, str(_stop(_other_process())))
    assert install_identity.hub_lock_held_elsewhere(tmp_path) is False


@pytest.mark.parametrize("text", ["", "   ", "not a pid", "-4", "0"])
def test_n5_an_empty_or_unreadable_lock_file_is_no_hub(tmp_path, monkeypatch, text):
    from agents.core import install_identity

    monkeypatch.setattr(install_identity, "_hub_handle", None)
    _write_hub_lock(tmp_path, text)
    assert install_identity.hub_lock_held_elsewhere(tmp_path) is False


def test_n5_a_missing_lock_file_or_this_processs_own_pid_is_no_hub(tmp_path, monkeypatch):
    import os

    from agents.core import install_identity

    monkeypatch.setattr(install_identity, "_hub_handle", None)
    assert install_identity.hub_lock_held_elsewhere(tmp_path) is False and not (tmp_path / "hub.lock").exists()
    _write_hub_lock(tmp_path, str(os.getpid()))
    assert install_identity.hub_lock_held_elsewhere(tmp_path) is False
