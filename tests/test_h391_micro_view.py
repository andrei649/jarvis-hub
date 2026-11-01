"""A micro summary is readable only with its durable source and clock receipt."""

from agents.core.checkpoint import CheckpointManager
from agents.core.memory import persistence
from agents.core.turn_compaction import TurnLifetime


def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    manager = CheckpointManager(str(tmp_path / "clock.db"))
    manager.initialize()
    manager.create_session_record("s")
    clock = manager.clock_snapshot("s")
    assert clock is not None
    return manager, clock


def _turns():
    return [{"role": "user", "content": "one", "timestamp": "t1"},
            {"role": "assistant", "content": "answer", "timestamp": "t2"},
            {"role": "user", "content": "two", "timestamp": "t3"},
            {"role": "assistant", "content": "reply", "timestamp": "t4"}]


def test_micro_view_commit_survives_restart_and_preserves_source(tmp_path, monkeypatch):
    manager, clock = _store(tmp_path, monkeypatch)
    original = _turns()
    persistence.save_memory("s", original, instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=manager)
    document, digest = persistence.read_snapshot_for_rewind("s")
    assert manager.commit_micro_view(clock, history_revision=4, history_digest=digest,
                                     covered_count=2, summary="one / answer")
    assert manager.load_micro_view("s")["summary"] == "one / answer"
    lineage = manager.load_micro_view("s")["lineage"]
    assert lineage["schema"] == "nerva.context-compaction.v1"
    assert lineage["evicted_turns"] == 2
    assert lineage["parent_session_id"] == "s"
    assert persistence.read_snapshot_for_rewind("s")[0]["turns"] == original
    manager.close()
    reopened = CheckpointManager(str(tmp_path / "clock.db"))
    reopened.initialize()
    assert reopened.load_micro_view("s")["covered_count"] == 2
    reopened.close()


def test_micro_view_refuses_stale_revision_and_rewind(tmp_path, monkeypatch):
    manager, clock = _store(tmp_path, monkeypatch)
    persistence.save_memory("s", _turns(), instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=manager)
    _, digest = persistence.read_snapshot_for_rewind("s")
    assert not manager.commit_micro_view(clock, history_revision=3, history_digest=digest,
                                         covered_count=2, summary="stale")
    assert manager.load_micro_view("s") is None
    assert manager.commit_micro_view(clock, history_revision=4, history_digest=digest,
                                     covered_count=2, summary="one / answer")
    document, _ = persistence.read_snapshot_for_rewind("s")
    persistence.save_memory("s", document["turns"], instance_id=clock.instance_id,
                            revision=5, checkpoint_mgr=manager)
    assert manager.load_micro_view("s") is not None  # append-only successor
    with (persistence._memory_dir() / "s.json").open("r+", encoding="utf8") as stream:
        import json
        changed = json.load(stream)
        changed["turns"][0]["content"] = "rewound"
        stream.seek(0)
        json.dump(changed, stream)
        stream.truncate()
    assert manager.load_micro_view("s") is None
    manager.close()


async def test_cancelled_lifetime_queued_behind_store_lock_cannot_publish(tmp_path, monkeypatch):
    import asyncio
    import threading

    manager, clock = _store(tmp_path, monkeypatch)
    persistence.save_memory("s", _turns(), instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=manager)
    _, digest = persistence.read_snapshot_for_rewind("s")
    lifetime = TurnLifetime()
    entered = threading.Event()
    manager._lock.acquire()
    try:
        def queued():
            entered.set()
            return manager.commit_micro_view(
                clock, history_revision=4, history_digest=digest,
                covered_count=2, summary="too late", lifetime=lifetime)

        worker = asyncio.create_task(asyncio.to_thread(queued))
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait), 2)
        lifetime.close()
    finally:
        manager._lock.release()
    assert not await asyncio.wait_for(worker, 2)
    assert manager.load_micro_view("s") is None
    assert manager.clock_snapshot("s") == clock
    manager.close()


def test_micro_insert_failure_rolls_back_clock_and_does_not_publish(tmp_path, monkeypatch):
    manager, clock = _store(tmp_path, monkeypatch)
    persistence.save_memory("s", _turns(), instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=manager)
    _, digest = persistence.read_snapshot_for_rewind("s")
    manager._conn.execute("""CREATE TRIGGER deny_micro BEFORE INSERT ON session_micro_views
        BEGIN SELECT RAISE(ABORT, 'blocked'); END""")
    manager._conn.commit()
    assert not manager.commit_micro_view(clock, history_revision=4,
                                         history_digest=digest, covered_count=2,
                                         summary="must not publish")
    assert manager.load_micro_view("s") is None
    assert manager.clock_snapshot("s") == clock
    manager.close()
