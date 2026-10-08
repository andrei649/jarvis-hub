"""H595 donor-style tool imports and one-shot interruption ownership."""

import asyncio
import json

import pytest

from agents.core import code_tools
from agents.core.file_tools import FileScope, FileTools, SnapshotStore, register_file_tools
from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime
from tests.test_code_tools import _run, _server, _session_tool, _tool
from tests.test_tool_rpc_runtime import _owner_invocation


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [False, True])
async def test_imported_tools_use_the_existing_broker_and_call_budget(tmp_path, session):
    factory = _session_tool if session else _tool
    _server_, tool = factory(tmp_path)
    try:
        result = await _run(tool, "from jarvis_tools import echo\n"
                            "print(echo('hello')['result']['echo'])")
        assert result["ok"], result["stderr"]
        assert result["stdout"].strip() == "hello"
        assert result["tool_calls"] == 1
    finally:
        if session:
            await tool._kernels.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [False, True])
async def test_model_registered_imports_preserve_approvals_and_call_caps(tmp_path, session):
    enqueued = []
    server = _server(gated_enqueued=enqueued)
    factory = _session_tool if session else _tool
    _server_, host = factory(tmp_path, server=server)
    host._settings = lambda key, default: {
        code_tools.SETTING: True, code_tools.MAX_TOOL_CALLS_SETTING: 2,
    }.get(key, default)
    if session:
        host._kernels._max_tool_calls = 2
    code_tools.register_code_tools(
        server, sandbox=host._sandbox, settings=host._settings,
        principal=host._principal, session_id=host._session_id,
        kernels=host._kernels, authorizer=host._authorizer,
    )
    try:
        response = await server.handle({"tool": code_tools.TOOL, "args": {"code":
            "from jarvis_tools import echo, send_email\nimport json\n"
            "print(json.dumps([echo('first'), send_email(), echo('over limit')]))"}})
        assert response["ok"]
        result = response["result"]
        assert result["ok"], result["stderr"]
        answers = json.loads(result["stdout"])
        assert answers[0]["result"]["echo"] == "first"
        assert answers[1]["reason"] == "approval_required"
        assert answers[2]["reason"] == "tool_call_limit_exceeded"
        assert result["tool_calls"] == 2
        assert len(enqueued) == 1
    finally:
        if session:
            await host._kernels.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [False, True])
async def test_imported_file_pipeline_reads_synthetic_project_data(tmp_path, session):
    root = tmp_path / "project"
    root.mkdir()
    (root / "notes.txt").write_text("hello project", encoding="utf-8")
    server = _server()
    register_file_tools(server, FileTools(FileScope([root]),
                        snapshots=SnapshotStore(tmp_path / "snapshots")), enabled=True)
    factory = _session_tool if session else _tool
    _server_, tool = factory(tmp_path / "runtime", server=server)
    try:
        result = await _run(tool, "from jarvis_tools import file_search, file_read\n"
                            "matches = file_search('hello')['result']['matches']\n"
                            "print(file_read(matches[0]['path'])['result']['content'])")
        assert result["ok"], result["stderr"]
        assert result["stdout"].strip() == "hello project"
        assert result["tool_calls"] == 2
    finally:
        if session:
            await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_resident_saved_import_cannot_keep_a_revoked_tool_offer(tmp_path):
    _server_, tool = _session_tool(tmp_path)
    try:
        assert (await _run(tool, "from jarvis_tools import echo\nsaved = echo"))["ok"]
        tool._agent_patterns = lambda _agent: []
        result = await _run(tool, "import json\nprint(json.dumps(saved('later')))")
        assert result["ok"]
        assert json.loads(result["stdout"])["reason"] == "tool_not_offered"
        result = await _run(tool, "from jarvis_tools import echo")
        assert result["ok"] is False
        assert "ImportError" in result["stderr"]
    finally:
        await tool._kernels.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [False, True])
async def test_imports_do_not_take_away_the_advertised_code_length(tmp_path, session):
    factory = _session_tool if session else _tool
    _server_, tool = factory(tmp_path)
    body = "from jarvis_tools import echo\nprint(echo('limit')['result']['echo'])\n#"
    code = body + "x" * (code_tools.MAX_CODE_CHARS - len(body))
    try:
        result = await _run(tool, code)
        assert result["ok"], result
        assert result["stdout"].strip() == "limit"
    finally:
        if session:
            await tool._kernels.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["executing", "servicing_tool"])
async def test_one_shot_cancel_awaits_backend_teardown_before_removing_rpc(tmp_path, phase):
    started, closed, servicing = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleanup_mailboxes = []
    owned_tasks = []

    class SandboxHost:
        work_dir = tmp_path
        timeout = 5

        def active_backend(self):
            return "subprocess"

        async def execute_python(self, _code, _filename, *, writable_paths, sinks):
            owned_tasks.append(asyncio.current_task())
            started.set()
            try:
                await asyncio.Future()
            finally:
                # Models the existing Docker sandbox's awaited container kill.
                cleanup_mailboxes.append(writable_paths[0].exists())
                closed.set()

    server = _server()
    runtime = ToolRPCSandboxRuntime(server, SandboxHost(), invocation=_owner_invocation(server))
    if phase == "servicing_tool":
        async def pending(*_args, **_kwargs):
            servicing.set()
            await asyncio.Future()
        runtime._service_pending = pending
    task = asyncio.create_task(runtime.run_python("print('unused')"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        if phase == "servicing_tool":
            await asyncio.wait_for(servicing.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set(), "Cancelled runtime left its execute task alive"
        assert cleanup_mailboxes == [True], "RPC mailbox disappeared before backend teardown"
        assert not list((tmp_path / ".jarvis_file_rpc").iterdir())
    finally:
        # Clean up the deliberately failing pre-fix run without orphaning a task.
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for pending_task in owned_tasks:
            pending_task.cancel()
        await asyncio.gather(*owned_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_backend_exception_still_removes_its_rpc_mailbox(tmp_path):
    class FailingHost:
        work_dir = tmp_path
        timeout = 5

        def active_backend(self):
            return "subprocess"

        async def execute_python(self, *_args, **_kwargs):
            raise RuntimeError("backend failed")

    server = _server()
    runtime = ToolRPCSandboxRuntime(server, FailingHost(), invocation=_owner_invocation(server))
    with pytest.raises(RuntimeError, match="backend failed"):
        await runtime.run_python("print('unused')")
    assert not list((tmp_path / ".jarvis_file_rpc").iterdir())


@pytest.mark.asyncio
async def test_schema_arguments_cannot_shadow_the_generated_transport(tmp_path):
    server = _server()

    async def combine(args):
        return args

    server.register_tool("combine", combine, input_schema={
        "type": "object", "properties": {
            "first": {"type": "string"}, "nullable": {}, "_call": {}, "_MISSING": {},
        }, "required": ["first"],
    })
    _server_, tool = _tool(tmp_path, server=server)
    result = await _run(tool, "from jarvis_tools import combine\nimport json\n"
                        "try:\n    combine()\nexcept TypeError:\n    print('missing argument')\n"
                        "print(json.dumps(combine('value', nullable=None, _call='arg', _MISSING='arg')))" )
    assert result["ok"], result["stderr"]
    lines = result["stdout"].splitlines()
    assert lines[0] == "missing argument"
    assert json.loads(lines[1])["result"] == {
        "first": "value", "nullable": None, "_call": "arg", "_MISSING": "arg",
    }
    assert result["tool_calls"] == 1
