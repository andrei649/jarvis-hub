"""The reply is durable before the optional rolling prompt view advances."""

from types import SimpleNamespace

from agents.core.checkpoint import CheckpointManager
from agents.core.memory import persistence
from agents.core.orchestrator import Orchestrator


def _turns(n):
    rows = []
    for index in range(n):
        rows.extend(({"role": "user", "content": f"ask {index}", "timestamp": f"u{index}"},
                     {"role": "assistant", "content": f"answer {index}", "timestamp": f"a{index}"}))
    return rows


async def test_micro_view_absorbs_one_old_exchange_per_completed_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "clock.db"))
    cp.initialize()
    cp.create_session_record("s")
    clock = cp.clock_snapshot("s")
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = cp
    orch.memory = SimpleNamespace(conversation=SimpleNamespace(persist=True))
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
        "memory.compression_micro_every_n_turns": 1,
    }.get(key, default)
    original = _turns(2)
    persistence.save_memory("s", original, instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=cp)
    assert await orch._maybe_micro_compact("answer 1")
    first = cp.load_micro_view("s")
    assert first["covered_count"] == 2
    assert "ask 0" in first["summary"]
    assert persistence.read_snapshot_for_rewind("s")[0]["turns"] == original

    more = _turns(3)
    persistence.save_memory("s", more, instance_id=clock.instance_id,
                            revision=6, checkpoint_mgr=cp)
    assert await orch._maybe_micro_compact("answer 2")
    assert cp.load_micro_view("s")["covered_count"] == 4
    assert persistence.read_snapshot_for_rewind("s")[0]["turns"] == more
    cp.close()


async def test_micro_default_off_checkpoint_and_cadence_do_not_advance(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "clock.db"))
    cp.initialize()
    cp.create_session_record("s")
    clock = cp.clock_snapshot("s")
    persistence.save_memory("s", _turns(2), instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=cp)
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = cp
    orch.memory = SimpleNamespace(conversation=SimpleNamespace(persist=True))
    settings = {"memory.context_compression": True}
    orch.get_setting = lambda key, default=None: settings.get(key, default)
    assert not await orch._maybe_micro_compact("answer 1")
    settings["memory.compression_micro_compact"] = True
    settings["memory.compression_checkpoint_required"] = True
    assert not await orch._maybe_micro_compact("answer 1")
    settings["memory.compression_checkpoint_required"] = False
    settings["memory.compression_micro_every_n_turns"] = 3
    assert not await orch._maybe_micro_compact("answer 1")
    assert cp.load_micro_view("s") is None
    cp.close()


async def test_next_prompt_reads_only_accepted_micro_view(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "clock.db"))
    cp.initialize()
    cp.create_session_record("s")
    clock = cp.clock_snapshot("s")
    rows = _turns(3)
    persistence.save_memory("s", rows, instance_id=clock.instance_id,
                            revision=6, checkpoint_mgr=cp)
    _, digest = persistence.read_snapshot_for_rewind("s")
    assert cp.commit_micro_view(clock, history_revision=6, history_digest=digest,
                                covered_count=2, summary="old exchange summary")

    class Memory:
        conversation = SimpleNamespace(foreign_origins={})

        async def get_history(self, sid, last_n=None):
            return list(rows)

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = cp
    orch.memory = Memory()
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
        "memory.compression_max_tokens": 2000,
    }.get(key, default)
    rendered = await orch._history_for_prompt(10)
    assert "old exchange summary" in rendered
    assert "ask 0" not in rendered
    assert "ask 2" in rendered
    cp.close()


async def test_cancelled_micro_worker_waiting_before_commit_cannot_publish(tmp_path, monkeypatch):
    import asyncio
    import threading

    import pytest

    from agents.core.turn_compaction import TurnLifetime

    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "clock.db"))
    cp.initialize()
    cp.create_session_record("s")
    before = cp.clock_snapshot("s")
    persistence.save_memory("s", _turns(2), instance_id=before.instance_id,
                            revision=4, checkpoint_mgr=cp)
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = cp
    orch.memory = SimpleNamespace(conversation=SimpleNamespace(persist=True))
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
    }.get(key, default)
    gate, entered, closed = threading.Event(), threading.Event(), threading.Event()
    original_commit = cp.commit_micro_view
    original_close = TurnLifetime.close

    def held_commit(*args, **kwargs):
        entered.set()
        gate.wait()
        return original_commit(*args, **kwargs)

    def noted_close(self):
        original_close(self)
        closed.set()

    monkeypatch.setattr(cp, "commit_micro_view", held_commit)
    monkeypatch.setattr(TurnLifetime, "close", noted_close)
    task = asyncio.create_task(orch._maybe_micro_compact("answer 1"))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait), 2)
        task.cancel()
        assert await asyncio.wait_for(asyncio.to_thread(closed.wait), 2)
    finally:
        gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cp.load_micro_view("s") is None
    assert cp.clock_snapshot("s") == before
    cp.close()


async def test_micro_opt_in_without_accepted_view_keeps_existing_last_n_history():
    rows = _turns(4)
    calls = []

    class Memory:
        conversation = SimpleNamespace(foreign_origins={})

        async def get_history(self, sid, last_n=None):
            calls.append(last_n)
            return rows[-last_n:] if last_n is not None else rows

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.memory = Memory()
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
    }.get(key, default)
    rendered = await orch._history_for_prompt(4)
    assert calls == [4]
    assert "ask 0" not in rendered
    assert "ask 2" in rendered


async def test_micro_uses_existing_strict_local_summarizer_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "clock.db"))
    cp.initialize()
    cp.create_session_record("s")
    clock = cp.clock_snapshot("s")
    persistence.save_memory("s", _turns(2), instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=cp)
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = cp
    orch.memory = SimpleNamespace(conversation=SimpleNamespace(persist=True))
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
        "memory.compression_summarizer": True,
    }.get(key, default)
    prompts = []

    async def local_summary(prompt):
        prompts.append(prompt)
        return "locally compressed exchange"

    orch._compression_summarizer = lambda: local_summary
    assert await orch._maybe_micro_compact("answer 1")
    assert cp.load_micro_view("s")["summary"] == "locally compressed exchange"
    assert "ask 0" in prompts[0]
    cp.close()
