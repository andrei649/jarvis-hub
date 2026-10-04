"""Owner commands use real checkpoint metadata without changing files or chat."""

import json
import shlex
from types import SimpleNamespace

import pytest

from agents.core.commands import Principal, build_default_registry
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore
from agents.core.turn_notices import open_turn_notices, reset_turn_notices

OWNER = Principal(channel="web", admin=True)
GUEST = Principal(channel="web", admin=False)


@pytest.fixture
def owner_store(tmp_path, monkeypatch):
    root = tmp_path / "project with spaces"
    root.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(root))
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    monkeypatch.setenv("JARVIS_FILE_TOOLS", "0")
    orch = SimpleNamespace(commands=build_default_registry())
    return orch, root, SnapshotStore()


async def command(orch, text, principal=OWNER):
    notices, token = open_turn_notices()
    try:
        outcome = await orch.commands.dispatch(text, orch=orch, principal=principal)
        return outcome, notices
    finally:
        reset_turn_notices(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["status", "list"])
async def test_owner_can_query_absent_store_without_creating_it(owner_store, action):
    orch, _root, snapshots = owner_store
    outcome, notices = await command(orch, "/checkpoints " + action)
    assert outcome.status == "answered"
    value = json.loads(outcome.reply)
    assert value["ok"] is True
    assert [n["code"] for n in notices] == ["checkpoint.complete"]
    assert not snapshots.directory.exists()


@pytest.mark.asyncio
async def test_owner_query_lists_actual_completed_group_and_support_flags(owner_store):
    orch, root, snapshots = owner_store
    note = root / "note.txt"
    note.write_text("before")
    history = FileCheckpointHistory(snapshots, FileScope([root]))
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("after")
    history.finish_scope(capture["id"], reaped=True, run_id=capture["run_id"])
    outcome, notices = await command(orch, "/checkpoints list --project " + shlex.quote(str(root)))
    value = json.loads(outcome.reply)
    assert value["items"][0]["id"] == "group:" + capture["id"]
    assert value["items"][0]["root_state"] == "live"
    assert note.read_text() == "after" and notices[0]["code"] == "checkpoint.complete"
    status, _ = await command(orch, "/checkpoints status")
    features = json.loads(status.reply)["features"]
    assert features["file_history"]["enabled"] is False
    assert features["terminal_groups"]["enabled"] is True


@pytest.mark.asyncio
async def test_guest_is_refused_before_store_or_scope_construction(owner_store, monkeypatch):
    orch, _root, snapshots = owner_store

    def forbidden(*args, **kwargs):
        raise AssertionError("guest must not construct checkpoint scope")

    monkeypatch.setattr(FileScope, "from_env", forbidden)
    outcome, notices = await command(orch, "/checkpoints status", GUEST)
    assert outcome.status == "refused"
    assert not snapshots.directory.exists() and not notices


@pytest.mark.asyncio
async def test_clear_preview_names_exact_group_without_effect(owner_store):
    orch, root, snapshots = owner_store
    note = root / "note.txt"
    note.write_text("before")
    history = FileCheckpointHistory(snapshots, FileScope([root]))
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("after")
    history.finish_scope(capture["id"], reaped=True)
    before = {p.name for p in snapshots.directory.iterdir()}
    outcome, notices = await command(orch, "/checkpoints clear --dry-run")
    value = json.loads(outcome.reply)
    assert value["complete"] is True
    assert [r["id"] for r in value["candidates"]] == ["group:" + capture["id"]]
    assert len(value["generation"]) == 64 and value["reclaimable_bytes"] is None
    assert [n["code"] for n in notices] == ["checkpoint.preview"]
    assert note.read_text() == "after"
    assert before == {p.name for p in snapshots.directory.iterdir()}


@pytest.mark.asyncio
@pytest.mark.parametrize("args", ["clear --execute", "prune --execute --force",
                                 "clear-legacy --execute", "restore anything",
                                 "status --limit 501", "status --limit 0",
                                 "status --limit 1 --limit 2", "status --project 'unterminated",
                                 "clear --dry-run --execute", "status --execute"])
async def test_invalid_or_unavailable_effect_is_not_reported_as_completed(owner_store, args):
    orch, _root, snapshots = owner_store
    outcome, notices = await command(orch, "/checkpoints " + args)
    assert outcome.status == "answered"
    assert len(notices) == 1
    assert notices[0]["code"] in {"checkpoint.refused", "checkpoint.unavailable"}
    assert not snapshots.directory.exists()


@pytest.mark.asyncio
async def test_registry_refuses_oversize_checkpoint_without_truncation(owner_store):
    orch, _root, snapshots = owner_store
    outcome, _ = await command(orch, "/checkpoints status --project " + "x" * 2000)
    assert outcome.status == "refused"
    assert not snapshots.directory.exists()


@pytest.mark.asyncio
async def test_bare_rollback_lists_without_restoring(owner_store):
    orch, _root, snapshots = owner_store
    outcome, notices = await command(orch, "/rollback")
    assert outcome.status == "answered" and json.loads(outcome.reply)["items"] == []
    assert notices[0]["code"] == "checkpoint.complete" and not snapshots.directory.exists()
