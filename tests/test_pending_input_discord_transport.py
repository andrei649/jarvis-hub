"""Local Discord pending-card transport and fast ingress, with no Discord network use."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels import discord as transport
from agents.core.channels.discord import DiscordChannel
from agents.core.channels.pending_input_cards import CardResult


class View:
    def __init__(self, *, timeout=None):
        self.timeout = timeout
        self.children = []
        self.stopped = False

    def add_item(self, button):
        self.children.append(button)

    def stop(self):
        self.stopped = True


class Button:
    def __init__(self, *, label, style, custom_id, row):
        self.label, self.style, self.custom_id, self.row = label, style, custom_id, row
        self.callback = None
        self.disabled = False


class Sent:
    def __init__(self, message_id=701, *, author_id=900):
        self.id = message_id
        self.author = SimpleNamespace(id=author_id)
        self.channel = SimpleNamespace(id=123)
        self.edits = []
        self.fail_edit = False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        if self.fail_edit:
            raise RuntimeError("local synthetic edit failure")


class Sink:
    id = 123

    def __init__(self, message_id=701):
        self.message_id = message_id
        self.calls = []
        self.messages = []
        self.before_ack = None

    async def send(self, content, **kwargs):
        self.calls.append((content, kwargs))
        if self.before_ack:
            await self.before_ack()
        sent = Sent(self.message_id)
        self.messages.append(sent)
        return sent


class Client:
    def __init__(self, sink):
        self.sink = sink
        self.user = SimpleNamespace(id=900)
        self.closed = False

    def is_ready(self):
        return not self.closed

    def get_channel(self, channel_id):
        return self.sink if channel_id == self.sink.id else None

    async def close(self):
        self.closed = True


class Pairing:
    allowed = True

    def is_allowed(self, channel, sender):
        return self.allowed and channel == "discord" and sender == "42"


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setattr(transport, "discord", SimpleNamespace(
        ui=SimpleNamespace(View=View, Button=Button),
        ButtonStyle=SimpleNamespace(primary=1, secondary=2, danger=3, success=4),
    ), raising=False)
    monkeypatch.setattr(transport, "DISCORD_AVAILABLE", True)
    ch = DiscordChannel(token="synthetic", pairing=Pairing())
    sink = Sink()
    ch._client = Client(sink)
    ch._running = True
    return ch, sink


def markup(*actions):
    return {"inline_keyboard": [[{"text": str(index), "callback_data": f"h067:abcdefghijklmnop:0:{action}"}]
                                for index, action in enumerate(actions)]}


@pytest.mark.asyncio
async def test_card_binds_only_final_verified_sdk_receipt(channel):
    ch, sink = channel
    receipt = await ch.send_pending_card("A" * 2100, reply_markup=markup("c0"), channel_id=123)
    assert receipt == {"channel": "discord", "target": "123", "message_id": "701",
                       "thread_id": None, "team_id": None}
    assert len(sink.calls) == 2
    assert sink.calls[0][1] == {}
    assert isinstance(sink.calls[1][1]["view"], View)
    assert len(ch._pending_views) == 1
    ch.discard_pending_card(receipt)
    assert not ch._pending_views and sink.calls[-1][1]["view"].stopped


@pytest.mark.asyncio
async def test_live_card_view_has_no_fixed_timeout(channel):
    ch, sink = channel
    await ch.send_pending_card("Choose", reply_markup=markup("c0"), channel_id=123)
    assert sink.calls[-1][1]["view"].timeout is None


@pytest.mark.asyncio
async def test_full_view_capacity_rejects_before_send_without_evicting_live_cards(channel):
    ch, sink = channel
    existing = {}
    for index in range(128):
        view = View()
        key = (str(index + 1), str(index + 1000))
        ch._pending_views[key] = view
        existing[key] = view
    assert await ch.send_pending_card("Choose", reply_markup=markup("c0"), channel_id=123) is None
    assert sink.calls == []
    assert len(ch._pending_views) == 128
    assert all(ch._pending_views[key] is view and not view.stopped for key, view in existing.items())


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [True, "701", 0, -1])
async def test_bad_ack_cannot_bind_buttons(channel, bad_id):
    ch, sink = channel
    sink.message_id = bad_id
    assert await ch.send_pending_card("Choose", reply_markup=markup("c0"), channel_id=123) is None
    assert not ch._pending_views


@pytest.mark.asyncio
async def test_generation_change_during_send_rejects_receipt(channel):
    ch, sink = channel

    async def change():
        ch._pending_callback_generation = object()

    sink.before_ack = change
    assert await ch.send_pending_card("Choose", reply_markup=markup("c0"), channel_id=123) is None
    assert not ch._pending_views


class Interaction:
    def __init__(self, ch, sent, custom_id, *, sender=42, target=123, client=None):
        self.client = ch._client if client is None else client
        self.channel_id = target
        self.message = sent
        self.user = SimpleNamespace(id=sender, bot=False)
        self.data = {"custom_id": custom_id}
        self.acks = []
        self.response = SimpleNamespace(defer=self.defer)
        self.followup = SimpleNamespace(send=self.followup_send)

    async def defer(self, **kwargs):
        self.acks.append(("defer", kwargs))

    async def followup_send(self, text, **kwargs):
        self.acks.append((text, kwargs))


@pytest.mark.asyncio
async def test_verified_button_uses_fast_handler_and_updates_exact_view(channel):
    ch, sink = channel
    received = []

    async def handler(callback, **kwargs):
        received.append((callback, kwargs))
        return CardResult(True, "selected", "p", markup("t0", "x"))

    ch.pending_callback_handler = handler
    receipt = await ch.send_pending_card("Choose", reply_markup=markup("t0"), channel_id=123)
    first = sink.calls[-1][1]["view"]
    tap = Interaction(ch, Sent(701), first.children[0].custom_id)
    await first.children[0].callback(tap)
    await asyncio.gather(*tuple(ch._pending_callback_fast.values()))
    assert tap.acks[0][0] == "defer"
    assert received == [({"channel": "discord", "target": "123", "message_id": "701",
                          "thread_id": None, "team_id": None, "sender": "42",
                          "data": "h067:abcdefghijklmnop:0:t0"}, {"channel": "discord"})]
    assert first.stopped
    assert sink.messages[-1].edits[-1]["view"] is ch._pending_views[("123", "701")]
    ch.discard_pending_card(receipt)


@pytest.mark.asyncio
async def test_foreign_and_stale_buttons_never_reach_resolver(channel):
    ch, sink = channel
    seen = []

    async def handler(callback, **kwargs):
        seen.append(callback)
        return CardResult(True, "resolved", "p")

    ch.pending_callback_handler = handler
    await ch.send_pending_card("Choose", reply_markup=markup("c0"), channel_id=123)
    view = sink.calls[-1][1]["view"]
    for bad in (Interaction(ch, sink.messages[-1], view.children[0].custom_id, sender=True),
                Interaction(ch, sink.messages[-1], view.children[0].custom_id, target=124),
                Interaction(ch, sink.messages[-1], view.children[0].custom_id, client=Client(sink))):
        await view.children[0].callback(bad)
    assert not seen
    ch._pending_callback_generation = object()
    await view.children[0].callback(Interaction(ch, sink.messages[-1], view.children[0].custom_id))
    assert not seen


@pytest.mark.asyncio
async def test_revoked_pairing_after_handler_cannot_rebind_view(channel):
    ch, sink = channel
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(_callback, **_kwargs):
        entered.set()
        await release.wait()
        return CardResult(True, "selected", "p", markup("t0", "x"))

    ch.pending_callback_handler = handler
    await ch.send_pending_card("Choose", reply_markup=markup("t0"), channel_id=123)
    view = sink.calls[-1][1]["view"]
    await view.children[0].callback(Interaction(ch, Sent(701), view.children[0].custom_id))
    await asyncio.wait_for(entered.wait(), 1)
    ch._pairing.allowed = False
    release.set()
    await asyncio.gather(*tuple(ch._pending_callback_fast.values()))
    assert sink.messages[-1].edits == []


@pytest.mark.asyncio
async def test_failed_view_edit_keeps_applied_answer_and_retires_buttons(channel):
    ch, sink = channel

    async def handler(_callback, **_kwargs):
        return CardResult(True, "selected", "p", markup("t0", "x"))

    ch.pending_callback_handler = handler
    await ch.send_pending_card("Choose", reply_markup=markup("t0"), channel_id=123)
    sent = sink.messages[-1]
    sent.fail_edit = True
    view = sink.calls[-1][1]["view"]
    tap = Interaction(ch, Sent(701), view.children[0].custom_id)
    await view.children[0].callback(tap)
    await asyncio.gather(*tuple(ch._pending_callback_fast.values()))
    assert tap.acks[-1][0] == "Applied."
    assert view.stopped and not ch._pending_views


@pytest.mark.asyncio
async def test_stop_drains_owned_fast_callback(channel):
    ch, sink = channel
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(_callback, **_kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    ch.pending_callback_handler = handler
    await ch.send_pending_card("Choose", reply_markup=markup("c0"), channel_id=123)
    view = sink.calls[-1][1]["view"]
    await view.children[0].callback(Interaction(ch, Sent(701), view.children[0].custom_id))
    await asyncio.wait_for(entered.wait(), 1)
    await ch.stop()
    assert cancelled.is_set() and not ch._pending_callback_fast and view.stopped


@pytest.mark.asyncio
async def test_real_discord_sdk_builds_native_view_when_available(channel, monkeypatch):
    sdk = pytest.importorskip("discord")
    # This test runs with the isolated Discord SDK target and sends no API request.
    monkeypatch.setattr(transport, "discord", sdk)
    ch, sink = channel
    receipt = await ch.send_pending_card("Choose", reply_markup=markup("c0", "c1", "x"),
                                         channel_id="123")
    assert receipt["message_id"] == "701"
    view = sink.calls[-1][1]["view"]
    assert isinstance(view, sdk.ui.View)
    assert all(isinstance(button, sdk.ui.Button) for button in view.children)
    assert [button.custom_id.rsplit(":", 1)[-1] for button in view.children] == ["c0", "c1", "x"]
    callbacks = []
    acknowledgements = []

    async def handler(callback, **_kwargs):
        callbacks.append(callback)
        return CardResult(False, "rejected")

    async def defer(**_kwargs):
        acknowledgements.append("deferred")

    async def notice(_text, **_kwargs):
        acknowledgements.append("noticed")

    ch.pending_callback_handler = handler
    sdk_message = object.__new__(sdk.Message)
    sdk_message.id = 701
    sdk_message.channel = sink
    sdk_message.author = SimpleNamespace(id=900)
    sdk_interaction = object.__new__(sdk.Interaction)
    sdk_interaction._client = ch._client
    sdk_interaction.channel = sink
    sdk_interaction.message = sdk_message
    sdk_interaction.user = SimpleNamespace(id=42, bot=False)
    sdk_interaction.data = {"custom_id": view.children[0].custom_id}
    sdk_interaction._cs_response = SimpleNamespace(defer=defer)
    sdk_interaction._cs_followup = SimpleNamespace(send=notice)
    await view.children[0].callback(sdk_interaction)
    await asyncio.gather(*tuple(ch._pending_callback_fast.values()))
    assert callbacks == [{"channel": "discord", "target": "123", "message_id": "701",
                          "thread_id": None, "team_id": None, "sender": "42",
                          "data": "h067:abcdefghijklmnop:0:c0"}]
    assert acknowledgements == ["deferred", "noticed"]
    await ch.stop()


@pytest.mark.asyncio
async def test_pending_text_bypasses_batch_and_model_only_on_exact_true(channel):
    ch, sink = channel
    turns = []
    pending = []

    async def model(text, **kwargs):
        turns.append(text)

    async def consume(text, **kwargs):
        pending.append((text, kwargs))
        return True

    ch.handler = model
    ch.pending_reply_handler = consume
    msg = SimpleNamespace(content="answer", author=SimpleNamespace(id=42, bot=False),
                          channel=sink, guild=None, webhook_id=None)
    await ch._handle_message(msg)
    assert pending == [("answer", {"channel": "discord", "sender": "42",
                                    "channel_id": "123", "chat_type": "private"})]
    assert not turns and len(ch._batch) == 0
    ch.pending_reply_handler = lambda *_args, **_kwargs: asyncio.sleep(0, result=False)
    await ch._handle_message(msg)
    await ch._batch.flush(("123", "42"))
    assert turns == ["answer"]
    await ch.stop()
