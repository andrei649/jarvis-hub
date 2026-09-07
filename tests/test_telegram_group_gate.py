"""Hermes absorption 0.4 — being in a room is not being addressed.

Nerva's only gating vocabulary was one flat ``allowed_user_ids`` list: a bot placed in a
group answered every message from every permitted member, and every message in the room
became context the agent reasoned and acted on. That is an authorization boundary, not a
convenience, so the gate fails closed — unknown chat types drop, a chat allowlist is exact,
and in a group only a mention of the bot or a reply to it counts as being addressed unless
the owner turns that requirement off. Observe mode is the one middle ground: recorded as
context, never answered, and never charged against the reply rate budget.

Hermetic: a fake Telegram transport, a recording handler, and bare orchestrator doubles.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from agents.core.channels.gateway import Gateway
from agents.core.channels.group_policy import (
    ANSWER,
    DROP,
    OBSERVE,
    GroupPolicy,
    gate_message,
)
from agents.core.channels.manager import ChannelManager
from agents.core.channels.session import SessionSource, build_session_key
from agents.core.channels.telegram import TelegramChannel
from agents.core.orchestrator import Orchestrator

BOT_ID = 999
BOT = "nerva_bot"
GROUP = -1001
_update_ids = itertools.count(1)


def _gate(text, policy=None, *, chat_type="supergroup", chat_id=GROUP, **kwargs):
    return gate_message(
        policy or GroupPolicy(),
        chat_type=chat_type,
        chat_id=chat_id,
        text=text,
        bot_id=BOT_ID,
        bot_username=BOT,
        **kwargs,
    )


# ── the decision ─────────────────────────────────────────────────────────────


def test_a_direct_message_is_answered_unchanged():
    decision = _gate("hello", chat_type="private", chat_id=42)
    assert (decision.action, decision.text) == (ANSWER, "hello")


def test_a_group_message_without_a_mention_is_dropped_by_default():
    decision = _gate("hello everyone")
    assert (decision.action, decision.reason) == (DROP, "not_addressed")


def test_a_mention_addresses_the_bot_and_is_stripped_from_the_text():
    decision = _gate("@nerva_bot what's the weather?")
    assert (decision.action, decision.text) == (ANSWER, "what's the weather?")
    assert _gate("hey @Nerva_Bot , status").text == "hey , status"


def test_a_command_addressed_to_the_bot_keeps_the_command():
    assert _gate("/status@nerva_bot").text == "/status"


def test_a_reply_to_the_bot_is_addressed():
    decision = _gate("thanks", reply_to_from_id=BOT_ID)
    assert decision.action == ANSWER
    assert _gate("thanks", reply_to_from_id=123).action == DROP


def test_a_text_mention_entity_for_the_bot_is_addressed():
    entity = {"type": "text_mention", "offset": 0, "length": 5, "user": {"id": BOT_ID}}
    assert _gate("Nerva, ping", entities=[entity]).action == ANSWER
    other = {"type": "text_mention", "offset": 0, "length": 5, "user": {"id": 1}}
    assert _gate("Nerva, ping", entities=[other]).action == DROP


def test_lookalikes_are_not_mentions():
    assert _gate("mail me at x@nerva_bot").action == DROP
    assert _gate("@nerva_bot2 hi").action == DROP
    assert _gate("nerva_bot hi").action == DROP


def test_the_chat_allowlist_is_exact_and_can_name_a_single_topic():
    policy = GroupPolicy(allowed_chat_ids=frozenset({"-1001", "-2002:7"}))
    assert _gate("@nerva_bot hi", policy, chat_id=-1001).action == ANSWER
    assert _gate("@nerva_bot hi", policy, chat_id=-3003).reason == "chat_not_allowed"
    assert _gate("@nerva_bot hi", policy, chat_id=-2002, thread_id=7).action == ANSWER
    assert _gate("@nerva_bot hi", policy, chat_id=-2002, thread_id=8).reason == "chat_not_allowed"
    assert _gate("@nerva_bot hi", policy, chat_id=-2002).reason == "chat_not_allowed"


def test_the_mention_requirement_is_the_owners_to_relax():
    relaxed = GroupPolicy(require_mention=False)
    decision = _gate("hello everyone", relaxed)
    assert (decision.action, decision.reason, decision.text) == (
        ANSWER, "mention_not_required", "hello everyone",
    )


def test_observe_mode_records_instead_of_dropping():
    decision = _gate("hello everyone", GroupPolicy(observe_mode=True))
    assert (decision.action, decision.text) == (OBSERVE, "hello everyone")
    # An addressed message is still answered in observe mode.
    assert _gate("@nerva_bot hi", GroupPolicy(observe_mode=True)).action == ANSWER


def test_unknown_chat_types_fail_closed():
    assert _gate("hi", chat_type="something_new").reason == "unknown_chat_type"
    assert _gate("hi", chat_type=None).action == DROP


def test_without_its_own_identity_the_bot_cannot_be_addressed():
    """getMe failed: no username, no id — every group message drops rather than answers."""
    decision = gate_message(
        GroupPolicy(), chat_type="group", chat_id=GROUP, text="@nerva_bot hi",
        bot_id=None, bot_username=None, reply_to_from_id=None,
    )
    assert decision.action == DROP


def test_policy_from_env_defaults_closed_and_parses_the_knobs():
    assert GroupPolicy.from_env({}) == GroupPolicy()
    policy = GroupPolicy.from_env(
        {
            "TELEGRAM_GROUP_REQUIRE_MENTION": "false",
            "TELEGRAM_ALLOWED_CHAT_IDS": " -1001, -2002:7 ,,",
            "TELEGRAM_GROUP_OBSERVE": "1",
        }
    )
    assert policy == GroupPolicy(
        require_mention=False,
        allowed_chat_ids=frozenset({"-1001", "-2002:7"}),
        observe_mode=True,
    )
    # Garbage never widens the gate.
    assert GroupPolicy.from_env({"TELEGRAM_GROUP_REQUIRE_MENTION": "maybe"}).require_mention is True


# ── the poll loop applies it ─────────────────────────────────────────────────


def _message(text, *, chat_type="supergroup", chat_id=GROUP, uid=42, **extra):
    return {
        "update_id": next(_update_ids),
        "message": {
            "message_id": 1,
            "from": {"id": uid},
            "chat": {"id": chat_id, "type": chat_type},
            "text": text,
            **extra,
        },
    }


async def _drain(channel: TelegramChannel, updates: list[dict]) -> None:
    batches = [updates]

    async def fake_updates():
        if batches:
            return batches.pop(0)
        channel._running = False
        return []

    channel._get_updates = fake_updates
    channel._running = True
    await channel._poll_loop()


def _channel(policy=None, *, identity=True):
    received = []

    async def handler(text, channel="telegram", **kwargs):
        received.append((text, kwargs))
        return "ok"

    channel = TelegramChannel(token="t", handler=handler, group_policy=policy)
    if identity:
        channel._bot_id, channel._bot_username = BOT_ID, BOT
    return channel, received


@pytest.mark.asyncio
async def test_the_poll_loop_answers_only_what_addresses_the_bot():
    channel, received = _channel()

    await _drain(
        channel,
        [
            _message("hi", chat_type="private", chat_id=42),
            _message("hello everyone"),
            _message("@nerva_bot status please"),
            _message("thanks", reply_to_message={"from": {"id": BOT_ID}}),
            _message("@nerva_bot hi", chat_type="channel_post_or_whatever"),
        ],
    )

    assert [(text, kwargs["chat_id"]) for text, kwargs in received] == [
        ("hi", 42),
        ("status please", GROUP),
        ("thanks", GROUP),
    ]
    assert all("observe_only" not in kwargs for _text, kwargs in received)


@pytest.mark.asyncio
async def test_the_poll_loop_forwards_observed_messages_as_context_only():
    channel, received = _channel(GroupPolicy(observe_mode=True))

    await _drain(channel, [_message("hello everyone"), _message("@nerva_bot hi")])

    assert received == [
        ("hello everyone", {"chat_id": GROUP, "sender": "42", "observe_only": True}),
        ("hi", {"chat_id": GROUP, "sender": "42"}),
    ]


@pytest.mark.asyncio
async def test_the_poll_loop_drops_group_traffic_when_getme_failed():
    channel, received = _channel(identity=False)

    await _drain(channel, [_message("@nerva_bot hi"), _message("hi", chat_type="private", chat_id=1)])

    assert [text for text, _ in received] == ["hi"]


@pytest.mark.asyncio
async def test_the_user_allowlist_still_runs_first():
    channel, received = _channel()
    channel.allowed_users = [7]

    await _drain(channel, [_message("@nerva_bot hi", uid=42), _message("@nerva_bot yo", uid=7)])

    assert [text for text, _ in received] == ["yo"]


# ── the gateway and the orchestrator honour observe-only ─────────────────────


@pytest.mark.asyncio
async def test_observed_messages_do_not_spend_the_reply_rate_budget():
    seen = []

    async def handler(text, channel="telegram", **kwargs):
        seen.append((text, kwargs.get("observe_only", False)))
        return "reply"

    gateway = Gateway(handler=handler)
    gateway.set_rate_limit(1)

    for _ in range(3):
        assert await gateway.route("chatter", channel="telegram", sender="1", observe_only=True) == "reply"
    assert await gateway.route("@bot hi", channel="telegram", sender="1") == "reply"
    assert (await gateway.route("@bot again", channel="telegram", sender="1")).startswith("Rate limit")
    assert seen == [("chatter", True)] * 3 + [("@bot hi", False)]


@pytest.mark.asyncio
async def test_an_unpaired_observer_is_held_silently():
    class _Pairing:
        def gate_inbound(self, channel, sender, code=None):
            return {"allowed": False, "status": "pending", "message": "Pair this device first."}

    gateway = Gateway(handler=None, pairing=_Pairing())

    assert await gateway.route("hi", channel="telegram", sender="9") == "Pair this device first."
    assert await gateway.route("hi", channel="telegram", sender="9", observe_only=True) is None


def _bare_orchestrator():
    orch = Orchestrator.__new__(Orchestrator)
    orch._channel_sessions = {}
    orch._runtime_settings = {}
    orch.session_id = "web_shared"
    orch.channel_manager = ChannelManager()
    orch._delivery_router = SimpleNamespace(
        resolve=lambda source, text="": SimpleNamespace(send=False, target=None)
    )
    turns = []
    generated = []

    async def fake_handle_input(text, channel="voice", agent_override=None):
        generated.append(text)
        return "reply"

    class _Memory:
        async def new_session(self, session_id=None):
            return f"session:{session_id}"

        async def resume_session(self, session_id):
            return False

        async def add_turn(self, session_id, role, text, **kwargs):
            turns.append((session_id, role, text, kwargs.get("channel")))

    orch.handle_input = fake_handle_input
    orch.memory = _Memory()
    return orch, turns, generated


@pytest.mark.asyncio
async def test_an_observed_message_becomes_context_and_never_a_turn():
    orch, turns, generated = _bare_orchestrator()

    result = await orch.channel_handler(
        "hello everyone", channel="telegram", chat_id=GROUP, sender="42", observe_only=True
    )

    assert result is None
    assert generated == []
    key = build_session_key(SessionSource(channel="telegram", sender="42", thread_id=GROUP))
    assert turns == [(f"session:{key}", "user", "hello everyone", "telegram")]
    assert orch.session_id == "web_shared"  # the per-chat binding was reset


@pytest.mark.asyncio
async def test_an_addressed_message_is_still_a_full_turn():
    orch, turns, generated = _bare_orchestrator()

    result = await orch.channel_handler("status", channel="telegram", chat_id=GROUP, sender="42")

    assert result == "reply"
    assert generated == ["status"]
    assert turns == []  # the fake handle_input owns its own transcript writes
