"""Direct H396 receipts describe one returned file mutation attempt only."""

import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import file_tools as module
from agents.core.file_tools import FileScope, FileTools, SnapshotStore
from agents.core.kernel import Decision, Verdict


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "workspace"
    path.mkdir()
    (path / "notes.txt").write_bytes(b"old")
    return path


def make_tools(root, *, authorizer=None, snapshots=None):
    return FileTools(
        FileScope([root]),
        snapshots=snapshots or SnapshotStore(root.parent / "snaps"),
        max_bytes=64,
        authorizer=authorizer,
    )


def receipt(result, path, op, outcome):
    assert result["mutation_receipt"] == {
        "path": str(path), "op": op, "outcome": outcome,
    }
    assert set(result["mutation_receipt"]) == {"path", "op", "outcome"}


@pytest.mark.asyncio
async def test_existing_write_has_applied_receipt_and_unchanged_legacy_result(root):
    tools = make_tools(root)
    target = root / "notes.txt"
    result = await tools.write_file({"path": "notes.txt", "content": "new"})
    assert target.read_bytes() == b"new"
    assert {k: result[k] for k in ("ok", "op", "path", "bytes", "existed")} == {
        "ok": True, "op": "write", "path": str(target), "bytes": 3, "existed": True,
    }
    assert tools.restore_snapshot(result["snapshot_ref"]) is True
    assert target.read_bytes() == b"old"
    receipt(result, target, "write", "applied")


@pytest.mark.asyncio
async def test_new_write_reports_applied(root):
    tools = make_tools(root)
    target = root / "new.txt"
    created = await tools.write_file({"path": "new.txt", "content": "fresh"})
    assert target.read_bytes() == b"fresh"
    assert created["ok"] is True and created["existed"] is False
    receipt(created, target, "write", "applied")


@pytest.mark.asyncio
async def test_delete_reports_applied_and_can_restore(root):
    tools = make_tools(root)
    target = root / "notes.txt"
    deleted = await tools.delete_file({"path": "notes.txt"})
    assert not target.exists()
    assert deleted["ok"] is True and deleted["op"] == "delete"
    assert deleted["path"] == str(target) and deleted["existed"] is True
    assert tools.restore_snapshot(deleted["snapshot_ref"]) is True
    assert target.read_bytes() == b"old"
    receipt(deleted, target, "delete", "applied")


@pytest.mark.asyncio
async def test_allowed_symlink_alias_uses_existing_canonical_target(root):
    target = root / "notes.txt"
    link = root / "alias.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    tools = make_tools(root)
    written = await tools.write_file({"path": "alias.txt", "content": "alias"})
    assert written["ok"] is True and target.read_bytes() == b"alias"
    assert written["path"] == str(target)
    receipt(written, target, "write", "applied")


@pytest.mark.asyncio
async def test_allowed_symlink_alias_denial_names_canonical_target(root, monkeypatch):
    target = root / "notes.txt"
    link = root / "alias.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    calls = []

    def deny(action):
        calls.append(action)
        return Decision(Verdict.DENY, reason="owner")

    result = await make_tools(root, authorizer=deny).write_file(
        {"path": "alias.txt", "content": "new"}
    )
    assert target.read_bytes() == b"old" and link.is_symlink()
    assert result["ok"] is False and result["reason"] == "kernel_denied:owner"
    assert calls[0].payload["path"] == str(target)
    receipt(result, target, "write", "refused")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError("snapshot_failed"), OSError("disk")])
async def test_snapshot_failures_refuse_without_applying(root, failure):
    class FailedSnapshots(SnapshotStore):
        def take(self, target, *, now=None):
            raise failure

    target = root / "notes.txt"
    tools = make_tools(root, snapshots=FailedSnapshots(root.parent / "snaps"))
    result = await tools.write_file({"path": "notes.txt", "content": "new"})
    assert target.read_bytes() == b"old"
    assert result["ok"] is False and result["reason"] == "snapshot_failed"
    if isinstance(failure, OSError):
        assert result["detail"] == "OSError"
    receipt(result, target, "write", "refused")


@pytest.mark.asyncio
@pytest.mark.parametrize("path,reason", [("missing.txt", "not_found"), ("sub", "not_a_file")])
async def test_delete_missing_or_directory_refuses_without_apply(root, path, reason):
    (root / "sub").mkdir()
    result = await make_tools(root).delete_file({"path": path})
    assert (root / "sub").is_dir() and (root / "notes.txt").read_bytes() == b"old"
    assert result["ok"] is False and result["reason"] == reason
    receipt(result, root / path, "delete", "refused")


