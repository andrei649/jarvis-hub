"""H23.10 — data-retention sweeps prune old data and keep the audit chain valid.

Covers: conversations pruned by the database clock through the lifecycle sweep (H262:
archived, unpinned, past the approved horizon; config JSON untouched), the audit log
pruned through a chain-preserving re-anchor (verify_chain still passes), the
off-by-default / TTL=0 no-ops, and the run_retention orchestration.
"""
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import retention
from agents.core import settings_db
from agents.core.security.audit import AuditLogger
from agents.core.security.types import SecurityEvent, SecurityEventType

_DAY = 86400


def _aged_session(root: Path, sid: str, age_days: float) -> None:
    root.mkdir(parents=True, exist_ok=True)
    jl = root / f"{sid}.jsonl"
    js = root / f"{sid}.json"
    jl.write_text('{"role": "user", "content": "hi"}\n', encoding="utf-8")
    js.write_text(f'{{"session_id": "{sid}", "turns": []}}', encoding="utf-8")
    t = time.time() - age_days * _DAY
    for p in (jl, js):
        os.utime(p, (t, t))


# ── conversation retention (H262: through the lifecycle sweep) ────────
def _sweep_env(tmp_path, monkeypatch, settings):
    from datetime import UTC, datetime, timedelta

    from agents.core.checkpoint import CheckpointManager
    from agents.core.memory import persistence
    from agents.core.memory.conversation import ConversationMemory
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(tmp_path.parent / f"{tmp_path.name}-bk"))
    monkeypatch.setattr(persistence, "MEMORY_DIR", None)
    cp = CheckpointManager(str(tmp_path / "cp.db"))
    cp.initialize()
    cp.put_state(retention.APPROVED_STATE, {"values": {k: settings.get(k) for k in retention.RETENTION_KEYS}})
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id, orch.checkpoints, orch.memory = "live", cp, ConversationMemory(persist=False)
    orch._runtime_settings, orch.audit, orch.ingestion_watcher = settings, None, None

    def chat(sid, idle_days):
        _aged_session(tmp_path, sid, age_days=0)                       # the file mtime is not the clock
        cp.create_session_record(sid, "jarvis", {})
        at = (datetime.now(UTC) - timedelta(days=idle_days)).isoformat()
        with cp._lock:
            cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?", (at, at, sid))
            cp._conn.commit()
        cp.set_archived(sid, True, at=at)
    return orch, cp, chat


async def test_old_conversations_pruned_new_kept(tmp_path, monkeypatch):
    from agents.core import lifecycle_sweep

    settings = {"retention.enabled": True, "retention.conversation_ttl_days": 90, "memory.auto_archive_days": 30}
    orch, cp, chat = _sweep_env(tmp_path, monkeypatch, settings)
    chat("old-sess", 120)
    chat("fresh-sess", 3)
    # Non-conversation files that must survive.
    (tmp_path / "notes.json").write_text('{"keep": 1}', encoding="utf-8")
    (tmp_path / "autonomy_journal.jsonl").write_text('{"keep": 1}\n', encoding="utf-8")

    report = await lifecycle_sweep.run_sweep(orch)

    assert report["retention"]["conversations"]["deleted"] == ["old-sess"]
    assert cp.session_row("old-sess") is None
    assert not (tmp_path / "old-sess.jsonl").exists()
    assert not (tmp_path / "old-sess.json").exists()
    assert (tmp_path / "fresh-sess.jsonl").exists()
    assert (tmp_path / "notes.json").exists()
    assert (tmp_path / "autonomy_journal.jsonl").exists()


async def test_conversation_ttl_zero_is_noop(tmp_path, monkeypatch):
    from agents.core import lifecycle_sweep

    settings = {"retention.enabled": True, "retention.conversation_ttl_days": 0, "memory.auto_archive_days": 30}
    orch, cp, chat = _sweep_env(tmp_path, monkeypatch, settings)
    chat("old-sess", 999)
    report = await lifecycle_sweep.run_sweep(orch)
    assert report["retention"]["conversations"]["deleted"] == []
    assert (tmp_path / "old-sess.jsonl").exists() and cp.session_row("old-sess") is not None


