"""Original Telegram owner commands alone carry sealed requester provenance."""

from __future__ import annotations

import asyncio

import pytest

from agents.core.channel_inbox import ChannelInboxStore
from agents.core.channels.gateway import Gateway
from agents.core.channels.telegram import TelegramChannel
from agents.core.command_source import plaintext_restart
from agents.core.commands import ADMIN, CommandRegistry, Principal, SlashCommand


class Pairing:
    allowed = True

    def gate_inbound(self, _channel, _sender, **_kwargs):
        return {"allowed": self.allowed}

    def is_allowed(self, _channel, _sender):
        return self.allowed


class Orch:
    owner = True

    def __init__(self):
        self.channels = {}
        self.before_dispatch = None
        self.nested_route = None

    def _channel_principal(self, channel, sender, chat_id, chat_type):
        return Principal(channel=channel, sender=str(sender), admin=self.owner,
                         chat=str(chat_id), scope="dm" if chat_type == "private" else "group")


def _update(*, text="/restart", bot_id=42, update_id=7, chat_id=10, message_id=12,
            edited=False, forwarded=False, backfilled=False, is_bot=False,
            chat_type="private", attachment=False):
    msg = {"from": {"id": chat_id, "is_bot": is_bot},
           "chat": {"id": chat_id, "type": chat_type},
           "message_id": message_id, "text": text}
    if forwarded:
        msg["forward_origin"] = {"type": "user"}
    if backfilled:
        msg["_backfilled"] = True
    if attachment:
        msg["document"] = {"file_id": "f", "file_name": "a.txt", "mime_type": "text/plain"}
    return {"update_id": update_id, "edited_message" if edited else "message": msg}


def _rig(tmp_path):
    captured = []
    pairing = Pairing()
    orch = Orch()
    registry = CommandRegistry()

    def handler(ctx):
        captured.append(ctx)
        return "receipt"

    registry.register(SlashCommand("restart", "test provenance", handler, tier=ADMIN))

    async def route_command(text, *, channel, **kwargs):
        if orch.nested_route is not None:
            nested = orch.nested_route
            orch.nested_route = None
            await nested()
        principal = orch._channel_principal(channel, kwargs["sender"], kwargs["chat_id"],
                                            kwargs.get("chat_type", "private"))
        if orch.before_dispatch is not None:
            orch.before_dispatch()
        command_text = ("/restart" if kwargs.get("chat_type", "private") == "private"
                        and plaintext_restart(text) else text)
        outcome = await registry.dispatch(command_text, orch=orch, principal=principal)
        return outcome.reply if outcome else ""

    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    gateway = Gateway(handler=route_command, pairing=pairing, inbox_store=inbox,
                      command_source_adapter=lambda: orch.channels.get("telegram"))
    channel = TelegramChannel("test-token", handler=gateway.route, pairing=pairing)
    channel._heal_dead_target = lambda _up: None
    channel._running = True
    channel._owner_once_generation = "current"
    channel._verified_bot_generation = "current"
    channel._bot_id = 42
    orch.channels["telegram"] = channel
    return channel, gateway, pairing, orch, inbox, captured


