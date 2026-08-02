"""H17.1a: origin must be bound at every turn/action choke point."""

import asyncio
import inspect

from agents.core import action_origin
from agents.core.kernel import Decision, Verdict
from agents.core.kernel import binding as kernel_binding
from agents.core.orchestrator import Orchestrator


def test_origin_for_channel_keeps_operator_and_internal_turns_trusted():
    trusted_channels = {
        "web",
        "voice",
        "eval",
        "notes",
        "builder",
        "room",
        "arena",
        "workflow",
        "internal",
    }

    for channel in trusted_channels:
        assert action_origin.origin_for_channel(channel) == action_origin.DEFAULT_ACTION_ORIGIN

    # Q10: `widget` moved here — the embed is a PUBLIC door (ch11 CHN-061).
    for channel in {"webhook", "mcp", "telegram", "discord", "slack", "email",
                    "widget", "unknown", ""}:
        assert action_origin.origin_for_channel(channel) == action_origin.INBOUND_ACTION_ORIGIN


def test_turn_origin_binding_never_downgrades_existing_inbound_origin():
    outer_token = action_origin.bind_action_origin(action_origin.INBOUND_ACTION_ORIGIN)
    try:
        inner_token = action_origin.bind_turn_action_origin("eval")
        try:
            assert action_origin.current_action_origin() == action_origin.INBOUND_ACTION_ORIGIN
        finally:
            action_origin.reset_action_origin(inner_token)
        assert action_origin.current_action_origin() == action_origin.INBOUND_ACTION_ORIGIN
    finally:
        action_origin.reset_action_origin(outer_token)


def test_public_turn_entrypoints_bind_origin_at_the_chokepoint():
    handle_src = inspect.getsource(Orchestrator.handle_input)
    stream_src = inspect.getsource(Orchestrator.handle_input_stream)

    for source in (handle_src, stream_src):
        assert "bind_turn_action_origin(channel)" in source
        assert "reset_action_origin(origin_token)" in source


def test_handle_input_binds_direct_external_channel_and_resets():
    orch = Orchestrator.__new__(Orchestrator)
    seen = []

    async def fake_handle_input(text, channel="voice", agent_override=None, session_id=None):
        seen.append((text, channel, action_origin.current_action_origin()))
        return "ok"

    orch._handle_input = fake_handle_input

    outer_token = action_origin.bind_action_origin(action_origin.DEFAULT_ACTION_ORIGIN)
    try:
        result = asyncio.run(Orchestrator.handle_input(orch, "ping", channel="webhook"))
        assert action_origin.current_action_origin() == action_origin.DEFAULT_ACTION_ORIGIN
    finally:
        action_origin.reset_action_origin(outer_token)

    assert result == "ok"
    assert seen == [("ping", "webhook", action_origin.INBOUND_ACTION_ORIGIN)]


def test_handle_input_never_downgrades_upstream_inbound_context():
    orch = Orchestrator.__new__(Orchestrator)
    seen = []

    async def fake_handle_input(text, channel="voice", agent_override=None, session_id=None):
        seen.append(action_origin.current_action_origin())
        return "ok"

    orch._handle_input = fake_handle_input

    outer_token = action_origin.bind_action_origin(action_origin.INBOUND_ACTION_ORIGIN)
    try:
        result = asyncio.run(Orchestrator.handle_input(orch, "ping", channel="eval"))
        assert action_origin.current_action_origin() == action_origin.INBOUND_ACTION_ORIGIN
    finally:
        action_origin.reset_action_origin(outer_token)

    assert result == "ok"
    assert seen == [action_origin.INBOUND_ACTION_ORIGIN]


def test_handle_input_stream_binds_direct_external_channel_and_resets():
    orch = Orchestrator.__new__(Orchestrator)
    seen = []
    tokens = []

    async def fake_handle_input_stream(
        text,
        channel="voice",
        on_token=None,
        agent_override=None,
        session_id=None,
    ):
        seen.append((text, channel, action_origin.current_action_origin()))
        if on_token:
            on_token("chunk")
        return "stream-ok"

    orch._handle_input_stream = fake_handle_input_stream

    outer_token = action_origin.bind_action_origin(action_origin.DEFAULT_ACTION_ORIGIN)
    try:
        result = asyncio.run(
            Orchestrator.handle_input_stream(orch, "ping", channel="mcp", on_token=tokens.append)
        )
        assert action_origin.current_action_origin() == action_origin.DEFAULT_ACTION_ORIGIN
    finally:
        action_origin.reset_action_origin(outer_token)

    assert result == "stream-ok"
    assert tokens == ["chunk"]
    assert seen == [("ping", "mcp", action_origin.INBOUND_ACTION_ORIGIN)]


def test_plugin_egress_kernel_hook_declares_current_origin(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    seen = []

    def kernel(action):
        seen.append(action)
        return Decision(Verdict.GRANT, reason="ok", tier=2)

    hook = kernel_binding.make_egress_kernel_hook(lambda: kernel)
    token = action_origin.bind_action_origin(action_origin.INBOUND_ACTION_ORIGIN)
    try:
        assert hook("weather", "GET", "https://api.example.test/data", "api.example.test") is None
    finally:
        action_origin.reset_action_origin(token)

    assert seen and seen[0].origin == action_origin.INBOUND_ACTION_ORIGIN


def test_plugin_egress_hook_has_no_hardcoded_generated_action_origin():
    source = inspect.getsource(kernel_binding.make_egress_kernel_hook)

    assert "current_action_origin()" in source
    assert 'origin="generated"' not in source
