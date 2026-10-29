"""The reply is durable before the optional rolling prompt view advances."""

from types import SimpleNamespace

from agents.core.checkpoint import CheckpointManager
from agents.core.memory import persistence
from agents.core.memory.compaction_state import _digest
from agents.core.memory.conversation import DurableAppendReceipt
from agents.core.orchestrator import Orchestrator


def _turns(n):
    rows = []
    for index in range(n):
        rows.extend(({"role": "user", "content": f"ask {index}", "timestamp": f"u{index}"},
                     {"role": "assistant", "content": f"answer {index}", "timestamp": f"a{index}"}))
    return rows


def _receipt(rows, clock, revision):
    return DurableAppendReceipt("s", clock.instance_id, revision,
                                len(rows), _digest(rows[-1]))


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
    assert await orch._maybe_micro_compact(
        "answer 1", append_receipt=_receipt(original, clock, 4))
    first = cp.load_micro_view("s")
    assert first["covered_count"] == 2
    assert "ask 0" in first["summary"]
    assert persistence.read_snapshot_for_rewind("s")[0]["turns"] == original

    more = _turns(3)
    persistence.save_memory("s", more, instance_id=clock.instance_id,
                            revision=6, checkpoint_mgr=cp)
    assert await orch._maybe_micro_compact(
        "answer 2", append_receipt=_receipt(more, clock, 6))
    assert cp.load_micro_view("s")["covered_count"] == 4
    assert persistence.read_snapshot_for_rewind("s")[0]["turns"] == more
    cp.close()


async def test_micro_refuses_old_snapshot_when_current_assistant_append_is_unproved(tmp_path, monkeypatch):
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
    }.get(key, default)
    assert not await orch._maybe_micro_compact("new answer")
    assert cp.load_micro_view("s") is None
    assert cp.clock_snapshot("s").revision == clock.revision
    cp.close()


async def test_failed_current_snapshot_save_produces_no_micro_receipt(tmp_path, monkeypatch):
    from agents.core.memory import conversation as conversation_module

    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "clock.db"))
    cp.initialize()
    cp.create_session_record("s")
    clock = cp.clock_snapshot("s")
    original = _turns(2)
    persistence.save_memory("s", original, instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=cp)
    conversation = conversation_module.ConversationMemory(persist=True)
    assert conversation.revisions["s"] == 4

    def failed_save(*args, **kwargs):
        raise OSError("synthetic full-snapshot failure")

    monkeypatch.setattr(conversation_module, "save_memory", failed_save)
    receipt = await conversation.add_turn("s", "assistant", "new answer")
    assert receipt is None
    assert persistence.read_snapshot_for_rewind("s")[0]["turns"] == original
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = cp
    orch.memory = SimpleNamespace(conversation=conversation)
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
    }.get(key, default)
    assert not await orch._maybe_micro_compact("new answer", append_receipt=receipt)
    assert cp.clock_snapshot("s").revision == clock.revision
    assert cp.load_micro_view("s") is None
    cp.close()


async def test_successful_real_assistant_append_receipt_allows_micro_commit(tmp_path, monkeypatch):
    from agents.core.memory.conversation import ConversationMemory
    from agents.core.memory.manager import MemoryManager

    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    monkeypatch.setattr("agents.core.settings_db.get_value",
                        lambda category, key, default=None: default)
    cp = CheckpointManager(str(tmp_path / "clock.db"))
    cp.initialize()
    cp.create_session_record("s")
    clock = cp.clock_snapshot("s")
    conversation = ConversationMemory(persist=True)
    await conversation.new_session("s")
    conversation.instances["s"] = clock.instance_id
    for row in _turns(2)[:-1]:
        await conversation.add_turn("s", row["role"], row["content"])
    memory = MemoryManager()
    memory.conversation = conversation
    memory.set_checkpoint_manager(cp)
    last = _turns(2)[-1]
    receipt = await memory.add_turn("s", last["role"], last["content"])
    assert isinstance(receipt, DurableAppendReceipt)
    assert receipt.revision == 4 and receipt.history_count == 4
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = cp
    orch.memory = memory
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
    }.get(key, default)
    assert await orch._maybe_micro_compact("answer 1", append_receipt=receipt)
    assert cp.load_micro_view("s")["covered_count"] == 2
    cp.close()


async def test_micro_receipt_rejects_repeated_and_stale_identical_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "clock.db"))
    cp.initialize()
    cp.create_session_record("s")
    clock = cp.clock_snapshot("s")
    rows = _turns(2)
    persistence.save_memory("s", rows, instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=cp)
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = cp
    orch.memory = SimpleNamespace(conversation=SimpleNamespace(persist=True))
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
    }.get(key, default)
    receipt = _receipt(rows, clock, 4)
    assert await orch._maybe_micro_compact("answer 1", append_receipt=receipt)
    after_first = cp.clock_snapshot("s").revision
    assert not await orch._maybe_micro_compact("answer 1", append_receipt=receipt)
    assert cp.clock_snapshot("s").revision == after_first
    later = _turns(3)
    later[-1]["content"] = "answer 1"
    persistence.save_memory("s", later, instance_id=clock.instance_id,
                            revision=6, checkpoint_mgr=cp)
    assert not await orch._maybe_micro_compact("answer 1", append_receipt=receipt)
    assert cp.clock_snapshot("s").revision == after_first
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
    task = asyncio.create_task(orch._maybe_micro_compact(
        "answer 1", append_receipt=_receipt(_turns(2), before, 4)))
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
    assert await orch._maybe_micro_compact(
        "answer 1", append_receipt=_receipt(_turns(2), clock, 4))
    assert cp.load_micro_view("s")["summary"] == "locally compressed exchange"
    assert "ask 0" in prompts[0]
    cp.close()