@pytest.mark.asyncio
async def test_original_owner_dm_command_seals_bot_scoped_source_after_inbox(tmp_path):
    channel, _gateway, _pairing, _orch, inbox, captured = _rig(tmp_path)
    try:
        await channel._handle_update(_update())
        assert len(captured) == 1
        source = captured[0].source
        assert source is not None
        assert (source.bot_id, source.update_id, source.message_id,
                source.chat_id, source.sender_id) == (42, 7, 12, 10, 10)
        assert source.provider_id == "telegram:42:7"
        stored = inbox.get_message(source.inbox_id)
        assert stored["provider_id"] == source.provider_id
        assert stored["reply"]["chat_id"] == 10
        assert source.candidate.task is asyncio.current_task()
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", [
    "restart gateway", "Please restart the gateway!", "restart Nerva gateway?",
    "please restart NERVA.",
])
async def test_private_restart_phrase_keeps_original_in_signed_source_and_inbox(tmp_path, phrase):
    channel, _gateway, _pairing, _orch, inbox, captured = _rig(tmp_path)
    try:
        await channel._handle_update(_update(text=phrase))
        assert len(captured) == 1
        source = captured[0].source
        assert source is not None and source.candidate.text == phrase
        assert inbox.get_message(source.inbox_id)["text"] == phrase
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"edited": True}, {"forwarded": True}, {"backfilled": True},
    {"attachment": True}, {"is_bot": True}, {"chat_type": "group"},
    {"text": "restart gateway now"}, {"text": "\nrestart gateway"},
])
async def test_private_phrase_false_contexts_do_not_mint_source(tmp_path, changes):
    channel, _gateway, _pairing, _orch, _inbox, captured = _rig(tmp_path)
    async def read_without_network(*_args):
        return "attachment text", ""

    channel._read_attachment = read_without_network
    try:
        await channel._handle_update(_update(**{"text": "restart gateway", **changes}))
        assert all(ctx.source is None for ctx in captured)
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"edited": True}, {"forwarded": True}, {"backfilled": True},
    {"is_bot": True}, {"chat_type": "group"}, {"text": "/restart now"},
    {"text": "/status"}, {"attachment": True}, {"update_id": 0},
])
async def test_untrusted_telegram_shapes_never_gain_source(tmp_path, changes):
    channel, _gateway, _pairing, _orch, _inbox, captured = _rig(tmp_path)
    try:
        await channel._handle_update(_update(**changes))
        assert all(ctx.source is None for ctx in captured)
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_guest_unpaired_and_missing_inbox_never_gain_source(tmp_path):
    channel, gateway, pairing, orch, _inbox, captured = _rig(tmp_path)
    try:
        orch.owner = False
        await channel._handle_update(_update(update_id=8))
        assert captured == []  # registry owner tier denies before invoking the handler
        orch.owner = True
        pairing.allowed = False
        before = len(captured)
        await channel._handle_update(_update(update_id=9))
        assert len(captured) == before
        pairing.allowed = True
        gateway.inbox_store = None
        await channel._handle_update(_update(update_id=10))
        assert captured[-1].source is None
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_forged_route_kwargs_and_stale_generation_cannot_create_source(tmp_path):
    channel, gateway, _pairing, _orch, _inbox, captured = _rig(tmp_path)
    try:
        await gateway.route("/restart", channel="telegram", sender="10", chat_id=10,
                            provider_id="telegram:42:7", dedup_key="telegram:telegram:42:7",
                            _command_source=object())
        assert captured[-1].source is None
        await channel._handle_update(_update())
        assert captured[-1].source is not None  # forged ID did not poison dedup
        channel._verified_bot_generation = "old"
        await channel._handle_update(_update(update_id=11))
        assert captured[-1].source is None
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_ordinary_telegram_provider_id_keeps_existing_generic_dedup(tmp_path):
    channel, gateway, _pairing, _orch, _inbox, captured = _rig(tmp_path)
    try:
        await gateway.route("/restart", channel="telegram", sender="10", chat_id=10,
                            provider_id="ordinary:55")
        await gateway.route("/restart", channel="telegram", sender="10", chat_id=10,
                            provider_id="ordinary:55")
        assert len(captured) == 1
        assert captured[0].source is None
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_provider_identity_distinguishes_bots_and_duplicate_update_is_dropped(tmp_path):
    channel, _gateway, _pairing, _orch, _inbox, captured = _rig(tmp_path)
    try:
        await channel._handle_update(_update())
        await channel._handle_update(_update())
        assert len(captured) == 1
        channel._bot_id = 43
        await channel._handle_update(_update(bot_id=43))
        assert len(captured) == 2
        assert captured[-1].source.provider_id == "telegram:43:7"
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_owner_or_adapter_revocation_before_dispatch_drops_source(tmp_path):
    channel, _gateway, pairing, orch, _inbox, captured = _rig(tmp_path)
    try:
        orch.before_dispatch = lambda: setattr(orch, "owner", False)
        await channel._handle_update(_update(update_id=20))
        assert captured[-1].source is None
        orch.owner = True
        orch.before_dispatch = lambda: orch.channels.__setitem__("telegram", object())
        await channel._handle_update(_update(update_id=21))
        assert captured[-1].source is None
        orch.channels["telegram"] = channel
        orch.before_dispatch = lambda: setattr(pairing, "allowed", False)
        await channel._handle_update(_update(update_id=22))
        assert captured[-1].source is None
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_overlapping_starts_share_one_verified_generation_then_restart(tmp_path):
    channel, _gateway, _pairing, _orch, _inbox, _captured = _rig(tmp_path)
    channel._running = False
    entered = asyncio.Event()
    finish_old = asyncio.Event()
    calls = 0

    async def get_me():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await finish_old.wait()
            return {"id": 111, "username": "old"}
        return {"id": 222, "username": "new"}

    async def no_poll():
        return None

    channel._get_me = get_me
    channel._poll_loop = no_poll
    channel._resume_offset = lambda: None
    channel.publish_command_menu = no_poll
    old = asyncio.create_task(channel.start())
    second = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        second = asyncio.create_task(channel.start())
        await asyncio.sleep(0)
        assert not second.done()
        assert calls == 1
        finish_old.set()
        await asyncio.wait_for(asyncio.gather(old, second), timeout=1)
        generation = channel._owner_once_generation
        assert channel._bot_id == 111
        assert channel._verified_bot_generation == generation
        assert calls == 1

        await channel.stop()
        await channel.start()
        assert channel._bot_id == 222
        assert channel._owner_once_generation != generation
        assert channel._verified_bot_generation == channel._owner_once_generation
        assert calls == 2
    finally:
        finish_old.set()
        for task in (old, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (old, second) if task is not None),
                             return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_nested_route_with_failed_inbox_clears_outer_source(tmp_path):
    channel, gateway, _pairing, orch, _inbox, captured = _rig(tmp_path)

    async def nested():
        store = gateway.inbox_store
        gateway.inbox_store = None
        try:
            await gateway.route("/restart", channel="telegram", sender="10", chat_id=10,
                                provider_id="telegram:42:999")
        finally:
            gateway.inbox_store = store

    orch.nested_route = nested
    try:
        await channel._handle_update(_update(update_id=24))
        assert len(captured) == 2
        assert captured[0].source is None
        assert captured[1].source.provider_id == "telegram:42:24"
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_direct_message_helper_cannot_smuggle_seed_object(tmp_path):
    channel, _gateway, _pairing, _orch, _inbox, captured = _rig(tmp_path)
    msg = _update()["message"]
    msg["_command_seed"] = object()
    try:
        await channel._handle_message_content(msg, 10, 10, "/restart", None)
        assert captured[-1].source is None
    finally:
        await channel.client.aclose()
