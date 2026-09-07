"""H20.R1 — governed file tools: scope, snapshots, gating and the ToolRPC seam."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

import hashlib  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402

from agents.core.file_tools import (
    FILE_TOOL_SPECS,
    FILE_WRITE_CONTRACT,
    GATED_TOOL_KINDS,
    KIND,
    FileScope,
    FileScopeError,
    FileTools,
    SnapshotStore,
    looks_secret_name,
    register_file_tools,
    restore_snapshot,
)
from agents.core.kernel import Decision, Verdict
from agents.core.tool_rpc import ToolRPCServer, ToolRPCValidationError

# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append({"agent": agent, "kind": kind, "title": title, "payload": payload,
                           "risk_tier": risk_tier, "autonomy_level": autonomy_level})
        return len(self.calls)


class _Task:
    def __init__(self, kind, payload):
        self.kind = kind
        self.payload = payload
        self.agent = "jarvis"
        self.id = 1


class _SpyKernel:
    def __init__(self, verdict=Verdict.GRANT, reason="spy"):
        self.calls = []
        self.verdict = verdict
        self.reason = reason

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self.verdict, reason=self.reason)


class _Audit:
    def __init__(self):
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.txt").write_text("hello", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "a.md").write_text("A", encoding="utf-8")
    return root


@pytest.fixture
def tools(workspace, tmp_path):
    return FileTools(
        FileScope([workspace]),
        snapshots=SnapshotStore(tmp_path / "snaps"),
        max_bytes=64,
    )


def _token_ctx():
    return object()


def _server(tools, *, queue=None, kernel=None, trusted=True):
    token = _token_ctx()

    def ctx_check(context, task):
        return trusted and context is token

    server = ToolRPCServer(
        enqueue=queue.enqueue if queue is not None else None,
        kernel=kernel,
        execution_context_check=ctx_check,
    )
    names = register_file_tools(server, tools, enabled=True)
    assert names == ["file_read", "file_list", "file_write", "file_delete"]
    return server, token


# ── scope ────────────────────────────────────────────────────────────────────

def test_scope_refuses_traversal_and_absolute_escape(workspace, tmp_path):
    scope = FileScope([workspace])
    with pytest.raises(FileScopeError) as info:
        scope.resolve("../outside.txt")
    assert info.value.reason == "outside_scope"
    with pytest.raises(FileScopeError) as info:
        scope.resolve("sub/../../escape.txt")
    assert info.value.reason == "outside_scope"
    with pytest.raises(FileScopeError) as info:
        scope.resolve(str(tmp_path / "other.txt"))
    assert info.value.reason == "outside_scope"
    # A sibling directory whose name merely starts with the root's name is outside.
    sibling = tmp_path / "workspace2"
    sibling.mkdir()
    with pytest.raises(FileScopeError) as info:
        scope.resolve(str(sibling / "x.txt"))
    assert info.value.reason == "outside_scope"


def test_scope_relative_paths_resolve_inside_first_root(workspace):
    scope = FileScope([workspace])
    assert scope.resolve("notes.txt") == (workspace / "notes.txt").resolve()
    assert scope.resolve("sub/a.md") == (workspace / "sub" / "a.md").resolve()
    assert scope.resolve(str(workspace)) == workspace.resolve()


def test_scope_refuses_symlink_escape(workspace, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret-ish", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks unavailable")
    scope = FileScope([workspace])
    with pytest.raises(FileScopeError) as info:
        scope.resolve("link.txt")
    assert info.value.reason == "symlink_escape"
    # A directory symlink pointing out escapes too, even with a plain name below it.
    dir_link = workspace / "dl"
    dir_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(FileScopeError) as info:
        scope.resolve("dl/outside.txt")
    assert info.value.reason == "symlink_escape"


@pytest.mark.parametrize("name", [
    ".env", ".env.production", "id_rsa", "id_ed25519.pub", "server.pem", "api_key.txt",
    "secrets.json", "ACCESS_TOKEN", "db-password.txt", "client_secret.json", "creds.yaml",
])
def test_scope_refuses_secret_looking_names(workspace, name):
    scope = FileScope([workspace])
    with pytest.raises(FileScopeError) as info:
        scope.resolve(name)
    assert info.value.reason == "secret_path"
    assert looks_secret_name(name)


@pytest.mark.parametrize("name", ["keyboard.md", "authors.txt", "tokenizer.py", "monkey.txt"])
def test_secret_policy_is_whole_token(name):
    assert not looks_secret_name(name)


def test_scope_refuses_secret_directory_components(workspace):
    scope = FileScope([workspace])
    for path in (".ssh/config", "sub/.aws/config", ".git/config"):
        with pytest.raises(FileScopeError) as info:
            scope.resolve(path)
        assert info.value.reason == "secret_path"


@pytest.mark.parametrize("bad", [None, "", 5, "a\x00b", " padded ", "x" * 5000])
def test_scope_refuses_bad_paths(workspace, bad):
    with pytest.raises(FileScopeError) as info:
        FileScope([workspace]).resolve(bad)
    assert info.value.reason == "bad_path"


def test_scope_needs_absolute_roots(tmp_path):
    with pytest.raises(ValueError):
        FileScope([])
    with pytest.raises(ValueError):
        FileScope(["relative/root"])


def test_scope_from_env(monkeypatch, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", f"{a}, {b}")
    assert FileScope.from_env().roots == (a.resolve(), b.resolve())
    monkeypatch.delenv("JARVIS_FILE_ROOTS")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    assert FileScope.from_env().roots == ((tmp_path / "home" / "workspace").resolve(),)


# ── ungated handlers ─────────────────────────────────────────────────────────

async def test_read_file_bounded(tools, workspace):
    out = await tools.read_file({"path": "notes.txt"})
    assert out["ok"] is True and out["content"] == "hello" and out["truncated"] is False
    assert out["sha256"] == hashlib.sha256(b"hello").hexdigest()
    (workspace / "big.txt").write_bytes(b"x" * 200)
    out = await tools.read_file({"path": "big.txt"})
    assert out["ok"] is True and out["bytes"] == 64 and out["truncated"] is True
    out = await tools.read_file({"path": "big.txt", "max_bytes": 10})
    assert out["bytes"] == 10 and out["size"] == 200
    assert (await tools.read_file({"path": "missing.txt"}))["reason"] == "not_found"
    assert (await tools.read_file({"path": "sub"}))["reason"] == "not_a_file"
    assert (await tools.read_file({"path": "../x"}))["reason"] == "outside_scope"


async def test_list_dir_hides_secrets_and_bounds(tools, workspace):
    (workspace / ".env").write_text("SECRET=1", encoding="utf-8")
    out = await tools.list_dir({})
    assert out["ok"] is True
    names = [e["name"] for e in out["entries"]]
    assert ".env" not in names and "notes.txt" in names and "sub" in names
    assert out["hidden"] == 1 and out["truncated"] is False
    assert next(e for e in out["entries"] if e["name"] == "sub")["type"] == "dir"
    out = await tools.list_dir({"path": ".", "max_entries": 1})
    assert len(out["entries"]) == 1 and out["truncated"] is True
    assert (await tools.list_dir({"path": "notes.txt"}))["reason"] == "not_a_dir"
    assert (await tools.list_dir({"path": "nope"}))["reason"] == "not_found"


# ── gated handlers: snapshot + restore ───────────────────────────────────────

async def test_write_snapshots_then_writes_and_restores(tools, workspace, tmp_path):
    out = await tools.write_file({"path": "notes.txt", "content": "changed"}, approved=True)
    assert out["ok"] is True and out["existed"] is True and out["bytes"] == 7
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "changed"
    ref = out["snapshot_ref"]
    assert len(ref) == 64
    record = json.loads((tmp_path / "snaps" / f"{ref}.json").read_text(encoding="utf-8"))
    assert record["existed"] is True and record["size"] == 5
    assert (tmp_path / "snaps" / "blobs" / record["blob_sha"]).read_bytes() == b"hello"
    assert tools.restore_snapshot(ref) is True
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"


async def test_write_new_file_restore_removes_it(tools, workspace):
    out = await tools.write_file({"path": "sub/new.txt", "content": "fresh"}, approved=True)
    assert out["ok"] is True and out["existed"] is False
    assert (workspace / "sub" / "new.txt").exists()
    assert tools.restore_snapshot(out["snapshot_ref"]) is True
    assert not (workspace / "sub" / "new.txt").exists()
    # Idempotent: restoring again still reports the recorded state (absent).
    assert tools.restore_snapshot(out["snapshot_ref"]) is True


async def test_delete_snapshots_then_restores(tools, workspace):
    out = await tools.delete_file({"path": "sub/a.md"}, approved=True)
    assert out["ok"] is True and out["op"] == "delete"
    assert not (workspace / "sub" / "a.md").exists()
    assert tools.restore_snapshot(out["snapshot_ref"]) is True
    assert (workspace / "sub" / "a.md").read_text(encoding="utf-8") == "A"
    assert (await tools.delete_file({"path": "ghost.txt"}, approved=True))["reason"] == "not_found"
    assert (await tools.delete_file({"path": "sub"}, approved=True))["reason"] == "not_a_file"


async def test_restore_refuses_tampered_or_unknown_refs(tools, workspace, tmp_path):
    out = await tools.write_file({"path": "notes.txt", "content": "v2"}, approved=True)
    ref = out["snapshot_ref"]
    assert tools.restore_snapshot("nope") is False
    assert tools.restore_snapshot("0" * 64) is False
    record_path = tmp_path / "snaps" / f"{ref}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["path"] = str(tmp_path / "elsewhere.txt")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert tools.restore_snapshot(ref) is False  # fingerprint no longer matches
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "v2"
    assert restore_snapshot(ref, tools=tools) is False


async def test_write_refuses_size_cap_scope_and_bad_content(tools, workspace):
    assert (await tools.write_file({"path": "notes.txt", "content": "x" * 65},
                                   approved=True))["reason"] == "too_large"
    assert (await tools.write_file({"path": "../out.txt", "content": "x"},
                                   approved=True))["reason"] == "outside_scope"
    assert (await tools.write_file({"path": ".env", "content": "x"},
                                   approved=True))["reason"] == "secret_path"
    assert (await tools.write_file({"path": "notes.txt", "content": 5},
                                   approved=True))["reason"] == "bad_content"
    assert (await tools.write_file({"path": "sub", "content": "x"},
                                   approved=True))["reason"] == "not_a_file"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"


def test_file_write_contract_shape(workspace):
    good = {
        "kind": KIND, "op": "write", "path": str(workspace / "n.txt"), "root": str(workspace),
        "bytes": 10, "max_bytes": 64, "snapshot_ref": "a" * 64,
    }
    assert FILE_WRITE_CONTRACT.evaluate(good).admissible is True
    assert FILE_WRITE_CONTRACT.requires_approval is True
    cases = {
        "invalid_kind": {"kind": "file.read"},
        "invalid_op": {"op": "chmod"},
        "bad_path": {"path": "relative.txt"},
        "outside_scope": {"root": str(workspace / "elsewhere")},
        "too_large": {"bytes": 65},
        "missing_snapshot": {"snapshot_ref": "zz"},
    }
    for reason, patch in cases.items():
        decision = FILE_WRITE_CONTRACT.evaluate({**good, **patch})
        assert decision.admissible is False and decision.reason == reason, reason


# ── kernel hook ──────────────────────────────────────────────────────────────

async def test_kernel_hook_deny_refuses_before_bytes_move(workspace, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = _SpyKernel(Verdict.DENY, reason="halted")
    audit = _Audit()
    tools = FileTools(FileScope([workspace]), snapshots=SnapshotStore(tmp_path / "s"),
                      max_bytes=64, authorizer=kernel, audit=audit)
    out = await tools.write_file({"path": "notes.txt", "content": "x"}, approved=True)
    assert out["ok"] is False and out["reason"] == "kernel_denied:halted"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"
    action = kernel.calls[0]
    assert action.kind == KIND and action.payload["op"] == "write"
    assert set(action.payload) == {"op", "path", "bytes", "snapshot_ref"}
    assert any(c["action"] == "file.kernel_denied" for c in audit.calls)


async def test_kernel_queue_refuses_unapproved_direct_caller(workspace, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = _SpyKernel(Verdict.QUEUE)
    tools = FileTools(FileScope([workspace]), snapshots=SnapshotStore(tmp_path / "s"),
                      max_bytes=64, authorizer=kernel)
    out = await tools.write_file({"path": "notes.txt", "content": "x"})
    assert out["reason"] == "approval_required"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"
    out = await tools.write_file({"path": "notes.txt", "content": "x"}, approved=True)
    assert out["ok"] is True


async def test_kernel_hook_skipped_when_kernel_flag_off(workspace, tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    kernel = _SpyKernel(Verdict.DENY, reason="halted")
    tools = FileTools(FileScope([workspace]), snapshots=SnapshotStore(tmp_path / "s"),
                      max_bytes=64, authorizer=kernel)
    out = await tools.write_file({"path": "notes.txt", "content": "x"}, approved=True)
    assert out["ok"] is True and kernel.calls == []


# ── ToolRPC seam ─────────────────────────────────────────────────────────────

def test_specs_are_closed_schemas():
    for name, spec in FILE_TOOL_SPECS.items():
        assert spec["input_schema"]["additionalProperties"] is False, name
        assert spec["capability_id"] == f"tool:{name}"
        assert spec["gated"] == (name in ("file_write", "file_delete"))
        assert spec["trusted_execution"] == spec["gated"]
    assert GATED_TOOL_KINDS == ("toolrpc.file_write", "toolrpc.file_delete")
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_write"]["preflight"]({"path": "x", "content": 3})
    assert info.value.reason == "bad_content"
    with pytest.raises(ToolRPCValidationError):
        FILE_TOOL_SPECS["file_read"]["preflight"]({"path": "x", "max_bytes": 0})


def test_register_is_noop_when_flag_off(tools, monkeypatch):
    monkeypatch.delenv("JARVIS_FILE_TOOLS", raising=False)
    server = ToolRPCServer()
    assert register_file_tools(server, tools) == []
    assert server.tools() == []
    monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    assert len(register_file_tools(server, tools)) == 4
    assert [t["name"] for t in server.tools()] == [
        "file_delete", "file_list", "file_read", "file_write",
    ]


async def test_ungated_tools_run_inline_within_scope(tools):
    server, _ = _server(tools)
    out = await server.handle({"tool": "file_read", "args": {"path": "notes.txt"}})
    assert out["ok"] is True and out["result"]["content"] == "hello"
    out = await server.handle({"tool": "file_list", "args": {}})
    assert out["ok"] is True and "notes.txt" in [e["name"] for e in out["result"]["entries"]]
    out = await server.handle({"tool": "file_read", "args": {"path": "../etc/passwd"}})
    assert out == {"ok": False, "reason": "outside_scope", "tool": "file_read"}
    out = await server.handle({"tool": "file_read", "args": {"path": ".env"}})
    assert out["reason"] == "secret_path"


async def test_gated_write_never_writes_inline(tools, workspace):
    queue = _FakeQueue()
    server, _ = _server(tools, queue=queue)
    out = await server.handle({"tool": "file_write",
                               "args": {"path": "notes.txt", "content": "evil"}})
    assert out["ok"] is False and out["reason"] == "approval_required" and out["task_id"] == 1
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"
    call = queue.calls[0]
    assert call["kind"] == "toolrpc.file_write" and call["autonomy_level"] == "ask"
    assert call["payload"] == {"tool": "file_write",
                               "args": {"path": "notes.txt", "content": "evil"},
                               "target": "file_write"}
    out = await server.handle({"tool": "file_delete", "args": {"path": "notes.txt"}})
    assert out["reason"] == "approval_required"
    assert (workspace / "notes.txt").exists()


async def test_gated_write_out_of_scope_refused_before_enqueue(tools):
    queue = _FakeQueue()
    server, _ = _server(tools, queue=queue)
    out = await server.handle({"tool": "file_write",
                               "args": {"path": "../escape.txt", "content": "x"}})
    assert out["reason"] == "outside_scope" and queue.calls == []
    out = await server.handle({"tool": "file_write",
                               "args": {"path": "big.txt", "content": "x" * 65}})
    assert out["reason"] == "too_large" and queue.calls == []
    out = await server.handle({"tool": "file_write",
                               "args": {"path": "a.txt", "content": "x", "mode": "0777"}})
    assert out["reason"] == "approval_required" and queue.calls[0]["payload"]["args"] == {
        "path": "a.txt", "content": "x",
    }


async def test_approved_execute_writes_exactly_once(tools, workspace):
    server, token = _server(tools)
    task = _Task("toolrpc.file_write", {"tool": "file_write",
                                        "args": {"path": "notes.txt", "content": "approved"},
                                        "target": "file_write"})
    out = await server.execute(task, execution_context=token)
    assert out["status"] == "ok" and out["result"]["ok"] is True
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "approved"
    ref = out["result"]["snapshot_ref"]
    assert tools.restore_snapshot(ref) is True
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"
    # Without the trusted execution context the handler is never reached.
    out = await server.execute(task, execution_context=object())
    assert out == {"status": "failed", "reason": "trusted_execution_required",
                   "tool": "file_write"}
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"


async def test_approved_execute_surfaces_handler_refusal(tools, workspace):
    server, token = _server(tools)
    (workspace / "notes.txt").unlink()
    task = _Task("toolrpc.file_delete", {"tool": "file_delete",
                                         "args": {"path": "notes.txt"},
                                         "target": "file_delete"})
    out = await server.execute(task, execution_context=token)
    assert out["status"] == "failed" and out["reason"] == "not_found"


def test_from_env_reads_cap(monkeypatch, tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    monkeypatch.setenv("JARVIS_FILE_MAX_BYTES", "128")
    tools = FileTools.from_env()
    assert tools.max_bytes == 128 and tools.scope.roots == (root.resolve(),)
    monkeypatch.setenv("JARVIS_FILE_MAX_BYTES", "-5")
    assert FileTools.from_env().max_bytes == 2_000_000
