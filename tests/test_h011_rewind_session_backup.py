"""The existing encrypted session-delete backup must retain rewind authority."""

import json
from pathlib import Path

import pytest

from agents.core import session_archive
from agents.core.checkpoint import CheckpointManager
from agents.core.memory import conversation, persistence
from agents.core.memory.manager import MemoryManager
from agents.core.session_continuation import history_identity


@pytest.mark.asyncio
async def test_encrypted_delete_backup_retains_exact_rewind_head(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    monkeypatch.setattr(persistence, "MEMORY_DIR", root)
    monkeypatch.setattr(conversation, "MEMORY_DIR", root)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("JARVIS_BACKUP_KEY", raising=False)
    cp = CheckpointManager(str(tmp_path / "checkpoints.db"))
    cp.initialize()
    try:
        memory = MemoryManager()
        memory.set_checkpoint_manager(cp)
        sid = await memory.new_session("rewound_backup")
        clock = cp.clock_snapshot(sid)
        await memory.add_turn(sid, "user", "private edit")
        ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
        await memory.commit_rollback_rewind(ticket)
        snapshot = json.loads((root / f"{sid}.json").read_text())
        with cp._lock:
            bound, _legacy = history_identity(cp._conn, sid)
            head = cp._conn.execute(
                "SELECT session_id,instance_id,revision,snapshot_sha256 "
                "FROM session_history_rewinds WHERE session_id=?", (sid,)
            ).fetchone()
        assert bound == clock.instance_id and head[1] == bound
        assert cp.set_archived(sid, True, at="2026-10-03T00:00:00+00:00") is True
        deleted = await session_archive.delete_session(
            sid, checkpoints=cp, backup_root=tmp_path / "backups", active="other", prune=False
        )
        backup = Path(deleted["backup"])
        assert backup.is_file() and b"private edit" not in backup.read_bytes()
        record = session_archive.read_backup(backup)
        assert record["rewind"] == dict(zip(
            ("session_id", "instance_id", "revision", "snapshot_sha256"), head, strict=True
        ))
        assert record["snapshot"] == snapshot
        assert json.loads(record["session"]["metadata"])["archived_at"] == "2026-10-03T00:00:00+00:00"
        assert record["history_instance"]["instance_id"] == bound
        assert record["clock"]["instance_id"] == bound
        assert deleted["removed"]["rows"]["session_history_rewinds"] == 1
        assert cp._conn.execute(
            "SELECT 1 FROM session_history_rewinds WHERE session_id=?", (sid,)
        ).fetchone() is None
    finally:
        cp.close()


def test_encrypted_legacy_backup_without_rewind_key_stays_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("JARVIS_BACKUP_KEY", raising=False)
    old = {"session_id": "legacy", "session": {"id": "legacy"},
           "snapshot": {"session_id": "legacy", "turns": []}}
    path = session_archive._write_backup(old, tmp_path / "legacy.json.enc")
    assert session_archive.read_backup(path) == old
    assert "rewind" not in session_archive.read_backup(path)
