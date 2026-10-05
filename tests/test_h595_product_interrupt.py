"""H595: a later admitted user message stops live code, then takes the turn lease."""

import asyncio
import os
import sys
import time
from types import SimpleNamespace

import httpx
import pytest

import agents.web as web
from agents.core import code_interruptions
from agents.core.action_origin import bind_action_origin, current_action_origin, reset_action_origin
from agents.core.channels.batching import Coalescer
from agents.core.channels.chat_lanes import ChatLanes
from agents.core.channels.gateway import Gateway
from agents.core.channels.session import SessionSource, build_session_key
from agents.core.channels.telegram import TelegramChannel
from agents.core.code_tools import register_code_tools
from agents.core.kernel import Decision, Verdict
from agents.core.orchestrator import Orchestrator
from agents.core.sandbox import Sandbox
from agents.core.security.taint import TAINTED_RECALL_ORIGIN
from agents.core.session_kernels import WORKER_SOURCE, PipeKernelBackend, SessionKernelManager
from agents.core.tool_rpc import ToolRPCServer


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
@pytest.mark.parametrize("output_limit", [50_000, 512])
async def test_http_new_message_interrupts_registered_code_before_turn_lease(tmp_path, monkeypatch, path, output_limit):
    """Use the real registered tool and subprocess; only its isolation claim is faked."""
    box = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=20,
                  max_output_bytes=output_limit)
    box._has_docker = False
    box._has_wasmtime = False
    box.is_isolated = lambda: True
    server = ToolRPCServer()
    async def echo(args):
        return {"value": args.get("value")}
    server.register_tool("echo", echo, description="Echo", input_schema={
        "type": "object", "properties": {"value": {"type": "string"}}})
    orch = object.__new__(Orchestrator)
    orch._session_id_default = "h595_http"
    orch._turn_lease_max_wait = 1
    orch._runtime_settings = {}
    orch.notes = None
    register_code_tools(
        server, sandbox=lambda: box,
        settings=lambda key, default: {
            "llm.execute_code": True, "llm.execute_code_sessions": False,
        }.get(key, default),
        session_id=lambda: orch.session_id,
    )
    marker = tmp_path / "worker.pid"
    outcomes = []

    async def handle_input(message, channel="web", **kwargs):
        if message == "run":
            result = await server.handle({"tool": "execute_code", "args": {
                "code": f"import os, time\njarvis_tool_call('echo', {{'value': 'x'}})\nprint('started', flush=True)\nprint('x'*1000, flush=True)\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(15)"
            }})
            outcomes.append(result["result"])
            return "old turn finished"
        return "new turn finished"

    orch.handle_input = handle_input
    async def handle_input_stream(message, channel="web", on_token=None, **kwargs):
        return await handle_input(message, channel=channel, **kwargs)
    orch.handle_input_stream = handle_input_stream
    monkeypatch.setattr(web, "orch", orch)
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = asyncio.create_task(client.post(path, json={"message": "run"}))
        try:
            for _ in range(200):
                records = code_interruptions._active.get("h595_http", ())
                if marker.exists() and any("started" in record.capture.stdout for record in records):
                    break
                await asyncio.sleep(.01)
            assert marker.exists() and records, "registered execute_code never streamed output"
            second = await asyncio.wait_for(
                client.post(path, json={"message": "follow up"}), 3)
            assert "new turn finished" in second.text
            assert "old turn finished" in (await asyncio.wait_for(first, 3)).text
            assert outcomes[0]["status"] == "interrupted", outcomes[0]
            assert outcomes[0]["tool_calls_made"] == 1
            assert "started" in outcomes[0]["output"]
            assert "[execution interrupted — user sent a new message]" in outcomes[0]["output"]
            assert len(outcomes[0]["stdout"].encode()) <= output_limit
            assert outcomes[0]["truncated"] is (output_limit == 512)
            pid = int(marker.read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if not first.done():
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
async def test_telegram_pre_lane_only_signals_current_admitted_conversation(tmp_path):
    """The exact chat's child is signalled while that chat's earlier turn still occupies its lane."""
    orch = object.__new__(Orchestrator)
    orch._session_id_default = "shared"
    orch._runtime_settings = {}
    source = SessionSource(channel="telegram", sender="99", thread_id="42")
    orch._channel_sessions = {build_session_key(source): "actual-session-42"}
    pairing = SimpleNamespace(is_allowed=lambda channel, sender: sender == "99")
    gateway = Gateway(interrupt_handler=orch.interrupt_channel_message, pairing=pairing)
    channel = TelegramChannel(
        token="fake", allowed_user_ids=[99], pairing=pairing,
        pending_reply_handler=lambda *args, **kwargs: asyncio.sleep(0, result=args[0] == "answer"),
        pre_turn_interrupt=gateway.pre_lane_interrupt,
    )
    channel._batch = Coalescer(window=0)
    channel._lanes = ChatLanes(name="h595-telegram")
    async def no_turn(*args, **kwargs):
        return None
    channel._run_turn = no_turn
    blocked = asyncio.Event()
    channel._lanes.submit(42, lambda: blocked.wait())
    task = asyncio.create_task(asyncio.sleep(30))
    record = code_interruptions.register("actual-session-42", task, code_interruptions.PartialOutput())

    async def message(text, chat=42, user=99, chat_type="private"):
        await channel._handle_update({"message": {
            "from": {"id": user}, "chat": {"id": chat, "type": chat_type}, "text": text,
        }})

    try:
        await message("answer")  # intercepted pending reply
        await message("hello", chat=43)  # different session
        await message("hello", user=100)  # allowlist rejection
        await message("ambient group text", chat_type="group")  # observation/ignore
        gateway._max_rate = 1
        gateway._rate_limits["telegram"] = [time.time()]
        await message("rate limited")
        assert not task.done()
        gateway._rate_limits["telegram"] = []
        await message("interrupt me")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert record.interrupted is True
        assert not blocked.is_set()  # the signal did not wait behind the lane
    finally:
        blocked.set()
        await channel._lanes.settle()
        code_interruptions.unregister(record)
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_gateway_channel_handler_signals_only_after_admission_and_pending_intercept():
    orch = object.__new__(Orchestrator)
    orch._session_id_default = "shared"
    orch._runtime_settings = {}
    orch.channel_manager = SimpleNamespace(channels={})
    orch._delivery_router = SimpleNamespace(resolve=lambda source, text: SimpleNamespace(send=False))
    source = SessionSource(channel="discord", sender="99", thread_id="42")
    orch._channel_sessions = {build_session_key(source): "actual-discord-session"}
    async def fake_turn(*args, **kwargs):
        return "done"
    orch._session_channel_input = fake_turn
    pairing = SimpleNamespace(
        is_allowed=lambda channel, sender: True,
        gate_inbound=lambda channel, sender, code=None: {"allowed": sender == "99"},
    )
    async def pending(text, **kwargs):
        return text == "pending answer"
    gateway = Gateway(handler=orch.channel_handler, pairing=pairing, pending_handler=pending)
    task = asyncio.create_task(asyncio.sleep(30))
    record = code_interruptions.register(
        "actual-discord-session", task, code_interruptions.PartialOutput())
    try:
        await gateway.route("pending answer", channel="discord", sender="99", channel_id="42")
        await gateway.route("stranger", channel="discord", sender="100", channel_id="42")
        await gateway.route("ambient", channel="discord", sender="99", channel_id="42",
                            observe_only=True)
        await gateway.route("different room", channel="discord", sender="99", channel_id="43")
        assert not task.done()
        assert await gateway.route("new message", channel="discord", sender="99", channel_id="42") == "done"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert record.interrupted
    finally:
        code_interruptions.unregister(record)


@pytest.mark.asyncio
async def test_background_code_is_not_a_conversation_and_transport_cancel_propagates(tmp_path):
    box = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=20)
    box._has_docker = False
    box._has_wasmtime = False
    box.is_isolated = lambda: True
    server = ToolRPCServer()
    register_code_tools(server, sandbox=lambda: box, session_id=lambda: "job-session",
                        settings=lambda key, default: {
                            "llm.execute_code": True, "llm.execute_code_sessions": False,
                        }.get(key, default))
    marker = tmp_path / "job.pid"
    job = asyncio.create_task(server.handle({"tool": "execute_code", "args": {
        "code": f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(15)"
    }}))
    try:
        for _ in range(200):
            if marker.exists():
                break
            await asyncio.sleep(.01)
        assert marker.exists()
        assert code_interruptions.interrupt("job-session") is False
        assert not job.done()
        job.cancel()  # request/job cancellation remains cancellation, never a tool result
        with pytest.raises(asyncio.CancelledError):
            await job
        with pytest.raises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)
    finally:
        if not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)


