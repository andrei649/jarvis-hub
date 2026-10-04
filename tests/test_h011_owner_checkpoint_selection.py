"""Real owner registry resolves stable checkpoint previews without file effects."""

import json
import shlex

import pytest

from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope
from tests.test_h011_owner_checkpoint_commands import command, owner_store


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["diff", "restore", "rollback"])
async def test_real_registry_owner_diff_and_selected_force_preview(owner_store, action):
    orch, root, snapshots = owner_store
    note = root / "note with spaces.txt"
    other = root / "other.txt"
    note.write_text("before")
    other.write_text("old other")
    history = FileCheckpointHistory(snapshots, FileScope([root]))
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("agent")
    other.write_text("new other")
    assert history.finish_scope(capture["id"], reaped=True)["status"] == "finished"
    if action == "diff":
        text = "/checkpoints diff group:" + capture["id"]
    elif action == "restore":
        note.write_text("later owner")
        text = "/checkpoints restore group:" + capture["id"] + " --path " + shlex.quote(note.name) + " --force --dry-run"
    else:
        text = "/rollback 1 --dry-run"
    before = note.read_bytes(), other.read_bytes()
    outcome, notices = await command(orch, text)
    assert outcome.status == "answered"
    assert [n["code"] for n in notices] == ["checkpoint.complete" if action == "diff" else "checkpoint.preview"]
    result = json.loads(outcome.reply)
    assert result["ok"] is True and result["checkpoint_id"] == "group:" + capture["id"]
    assert result["requires_authority"] is True
    if action == "diff":
        assert "note with spaces.txt" in result["storage_diff"]["diff"]
    else:
        paths = result["storage_plan"]["paths"]
        assert {p["path"] for p in paths} == ({note.name} if action == "restore" else {note.name, other.name})
        if action == "restore":
            assert result["storage_plan"]["current"][note.name][2] == len(b"later owner")
    assert (note.read_bytes(), other.read_bytes()) == before
    assert not (snapshots.directory / "checkpoint_operations.sqlite3").exists()
