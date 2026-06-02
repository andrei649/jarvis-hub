"""H7.2 / H7.3 — performance hot-path tests.

Tests:
  1. CheckpointManager is thread-safe: calling create_session_record from
     asyncio.to_thread does not raise "SQLite objects created in a thread".
  2. _maybe_checkpoint only persists every N turns (debounce).
  3. _flush_checkpoint forces a save immediately and resets the counter.

All offline, no network, no real LLM backend.
"""
import sys
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.checkpoint import CheckpointManager
from agents.core.orchestrator import Orchestrator


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_checkpoint_manager(tmp_path) -> CheckpointManager:
    """Return an initialized CheckpointManager backed by a tmp SQLite DB."""
    cm = CheckpointManager(db_path=str(tmp_path / "cp_test.db"))
    cm.initialize()
    return cm


def _make_bare_orchestrator(checkpoint_every: int = 3):
    """Build an Orchestrator without __init__ (heavy deps).

    Wires only the attributes touched by _maybe_checkpoint/_flush_checkpoint.
    """
    orch = Orchestrator.__new__(Orchestrator)
    orch._runtime_settings = {"memory.checkpoint_every": checkpoint_every}
    orch._turns_since_checkpoint = 0
    return orch


# ── test 1: thread-safety of CheckpointManager ───────────────────────────────

async def test_checkpoint_thread_safe_create_session(tmp_path):
    """create_session_record called via asyncio.to_thread must not raise."""
    cm = _make_checkpoint_manager(tmp_path)
    # Should complete without raising "SQLite objects created in a thread"
    await asyncio.to_thread(cm.create_session_record, "sess-thread-1", "jarvis")
    # Verify the record was actually written
    sessions = cm.get_sessions(limit=5)
    ids = [s["id"] for s in sessions]
    assert "sess-thread-1" in ids, f"Expected 'sess-thread-1' in sessions, got {ids}"
    cm.close()


async def test_checkpoint_thread_safe_save(tmp_path, monkeypatch):
    """CheckpointManager.save called from a worker thread must not raise."""
    cm = _make_checkpoint_manager(tmp_path)

    # Build a minimal orchestrator-like object with the fields save() reads.
    class FakeLLMRouter:
        name = "test"

    fake_orch = MagicMock()
    fake_orch.session_id = "sess-save-thread"
    fake_orch.agents = {}
    fake_orch.channels = {}
    fake_orch.llm_router = FakeLLMRouter()

    result = await asyncio.to_thread(cm.save, fake_orch)
    assert result is True, "save() should return True on success"
    cm.close()


async def test_checkpoint_thread_safe_concurrent(tmp_path):
    """Multiple concurrent to_thread calls must not corrupt the DB."""
    cm = _make_checkpoint_manager(tmp_path)

    async def _create(i):
        await asyncio.to_thread(cm.create_session_record, f"sess-concurrent-{i}", "jarvis")

    await asyncio.gather(*[_create(i) for i in range(10)])

    sessions = cm.get_sessions(limit=20)
    ids = {s["id"] for s in sessions}
    for i in range(10):
        assert f"sess-concurrent-{i}" in ids
    cm.close()


# ── test 2: _maybe_checkpoint debounce ───────────────────────────────────────

async def test_maybe_checkpoint_fires_every_n_turns(tmp_path):
    """save() should be called exactly once after N turns (default N=3 here)."""
    N = 3
    orch = _make_bare_orchestrator(checkpoint_every=N)

    save_calls = []

    class FakeCheckpoints:
        def save(self, o):
            save_calls.append(1)
            return True

    orch.checkpoints = FakeCheckpoints()

    # Drive N-1 turns — no save yet.
    for _ in range(N - 1):
        await orch._maybe_checkpoint()
    assert len(save_calls) == 0, f"Expected 0 saves after {N-1} turns, got {len(save_calls)}"

    # N-th turn — save fires and counter resets.
    await orch._maybe_checkpoint()
    assert len(save_calls) == 1, f"Expected 1 save after {N} turns, got {len(save_calls)}"
    assert orch._turns_since_checkpoint == 0, "Counter should reset after save"


async def test_maybe_checkpoint_fires_again_after_reset(tmp_path):
    """After the counter resets, save fires again after another N turns."""
    N = 3
    orch = _make_bare_orchestrator(checkpoint_every=N)
    save_calls = []

    class FakeCheckpoints:
        def save(self, o):
            save_calls.append(1)
            return True

    orch.checkpoints = FakeCheckpoints()

    # First batch of N turns.
    for _ in range(N):
        await orch._maybe_checkpoint()
    assert len(save_calls) == 1

    # Second batch of N turns.
    for _ in range(N):
        await orch._maybe_checkpoint()
    assert len(save_calls) == 2


async def test_maybe_checkpoint_n_plus_one_turns(tmp_path):
    """Driving N+1 turns produces exactly 1 save (the +1 is still pending)."""
    N = 3
    orch = _make_bare_orchestrator(checkpoint_every=N)
    save_calls = []

    class FakeCheckpoints:
        def save(self, o):
            save_calls.append(1)
            return True

    orch.checkpoints = FakeCheckpoints()

    for _ in range(N + 1):
        await orch._maybe_checkpoint()
    assert len(save_calls) == 1
    assert orch._turns_since_checkpoint == 1, "1 pending turn after second batch starts"


# ── test 3: _flush_checkpoint forces save and resets counter ─────────────────

async def test_flush_checkpoint_forces_save(tmp_path):
    """_flush_checkpoint() must call save() unconditionally."""
    orch = _make_bare_orchestrator(checkpoint_every=10)

    save_calls = []

    class FakeCheckpoints:
        def save(self, o):
            save_calls.append(1)
            return True

    orch.checkpoints = FakeCheckpoints()

    # Only 1 turn — would NOT normally trigger a save (threshold=10).
    await orch._maybe_checkpoint()
    assert len(save_calls) == 0

    # Flush must force save regardless.
    await orch._flush_checkpoint()
    assert len(save_calls) == 1, "flush must save immediately"
    assert orch._turns_since_checkpoint == 0, "flush must reset counter"


async def test_flush_checkpoint_resets_counter_to_zero():
    """Even if counter is mid-batch, flush resets it to 0."""
    orch = _make_bare_orchestrator(checkpoint_every=5)

    class FakeCheckpoints:
        def save(self, o):
            return True

    orch.checkpoints = FakeCheckpoints()

    # Accumulate 3 turns (mid-batch).
    for _ in range(3):
        await orch._maybe_checkpoint()
    assert orch._turns_since_checkpoint == 3

    await orch._flush_checkpoint()
    assert orch._turns_since_checkpoint == 0


async def test_aclose_flushes_checkpoint():
    """aclose() must trigger a flush (and not raise)."""
    orch = _make_bare_orchestrator(checkpoint_every=10)

    flush_called = []

    async def fake_flush():
        flush_called.append(1)

    orch._flush_checkpoint = fake_flush

    await orch.aclose()
    assert flush_called == [1], "aclose must call _flush_checkpoint"
