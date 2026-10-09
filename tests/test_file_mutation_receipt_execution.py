"""Approved file mutation receipts belong to execution, not approval intake."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

import agents.core.file_tools as file_tools
from agents.core.file_checkpoint_history import HISTORY_SUPPORTED
from agents.core.file_tools import FileScope, FileTools, SnapshotStore, register_file_tools
from agents.core.kernel import Decision, Verdict
from agents.core.tool_rpc import ToolRPCServer


@pytest.fixture
def registered(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "notes.txt"
    target.write_text("before", encoding="utf-8")
    queued = []
    token = object()
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))

    def enqueue(agent, kind, title, payload=None, **kwargs):
        queued.append(SimpleNamespace(id=len(queued) + 1, agent=agent, kind=kind,
                                      title=title, payload=payload))
        return len(queued)

    server = ToolRPCServer(
        enqueue=enqueue,
        execution_context_check=lambda context, task: context is token,
    )
    register_file_tools(server, tools, enabled=True)
    return SimpleNamespace(root=root, target=target, queued=queued, token=token,
                           tools=tools, server=server)


def _task(tool, args, *, classification=None):
    payload = {"tool": tool, "target": tool, "args": args}
    if classification is not None:
        payload["class"] = classification
    return SimpleNamespace(id=1, agent="jarvis", kind=f"toolrpc.{tool}", payload=payload)


def _receipt(target, op, outcome):
    return {"path": str(target.resolve()), "op": op, "outcome": outcome}


async def test_gated_intake_only_queues_and_approved_execute_returns_applied_receipt(registered):
    args = {"path": "notes.txt", "content": "after"}
    intake = await registered.server.handle({"tool": "file_write", "args": args})
    assert intake == {"ok": False, "reason": "approval_required", "tool": "file_write",
                      "task_id": 1}
    assert registered.target.read_text(encoding="utf-8") == "before"
    assert "mutation_receipt" not in intake
    assert len(registered.queued) == 1
    assert registered.queued[0].payload["args"] == args

    result = await registered.server.execute(registered.queued[0],
                                             execution_context=registered.token)
    assert result["status"] == "ok"
    assert result["tool"] == "file_write"
    assert result["result"]["ok"] is True
    assert registered.target.read_text(encoding="utf-8") == "after"
    assert result["result"]["mutation_receipt"] == _receipt(
        registered.target, "write", "applied")
    assert result["result"]["snapshot_ref"]


async def test_approved_handler_refusal_keeps_failed_envelope_and_canonical_receipt(registered):
    absent = registered.root / "absent.txt"
    task = _task("file_delete", {"path": "absent.txt"})
    result = await registered.server.execute(task, execution_context=registered.token)
    assert result["status"] == "failed"
    assert result["reason"] == "not_found"
    assert result["tool"] == "file_delete"
    assert result["result"]["ok"] is False
    assert result["result"]["reason"] == "not_found"
    assert not absent.exists()
    assert result["result"]["mutation_receipt"] == _receipt(absent, "delete", "refused")


async def test_approved_kernel_refusal_preserves_file_and_failed_envelope(
    registered, monkeypatch,
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    seen = []

    def deny(action):
        seen.append(action)
        return Decision(Verdict.DENY, reason="halted")

    registered.tools._authorizer = deny
    task = _task("file_write", {"path": "notes.txt", "content": "after"})
    result = await registered.server.execute(task, execution_context=registered.token)
    assert result["status"] == "failed"
    assert result["reason"] == "kernel_denied:halted"
    assert result["result"]["snapshot_ref"]
    assert registered.target.read_text(encoding="utf-8") == "before"
    assert len(seen) == 1
    assert set(seen[0].payload) == {
        "op", "path", "bytes", "snapshot_ref", "steers_future_runs",
    }
    assert result["result"]["mutation_receipt"] == _receipt(
        registered.target, "write", "refused")


@pytest.mark.parametrize("after_real_write", [False, True])
async def test_apply_oserror_remains_unknown_even_after_real_write(
    registered, monkeypatch, after_real_write,
):
    original = registered.tools.history.apply_mutation

    def fail_at_target(*args, **kwargs):
        if after_real_write:
            original(*args, **kwargs)
        raise OSError("synthetic write failure")

    if HISTORY_SUPPORTED:
        monkeypatch.setattr(registered.tools.history, "apply_mutation", fail_at_target)
    else:
        original_legacy = file_tools._atomic_write

        def fail_legacy(target, data, *, mode=None):
            if target != registered.target:
                return original_legacy(target, data, mode=mode)
            if after_real_write:
                original_legacy(target, data, mode=mode)
            raise OSError("synthetic write failure")

        monkeypatch.setattr(file_tools, "_atomic_write", fail_legacy)
    task = _task("file_write", {"path": "notes.txt", "content": "after"})
    result = await registered.server.execute(task, execution_context=registered.token)
    assert result["status"] == "failed"
    assert result["reason"] == "io_error"
    assert result["result"]["ok"] is False
    assert result["result"]["detail"] == "OSError"
    assert result["result"]["snapshot_ref"]
    assert registered.target.read_text(encoding="utf-8") == (
        "after" if after_real_write else "before")
    assert result["result"]["mutation_receipt"] == _receipt(
        registered.target, "write", "unknown")


async def test_prehandler_trusted_context_and_class_refusals_have_no_receipt(registered):
    task = _task("file_write", {"path": "notes.txt", "content": "after"})
    untrusted = await registered.server.execute(task, execution_context=object())
    assert untrusted == {"status": "failed", "reason": "trusted_execution_required",
                         "tool": "file_write"}
    mismatched = _task("file_write", {"path": "notes.txt", "content": "after"},
                       classification="instruction_file")
    wrong_class = await registered.server.execute(mismatched,
                                                  execution_context=registered.token)
    assert wrong_class["status"] == "failed"
    assert wrong_class["reason"] == "approval_class_mismatch"
    assert "mutation_receipt" not in wrong_class
    assert registered.target.read_text(encoding="utf-8") == "before"


async def test_cancelled_approved_execute_can_finish_real_worker_without_returned_receipt(
    registered, monkeypatch,
):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original = registered.tools.history.apply_mutation

    def delayed_write(*args, **kwargs):
        started.set()
        try:
            assert release.wait(3), "test did not release the filesystem worker"
            return original(*args, **kwargs)
        finally:
            finished.set()

    if HISTORY_SUPPORTED:
        monkeypatch.setattr(registered.tools.history, "apply_mutation", delayed_write)
    else:
        original_legacy = file_tools._atomic_write

        def delayed_legacy(target, data, *, mode=None):
            if target != registered.target:
                return original_legacy(target, data, mode=mode)
            started.set()
            try:
                assert release.wait(3), "test did not release the filesystem worker"
                return original_legacy(target, data, mode=mode)
            finally:
                finished.set()

        monkeypatch.setattr(file_tools, "_atomic_write", delayed_legacy)
    task = _task("file_write", {"path": "notes.txt", "content": "after"})
    pending = asyncio.create_task(registered.server.execute(
        task, execution_context=registered.token))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        assert registered.target.read_text(encoding="utf-8") == "before"
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 3)
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 3)
    assert registered.target.read_text(encoding="utf-8") == "after"


async def test_escaping_handler_error_uses_legacy_tool_error_without_receipt(
    registered, monkeypatch,
):
    def crash_after_effect(*_args, **_kwargs):
        raise RuntimeError("synthetic post-effect bookkeeping failure")

    # _record runs after the owned checkpoint worker reports the byte effect.
    # An escaping handler error has no returned receipt, even after real I/O.
    monkeypatch.setattr(registered.tools, "_record", crash_after_effect)
    task = _task("file_write", {"path": "notes.txt", "content": "after"})
    result = await registered.server.execute(task, execution_context=registered.token)
    assert result == {"status": "failed", "reason": "tool_error", "tool": "file_write"}
    assert registered.target.read_text(encoding="utf-8") == "after"
