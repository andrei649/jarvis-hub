"""H23.10 — data-retention sweeps prune old data and keep the audit chain valid.

Covers: conversation transcripts pruned by mtime (config JSON untouched), the
audit log pruned through a chain-preserving re-anchor (verify_chain still passes),
the off-by-default / TTL=0 no-ops, and the run_retention orchestration.
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


# ── conversation retention ─────────────────────────────────────────
def test_old_conversations_pruned_new_kept(tmp_path):
    _aged_session(tmp_path, "old-sess", age_days=120)
    _aged_session(tmp_path, "fresh-sess", age_days=3)
    # Non-conversation files that must survive.
    (tmp_path / "notes.json").write_text('{"keep": 1}', encoding="utf-8")
    (tmp_path / "autonomy_journal.jsonl").write_text('{"keep": 1}\n', encoding="utf-8")

    report = retention.purge_old_conversations(ttl_days=90, root=tmp_path)

    assert report["deleted"] == ["old-sess"]
    assert not (tmp_path / "old-sess.jsonl").exists()
    assert not (tmp_path / "old-sess.json").exists()
    assert (tmp_path / "fresh-sess.jsonl").exists()
    assert (tmp_path / "notes.json").exists()
    assert (tmp_path / "autonomy_journal.jsonl").exists()


def test_conversation_ttl_zero_is_noop(tmp_path):
    _aged_session(tmp_path, "old-sess", age_days=999)
    report = retention.purge_old_conversations(ttl_days=0, root=tmp_path)
    assert report["deleted"] == []
    assert (tmp_path / "old-sess.jsonl").exists()


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


def test_run_retention_enabled_prunes_both(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    _aged_session(tmp_path, "old", age_days=120)
    _aged_session(tmp_path, "fresh", age_days=2)
    audit = _seed_audit(tmp_path, ages_days=[400, 1])
    settings = {
        "retention.enabled": True,
        "retention.conversation_ttl_days": 90,
        "retention.audit_ttl_days": 365,
    }
    out = retention.run_retention(lambda k, d=None: settings.get(k, d),
                                  audit_logger=audit, root=tmp_path)
    assert out["enabled"] is True
    assert out["conversations"]["deleted"] == ["old"]
    assert out["audit"]["deleted"] == 1
    assert not (tmp_path / "old.jsonl").exists()
    assert (tmp_path / "fresh.jsonl").exists()
    assert audit.verify_chain() == (True, None)


# ── settings ───────────────────────────────────────────────────────
def test_retention_settings_exist_and_default_off():
    by_key = {d["key"]: d for d in settings_db.DEFAULTS if d["category"] == "retention"}
    assert by_key["enabled"]["value"] is False           # off by default
    assert by_key["conversation_ttl_days"]["value"] == 90
    assert by_key["audit_ttl_days"]["value"] == 365
