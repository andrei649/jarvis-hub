"""Owner quick commands adapt Hermes dispatch while retaining Nerva approval."""

from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.commands import ADMIN, CommandRegistry, Principal, SlashCommand
from agents.core.tool_rpc import ToolRPCServer
from tests.test_session_command_kernel import governed  # noqa: F401


def host(mapping, monkeypatch, server=None):
    # Production reads the governed commands.quick_commands setting, not the
    # legacy config.general field. Keep each test's mapping request-local.
    original_get_value = settings_db.get_value
    monkeypatch.setattr(settings_db, "get_value", lambda category, key, default=None:
                        mapping if (category, key) == ("commands", "quick_commands")
                        else original_get_value(category, key, default))
    registry = CommandRegistry()
    registry.register(SlashCommand("echo", "echo", lambda ctx: ctx.args))
    registry.register(SlashCommand("owner", "owner", lambda _ctx: "owner", tier=ADMIN))
    orch = SimpleNamespace(config=SimpleNamespace(general={"quick_commands": mapping}),
                           tool_rpc=server, secret_broker=None, commands=registry)
    return registry, orch


OWNER = Principal(channel="web", sender="owner", admin=True)
GUEST = Principal(channel="web", sender="guest")


@pytest.mark.asyncio
async def test_alias_keeps_fixed_and_callsite_arguments_and_skips_the_model(monkeypatch):
    registry, orch = host({"hello": {"type": "alias", "target": "/echo fixed"}}, monkeypatch)
    result = await registry.dispatch("/hello more", orch=orch, principal=OWNER)
    assert result.status == "answered" and result.reply == "fixed more"


@pytest.mark.asyncio
async def test_builtin_precedence_and_owner_floor(monkeypatch):
    registry, orch = host({"echo": {"type": "alias", "target": "/owner"},
                           "custom": {"type": "alias", "target": "/owner"}}, monkeypatch)
    assert (await registry.dispatch("/echo safe", orch=orch, principal=GUEST)).reply == "safe"
    assert (await registry.dispatch("/custom", orch=orch, principal=GUEST)).status == "refused"


@pytest.mark.asyncio
@pytest.mark.parametrize("mapping,text", [
    ({"a": {"type": "alias", "target": "/b"}, "b": {"type": "alias", "target": "/a"}}, "/a"),
    ({"a": {"type": "alias", "target": ""}}, "/a"),
    ({"a": {"type": "exec", "command": ""}}, "/a"),
    ({"a": {"type": "plugin", "target": "/echo"}}, "/a"),
    ({"a": {"type": "alias", "target": "/echo"}}, "/a " + "x" * 2100),
])
async def test_invalid_or_cyclic_configuration_refuses_without_effect(mapping, text, monkeypatch):
    registry, orch = host(mapping, monkeypatch)
    assert (await registry.dispatch(text, orch=orch, principal=OWNER)).status == "refused"


@pytest.mark.asyncio
async def test_exec_uses_real_gated_rpc_and_does_not_interpolate_inbound_args(monkeypatch):
    queued, executed = [], []

    def enqueue(*args, **kwargs):
        queued.append((args, kwargs))
        return 7

    async def run(args):
        executed.append(args)
        return {"stdout": "done", "exit_code": 0}

    server = ToolRPCServer(enqueue=enqueue)
    server.register_tool("terminal_run", run, gated=True,
                         input_schema={"type": "object", "properties": {
                             "target": {"type": "string"}, "command": {"type": "string"},
                             "timeout": {"type": "integer"}}, "required": ["target", "command"],
                             "additionalProperties": False})
    registry, orch = host({"disk": {"type": "exec", "command": "printf healthy"}}, monkeypatch, server)
    result = await registry.dispatch("/disk ; injected", orch=orch, principal=OWNER)
    assert result.status == "queued" and "7" in result.reply
    assert not executed and len(queued) == 1
    payload = queued[0][1]["payload"]
    assert payload["args"] == {"target": "local-host", "command": "printf healthy"}