@pytest.mark.asyncio
async def test_one_session_interrupts_every_parallel_code_child():
    children = [asyncio.create_task(asyncio.sleep(30)) for _ in range(2)]
    records = [code_interruptions.register("same", child, code_interruptions.PartialOutput())
               for child in children]
    try:
        assert code_interruptions.interrupt("other") is False
        assert code_interruptions.interrupt("same") is True
        for child in children:
            with pytest.raises(asyncio.CancelledError):
                await child
        assert all(record.interrupted for record in records)
    finally:
        for record in records:
            code_interruptions.unregister(record)


@pytest.mark.asyncio
async def test_registered_timeout_has_timeout_status(tmp_path):
    box = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=.2)
    box._has_docker = False
    box._has_wasmtime = False
    box.is_isolated = lambda: True
    server = ToolRPCServer()
    register_code_tools(server, sandbox=lambda: box, session_id=lambda: "timeout",
                        settings=lambda key, default: {
                            "llm.execute_code": True, "llm.execute_code_sessions": False,
                        }.get(key, default))
    success = (await server.handle({"tool": "execute_code", "args": {
        "code": "print('ok')"
    }}))["result"]
    error = (await server.handle({"tool": "execute_code", "args": {
        "code": "raise ValueError('bad')"
    }}))["result"]
    assert success["status"] == "success" and success["output"] == success["stdout"]
    assert error["status"] == "error" and "ValueError" in error["output"]
    reply = await server.handle({"tool": "execute_code", "args": {
        "code": "import time\ntime.sleep(2)"
    }})
    result = reply["result"]
    assert result["status"] == "timeout"
    assert result["duration_seconds"] > 0
    assert result["tool_calls_made"] == 0


