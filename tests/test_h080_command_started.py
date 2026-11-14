"""A command-start event is a bounded observation immediately before its handler."""

from types import SimpleNamespace

import pytest

from agents.core import command_source, quick_commands, slash_access
from agents.core.commands import ADMIN, CommandRegistry, Principal, SlashCommand
from agents.core.extensions import events as events_module


@pytest.fixture
def observed(monkeypatch):
    calls = []
    monkeypatch.setattr(events_module, "EXTENSION_EVENTS",
                        SimpleNamespace(emit=lambda event, **fields: calls.append((event, fields))))
    monkeypatch.setattr(slash_access, "_policy", lambda: {})
    return calls


@pytest.mark.asyncio
async def test_start_is_after_source_check_and_before_handler_with_no_body(monkeypatch, observed):
    order = []
    source = object()

    def check(**kwargs):
        order.append("source")
        assert kwargs["text"] == "/alias private arguments"
        return source

    def handler(ctx):
        order.append("handler")
        assert ctx.source is source
        assert observed == [("command.started", {"command": "actual"})]
        return "private reply"

    monkeypatch.setattr(command_source, "source_for_dispatch", check)
    registry = CommandRegistry()
    registry.register(SlashCommand("actual", "does work", handler, aliases=("alias",)))
    result = await registry.dispatch("/alias private arguments", orch=None, principal=Principal(admin=True))
    assert result.reply == "private reply"
    assert order == ["source", "handler"]
    assert observed == [
        ("command.started", {"command": "actual"}),
        ("command.completed", {"command": "alias", "status": "answered"}),
    ]
    assert "private" not in str(observed)


@pytest.mark.asyncio
async def test_denied_oversized_and_unknown_commands_never_start(observed):
    registry = CommandRegistry()
    registry.register(SlashCommand("danger", "owner", lambda _: "wrong", tier=ADMIN))
    registry.register(SlashCommand("kanban", "board", lambda _: "wrong"))
    guest = Principal(channel="telegram", scope="group")
    denied = await registry.dispatch("/danger", orch=None, principal=guest)
    oversized = await registry.dispatch("/kanban " + "x" * 2100, orch=None,
                                        principal=Principal(admin=True))
    unknown = await registry.dispatch("/someone_private", orch=None, principal=guest)
    assert (denied.status, oversized.status, unknown.status) == ("refused", "refused", "unknown")
    assert observed == [
        ("command.completed", {"command": "danger", "status": "refused"}),
        ("command.completed", {"command": "kanban", "status": "refused"}),
    ]


@pytest.mark.asyncio
async def test_quick_alias_enters_registered_target_once_but_quick_exec_does_not(monkeypatch, observed):
    settings = {
        "shortcut": {"type": "alias", "target": "/ping"},
        "runner": {"type": "exec", "command": "echo fixed"},
    }
    monkeypatch.setattr(quick_commands.settings_db, "get_value", lambda *_a, **_k: settings)
    registry = CommandRegistry()
    registry.register(SlashCommand("ping", "reply", lambda _: "pong"))

    async def handle(*_a, **_k):
        return {"ok": True, "result": {"stdout": "done"}}

    orch = SimpleNamespace(tool_rpc=SimpleNamespace(handle=handle))
    principal = Principal(admin=True)
    assert (await registry.dispatch("/shortcut", orch=orch, principal=principal)).reply == "pong"
    assert (await registry.dispatch("/runner", orch=orch, principal=principal)).reply == "done"
    assert observed == [
        ("command.started", {"command": "ping"}),
        ("command.completed", {"command": "ping", "status": "answered"}),
        ("command.completed", {"command": "ping", "status": "answered"}),
        ("command.completed", {"command": "runner", "status": "answered"}),
    ]


@pytest.mark.asyncio
async def test_bad_registered_identifier_is_not_sent_to_start_observers(observed):
    name = "a" * 65
    registry = CommandRegistry()
    registry.register(SlashCommand(name, "oversized registered name", lambda _: "ran"))
    result = await registry.dispatch("/" + name, orch=None, principal=Principal(admin=True))
    assert result.reply == "ran"
    assert all(event != "command.started" for event, _ in observed)


@pytest.mark.asyncio
async def test_mixed_case_registration_and_alias_start_under_canonical_registry_key(observed):
    registry = CommandRegistry()
    registry.register(SlashCommand("PinG", "reply", lambda _: "pong", aliases=("hello",)))
    result = await registry.dispatch("/hello", orch=None, principal=Principal(admin=True))
    assert result.reply == "pong"
    assert [fields for event, fields in observed if event == "command.started"] == [
        {"command": "ping"},
    ]


@pytest.mark.asyncio
async def test_source_check_failure_never_announces_handler_entry(monkeypatch, observed):
    def broken_source(**_kwargs):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(command_source, "source_for_dispatch", broken_source)
    ran = []
    registry = CommandRegistry()
    registry.register(SlashCommand("ping", "reply", lambda _: ran.append(True) or "pong"))
    result = await registry.dispatch("/ping", orch=None, principal=Principal(admin=True))
    assert result.status == "failed" and ran == []
    assert observed == [("command.completed", {"command": "ping", "status": "failed"})]


@pytest.mark.asyncio
async def test_start_emitter_failure_does_not_block_handler(monkeypatch, observed):
    ran = []

    def emit(event, **fields):
        if event == "command.started":
            raise RuntimeError("observer broken")
        observed.append((event, fields))

    monkeypatch.setattr(events_module.EXTENSION_EVENTS, "emit", emit)
    registry = CommandRegistry()
    registry.register(SlashCommand("ping", "reply", lambda _: ran.append(True) or "pong"))
    result = await registry.dispatch("/ping", orch=None, principal=Principal(admin=True))
    assert result.status == "answered" and ran == [True]
    assert observed == [("command.completed", {"command": "ping", "status": "answered"})]
