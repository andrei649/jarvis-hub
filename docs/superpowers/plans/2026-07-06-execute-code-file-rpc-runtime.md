# Execute Code File-RPC Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest governed runtime path where sandboxed Python code can call Jarvis tools through the existing file-RPC primitives and `ToolRPCServer`.

**Architecture:** Add an additive `ToolRPCSandboxRuntime` that wraps a `Sandbox` and a `ToolRPCServer`. The runtime injects a tiny Python client shim, services JSON request files from the host, and routes every tool call through `ToolRPCServer.handle()` so allowlist, contracts, Action Kernel mediation, approval queues, and secret scrubbing stay unchanged.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, existing `agents.core.sandbox`, `agents.core.tool_rpc`, and `agents.core.environments.file_rpc`.

## Global Constraints

- Do not edit `BACKLOG.md` or `STATUS.md` in this branch because Claude's learning-loop branch owns backlog reconciliation.
- Do not touch Claude-owned files: `agents/core/orchestrator.py`, `agents/core/learning/*`, `agents/core/cognition/*`, `agents/core/skills/{curator,loader,proposals,usage}.py`, `agents/core/subagents.py`, or their current Claude tests.
- No new public HTTP endpoint in this slice.
- No SSH backend implementation.
- No governance bypass: all tool calls must go through `ToolRPCServer.handle()`.
- Preserve the existing default sandbox behavior when no file-RPC runtime is used.

---

### Task 1: Add Failing Runtime Tests

**Files:**
- Create: `tests/test_tool_rpc_runtime.py`

**Interfaces:**
- Consumes: `ToolRPCServer.register_tool(name, handler, gated=False)`, `Sandbox.execute_python(...)`
- Produces: test expectations for `ToolRPCSandboxRuntime.run_python()` and `ToolRPCSandboxRun`

- [ ] **Step 1: Write the failing tests**

```python
"""File-RPC runtime bridge for governed sandbox tool calls."""

import json

import pytest

from agents.core.sandbox import Sandbox
from agents.core.tool_rpc import ToolRPCServer
from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime


def _host_sandbox(tmp_path, *, max_output_bytes=50_000):
    sandbox = Sandbox(
        allow_subprocess=True,
        work_dir=str(tmp_path),
        timeout=5,
        max_output_bytes=max_output_bytes,
    )
    sandbox._has_docker = False
    sandbox._has_wasmtime = False
    return sandbox


@pytest.mark.asyncio
async def test_sandbox_script_calls_readonly_tool_through_file_rpc(tmp_path):
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args}

    server.register_tool("echo", echo)
    runtime = ToolRPCSandboxRuntime(server, _host_sandbox(tmp_path))

    run = await runtime.run_python(
        "import json\n"
        "response = jarvis_tool_call('echo', {'message': 'hello'})\n"
        "print(json.dumps(response, sort_keys=True))\n"
    )

    assert run.result.success
    assert run.tool_calls == 1
    payload = json.loads(run.result.stdout.strip())
    assert payload == {
        "ok": True,
        "tool": "echo",
        "result": {"echo": {"message": "hello"}},
    }


@pytest.mark.asyncio
async def test_gated_tool_returns_approval_required_without_inline_execution(tmp_path):
    enqueued = []
    ran = {"value": False}

    def enqueue(*args, **kwargs):
        enqueued.append((args, kwargs))
        return 7

    server = ToolRPCServer(enqueue=enqueue)

    async def send_email(args):
        ran["value"] = True
        return {"sent": True}

    server.register_tool("send_email", send_email, gated=True)
    runtime = ToolRPCSandboxRuntime(server, _host_sandbox(tmp_path))

    run = await runtime.run_python(
        "import json\n"
        "response = jarvis_tool_call('send_email', {'to': 'a@example.test'})\n"
        "print(json.dumps(response, sort_keys=True))\n"
    )

    assert run.result.success
    assert run.tool_calls == 1
    assert ran["value"] is False
    assert len(enqueued) == 1
    payload = json.loads(run.result.stdout.strip())
    assert payload["ok"] is False
    assert payload["reason"] == "approval_required"
    assert payload["task_id"] == 7


@pytest.mark.asyncio
async def test_unknown_tool_is_refused_by_existing_allowlist(tmp_path):
    runtime = ToolRPCSandboxRuntime(ToolRPCServer(), _host_sandbox(tmp_path))

    run = await runtime.run_python(
        "import json\n"
        "print(json.dumps(jarvis_tool_call('missing', {}), sort_keys=True))\n"
    )

    assert run.result.success
    assert run.tool_calls == 1
    payload = json.loads(run.result.stdout.strip())
    assert payload == {"ok": False, "reason": "tool_not_allowed", "tool": "missing"}


@pytest.mark.asyncio
async def test_runtime_caps_tool_calls_before_host_execution(tmp_path):
    calls = {"count": 0}
    server = ToolRPCServer()

    async def echo(args):
        calls["count"] += 1
        return {"echo": args}

    server.register_tool("echo", echo)
    runtime = ToolRPCSandboxRuntime(server, _host_sandbox(tmp_path), max_tool_calls=2)

    run = await runtime.run_python(
        "import json\n"
        "responses = [jarvis_tool_call('echo', {'i': i}) for i in range(3)]\n"
        "print(json.dumps(responses, sort_keys=True))\n"
    )

    assert run.result.success
    assert run.tool_calls == 2
    assert calls["count"] == 2
    responses = json.loads(run.result.stdout.strip())
    assert responses[2] == {
        "ok": False,
        "reason": "tool_call_limit_exceeded",
        "tool": "echo",
    }


@pytest.mark.asyncio
async def test_runtime_preserves_sandbox_stdout_cap(tmp_path):
    server = ToolRPCServer()
    server.register_tool("echo", lambda args: args)
    runtime = ToolRPCSandboxRuntime(
        server,
        _host_sandbox(tmp_path, max_output_bytes=40),
    )

    run = await runtime.run_python("print('x' * 200)\n")

    assert run.result.success
    assert "OUTPUT TRUNCATED" in run.result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tool_rpc_runtime.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'agents.core.tool_rpc_runtime'`.

