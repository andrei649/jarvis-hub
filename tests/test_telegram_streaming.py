"""Hermes absorption 4c — a chat reply written in place as it is produced.

On a chat surface a long silence and a crash look the same. On a channel whose descriptor
says it can edit a message, the orchestrator streams the turn into a draft: the first token
sends the message, later tokens edit it under Telegram's edit budget, and the final text is
rendered exactly as `send()` would render it. Every step is best effort and never raises
into the turn; the words always arrive.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core.channels.descriptor import ChannelDescriptor  # noqa: E402
from agents.core.channels.telegram import (  # noqa: E402
    TELEGRAM_MAX_MESSAGE_LENGTH,
    TelegramChannel,
    TelegramDraft,
)
from agents.core.orchestrator import Orchestrator  # noqa: E402


class _Resp:
    def __init__(self, status: int, message_id: int = 0) -> None:
        self.status_code = status
        self._message_id = message_id

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"ok": True, "result": {"message_id": self._message_id}}


class _Client:
    """Statuses are per method: {"sendMessage": [..], "editMessageText": [..]}; default 200."""

    def __init__(self, statuses=None) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.statuses = {k: list(v) for k, v in (statuses or {}).items()}
        self.next_id = 100

    async def post(self, url, json=None, **kwargs):
        method = url.rsplit("/", 1)[-1]
        self.posts.append((method, dict(json or {})))
        queue = self.statuses.get(method)
        status = queue.pop(0) if queue else 200
        if method == "sendMessage" and status < 400:
            self.next_id += 1
            return _Resp(status, self.next_id)
        return _Resp(status)

    async def aclose(self) -> None:
        pass


def _channel(statuses=None):
    channel = TelegramChannel("tok")
    channel.client = _Client(statuses)
    return channel


def _clock(values):
    values = list(values)

    def tick():
        return values.pop(0) if len(values) > 1 else values[0]

    return tick


def _edits(client):
    return [body for method, body in client.posts if method == "editMessageText"]


def _sends(client):
    return [body for method, body in client.posts if method == "sendMessage"]


@pytest.mark.asyncio
async def test_first_token_sends_then_edits_are_throttled_and_deduplicated():
    channel = _channel()
    draft = TelegramDraft(channel, 7, interval=1.0, clock=_clock([0.0, 0.5, 1.5, 3.0, 3.1]))
    assert draft.started is False
    await draft.push("Hel")
    assert draft.started and _sends(channel.client) == [
        {"chat_id": 7, "text": "Hel ▍", "parse_mode": "HTML"},
    ]
    await draft.push("lo")               # t=0.5: inside the budget, no edit
    assert _edits(channel.client) == []
    await draft.push(" **world**")       # t=1.5: one edit, balanced markup rendered
    assert _edits(channel.client) == [
        {"chat_id": 7, "message_id": 101, "text": "Hello <b>world</b> ▍", "parse_mode": "HTML"},
    ]
    await draft.push("")                 # t=3.0: nothing changed, no edit
    assert len(_edits(channel.client)) == 1
    assert draft.text == "Hello **world**"


@pytest.mark.asyncio
async def test_finish_settles_the_message_and_sends_the_overflow_as_new_messages():
    channel = _channel()
    draft = TelegramDraft(channel, 7, interval=0.0, clock=_clock([0.0, 1.0, 2.0, 3.0]))
    await draft.push("first")
    long_tail = "\n\n".join("para " * 400 for _ in range(4))
    assert await draft.finish("**first**\n\n" + long_tail) is True
    edits = _edits(channel.client)
    assert edits[-1]["message_id"] == 101 and edits[-1]["text"].startswith("<b>first</b>")
    assert " ▍" not in edits[-1]["text"]
    extra = _sends(channel.client)[1:]
    assert len(extra) >= 1 and all(len(b["text"]) <= TELEGRAM_MAX_MESSAGE_LENGTH for b in extra)
    assert draft.finished is True
    assert await draft.finish("again") is False
    before = len(channel.client.posts)
    await draft.push("late")
    assert len(channel.client.posts) == before


@pytest.mark.asyncio
async def test_markup_telegram_rejects_is_retried_as_plain_text():
    channel = _channel({"editMessageText": [400, 200]})
    draft = TelegramDraft(channel, 7, interval=0.0, clock=_clock([0.0, 1.0, 2.0]))
    await draft.push("a")
    assert await draft.finish("`code` here") is True
    edits = _edits(channel.client)
    assert edits[0]["text"] == "<code>code</code> here" and edits[0]["parse_mode"] == "HTML"
    assert edits[1] == {"chat_id": 7, "message_id": 101, "text": "code here"}


@pytest.mark.asyncio
async def test_failures_never_raise_and_the_final_text_still_arrives():
    channel = _channel({"editMessageText": [500, 500, 500, 500]})
    draft = TelegramDraft(channel, 7, interval=0.0, clock=_clock([0.0, 1.0, 2.0, 3.0]))
    await draft.push("hello")
    await draft.push(" there")           # the edit fails: a skipped frame, no exception
    assert await draft.finish("hello there") is True
    sends = _sends(channel.client)
    assert sends[-1] == {"chat_id": 7, "text": "hello there", "parse_mode": "HTML"}


@pytest.mark.asyncio
async def test_a_draft_that_never_started_sends_normally_and_nothing_sends_nothing():
    channel = _channel()
    draft = TelegramDraft(channel, 7)
    assert await draft.finish("plain reply") is True
    assert _sends(channel.client) == [{"chat_id": 7, "text": "plain reply", "parse_mode": "HTML"}]
    draft = TelegramDraft(channel, 7)
    assert await draft.finish("   ") is False
    assert len(channel.client.posts) == 1


def test_begin_stream_needs_a_chat_and_the_descriptor_says_it_can_edit():
    channel = _channel()
    assert channel.begin_stream() is None
    assert isinstance(channel.begin_stream(chat_id=5), TelegramDraft)
    assert TelegramChannel.descriptor.supports_edit is True


# ── the orchestrator wiring ──────────────────────────────────────────────────

class _Draft:
    def __init__(self):
        self.pushes: list[str] = []
        self.finished_with = None

    @property
    def started(self):
        return bool(self.pushes)

    async def push(self, token):
        self.pushes.append(token)

    async def finish(self, text=None):
        self.finished_with = text
        return True


class _Adapter:
    def __init__(self, can_edit=True):
        self.descriptor = ChannelDescriptor(supports_edit=can_edit, max_message_length=4096)
        self.drafts: list[_Draft] = []
        self.allowed_users = []

    def begin_stream(self, chat_id=None, **kwargs):
        draft = _Draft()
        self.drafts.append(draft)
        return draft


def _orchestrator(adapter, *, streaming=True):
    orch = Orchestrator.__new__(Orchestrator)
    orch._channel_sessions = {}
    orch._runtime_settings = {"channels.streaming_replies": streaming}
    orch.session_id = "web_shared"
    captured = {"sent": [], "whole": 0, "streamed": 0}

    async def fake_handle_input(text, channel="voice", agent_override=None):
        captured["whole"] += 1
        return "whole reply"

    async def fake_handle_input_stream(text, channel="voice", on_token=None, agent_override=None, session_id=None):
        captured["streamed"] += 1
        for piece in ("streamed", " reply"):
            await on_token(piece)
        return "streamed reply"

    orch.handle_input = fake_handle_input
    orch.handle_input_stream = fake_handle_input_stream

    class FakeMem:
        async def new_session(self, session_id=None):
            return f"mem:{session_id}"

        async def resume_session(self, session_id):
            return False

        async def add_turn(self, *args, **kwargs):
            return None

    orch.memory = FakeMem()

    async def fake_send(channel, message, **kwargs):
        captured["sent"].append((channel, message))
        return True

    orch.channel_manager = SimpleNamespace(send=fake_send, channels={"telegram": adapter})
    return orch, captured


@pytest.mark.asyncio
async def test_a_channel_that_can_edit_gets_the_reply_streamed_and_no_second_send():
    adapter = _Adapter()
    orch, cap = _orchestrator(adapter)
    out = await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42")
    assert out == "streamed reply"
    assert cap["streamed"] == 1 and cap["whole"] == 0
    assert adapter.drafts[0].pushes == ["streamed", " reply"]
    assert adapter.drafts[0].finished_with == "streamed reply"
    assert cap["sent"] == []


@pytest.mark.asyncio
async def test_streaming_off_or_a_channel_that_cannot_edit_replies_whole():
    adapter = _Adapter()
    orch, cap = _orchestrator(adapter, streaming=False)
    assert await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42") == "whole reply"
    assert cap["whole"] == 1 and adapter.drafts == [] and cap["sent"] == [("telegram", "whole reply")]

    adapter = _Adapter(can_edit=False)
    orch, cap = _orchestrator(adapter)
    assert await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42") == "whole reply"
    assert adapter.drafts == [] and cap["sent"] == [("telegram", "whole reply")]


@pytest.mark.asyncio
async def test_an_observed_message_never_opens_a_draft():
    adapter = _Adapter()
    orch, cap = _orchestrator(adapter)
    out = await orch.channel_handler(
        "room chatter", channel="telegram", chat_id="123", sender="42", observe_only=True,
    )
    assert out is None and adapter.drafts == [] and cap["sent"] == []
    assert cap["streamed"] == 0 and cap["whole"] == 0


@pytest.mark.asyncio
async def test_a_draft_that_never_started_falls_back_to_the_normal_send():
    adapter = _Adapter()
    orch, cap = _orchestrator(adapter)

    async def silent_stream(text, channel="voice", on_token=None, agent_override=None, session_id=None):
        return "late reply"   # a backend that could not stream: no tokens at all

    orch.handle_input_stream = silent_stream
    assert await orch.channel_handler("salut", channel="telegram", chat_id="123", sender="42") == "late reply"
    assert adapter.drafts[0].finished_with is None
    assert cap["sent"] == [("telegram", "late reply")]