@pytest.mark.asyncio
async def test_guest_cannot_propose_exec_or_use_an_absent_rpc(monkeypatch):
    registry, orch = host({"disk": {"type": "exec", "command": "printf healthy"}}, monkeypatch)
    assert (await registry.dispatch("/disk", orch=orch, principal=GUEST)).status == "refused"
    assert (await registry.dispatch("/disk", orch=orch, principal=OWNER)).status == "refused"


@pytest.mark.asyncio
async def test_quick_exec_reaches_production_signed_intake_before_any_execution(governed, monkeypatch):
    import asyncio

    _, _, queue, worker, executor, _, _ = governed
    server = executor.resolve("toolrpc").__self__
    registry, orch = host({"disk": {"type": "exec", "command": "printf healthy"}}, monkeypatch, server)
    result = await asyncio.wait_for(registry.dispatch("/disk", orch=orch, principal=OWNER), 1)
    assert result.status == "queued", result
    [task] = queue.list()
    assert task.kind == "toolrpc.terminal_run" and task.status == "blocked"
    assert task.mediation_receipt is not None
    assert task.payload["args"]["command"] == "printf healthy"
    assert (await worker.tick(task_id=task.id))["done"] == 0


@pytest.fixture
def governed_terminal(request, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TERMINAL_TARGETS", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(tmp_path))
    return request.getfixturevalue("governed")


@pytest.mark.asyncio
async def test_owner_quick_exec_runs_only_after_signed_human_approval(governed_terminal, tmp_path, monkeypatch):
    _, _, queue, worker, executor, _, kernel_calls = governed_terminal
    server = executor.resolve("toolrpc").__self__
    registry, orch = host({"where": {"type": "exec", "command": "/bin/pwd"}}, monkeypatch, server)
    reply = await registry.dispatch("/where", orch=orch, principal=OWNER)
    assert reply.status == "queued"
    [task] = queue.list()
    assert task.mediation_receipt is not None
    assert (await worker.tick(task_id=task.id))["done"] == 0
    await worker.apply_decision(task.id, "accept", decided_by="owner")
    result = await worker.tick(task_id=task.id)
    completed = queue.get(task.id)
    assert result["done"] == 1 and completed.result["status"] == "ok", completed.result
    assert completed.result["result"]["exit_code"] == 0
    assert completed.result["result"]["stdout"].strip() == str(tmp_path.resolve())
    assert any(action.kind == "terminal.exec" for action, _decision in kernel_calls)


@pytest.mark.asyncio
async def test_exec_response_redacts_unregistered_sensitive_values(monkeypatch):
    class Server:
        async def handle(self, *_args, **_kwargs):
            return {"ok": True, "result": {"stdout": "Authorization: Bearer synthetic-sensitive-token\n",
                                           "exit_code": 0}}

    registry, orch = host({"read": {"type": "exec", "command": "/bin/pwd"}}, monkeypatch, Server())
    result = await registry.dispatch("/read", orch=orch, principal=OWNER)
    assert result.status == "answered"
    assert "synthetic-sensitive-token" not in result.reply


@pytest.mark.asyncio
async def test_approved_quick_output_is_redacted_before_durable_result(governed_terminal, tmp_path, monkeypatch):
    _, _, queue, worker, executor, _, _ = governed_terminal
    server = executor.resolve("toolrpc").__self__
    command = "/usr/bin/printf 'Authorization: Bearer synthetic-sensitive-token\\n'"
    registry, orch = host({"probe": {"type": "exec", "command": command}}, monkeypatch, server)
    result = await registry.dispatch("/probe", orch=orch, principal=OWNER)
    assert result.status == "queued"
    [task] = queue.list()
    await worker.apply_decision(task.id, "accept", decided_by="owner")
    assert (await worker.tick(task_id=task.id))["done"] == 1
    completed = queue.get(task.id)
    assert completed.result["status"] == "ok", completed.result
    assert "synthetic-sensitive-token" not in completed.result["result"]["stdout"]
