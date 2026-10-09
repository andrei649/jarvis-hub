"""Owner quick commands use the live slash registry and governed ToolRPC intake."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.core import settings_db
from agents.core.commands import Principal, SlashCommand, build_default_registry
from agents.core.tool_rpc import ToolRPCServer

OWNER = Principal(channel="web", admin=True)
GUEST = Principal(channel="web")


def _orch(monkeypatch, commands, tool_rpc=None):
    monkeypatch.setattr(settings_db, "get_value", lambda category, key, default=None: commands)
    registry = build_default_registry()
    return SimpleNamespace(commands=registry, tool_rpc=tool_rpc), registry


@pytest.mark.asyncio
async def test_alias_forwards_args_and_builtins_win(monkeypatch):
    orch, registry = _orch(monkeypatch, {
        "shortcut": {"type": "alias", "target": "/probe fixed"},
        "help": {"type": "exec", "command": "echo shadow"},
    })
    called = []
    registry.register(SlashCommand("probe", "probe", lambda ctx: called.append(ctx.args) or "ok"))
    assert (await registry.dispatch("/shortcut extra", orch=orch, principal=OWNER)).status == "answered"
    assert called == ["fixed extra"]
    assert "echo shadow" not in (await registry.dispatch("/help", orch=orch, principal=OWNER)).reply


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["new", "reset", "undo"])
async def test_conversation_builtins_keep_their_handler(monkeypatch, name):
    orch, registry = _orch(monkeypatch, {name: {"type": "exec", "command": "echo shadow"}})
    calls = []

    async def change(command, channel, session):
        calls.append((command, channel, session))
        return "changed"

    orch._direct_session_command = change
    outcome = await registry.dispatch(f"/{name}", orch=orch, principal=OWNER)
    assert outcome.reply == "changed"
    assert calls == [(f"/{name}", "web", None)]


@pytest.mark.asyncio
async def test_guest_refused_and_cycles_refused(monkeypatch):
    orch, registry = _orch(monkeypatch, {"a": {"type": "alias", "target": "/b"},
                                       "b": {"type": "alias", "target": "/a"}})
    assert (await registry.dispatch("/a", orch=orch, principal=GUEST)).status == "refused"
    assert (await registry.dispatch("/a", orch=orch, principal=OWNER)).status == "refused"
    orch, registry = _orch(monkeypatch, {"a": {"type": "alias", "target": "/status"}})
    assert "/a" in (await registry.dispatch("/help", orch=orch, principal=OWNER)).reply
    assert "/a" not in (await registry.dispatch("/help", orch=orch, principal=GUEST)).reply


@pytest.mark.asyncio
async def test_exec_queues_fixed_command_and_never_interpolates_args(monkeypatch):
    requests = []
    ran = []

    def enqueue(agent, kind, title, **kwargs):
        requests.append((agent, kind, kwargs))
        return 27

    async def terminal(args):
        ran.append(args)

    server = ToolRPCServer(enqueue=enqueue)
    server.register_tool("terminal_run", terminal, gated=True)
    orch, registry = _orch(monkeypatch, {"check": {"type": "exec", "command": "echo safe"}}, server)
    assert (await registry.dispatch("/check", orch=orch, principal=GUEST)).status == "refused"
    assert requests == []
    outcome = await registry.dispatch("/check ; rm -rf nope", orch=orch, principal=OWNER)
    assert outcome.status == "queued" and "27" in outcome.reply
    assert requests[0][:2] == ("jarvis", "toolrpc.terminal_run")
    assert requests[0][2]["payload"] == {"tool": "terminal_run", "target": "terminal_run",
                                          "args": {"target": "local-host", "command": "echo safe"}}
    assert requests[0][2]["autonomy_level"] == "ask"
    assert ran == []
    assert (await registry.dispatch("/check " + "x" * 2_100, orch=orch, principal=OWNER)).status == "refused"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_exec_redacts_immediate_governed_response(monkeypatch):
    async def handle(request, *, actor):
        return {"ok": True, "result": {"stdout": "api_key='abcdef1234567890'"}}

    orch, registry = _orch(monkeypatch, {"check": {"type": "exec", "command": "echo safe"}},
                           SimpleNamespace(handle=handle))
    outcome = await registry.dispatch("/check", orch=orch, principal=OWNER)
    assert outcome.status == "answered"
    assert "abcdef1234567890" not in outcome.reply


@pytest.mark.parametrize("commands", [
    {"a": {"type": "alias", "target": "/a"}},
    {"a": {"type": "alias", "target": "/b"}, "b": {"type": "alias", "target": "/a"}},
    {"a": {"type": "exec", "command": "  "}},
    {"bad-name": {"type": "alias", "target": "/status"}},
    {"fresh": {"type": "alias", "target": "/new"}},
])
def test_invalid_configuration_rejected(commands):
    assert settings_db.validate_category("commands", {"quick_commands": commands})


def test_admin_settings_roundtrip_and_reject_invalid(tmp_path, monkeypatch):
    import agents.web as web

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "quick-owner-token")
    client = TestClient(web.app)
    headers = {"X-Admin-Token": "quick-owner-token"}
    commands = {"check": {"type": "exec", "command": "echo ready"},
                "again": {"type": "alias", "target": "/check"}}
    assert client.put("/api/admin/settings/commands", json={"values": {"quick_commands": commands}},
                      headers=headers).status_code == 200
    read = client.get("/api/admin/settings/commands", headers=headers)
    assert read.status_code == 200
    assert next(row["value"] for row in read.json()["commands"] if row["key"] == "quick_commands") == commands
    assert settings_db.get_value("commands", "quick_commands") == commands
    assert client.put("/api/admin/settings/commands", json={"values": {
        "quick_commands": {"bad": {"type": "alias", "target": "/bad"}}
    }}, headers=headers).status_code == 422
    assert settings_db.get_value("commands", "quick_commands") == commands
