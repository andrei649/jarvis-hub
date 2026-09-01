"""DRA-08 phase 3 — `/sandbox/execute` can run a script through governed Tool-RPC.

`ToolRPCSandboxRuntime` had no production caller: the only way to run code in the
sandbox (`POST /sandbox/execute`) went straight to `Sandbox.execute_python`, so a
script could never reach a governed tool. These tests drive the real FastAPI app
with an opt-in `tools: true` flag and assert that (a) the pipeline actually runs,
(b) governance (allowlist + gated approval) still applies, and (c) there is no
silent ungoverned fallback when the Tool-RPC server is missing.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.sandbox import Sandbox  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402


def _host_sandbox(tmp_path):
    sandbox = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=5)
    sandbox._has_docker = False
    sandbox._has_wasmtime = False
    return sandbox


def _stub_orch(tmp_path, server):
    return SimpleNamespace(
        sandbox=_host_sandbox(tmp_path),
        tool_rpc=server,
        get_setting=lambda key, default=None: default,
    )


@pytest.fixture
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def dev_mode(monkeypatch):
    from agents import web
    monkeypatch.setattr(web, "DEV_MODE", True, raising=False)
    return web


def _bind(monkeypatch, orch):
    from agents import web
    monkeypatch.setattr(web, "orch", orch, raising=False)


def test_tools_flag_runs_script_through_governed_tool_rpc(client, dev_mode, monkeypatch, tmp_path):
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args}

    server.register_tool("echo", echo)
    _bind(monkeypatch, _stub_orch(tmp_path, server))

    resp = client.post("/sandbox/execute", json={
        "code": (
            "import json\n"
            "print(json.dumps(jarvis_tool_call('echo', {'m': 1}), sort_keys=True))\n"
        ),
        "language": "python",
        "tools": True,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    assert body["tool_calls"] == 1
    assert body["timed_out"] is False
    assert json.loads(body["stdout"].strip()) == {
        "ok": True, "tool": "echo", "result": {"echo": {"m": 1}},
    }


def test_gated_tool_still_requires_approval_from_the_pipeline(client, dev_mode, monkeypatch, tmp_path):
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
    _bind(monkeypatch, _stub_orch(tmp_path, server))

    resp = client.post("/sandbox/execute", json={
        "code": (
            "import json\n"
            "print(json.dumps(jarvis_tool_call('send_email', {'to': 'a@b.test'}),"
            " sort_keys=True))\n"
        ),
        "language": "python",
        "tools": True,
    })
    assert resp.status_code == 200, resp.text
    payload = json.loads(resp.json()["stdout"].strip())
    assert payload["ok"] is False
    assert payload["reason"] == "approval_required"
    assert ran["value"] is False
    assert len(enqueued) == 1


def test_missing_tool_rpc_server_refuses_instead_of_running_ungoverned(client, dev_mode, monkeypatch, tmp_path):
    orch = _stub_orch(tmp_path, None)
    called = {"n": 0}
    real_execute = orch.sandbox.execute_python

    async def spy(*args, **kwargs):
        called["n"] += 1
        return await real_execute(*args, **kwargs)

    orch.sandbox.execute_python = spy
    _bind(monkeypatch, orch)

    resp = client.post("/sandbox/execute", json={
        "code": "print('hi')", "language": "python", "tools": True,
    })
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"] == "tool-rpc unavailable"
    assert called["n"] == 0


def test_default_path_is_byte_identical_without_the_flag(client, dev_mode, monkeypatch, tmp_path):
    server = ToolRPCServer()
    orch = _stub_orch(tmp_path, server)
    seen = {}
    real_execute = orch.sandbox.execute_python

    async def spy(code, *args, **kwargs):
        seen["code"] = code
        seen["args"] = args
        seen["kwargs"] = kwargs
        return await real_execute(code, *args, **kwargs)

    orch.sandbox.execute_python = spy
    _bind(monkeypatch, orch)

    resp = client.post("/sandbox/execute", json={
        "code": "print('plain')", "language": "python",
    })
    assert resp.status_code == 200, resp.text
    assert seen["code"] == "print('plain')"
    assert "writable_paths" not in seen["kwargs"]
    assert set(resp.json()) == {"stdout", "stderr", "exit_code", "duration", "success"}


def test_non_python_language_is_refused_not_downgraded(client, dev_mode, monkeypatch, tmp_path):
    server = ToolRPCServer()
    orch = _stub_orch(tmp_path, server)
    called = {"n": 0}

    async def spy(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("shell must not run for a tools=true request")

    orch.sandbox.execute_shell = spy
    _bind(monkeypatch, orch)

    resp = client.post("/sandbox/execute", json={
        "code": "echo hi", "language": "shell", "tools": True,
    })
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "tool_rpc_pipeline_python_only"
    assert called["n"] == 0


def test_status_discloses_tool_rpc_availability_and_tools(client, monkeypatch, tmp_path):
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args}

    server.register_tool("echo", echo)
    _bind(monkeypatch, _stub_orch(tmp_path, server))

    body = client.get("/sandbox/status").json()
    assert body["tool_rpc"]["available"] is True
    assert [t["name"] for t in body["tool_rpc"]["tools"]] == ["echo"]

    _bind(monkeypatch, _stub_orch(tmp_path, None))
    body = client.get("/sandbox/status").json()
    assert body["tool_rpc"] == {"available": False, "tools": []}
