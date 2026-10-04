"""Root integration proves checkpoint capture surrounds governed physical spawn."""

from __future__ import annotations

import pytest

from agents.core.environments import TargetAuditChain, TargetRegistry, TerminalTarget
from agents.core.environments.execution import GovernedTargetRunner
from agents.core.environments.local_transport import LocalHostTransport
from agents.core.kernel import Decision, Verdict


@pytest.mark.asyncio
async def test_governed_spawn_preserves_before_and_after_image(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    for name in ("JARVIS_TERMINAL_LOCAL_HOST", "JARVIS_ACTION_KERNEL",
                 "JARVIS_TERMINAL_CHECKPOINTS"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    calls = []

    class Stream:
        async def read(self, count):
            return b""

    class Process:
        stdout = Stream()
        stderr = Stream()
        returncode = 0

        async def wait(self):
            return self.returncode

    async def spawn(*argv, **kwargs):
        calls.append(argv)
        note.write_text("after", encoding="utf-8")
        return Process()

    registry = TargetRegistry((TerminalTarget(
        name="host", backend="local", enabled=True,
        allowed_agents=frozenset({"jarvis"}),
        capabilities=frozenset({"terminal.exec"}),
        approval_required=frozenset({"terminal.exec"}),
    ),), audit=TargetAuditChain())
    runner = GovernedTargetRunner(
        registry, object(), local_transport=LocalHostTransport([root], spawn=spawn),
        authorizer=lambda *a, **k: Decision(Verdict.GRANT, reason="synthetic", tier=3),
        approval_check=lambda task_id: task_id == 12,
        request_check=lambda task_id, request: task_id == 12,
    )
    result = await runner.run(target="host", agent="jarvis", command="rm note.txt",
                              cwd=str(root), approved_task_id=12)
    assert result["ok"] is True and calls == [("rm", "note.txt")]
    assert note.read_text() == "after"
    assert result["checkpoint"]["status"] == "finished"
    assert result["checkpoint"]["modified"] == 1

    from agents.core.file_checkpoint_history import FileCheckpointHistory
    from agents.core.file_tools import FileScope, SnapshotStore

    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    restored = history.restore_group(result["checkpoint"]["id"])
    assert restored["status"] == "restored" and note.read_text() == "before"