@pytest.mark.asyncio
async def test_contract_denial_retains_snapshot_and_refused_receipt(root, monkeypatch):
    class DenyContract:
        def evaluate(self, payload, *, now):
            return SimpleNamespace(admissible=False, reason="contract_denied")

    monkeypatch.setattr(module, "FILE_WRITE_CONTRACT", DenyContract())
    target = root / "notes.txt"
    result = await make_tools(root).write_file({"path": "notes.txt", "content": "new"})
    assert target.read_bytes() == b"old"
    assert result["ok"] is False and result["reason"] == "contract_denied"
    assert isinstance(result["snapshot_ref"], str)
    receipt(result, target, "write", "refused")


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict,expected", [
    (Verdict.DENY, "kernel_denied:owner"),
    (Verdict.QUEUE, "approval_required"),
])
async def test_kernel_denial_or_queue_keeps_action_shape_and_refuses(root, monkeypatch, verdict, expected):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    calls = []

    def kernel(action):
        calls.append(action)
        return Decision(verdict, reason="owner")

    target = root / "notes.txt"
    result = await make_tools(root, authorizer=kernel).write_file(
        {"path": "notes.txt", "content": "new"}
    )
    assert target.read_bytes() == b"old"
    assert result["ok"] is False and result["reason"] == expected
    assert isinstance(result["snapshot_ref"], str)
    assert len(calls) == 1
    assert calls[0].payload == {
        "op": "write", "path": str(target), "bytes": 3,
        "snapshot_ref": result["snapshot_ref"], "steers_future_runs": False,
    }
    receipt(result, target, "write", "refused")


@pytest.mark.asyncio
async def test_kernel_exception_is_refusal(root, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")

    def broken_kernel(action):
        raise RuntimeError("unavailable")

    target = root / "notes.txt"
    denied = await make_tools(root, authorizer=broken_kernel).write_file(
        {"path": "notes.txt", "content": "new"}
    )
    assert target.read_bytes() == b"old"
    assert denied["ok"] is False and denied["reason"] == "kernel_error"
    receipt(denied, target, "write", "refused")


@pytest.mark.asyncio
async def test_instruction_floor_is_refusal(root):
    soul = root / "SOUL.md"
    soul.write_text("old", encoding="utf-8")
    floor = await make_tools(root).write_file({"path": "SOUL.md", "content": "new"})
    assert soul.read_text(encoding="utf-8") == "old"
    assert floor["ok"] is False and floor["reason"] == "approval_required"
    assert floor["class"] == "agent_instructions"
    receipt(floor, soul, "write", "refused")


@pytest.mark.asyncio
@pytest.mark.parametrize("after_effect", [False, True])
async def test_write_oserror_is_unknown_even_if_bytes_changed(root, monkeypatch, after_effect):
    target = root / "notes.txt"
    original = module._atomic_write

    def fault(path, data, *, mode):
        if path == target:
            if after_effect:
                original(path, data, mode=mode)
            raise OSError("injected")
        return original(path, data, mode=mode)

    monkeypatch.setattr(module, "_atomic_write", fault)
    result = await make_tools(root).write_file({"path": "notes.txt", "content": "new"})
    assert target.read_bytes() == (b"new" if after_effect else b"old")
    assert result["ok"] is False and result["reason"] == "io_error"
    assert result["detail"] == "OSError" and isinstance(result["snapshot_ref"], str)
    receipt(result, target, "write", "unknown")


@pytest.mark.asyncio
@pytest.mark.parametrize("after_effect", [False, True])
async def test_delete_oserror_is_unknown_even_if_file_disappeared(root, monkeypatch, after_effect):
    target = root / "notes.txt"
    original = Path.unlink

    def fault(path, *args, **kwargs):
        if path == target:
            if after_effect:
                original(path, *args, **kwargs)
            raise OSError("injected")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fault)
    result = await make_tools(root).delete_file({"path": "notes.txt"})
    assert target.exists() is (not after_effect)
    assert result["ok"] is False and result["reason"] == "io_error"
    assert result["detail"] == "OSError" and isinstance(result["snapshot_ref"], str)
    receipt(result, target, "delete", "unknown")


@pytest.mark.asyncio
async def test_early_validation_and_scope_refusals_have_no_identity_receipt(root, tmp_path):
    tools = make_tools(root)
    attempts = [
        (lambda: tools.write_file({"path": "notes.txt", "content": 3}), "bad_content"),
        (lambda: tools.write_file({"path": "notes.txt", "content": "x" * 65}), "too_large"),
        (lambda: tools.write_file({"path": "../escape.txt", "content": "x"}), "outside_scope"),
        (lambda: tools.write_file({"path": ".env", "content": "x"}), "secret_path"),
        (lambda: tools.delete_file({"path": str(root)}), "outside_scope"),
        (lambda: tools.delete_file({"path": None}), "bad_path"),
    ]
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"untouched")
    link = root / "escape.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pass
    else:
        attempts.append((lambda: tools.delete_file({"path": "escape.txt"}), "symlink_escape"))
    for attempt, reason in attempts:
        result = await attempt()
        assert result["ok"] is False and result["reason"] == reason
        assert "mutation_receipt" not in result
    assert (root / "notes.txt").read_bytes() == b"old"
    assert outside.read_bytes() == b"untouched"
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.asyncio
async def test_cancellation_during_worker_propagates_without_returned_receipt(root, monkeypatch):
    target = root / "notes.txt"
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original = module._atomic_write

    def blocked(path, data, *, mode):
        if path == target:
            entered.set()
            try:
                if not release.wait(2):
                    raise OSError("worker timeout")
                return original(path, data, mode=mode)
            finally:
                finished.set()
        return original(path, data, mode=mode)

    monkeypatch.setattr(module, "_atomic_write", blocked)
    task = asyncio.create_task(make_tools(root).write_file({"path": "notes.txt", "content": "late"}))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert target.read_bytes() == b"late"
