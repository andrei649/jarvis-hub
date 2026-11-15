"""Isolated native lineage fixture for HTTP and selected-image route tests."""

from pathlib import Path
from tempfile import TemporaryDirectory

from agents.core.checkpoint import CheckpointManager
from agents.core.memory import conversation, persistence


def _register_undo_callback(monkeypatch, fn) -> None:
    """Register *fn* on *monkeypatch* teardown across both pytest 8.x and pytest 9+."""
    if hasattr(monkeypatch, "callback"):
        monkeypatch.callback(fn)
        return

    class _UndoHook:
        active = True

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if name == "active" and value is True:
                fn()

    hook = _UndoHook()
    monkeypatch.setattr(hook, "active", False)


def bind_native(orch, monkeypatch, *, session_ids=()) -> CheckpointManager:
    """Bind a real private checkpoint store before creating native sessions.

    Keep the temporary root alive with the orchestrator; tests can create further
    sessions through memory.new_session, which records their native lineage.
    """
    temporary = TemporaryDirectory(prefix="nerva-native-test-", ignore_cleanup_errors=True)
    root = Path(temporary.name)
    orch._h441_native_fixture_root = temporary
    monkeypatch.setenv("JARVIS_HOME", str(root))
    monkeypatch.setattr(conversation, "MEMORY_DIR", root / "memory")
    monkeypatch.setattr(persistence, "MEMORY_DIR", root / "memory")
    checkpoints = CheckpointManager(str(root / "checkpoints.db"))
    checkpoints.initialize()
    _register_undo_callback(monkeypatch, temporary.cleanup)
    _register_undo_callback(monkeypatch, checkpoints.close)
    orch.checkpoints = checkpoints
    if hasattr(orch, "memory") and hasattr(orch.memory, "set_checkpoint_manager"):
        orch.memory.set_checkpoint_manager(checkpoints)
    for sid in session_ids:
        checkpoints.create_session_record(sid)
    return checkpoints