# ── audit retention (chain-preserving) ─────────────────────────────
def _seed_audit(tmp_path, ages_days) -> AuditLogger:
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    now = time.time()
    for age in ages_days:
        audit.log(SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG,
            timestamp=now - age * _DAY,
            content_preview=f"event {age}d",
            action_taken="logged",
        ))
    return audit


def test_audit_prune_keeps_chain_verifiable(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    audit = _seed_audit(tmp_path, ages_days=[100, 50, 10, 1])
    assert audit.count() == 4
    assert audit.verify_chain() == (True, None)

    deleted = audit.prune_before(time.time() - 30 * _DAY)  # drop the 100d + 50d rows
    assert deleted == 2
    assert audit.count() == 2
    # The re-anchored chain still verifies, and new appends keep linking.
    assert audit.verify_chain() == (True, None)
    audit.log(SecurityEvent(event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(),
                            content_preview="after prune", action_taken="logged"))
    assert audit.verify_chain() == (True, None)
    assert audit.count() == 3


def test_audit_prune_keyed_chain_verifiable(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "off-box-key")
    audit = _seed_audit(tmp_path, ages_days=[100, 1])
    deleted = audit.prune_before(time.time() - 30 * _DAY)
    assert deleted == 1
    assert audit.verify_chain() == (True, None)


def test_audit_ttl_zero_is_noop(tmp_path):
    audit = _seed_audit(tmp_path, ages_days=[999])
    out = retention.purge_old_audit(0, audit)
    assert out["deleted"] == 0
    assert audit.count() == 1


# ── run_retention orchestration ────────────────────────────────────
def test_run_retention_disabled_is_noop(tmp_path):
    _aged_session(tmp_path, "old", age_days=999)
    settings = {"retention.enabled": False}
    out = retention.run_retention(lambda k, d=None: settings.get(k, d), root=tmp_path)
    assert out == {"enabled": False}
    assert (tmp_path / "old.jsonl").exists()


async def test_run_retention_enabled_prunes_both(tmp_path, monkeypatch):
    from agents.core import lifecycle_sweep

    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    settings = {
        "retention.enabled": True,
        "retention.conversation_ttl_days": 90,
        "retention.audit_ttl_days": 365,
        "memory.auto_archive_days": 30,
    }
    orch, cp, chat = _sweep_env(tmp_path, monkeypatch, settings)
    chat("old", 120)
    chat("fresh", 2)
    audit = _seed_audit(tmp_path, ages_days=[400, 1])
    orch.audit = audit
    out = await lifecycle_sweep.run_sweep(orch)
    assert out["retention"]["conversations"]["deleted"] == ["old"]
    assert out["retention"]["audit"]["deleted"] == 1
    assert not (tmp_path / "old.jsonl").exists()
    assert (tmp_path / "fresh.jsonl").exists()
    assert audit.verify_chain() == (True, None)


def test_run_retention_no_longer_touches_transcripts(tmp_path):
    """H262 — the file-glob delete is gone: a transcript goes only through the sweep's
    backup-first delete of an archived session, never by its file mtime."""
    _aged_session(tmp_path, "old", age_days=999)
    settings = {"retention.enabled": True, "retention.conversation_ttl_days": 1}
    out = retention.run_retention(lambda k, d=None: settings.get(k, d), root=tmp_path)
    assert "conversations" not in out and (tmp_path / "old.jsonl").exists()


# ── settings ───────────────────────────────────────────────────────
def test_retention_settings_exist_and_default_off():
    by_key = {d["key"]: d for d in settings_db.DEFAULTS if d["category"] == "retention"}
    assert by_key["enabled"]["value"] is False           # off by default
    assert by_key["conversation_ttl_days"]["value"] == 90
    assert by_key["audit_ttl_days"]["value"] == 365
