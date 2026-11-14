"""H057: Slack's native slash envelope and bounded command fallback."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels import slack
from agents.core.channels.gateway import Gateway
from agents.core.channels.pairing import SenderPairing
from agents.core.commands import (
    ADMIN,
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
    slack_native_slashes,
)


def test_slack_projection_reserves_fallback_and_skips_slack_owned_names():
    entries = slack_native_slashes(build_default_registry())
    names = [entry["command"] for entry in entries]
    assert names[0] == "/nerva"
    assert len(names) == len(set(names)) <= 50
    assert "/help" in names and "/stop" in names
    assert "/status" not in names and "/pause" not in names
    assert "/me" not in names and "/remind" not in names
    assert all(len(entry["description"]) <= 140 for entry in entries)

    many = CommandRegistry()
    for index in range(80):
        many.register(SlashCommand(f"command{index:02d}", "d" * 200, lambda ctx: "ok"))
    bounded = slack_native_slashes(many)
    assert len(bounded) == 50 and bounded[0]["command"] == "/nerva"
    assert all(len(entry["description"]) <= 140 for entry in bounded)


def test_quick_commands_cannot_take_the_slack_fallback_name():
    from agents.core.quick_commands import configuration_problem

    assert "built-in command fallback" in configuration_problem({
        "NERVA": {"type": "alias", "target": "/help"},
    })


@pytest.mark.asyncio
async def test_slack_fallback_dispatches_canonical_target_with_its_access_gate():
    registry = CommandRegistry()
    registry.register(SlashCommand("help", "help", lambda ctx: "helped"))
    registry.register(SlashCommand("secret", "secret", lambda ctx: "done", tier=ADMIN))
    guest = Principal(channel="slack", sender="T1:U1")
    owner = Principal(channel="slack", sender="T1:U1", admin=True)
    answer = await registry.dispatch("/nerva help", orch=None, principal=guest)
    assert answer.name == "help" and answer.reply == "helped"
    denied = await registry.dispatch("/nerva secret", orch=None, principal=guest)
    assert denied.name == "secret" and denied.status == "refused"
    allowed = await registry.dispatch("/nerva secret", orch=None, principal=owner)
    assert allowed.name == "secret" and allowed.reply == "done"
    nested = await registry.dispatch("/nerva nerva secret", orch=None, principal=owner)
    assert nested.status == "refused"
    assert CommandRegistry.parse("/nerva stop now") == ("stop", "now")
    assert CommandRegistry.parse("/nerva h") == ("help", "")


@pytest.mark.parametrize("sub", ["new", "reset", "undo", "btw", "checkpoints", "rollback"])
@pytest.mark.asyncio
async def test_slack_fallback_does_not_move_special_commands_after_append(sub):
    registry = build_default_registry()
    outcome = await registry.dispatch(f"/nerva {sub}", orch=None,
                                      principal=Principal(channel="slack", admin=True))
    assert outcome.status == "refused"


@pytest.mark.asyncio
async def test_socket_slash_ack_precedes_normal_gateway_ingress(monkeypatch):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    monkeypatch.setattr(slack, "SocketModeResponse", SimpleNamespace, raising=False)
    seen, reached, pending = [], asyncio.Event(), []

    async def handler(text, **meta):
        seen.append((text, meta))
        reached.set()

    registry = build_default_registry()
    async def pending_reply(*args, **kwargs):
        pending.append((args, kwargs))
        return True

    channel = slack.SlackChannel("bot", handler, app_token="app", command_registry=registry,
                                 pending_reply_handler=pending_reply)

    class Client:
        def __init__(self):
            self.acks = []

        def send_socket_mode_response(self, response):
            self.acks.append(response.envelope_id)

    client = Client()
    channel._socket_client = client
    channel._running = True
    channel._team_id = "T1"
    channel._loop = asyncio.get_running_loop()
    channel._inbound_ready = asyncio.Event()
    worker = asyncio.create_task(channel._dispatch_events())
    request = SimpleNamespace(
        type="slash_commands", envelope_id="envelope-1",
        payload={"team_id": "T1", "user_id": "U1", "channel_id": "D1",
                 "command": "/nerva", "text": "status", "trigger_id": "123.456.abc"},
    )
    try:
        await asyncio.to_thread(channel._on_socket_request, client, request)
        await asyncio.wait_for(reached.wait(), 2)
        assert client.acks == ["envelope-1"]
        assert seen == [("/nerva status", {
            "channel": "slack", "slack_channel": "D1", "sender": "T1:U1",
            "provider_id": "T1:D1:123.456.abc", "pending_input_eligible": False,
        })]
        assert pending == []
        await asyncio.to_thread(channel._on_socket_request, client, request)
        await asyncio.sleep(0)
        assert len(seen) == 1
        second_envelope = SimpleNamespace(**{**request.__dict__, "envelope_id": "envelope-2"})
        await asyncio.to_thread(channel._on_socket_request, client, second_envelope)
        await asyncio.sleep(0)
        assert len(seen) == 1 and len(client.acks) == 3
    finally:
        channel._running = False
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker


def test_socket_slash_rejects_unregistered_native_name_and_forged_workspace():
    registry = build_default_registry()
    channel = slack.SlackChannel("bot", app_token="app", command_registry=registry)
    channel._team_id = "T1"
    channel._bot_user_id = "UBOT"
    valid = {"team_id": "T1", "user_id": "U1", "channel_id": "D1",
             "command": "/nerva", "text": "status", "trigger_id": "123.456.abc"}
    assert channel._normalize_slash({**valid, "command": "/status"}) is None
    assert channel._normalize_slash({**valid, "team_id": "T2"}) is None
    assert channel._normalize_slash({**valid, "user_id": "UBOT"}) is None
    assert channel._normalize_slash(valid) is not None


@pytest.mark.asyncio
async def test_native_slash_keeps_gateway_pairing_pending_and_guest_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "1")
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    pairing = SenderPairing(tmp_path / "pairing.json")
    registry = CommandRegistry()
    registry.register(SlashCommand("help", "help", lambda ctx: "helped"))
    registry.register(SlashCommand("secret", "secret", lambda ctx: "ran", tier=ADMIN))
    seen, pending = [], []

    async def handler(text, *, channel, sender, **kwargs):
        seen.append((text, sender))
        return (await registry.dispatch(text, orch=None,
                                        principal=Principal(channel=channel, sender=sender))).reply

    async def consume_pending(*args, **kwargs):
        pending.append((args, kwargs))
        return True

    gateway = Gateway(handler=handler, pairing=pairing, pending_handler=consume_pending)
    channel = slack.SlackChannel("bot", handler=gateway.route, app_token="app",
                                 pairing=pairing, pending_reply_handler=gateway.route_pending,
                                 command_registry=registry)
    channel._team_id = "T1"
    payload = {"team_id": "T1", "user_id": "U1", "channel_id": "D1",
               "command": "/nerva", "text": "secret", "trigger_id": "123.456.abc"}
    _key, normalized = channel._normalize_slash(payload)
    held = await channel.receive_event(**normalized)
    assert held is not None and seen == [] and pending == []
    assert gateway.get_summary()["total_held"] == 1

    pairing.approve("slack", "T1:U1")
    payload["trigger_id"] = "123.457.abc"
    _key, normalized = channel._normalize_slash(payload)
    denied = await channel.receive_event(**normalized)
    assert "/secret is admin-only" in denied
    assert seen == [("/nerva secret", "T1:U1")]
    assert pending == []
