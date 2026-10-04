"""Legacy GC remains compatible; new owned GC needs separate approved maintenance."""

import shutil

import pytest

from agents.core.file_tools import FileScope, FileTools, SnapshotStore


def _legacy_layout(tools):
    """Persist the pre-upgrade layout to exercise its unchanged GC contract."""
    owned = tools.history.payloads.directory
    for record in (owned / "records").iterdir():
        shutil.copyfile(record, tools.snapshots.directory / record.name)
    for blob in (owned / "blobs").iterdir():
        shutil.copyfile(blob, tools.snapshots.directory / "blobs" / blob.name)
    shutil.rmtree(owned)


@pytest.mark.asyncio
async def test_prune_index_does_not_destroy_generic_snapshot_ref(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("first", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    result = await tools.write_file({"path": str(target), "content": "second"}, approved=True)
    assert result["ok"]
    _legacy_layout(tools)
    entry = tools.history.list_entries()[0]
    post_blob = tools.snapshots.directory / "blobs" / entry["post_sha"]
    assert post_blob.exists()
    dry_run = tools.history.prune([entry["id"]], dry_run=True)
    assert dry_run["removed_entries"] == 1
    assert dry_run["would_reclaim_bytes"] == len(b"second")
    assert post_blob.exists() and len(tools.history.list_entries()) == 1
    report = tools.history.prune([entry["id"]], dry_run=False)
    assert report["removed_entries"] == 1
    assert report["reclaimed_bytes"] == len(b"second")
    assert not post_blob.exists()
    assert tools.history.list_entries() == []
    assert tools.snapshots.load(result["snapshot_ref"]) is not None
    assert tools.restore_snapshot(result["snapshot_ref"]) is True
    assert target.read_text(encoding="utf-8") == "first"


@pytest.mark.asyncio
async def test_malformed_generic_record_keeps_unproven_blob(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("first", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    assert (await tools.write_file({"path": str(target), "content": "second"}, approved=True))["ok"]
    _legacy_layout(tools)
    entry = tools.history.list_entries()[0]
    post_blob = tools.snapshots.directory / "blobs" / entry["post_sha"]
    (tools.snapshots.directory / ("a" * 64 + ".json")).write_text("broken", encoding="utf-8")
    report = tools.history.prune([entry["id"]], dry_run=False)
    assert report["blob_gc"] == "retained_ambiguous_record"
    assert post_blob.exists()


@pytest.mark.asyncio
async def test_index_only_prune_retains_owned_payloads_pending_approved_gc(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("first", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    result = await tools.write_file({"path": str(target), "content": "second"}, approved=True)
    assert result["ok"]
    row = tools.history.list_entries()[0]
    owned = tools.history.payloads.directory
    before = {str(p.relative_to(owned)): p.read_bytes()
              for p in owned.rglob("*") if p.is_file()}
    report = tools.history.prune([row["id"]], dry_run=False)
    assert report["removed_entries"] == 1 and report["reclaimed_bytes"] == 0
    assert before == {str(p.relative_to(owned)): p.read_bytes()
                      for p in owned.rglob("*") if p.is_file()}
    assert tools.restore_snapshot(result["snapshot_ref"])
    assert target.read_text() == "first"
