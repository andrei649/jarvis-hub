"""Opt-in end-to-end checks against a separately provisioned pinned Hermes tree.

Run with JARVIS_HERMES_SMOKE_ROOT=/path/to/hermes-runtime (source/ and home/).
This never downloads or calls an external model provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.hermes_runtime.approvals import HermesApprovals
from agents.core.hermes_runtime.bridge import AuthorizationBridge
from agents.core.hermes_runtime.client import HermesRPCClient
from agents.core.hermes_runtime.distribution import (
    runtime_environment,
    validate_python,
    verify_source,
)
from agents.core.hermes_runtime.policy import HermesGate, RuntimeDenied
from agents.core.hermes_runtime.process import WORKER_SCRIPT, RuntimeProcess
from agents.core.security.capability import CapabilityBroker, KillSwitch

pytestmark = pytest.mark.skipif(
    not os.environ.get("JARVIS_HERMES_SMOKE_ROOT"),
    reason="set JARVIS_HERMES_SMOKE_ROOT to an already installed pinned runtime",
)


def _installation() -> tuple[Path, Path, Path]:
    root = Path(os.environ["JARVIS_HERMES_SMOKE_ROOT"]).resolve()
    source, home = root / "source", root / "home"
    verify_source(source)
    key = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16]
    facts = json.loads((home / "installs" / key / "facts.json").read_text(encoding="utf-8"))
    python = Path(facts["packages"]["venv"]["environment"]) / "bin/python"
    validate_python(python, source, home)
    return source, home, python


def _fake_provider(home: Path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != "/v1/models":
                self.send_error(404)
                return
            body = json.dumps({"object": "list", "data": [{"id": "fake-model", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if size > 1024 * 1024:
                self.send_error(413)
                return
            request = json.loads(self.rfile.read(size))
            requests.append(request)
            if request.get("stream"):
                def chunk(delta, finish=None):
                    return f"data: {json.dumps({'id': 'chatcmpl-offline', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'fake-model', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]})}\n\n".encode()

                body = chunk({"role": "assistant"}) + chunk({"content": "offline reply"}) + chunk({}, "stop") + b"data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
            else:
                body = json.dumps({"id": "chatcmpl-offline", "object": "chat.completion", "created": 1,
                    "model": "fake-model", "choices": [{"index": 0, "message": {"role": "assistant", "content": "offline reply"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = home / "config.yaml"
    previous = config.read_bytes() if config.exists() else None
    config.write_text(
        "model:\n"
        "  provider: custom\n"
        f"  base_url: http://127.0.0.1:{server.server_port}/v1\n"
        "  default: fake-model\n"
        "  api_mode: chat_completions\n"
        "  context_length: 131072\n"
        "agent:\n"
        "  api_max_retries: 1\n"
        "updates:\n"
        "  check: false\n"
        "compression:\n"
        "  enabled: false\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    return server, thread, previous, requests


@pytest.mark.asyncio
async def test_real_worker_rpc_kernel_and_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    source, home, python = _installation()
    orchestrator = SimpleNamespace(
        autonomy_policy=AutonomyPolicy(),
        capabilities=CapabilityBroker(),
        kill_switch=KillSwitch(tmp_path / "kill-switch.json"),
        intent_log=None,
    )
    gate = HermesGate(orchestrator=lambda: orchestrator)
    provider, provider_thread, prior_config, provider_requests = _fake_provider(home)
    bridge = AuthorizationBridge(lambda frame: gate.authorize(
        frame["kind"], frame["target"], frame["args"], frame["generation"],
    ))
    bridge.start()
    runtime = RuntimeProcess(source, home, python)
    client = None
    try:
        private = await runtime.start(bridge_url=bridge.url, bridge_token=bridge.token)
        bridge.generation = private["generation"]
        client = HermesRPCClient(private["url"], private["token"], private["generation"])
        await client.open()
        assert await client.rpc("ping", {})

        created = await client.rpc("session.create", {
            "title": "Jarvis offline smoke", "source": "tui",
            "messages": [{"role": "user", "content": "offline smoke"},
                         {"role": "assistant", "content": "ready"}],
        })
        session_id = created["session_id"]
        stored_id = created["stored_session_id"]
        assert created["message_count"] == 2
        listed = await client.rpc("session.list", {"include_hidden": True})
        assert any(row.get("id") == stored_id for row in listed["sessions"])
        history = await client.rpc("session.history", {"session_id": session_id})
        assert history["count"] >= 2

        async def collect_turn():
            seen = []
            async for frame in client.events():
                event_type = frame.get("params", {}).get("type")
                if frame.get("method") == "event" and event_type in {"message.delta", "message.complete"}:
                    seen.append(frame)
                if event_type == "message.complete":
                    return seen

        events_task = asyncio.create_task(collect_turn())
        await asyncio.sleep(0.05)
        await client.rpc("prompt.submit", {"session_id": session_id, "text": "Reply briefly offline"})
        events = await asyncio.wait_for(events_task, timeout=45)
        assert provider_requests, json.dumps([frame.get("params", {}).get("payload") for frame in events])
        assert any(frame["params"]["type"] == "message.delta" for frame in events)
        assert events[-1]["params"]["type"] == "message.complete"
        assert "offline reply" in json.dumps(events[-1]["params"])
        assert (await client.rpc("session.interrupt", {"session_id": session_id}))["status"] == "interrupted"

        sentinel = tmp_path / "shell-effect"
        with pytest.raises(RuntimeDenied) as shell:
            await client.rpc("shell.exec", {"command": f"touch {sentinel}"})
        assert shell.value.verdict == "queue"
        assert not sentinel.exists()
        config_path = home / "config.yaml"
        before = config_path.read_bytes() if config_path.exists() else None
        with pytest.raises(RuntimeDenied) as cli:
            await client.rpc("cli.exec", {"argv": ["config", "set", "model.default", "smoke-must-not-write"]})
        assert cli.value.verdict == "queue"
        assert (config_path.read_bytes() if config_path.exists() else None) == before

        old_generation = private["generation"]
        await client.close()
        client = None
        await runtime.stop()
        bridge.generation = None
        next_private = await runtime.start(bridge_url=bridge.url, bridge_token=bridge.token)
        assert next_private["generation"] != old_generation
        bridge.generation = next_private["generation"]
        old_frame = {"generation": old_generation, "nonce": "old-generation-nonce",
                     "kind": "rpc", "target": "ping", "args": {}}
        headers = {"X-Jarvis-Bridge-Token": bridge.token}
        assert httpx.post(bridge.url, json=old_frame, headers=headers, trust_env=False).status_code == 403
        current = {**old_frame, "generation": next_private["generation"], "nonce": "current-nonce"}
        assert httpx.post(bridge.url, json=current, headers=headers, trust_env=False).json()["verdict"] == "grant"
        assert httpx.post(bridge.url, json=current, headers=headers, trust_env=False).status_code == 403

        client = HermesRPCClient(next_private["url"], next_private["token"], next_private["generation"])
        await client.open()
        resumed = await client.rpc("session.resume", {"session_id": stored_id, "omit_messages": False})
        assert resumed["session_id"]
        assert (await client.rpc("session.history", {"session_id": resumed["session_id"]}))["count"] >= 2
    finally:
        if client is not None:
            await client.close()
        bridge.generation = None
        await runtime.stop()
        bridge.stop()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)
        config = home / "config.yaml"
        if prior_config is None:
            config.unlink(missing_ok=True)
        else:
            config.write_bytes(prior_config)
            config.chmod(0o600)


def test_real_tool_registry_dispatch_fails_closed_without_bridge(tmp_path):
    source, home, python = _installation()
    marker = tmp_path / "tool-effect"
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from bridge import BrokerClient
from worker import install_guards
from tools.registry import ToolRegistry
marker = Path(sys.argv[2])
registry = ToolRegistry()
for name in ('read_file', 'unknown_effect'):
    registry.register(name, 'smoke', {'name': name, 'parameters': {'type': 'object'}}, lambda args: marker.write_text('effect'))
install_guards(BrokerClient('http://127.0.0.1:1/authorize', 'unavailable', 'generation'))
for name in ('read_file', 'unknown_effect'):
    result = registry.dispatch(name, {'path': 'anything'})
    assert isinstance(result, dict) and result.get('jarvis_verdict') == 'deny', result
assert not marker.exists()
"""
    result = subprocess.run(
        [str(python), "-c", script, str(WORKER_SCRIPT.parent), str(marker)],
        cwd=source, env=runtime_environment(home), capture_output=True, text=True,
        timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert not marker.exists()


@pytest.mark.asyncio
async def test_real_shell_requires_canonical_approval_and_executes_once(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    source, home, python = _installation()
    signer = DetachedHMACSigner(lambda data: hmac.new(b"hermes-live-approval-fixture", data, hashlib.sha256).hexdigest())
    head = [None]

    def cas(previous, replacement):
        if previous != head[0]:
            return False
        head[0] = replacement
        return True

    queue = TaskQueue(str(tmp_path / "approvals.db"), mediation_mode="enforce",
                      mediation_signer=signer,
                      mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
                      mediation_scope="global").initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(mode="auto"))
    orch = SimpleNamespace(autonomy=worker, capabilities=CapabilityBroker(),
                           kill_switch=KillSwitch(tmp_path / "halt.json"), intent_log=None)
    gate = HermesGate(orchestrator=lambda: orch)
    from agents.core.kernel.binding import make_action_kernel
    worker.bind_mediation(make_action_kernel(orch), signer)
    loop = asyncio.get_running_loop()
    manager = None

    def authorize(frame):
        if frame.get("phase") == "complete":
            return manager.complete(frame)
        if frame.get("phase") == "continue":
            return manager.continue_tool(frame)
        try:
            return manager.authorize(frame)
        except RuntimeDenied as exc:
            if exc.verdict != "queue":
                raise
            return asyncio.run_coroutine_threadsafe(manager.submit(frame), loop).result(timeout=10)

    bridge = AuthorizationBridge(authorize)
    bridge.start()
    runtime = RuntimeProcess(source, home, python)
    client = None
    try:
        private = await runtime.start(bridge_url=bridge.url, bridge_token=bridge.token)
        bridge.generation = private["generation"]
        client = HermesRPCClient(private["url"], private["token"], private["generation"])
        await client.open()
        manager = HermesApprovals(worker=worker, queue=queue, gate=gate,
                                  generation=private["generation"], client=client)
        sentinel = tmp_path / "approved-shell"
        args = {"command": f"printf authorized > {sentinel}"}
        with pytest.raises(RuntimeDenied) as queued:
            await client.rpc("shell.exec", args)
        task_id = queued.value.task_id
        assert queued.value.verdict == "queue" and type(task_id) is int
        assert not sentinel.exists()
        await manager.decide(task_id, True)
        await asyncio.wait_for(next(iter(manager._jobs)), timeout=45)
        assert sentinel.read_text() == "authorized"
        assert queue.get(task_id).status == "done"
        assert queue.get(task_id).result["disposition"] == "completed"
        assert "value" in queue.get(task_id).result

        with pytest.raises(RuntimeDenied) as invalid_request:
            await client.rpc("shell.exec", {"command": ""})
        invalid_task = invalid_request.value.task_id
        await manager.decide(invalid_task, True)
        await asyncio.wait_for(next(iter(manager._jobs)), timeout=45)
        assert queue.get(invalid_task).status == "failed"
        assert queue.get(invalid_task).result["disposition"] == "native_error"

        denied = tmp_path / "denied-shell"
        with pytest.raises(RuntimeDenied) as denied_request:
            await client.rpc("shell.exec", {"command": f"printf denied > {denied}"})
        await manager.decide(denied_request.value.task_id, False)
        assert not denied.exists()

        stale = tmp_path / "stale-shell"
        with pytest.raises(RuntimeDenied) as old_request:
            await client.rpc("shell.exec", {"command": f"printf stale > {stale}"})
        manager.revoke()
        bridge.generation = None
        await client.close()
        client = None
        await runtime.stop()
        with pytest.raises(RuntimeDenied, match="generation revoked"):
            await manager.decide(old_request.value.task_id, True)
        assert not stale.exists()
    finally:
        if client is not None:
            await client.close()
        bridge.generation = None
        await runtime.stop()
        bridge.stop()
        queue.close()


@pytest.mark.asyncio
async def test_real_tool_registry_pauses_for_canonical_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    source, home, python = _installation()
    signer = DetachedHMACSigner(lambda data: hmac.new(b"hermes-live-tool-fixture", data, hashlib.sha256).hexdigest())
    head = [None]

    def cas(previous, replacement):
        if previous != head[0]:
            return False
        head[0] = replacement
        return True

    queue = TaskQueue(str(tmp_path / "tool-approvals.db"), mediation_mode="enforce",
                      mediation_signer=signer,
                      mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
                      mediation_scope="global").initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(mode="auto"))
    orch = SimpleNamespace(autonomy=worker, capabilities=CapabilityBroker(),
                           kill_switch=KillSwitch(tmp_path / "halt.json"), intent_log=None)
    gate = HermesGate(orchestrator=lambda: orch)
    from agents.core.kernel.binding import make_action_kernel
    worker.bind_mediation(make_action_kernel(orch), signer)
    loop = asyncio.get_running_loop()
    manager = None

    def authorize(frame):
        if frame.get("phase") == "complete":
            return manager.complete(frame)
        if frame.get("phase") == "continue":
            return manager.continue_tool(frame)
        try:
            return manager.authorize(frame)
        except RuntimeDenied as exc:
            if exc.verdict != "queue":
                raise
            return asyncio.run_coroutine_threadsafe(manager.submit(frame), loop).result(timeout=10)

    bridge = AuthorizationBridge(authorize)
    bridge.start()
    bridge.generation = "g1"
    manager = HermesApprovals(worker=worker, queue=queue, gate=gate,
                              generation="g1", client=None)
    sentinel = tmp_path / "tool-effect"
    script = """
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ['JARVIS_TEST_WORKER_DIR'])
from bridge import BrokerClient
from worker import install_guards
from tools.registry import ToolRegistry
marker = Path(os.environ['JARVIS_TEST_MARKER'])
registry = ToolRegistry()
registry.register('fixture_write', 'smoke', {'name': 'fixture_write', 'parameters': {'type': 'object'}}, lambda args: marker.write_text(args['content']))
broker = BrokerClient(os.environ['JARVIS_TEST_BRIDGE_URL'], os.environ['JARVIS_TEST_BRIDGE_TOKEN'], 'g1')
install_guards(broker)
assert registry.dispatch('fixture_write', {'content': 'authorized'})
"""
    env = runtime_environment(home)
    env.update({"JARVIS_TEST_WORKER_DIR": str(WORKER_SCRIPT.parent),
                "JARVIS_TEST_MARKER": str(sentinel),
                "JARVIS_TEST_BRIDGE_URL": bridge.url,
                "JARVIS_TEST_BRIDGE_TOKEN": bridge.token})
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            str(python), "-c", script, cwd=source, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        task = None
        for _ in range(100):
            rows = queue.pending_decisions(kind="hermes.runtime")
            if rows:
                task = rows[0]
                break
            await asyncio.sleep(0.1)
        if task is None:
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            pytest.fail(f"tool approval was not queued (exit={proc.returncode}): {stderr.decode(errors='replace')[-2000:]}")
        assert not sentinel.exists()
        await manager.decide(task.id, True)
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
        assert proc.returncode == 0, stderr.decode(errors="replace")[-2000:]
        assert sentinel.read_text() == "authorized"
        assert queue.get(task.id).status == "done"
    finally:
        manager.revoke()
        bridge.generation = None
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        bridge.stop()
        queue.close()
