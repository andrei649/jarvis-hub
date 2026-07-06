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