### Task 2: Add Docker Writable RPC Mount Support

**Files:**
- Modify: `agents/core/sandbox.py`
- Test: `tests/test_tool_rpc_runtime.py`

**Interfaces:**
- Produces: `Sandbox.execute_python(code, filename="script.py", writable_paths=None)`

- [ ] **Step 1: Add failing Docker mount test**

Append this test to `tests/test_tool_rpc_runtime.py`:

```python
@pytest.mark.asyncio
async def test_docker_python_mounts_file_rpc_dir_as_writable(tmp_path, monkeypatch):
    sandbox = Sandbox(work_dir=str(tmp_path), timeout=5)
    sandbox._has_docker = True
    rpc_dir = tmp_path / ".jarvis_file_rpc" / "run"
    rpc_dir.mkdir(parents=True)
    calls = []

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"ok\n", b""

        def kill(self):
            return None

        async def wait(self):
            return None

    async def fake_exec(*cmd, stdout=None, stderr=None):
        calls.append(cmd)
        return _Proc()

    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", fake_exec)

    result = await sandbox.execute_python(
        "print('ok')",
        writable_paths=[rpc_dir],
    )

    assert result.success
    docker_cmd = list(calls[0])
    assert "--read-only" in docker_cmd
    assert f"{tmp_path}:/workspace:ro" in docker_cmd
    assert f"{rpc_dir}:/workspace/.jarvis_file_rpc/run:rw" in docker_cmd
```

- [ ] **Step 2: Run the Docker mount test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tool_rpc_runtime.py::test_docker_python_mounts_file_rpc_dir_as_writable -q`

Expected: `TypeError` because `Sandbox.execute_python()` does not yet accept `writable_paths`.

- [ ] **Step 3: Implement optional writable paths**

Change `Sandbox.execute_python`, `_execute_docker_python`, and `_run_docker` to accept `writable_paths=None`. For Docker, validate every writable path resolves inside `self.work_dir`, create the directory, and append a second bind mount with `:rw` under `/workspace/<relative-path>`. Keep the existing read-only workspace mount.

- [ ] **Step 4: Run Docker mount test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tool_rpc_runtime.py::test_docker_python_mounts_file_rpc_dir_as_writable -q`

Expected: pass.

### Task 3: Implement the Runtime Bridge

**Files:**
- Create: `agents/core/tool_rpc_runtime.py`
- Test: `tests/test_tool_rpc_runtime.py`

**Interfaces:**
- Produces: `ToolRPCSandboxRuntime`, `ToolRPCSandboxRun`, `sandbox_client_source`

- [ ] **Step 1: Implement runtime module**

Create `agents/core/tool_rpc_runtime.py` with:

- `ToolRPCSandboxRun(result, tool_calls, timed_out=False)`
- `sandbox_client_source(rpc_dir, max_tool_calls, timeout_seconds, poll_interval)`
- `ToolRPCSandboxRuntime.run_python(code, filename="script.py")`

The runtime must:

- create `.jarvis_file_rpc/<uuid>` under `sandbox.work_dir`
- choose `/workspace/.jarvis_file_rpc/<uuid>` for Docker/WASM child paths and host path for subprocess
- start `sandbox.execute_python(full_code, filename, writable_paths=[rpc_dir])`
- poll `FileRPCStore.pending_requests()`
- route each allowed request through `ToolRPCServer.handle()`
- return `tool_call_limit_exceeded` after `max_tool_calls`
- return the final `SandboxResult`

- [ ] **Step 2: Run runtime tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tool_rpc_runtime.py -q`

Expected: pass.

### Task 4: Regression Sweep

**Files:**
- No new production files beyond Tasks 2 and 3.

**Interfaces:**
- Consumes all prior tasks.

- [ ] **Step 1: Run focused regression suite**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tool_rpc_runtime.py tests/test_tool_rpc_h20_1.py tests/test_environment_file_rpc.py tests/test_environment_output_limits.py tests/test_sandbox_child_env.py -q`

Expected: all pass.

- [ ] **Step 2: Run static checks on touched Python files**

Run: `.venv\Scripts\python.exe -m py_compile agents/core/tool_rpc_runtime.py agents/core/sandbox.py`

Expected: no output and exit 0.

- [ ] **Step 3: Run ruff on touched files**

Run: `.venv\Scripts\ruff.exe check agents/core/tool_rpc_runtime.py agents/core/sandbox.py tests/test_tool_rpc_runtime.py`

Expected: no findings.

- [ ] **Step 4: Commit implementation**

Run:

```bash
git add agents/core/tool_rpc_runtime.py agents/core/sandbox.py tests/test_tool_rpc_runtime.py
git commit -m "feat: add governed file rpc sandbox runtime"
```

Expected: commit succeeds.