@pytest.mark.asyncio
async def test_interrupted_resident_cell_loses_namespace_before_next_cell(tmp_path):
    """The product wrapper waits for kernel teardown, then the next cell starts empty."""
    box = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=20)
    box.is_isolated = lambda: True
    manager = SessionKernelManager(
        PipeKernelBackend(lambda key, token, rpc_dir="": [sys.executable, "-c", WORKER_SOURCE],
                          name="local"),
        cell_timeout_seconds=20, rpc_root=str(tmp_path / "rpc"),
    )
    server = ToolRPCServer()
    register_code_tools(server, sandbox=lambda: box, kernels=manager,
                        authorizer=lambda action: Decision(Verdict.GRANT),
                        session_id=lambda: "resident-h595",
                        settings=lambda key, default: {
                            "llm.execute_code": True, "llm.execute_code_sessions": True,
                        }.get(key, default))
    token = code_interruptions.bind_conversation("resident-h595")
    async def cell(script):
        return (await server.handle({"tool": "execute_code", "args": {"code": script}}))["result"]
    try:
        first = await cell("x = 42\nprint('set')")
        assert first["status"] == "success"
        running = asyncio.create_task(cell("import time\nprint('running', flush=True)\ntime.sleep(15)"))
        for _ in range(200):
            records = code_interruptions._active.get("resident-h595", ())
            if records and any("running" in record.capture.stdout for record in records):
                break
            await asyncio.sleep(.01)
        assert records, "resident worker did not start"
        assert code_interruptions.interrupt("resident-h595") is True
        interrupted = await asyncio.wait_for(running, 3)
        assert interrupted["status"] == "interrupted"
        assert "running" in interrupted["output"]
        assert manager.status() == []
        later = await cell("print(x)")
        assert later["status"] == "error"
        assert "NameError" in later["stderr"]
        assert later["state_lost"] is True
    finally:
        code_interruptions.reset_conversation(token)
        await manager.shutdown()


@pytest.mark.asyncio
async def test_resident_timeout_reports_timeout_status(tmp_path):
    box = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=2)
    box.is_isolated = lambda: True
    manager = SessionKernelManager(
        PipeKernelBackend(lambda key, token, rpc_dir="": [sys.executable, "-c", WORKER_SOURCE],
                          name="local"),
        cell_timeout_seconds=.2, rpc_root=str(tmp_path / "rpc"),
    )
    server = ToolRPCServer()
    register_code_tools(server, sandbox=lambda: box, kernels=manager,
                        authorizer=lambda action: Decision(Verdict.GRANT),
                        session_id=lambda: "resident-timeout",
                        settings=lambda key, default: {
                            "llm.execute_code": True, "llm.execute_code_sessions": True,
                        }.get(key, default))
    try:
        result = (await server.handle({"tool": "execute_code", "args": {
            "code": "import time\ntime.sleep(2)"
        }}))["result"]
        assert result["status"] == "timeout"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_nested_untrusted_tool_taints_parent_turn_without_script_output(tmp_path):
    box = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=5)
    box._has_docker = False
    box._has_wasmtime = False
    box.is_isolated = lambda: True
    server = ToolRPCServer()
    async def fetched(args):
        return {"content": "untrusted page"}
    server.register_tool("fetched", fetched, description="Fetch", untrusted_output=True,
                         input_schema={"type": "object", "properties": {}})
    register_code_tools(server, sandbox=lambda: box, session_id=lambda: "taint",
                        settings=lambda key, default: {
                            "llm.execute_code": True, "llm.execute_code_sessions": False,
                        }.get(key, default))
    token = bind_action_origin("generated")
    try:
        result = (await server.handle({"tool": "execute_code", "args": {
            "code": "jarvis_tool_call('fetched', {})"
        }}))["result"]
        assert result["status"] == "success" and result["stdout"] == ""
        assert result["tainted"] is True
        assert current_action_origin() == TAINTED_RECALL_ORIGIN
    finally:
        reset_action_origin(token)
