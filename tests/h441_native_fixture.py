"""Isolated native lineage fixture for HTTP and selected-image route tests."""

from pathlib import Path
from tempfile import TemporaryDirectory

from agents.core.checkpoint import CheckpointManager
from agents.core.memory import conversation, persistence


def bind_native(orch, monkeypatch, *, session_ids=()) -> CheckpointManager:
    """Bind a real private checkpoint store before creating native sessions.

    Keep the temporary root alive with the orchestrator; tests can create further
    sessions through memory.new_session, which records their native lineage.
    """
    temporary = TemporaryDirectory(prefix="nerva-native-test-")
    root = Path(temporary.name)
    orch._h441_native_fixture_root = temporary
    monkeypatch.setenv("JARVIS_HOME", str(root))
    monkeypatch.setattr(conversation, "MEMORY_DIR", root / "memory")
    monkeypatch.setattr(persistence, "MEMORY_DIR", root / "memory")
    checkpoints = CheckpointManager(str(root / "checkpoints.db"))
    checkpoints.initialize()
    orch.checkpoints = checkpoints
    if hasattr(orch, "memory") and hasattr(orch.memory, "set_checkpoint_manager"):
        orch.memory.set_checkpoint_manager(checkpoints)
    for sid in session_ids:
        checkpoints.create_session_record(sid)
    return checkpoints
