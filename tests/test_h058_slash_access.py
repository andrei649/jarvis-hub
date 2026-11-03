"""H058 — per-command access tiers on the chat command plane (Hermes ``gateway/slash_access.py``).

The owner (admin tier) runs every command; any other admitted sender (user tier) runs
``/help`` and ``/whoami`` plus the user-tier commands ``commands.user_allowed_commands``
allows for that channel, keyed separately for a DM and a group. A denial reads
``⛔ /<cmd> is admin-only here. You can run: …`` and is written to the security audit log.
The gate is asked on the cold path (the registry, inside the turn), on the busy path (a
channel command while a turn holds the route; the ``/btw`` side question) and again for
quick commands, on the raw typed name. ``/whoami`` reports platform, scope, sender id, tier
and the exact command list.

Every clause is driven through a real entry point: the web ``/chat`` endpoint (the real
``Orchestrator.handle_input``), and the Telegram adapter (``TelegramChannel`` → ``Gateway``
→ ``Orchestrator.channel_handler`` → the channel session lifecycle → ``handle_input``).
Hermetic: a private settings store, a private audit log, no model.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agents.core import settings_db, slash_access
from agents.core.channels.gateway import Gateway
from agents.core.channels.group_policy import GroupPolicy
from agents.core.channels.telegram import TelegramChannel
from agents.core.commands import (
    ADMIN,
    USER,
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
)
from agents.core.memory.conversation import ConversationMemory
from agents.core.orchestrator import TURN_BUSY_REPLY, bind_turn_principal, reset_turn_principal
from agents.core.security.audit import AuditLogger

OWNER_ID, GUEST_ID, GROUP_CHAT = 42, 7, -500


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A private settings store; ``allow(value)`` writes ``commands.user_allowed_commands``."""
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)

    def allow(value=None, **other):
        values = {} if value is None else {slash_access.KEY: value}
        settings_db.put_category(slash_access.CATEGORY, {**values, **other})

    return allow


def _denials(audit: AuditLogger) -> list[dict]:
    return [json.loads(event.content_preview) for event in audit.query(event_type="audit_log")
            if event.action_taken == slash_access.AUDIT_ACTION]


async def _nothing(*_args, **_kwargs):
    return None


# ── the Telegram adapter, all the way to the registry ─────────────────────────────


class _Hub:
    """``TelegramChannel`` → ``Gateway.route`` → the real ``Orchestrator.channel_handler``,
    the real channel session lifecycle and the real ``handle_input`` up to the command
    plane (the model half is never reached: every message here is a command)."""

    def __init__(self, tmp_path):
        from tests.test_session_lifecycle_integration import host

        orch, cap, _clock = host(tmp_path)
        self.orch, self.cap = orch, cap
        orch._telegram_owner_settings = lambda: {"autonomy.owner_chat_id": "",
                                                 "autonomy.owner_user_ids": [OWNER_ID]}
        orch.commands = build_default_registry()
        orch.audit = AuditLogger(str(tmp_path / "audit.db"))
        orch.llm_router = SimpleNamespace(name="lm-studio")
        orch.agents = {}
        orch.checkpoints = SimpleNamespace(get_sessions=lambda limit=5: [])
        conversation = ConversationMemory(persist=False)
        memory = orch.memory

        async def new_session(session_id=None):
            conversation.sessions.setdefault(session_id, [])
            return session_id

        async def add_turn(sid, role, content, agent_id=None, *, channel=None, **kwargs):
            await conversation.add_turn(sid, role, content, agent_id, **kwargs)

        memory.new_session = new_session
        memory.conversation = conversation
        memory.add_turn = add_turn
        memory.get_history = lambda sid, last_n=None: conversation.get_history(sid)
        orch.__dict__.pop("handle_input")                     # the real handle_input from here on
        orch._resolve_session = lambda session_id: orch.session_id
        orch._guard_foreign_turn = _nothing
        orch._guard_media_history = _nothing
        orch._title_session = lambda text, channel: None
        orch._begin_chat_outcomes = lambda: None
        self.sent: list[tuple[int, str]] = []
        pairing = SimpleNamespace(is_allowed=lambda channel, sender: True,
                                  gate_inbound=lambda channel, sender, code=None: {"allowed": True})
        # Wired as agents/web.py wires the production hub.
        gateway = Gateway(handler=orch.channel_handler, pairing=pairing,
                          interrupt_handler=orch.interrupt_channel_message,
                          command_probe=orch.command_refused_here)
        channel = TelegramChannel(token="fake", allowed_user_ids=[OWNER_ID, GUEST_ID], pairing=pairing,
                                  group_policy=GroupPolicy(require_mention=False),
                                  pre_turn_interrupt=gateway.pre_lane_interrupt,
                                  pre_turn_refused=gateway.pre_lane_refused)
        channel.handler = gateway.route
        self.channel = channel
        orch.channels = {"telegram": channel}

        async def send(target, text, **kwargs):
            self.sent.append((kwargs.get("chat_id"), str(text)))
            return True

        orch.channel_manager = SimpleNamespace(send=send)

    async def say(self, text, *, user=GUEST_ID, chat=None, kind="private") -> str:
        """One Telegram update; the reply the hub sent back to that chat."""
        chat = user if chat is None else chat
        before = len(self.sent)
        await self.channel._handle_update({"message": {
            "message_id": 1, "from": {"id": user}, "chat": {"id": chat, "type": kind}, "text": text,
        }})
        replies = [reply for to, reply in self.sent[before:] if str(to) == str(chat)]
        return replies[-1] if replies else ""

    async def close(self):
        if self.channel._lanes is not None:
            await self.channel._lanes.settle()
        await self.channel.client.aclose()


@pytest.fixture
async def hub(tmp_path, store):
    hub = _Hub(tmp_path)
    yield hub
    await hub.close()


# ── the tiers, keyed by channel and scope ─────────────────────────────────────────


async def test_unconfigured_a_guest_runs_only_the_floor_and_never_an_owner_command(hub):
    """Fail closed, where Hermes fails open: until the owner sets the list, an admitted
    non-owner runs /help and /whoami and nothing else — in a DM and in a group."""
    for where in ({}, {"chat": GROUP_CHAT, "kind": "group"}):
        status = await hub.say("/status", **where)
        assert status.startswith("⛔ /status is admin-only here. You can run: /help, /whoami. "
                                 "Use /whoami for the full list.")
        assert "The owner can allow it in" in status and "commands.user_allowed_commands" in status
        assert (await hub.say("/whoami", **where)).splitlines()[-1] == "Slash commands you can run: /help, /whoami"
    denied = await hub.say("/pause")
    assert denied.startswith("⛔ /pause is admin-only here. You can run: /help, /whoami. ")
    assert "/pause is an owner command" in denied
    owner = await hub.say("/status", user=OWNER_ID)
    assert "backend lm-studio" in owner
    assert "backend lm-studio" in await hub.say("/status", user=OWNER_ID, chat=GROUP_CHAT, kind="group")


async def test_a_scope_the_owner_left_out_is_never_wider_than_the_one_restricted(hub, store):
    """Restricting the DM must not leave the less trusted group open: a scope nobody
    configured — for this channel or "*" — keeps only the floor."""
    store({"telegram": {"dm": ["status"]}})
    assert "backend lm-studio" in await hub.say("/status")
    group = await hub.say("/status", chat=GROUP_CHAT, kind="group")
    assert group.startswith("⛔ /status is admin-only here. You can run: /help, /whoami. ")
    registry = build_default_registry()
    group_guest = Principal(channel="telegram", sender=str(GUEST_ID), scope="group")
    assert slash_access.allowed_names(registry, group_guest) == ["help", "whoami"]
    other_channel = Principal(channel="discord", sender="9", scope="dm")
    assert slash_access.allowed_names(registry, other_channel) == ["help", "whoami"]


async def test_the_allowlist_is_keyed_separately_for_a_dm_and_a_group(hub, store):
    store({"telegram": {"dm": ["status"], "group": []}})
    assert "backend lm-studio" in await hub.say("/status")                         # DM: listed
    sessions = await hub.say("/sessions")                                          # DM: not listed
    assert sessions.startswith("⛔ /sessions is admin-only here. You can run: /help, /whoami, /status.")
    assert "commands.user_allowed_commands" in sessions and "owner command" not in sessions
    group = await hub.say("/status", chat=GROUP_CHAT, kind="group")                # group: empty list
    assert group.startswith("⛔ /status is admin-only here. You can run: /help, /whoami.")
    # The owner's tier is not keyed by scope: every command, in a group too.
    assert "backend lm-studio" in await hub.say("/status", user=OWNER_ID, chat=GROUP_CHAT, kind="group")


async def test_the_floor_is_help_and_whoami_and_no_setting_removes_it(hub, store):
    store({"*": {"dm": [], "group": []}})
    help_reply = await hub.say("/help")
    assert "/help — the commands you can use here" in help_reply and "/whoami" in help_reply
    assert "/status —" not in help_reply
    assert "Tier: user" in await hub.say("/whoami", chat=GROUP_CHAT, kind="group")
    assert (await hub.say("/status")).startswith("⛔ /status is admin-only here")


async def test_a_dm_list_left_unset_uses_the_same_channels_group_list_and_star_covers_the_rest(hub, store):
    store({"telegram": {"group": ["jobs"]}, "*": {"dm": ["status", "jobs"]}})
    assert (await hub.say("/status")).startswith("⛔ /status is admin-only here. You can run: /help, /whoami, /jobs.")
    assert "Scheduled jobs are not available" in await hub.say("/jobs")
    # Another channel with no entry of its own takes "*".
    registry = build_default_registry()
    discord_dm = Principal(channel="discord", sender="9", scope="dm")
    assert slash_access.allowed_names(registry, discord_dm) == ["help", "whoami", "jobs", "status"]
    # "*" sets no group list, so a Discord group keeps the floor only.
    assert slash_access.allowed_names(registry, Principal(channel="discord", sender="9", scope="group")) \
        == ["help", "whoami"]


async def test_no_list_grants_an_owner_command_and_a_broken_store_fails_closed(hub, store, monkeypatch):
    # A stored value that names an owner command (written past the Admin validation) is
    # ignored whole: the floor only, and /pause is still the owner's.
    store({"telegram": {"dm": ["status", "pause"]}})
    assert (await hub.say("/pause")).startswith("⛔ /pause is admin-only here. You can run: /help, /whoami.")
    assert (await hub.say("/status")).startswith("⛔ /status is admin-only here")

    def unreadable(category, key):
        raise settings_db.SettingsUnreadable("disk gone")

    store({})
    monkeypatch.setattr(settings_db, "read_setting", unreadable)
    assert (await hub.say("/status")).startswith("⛔ /status is admin-only here. You can run: /help, /whoami.")
    assert "You — telegram (DM)" in await hub.say("/whoami")


async def test_the_preview_shows_twelve_commands_then_points_at_whoami(store):
    store({"web": {"dm": [f"c{index:02d}" for index in range(15)]}})
    registry = CommandRegistry()
    registry.register(SlashCommand("help", "help", lambda ctx: "h"))
    registry.register(SlashCommand("whoami", "who", lambda ctx: "w"))
    for index in range(15):
        registry.register(SlashCommand(f"c{index:02d}", "x", lambda ctx: "ok"))
    registry.register(SlashCommand("boss", "owner", lambda ctx: "no", tier=ADMIN))
    outcome = await registry.dispatch("/boss", orch=None, principal=Principal(channel="web"))
    shown = outcome.reply.split("You can run: ", 1)[1].split(". Use /whoami", 1)[0]
    assert shown.split(", ")[:12] == ["/help", "/whoami", *[f"/c{i:02d}" for i in range(10)]]
    assert shown.endswith(", …") and "/c10" not in shown


# ── the audit log ─────────────────────────────────────────────────────────────────


async def test_every_denial_is_written_to_the_audit_log_not_only_emitted(hub, store, monkeypatch):
    from agents.core.extensions.events import EXTENSION_EVENTS

    store({"telegram": {"dm": ["status"], "group": []}})
    emitted = []
    monkeypatch.setattr(EXTENSION_EVENTS, "emit", lambda event, **fields: emitted.append((event, fields)))
    await hub.say("/pause")
    await hub.say("/status", chat=GROUP_CHAT, kind="group")
    await hub.say("/status")                                   # allowed: no row
    await hub.say("/usage", user=OWNER_ID)                     # the owner: no row
    # The extension event still goes out (name and status only) …
    assert ("command.completed", {"command": "pause", "status": "refused"}) in emitted
    # … and the audit log now has the denial itself: who, where, which command, why.
    rows = _denials(hub.orch.audit)
    assert sorted((row["command"], row["scope"], row["reason"]) for row in rows) == [
        ("pause", "dm", "owner_tier"), ("status", "group", "not_allowed")]
    assert all(row["channel"] == "telegram" and row["sender"] == str(GUEST_ID) and row["tier"] == "user"
               for row in rows)
    assert hub.orch.audit.verify_chain()[0] is True


# ── /whoami ───────────────────────────────────────────────────────────────────────


async def test_whoami_reports_platform_scope_sender_tier_and_the_exact_list(hub, store):
    store({"telegram": {"dm": ["status", "voice"], "group": ["status"]}})
    dm = await hub.say("/whoami")
    assert dm.splitlines() == [
        "You — telegram (DM)", f"Sender ID: {GUEST_ID}",
        "Tier: user — owner commands answer only the owner; commands.user_allowed_commands sets the rest",
        "Slash commands you can run: /help, /whoami, /status, /voice",
    ]
    group = await hub.say("/whoami", chat=GROUP_CHAT, kind="supergroup")
    assert group.splitlines()[0] == "You — telegram (group)"
    assert group.splitlines()[-1] == "Slash commands you can run: /help, /whoami, /status"
    owner = (await hub.say("/whoami", user=OWNER_ID)).splitlines()
    assert owner[:3] == ["You — telegram (DM)", f"Sender ID: {OWNER_ID}",
                         "Tier: admin (the owner) — every command answers you here"]
    listed = owner[3].removeprefix("Slash commands you can run: ").split(", ")
    assert listed == sorted(f"/{c.name}" for c in hub.orch.commands.commands())
    assert "/pause" in listed and "/whoami" in listed


def test_whoami_is_a_user_tier_command_in_the_default_registry():
    command = build_default_registry().get("whoami")
    assert command is not None and command.tier == USER
    assert slash_access.FLOOR == ("help", "whoami")


# ── the busy path ─────────────────────────────────────────────────────────────────


async def _while_busy(hub, text, *, user=GUEST_ID):
    """Send *text* while another turn holds this chat's route lease."""
    from agents.core.channels.session import SessionSource, build_session_key

    base = build_session_key(SessionSource(channel="telegram", sender=str(user), thread_id=str(user)))
    started, release = asyncio.Event(), asyncio.Event()

    async def hold():
        async with hub.orch.turn_lease(base) as held:
            assert held
            started.set()
            await release.wait()

    holder = asyncio.create_task(hold())
    await started.wait()
    try:
        return await asyncio.wait_for(hub.say(text, user=user), timeout=5)
    finally:
        release.set()
        await holder


async def test_a_denied_command_is_answered_at_once_while_a_turn_holds_the_route(hub, store, monkeypatch):
    from agents.core import code_interruptions

    store({"telegram": {"dm": ["status"]}})
    interrupts = []
    monkeypatch.setattr(code_interruptions, "interrupt", lambda sid: interrupts.append(sid) or False)
    hub.orch._turn_lease_max_wait = 30
    reply = await _while_busy(hub, "/sessions")
    assert reply.startswith("⛔ /sessions is admin-only here. You can run: /help, /whoami, /status.")
    assert reply != TURN_BUSY_REPLY and interrupts == []
    assert [row["command"] for row in _denials(hub.orch.audit)] == ["sessions"]


async def test_a_side_question_is_judged_on_the_busy_path_too(hub, store):
    store({"telegram": {"dm": ["status"]}})
    hub.orch._turn_lease_max_wait = 30
    reply = await _while_busy(hub, "/btw what did I ask?")
    assert reply.startswith("⛔ /btw is admin-only here. You can run: /help, /whoami, /status.")
    assert [row["command"] for row in _denials(hub.orch.audit)] == ["btw"]


async def _reply_to(hub, chat, before: int, *, timeout: float = 5) -> str:
    """The first reply the hub sent to *chat* after ``hub.sent[before]`` (waits for it)."""
    async def first():
        while True:
            replies = [reply for to, reply in hub.sent[before:] if str(to) == str(chat)]
            if replies:
                return replies[0]
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(first(), timeout)


async def test_a_refused_command_skips_the_telegram_chat_lane_while_that_chat_runs_a_turn(hub, store, monkeypatch):
    """The production busy path: the poll loop hands each chat's turns to its lane, so a
    command sent while that chat's turn runs would wait behind it. A command this sender
    may not run changes nothing — it is answered beside the lane, at once, audited, and it
    neither interrupts the running work nor waits for it; a command it may run still waits."""
    from agents.core import code_interruptions
    from agents.core.channels.chat_lanes import ChatLanes
    from agents.core.channels.session import SessionSource, build_session_key

    store({"telegram": {"dm": ["status"], "group": []}})
    interrupts = []
    monkeypatch.setattr(code_interruptions, "interrupt", lambda sid: interrupts.append(sid) or False)
    hub.orch._turn_lease_max_wait = 30
    hub.channel._lanes = ChatLanes(name="telegram")            # what the poll loop runs on
    base = build_session_key(SessionSource(channel="telegram", sender=str(GUEST_ID), thread_id=str(GUEST_ID)))
    started, release = asyncio.Event(), asyncio.Event()

    async def running_turn():
        async with hub.orch.turn_lease(base) as held:
            assert held
            started.set()
            await release.wait()

    hub.channel._lanes.submit(GUEST_ID, running_turn)
    await asyncio.wait_for(started.wait(), 5)
    try:
        before = len(hub.sent)
        await hub.say("/sessions")
        refused = await _reply_to(hub, GUEST_ID, before)
        assert refused.startswith("⛔ /sessions is admin-only here. You can run: /help, /whoami, /status.")
        assert not release.is_set() and interrupts == []
        assert [row["command"] for row in _denials(hub.orch.audit)] == ["sessions"]
        before = len(hub.sent)
        await hub.say("/status")                                 # allowed: it waits its turn
        await asyncio.sleep(0.2)
        assert [reply for to, reply in hub.sent[before:] if str(to) == str(GUEST_ID)] == []
    finally:
        release.set()
    assert "backend lm-studio" in await _reply_to(hub, GUEST_ID, before)


async def test_a_refused_discord_command_does_not_wait_behind_the_authors_running_turn(store):
    """Discord holds an author's next turn behind the one running in that channel (the
    batcher's key lock). A command the author may not run is handed over beside it, through
    the same Gateway probe the hub wires; one the author may run still waits its turn."""
    from agents.core.channels.discord import DiscordChannel
    from tests.test_slash_commands import _bare_orchestrator

    store({"discord": {"dm": ["status"]}})
    orch, _seen = _bare_orchestrator()
    gateway = Gateway(handler=None, command_probe=orch.command_refused_here)
    delivered, release = [], asyncio.Event()

    async def handler(text, **_kwargs):
        delivered.append(text)
        if text == "a long question":
            await release.wait()

    channel = DiscordChannel(token="fake", handler=handler, pre_turn_refused=gateway.pre_lane_refused)
    author = SimpleNamespace(id=7, bot=False)

    def message(text):
        return SimpleNamespace(author=author, channel=SimpleNamespace(id=900, parent_id=None),
                               guild=None, content=text, webhook_id=None, edited_at=None)

    running = asyncio.create_task(channel._handle_message(message("a long question")))
    while delivered != ["a long question"]:
        await asyncio.sleep(0.01)
    try:
        await asyncio.wait_for(channel._handle_message(message("/pause")), 5)
        assert delivered == ["a long question", "/pause"] and not release.is_set()
        allowed = asyncio.create_task(channel._handle_message(message("/status")))
        await asyncio.sleep(0.2)
        assert delivered == ["a long question", "/pause"]          # it waits its turn
    finally:
        release.set()
    await asyncio.wait_for(asyncio.gather(running, allowed), 5)
    assert delivered == ["a long question", "/pause", "/status"]


async def test_the_web_door_refuses_a_command_at_once_while_its_session_runs_a_turn(web_chat, store, monkeypatch):
    """``POST /chat`` and ``/chat/stream`` interrupt running work and then wait for the
    session's lease; a command the requester may not run is refused before either."""
    from agents.core import code_interruptions

    store({"web": {"dm": ["status"]}})
    interrupts = []
    monkeypatch.setattr(code_interruptions, "interrupt", lambda sid: interrupts.append(sid) or False)
    web_chat.orch._turn_lease_max_wait = 30
    started, release = asyncio.Event(), asyncio.Event()

    async def running_turn():
        async with web_chat.orch.turn_lease() as held:
            assert held
            started.set()
            await release.wait()

    holder = asyncio.create_task(running_turn())
    await asyncio.wait_for(started.wait(), 5)
    try:
        reply = await asyncio.wait_for(web_chat.chat("/sessions"), 5)
        assert reply.startswith("⛔ /sessions is admin-only here. You can run: /help, /whoami, /status.")
        streamed = await asyncio.wait_for(web_chat.stream("/pause"), 5)
        assert streamed.startswith("⛔ /pause is admin-only here") and "owner command" in streamed
        assert interrupts == [] and not release.is_set()
        assert web_chat.conversation.sessions["h058_web"] == []      # nothing was appended
    finally:
        release.set()
        await holder
    assert sorted(row["command"] for row in _denials(web_chat.orch.audit)) == ["pause", "sessions"]


async def test_a_refused_slack_command_does_not_hold_the_dispatcher_behind_the_members_turn(store):
    """Slack's batcher runs a member's turn on its timer while the event dispatcher keeps
    reading, and holds that member's next command behind the running turn — the dispatcher
    with it. A command the member may not run is handed over beside it through the same
    Gateway probe the hub wires (a ``D`` channel judged as a DM); one it may run still waits."""
    from agents.core.channels.slack import SlackChannel
    from tests.test_slash_commands import _bare_orchestrator

    store({"slack": {"dm": ["status"]}})
    orch, _seen = _bare_orchestrator()
    gateway = Gateway(handler=None, command_probe=orch.command_refused_here)
    delivered, release = [], asyncio.Event()

    async def handler(text, **_kwargs):
        delivered.append(text)
        if text == "a long question":
            await release.wait()

    channel = SlackChannel(token="fake", handler=handler, pre_turn_refused=gateway.pre_lane_refused)
    assert channel._batch.enabled                   # the default: batched, so a turn runs on a timer
    member = {"channel": "D0123", "user": "T0001:U0007"}
    await asyncio.wait_for(channel.receive_event("a long question", **member), 5)   # returns at once
    while delivered != ["a long question"]:
        await asyncio.sleep(0.01)
    try:
        await asyncio.wait_for(channel.receive_event("/pause", **member), 5)
        assert delivered == ["a long question", "/pause"] and not release.is_set()
        allowed = asyncio.create_task(channel.receive_event("/status", **member))
        await asyncio.sleep(0.2)
        assert delivered == ["a long question", "/pause"]          # it waits its turn
        # In a room the member's /status is not on the DM list: refused, so beside too.
        await asyncio.wait_for(channel.receive_event("/status", channel="C0456", user="T0001:U0007"), 5)
        assert delivered == ["a long question", "/pause", "/status"] and not release.is_set()
    finally:
        release.set()
    await asyncio.wait_for(allowed, 5)
    assert delivered == ["a long question", "/pause", "/status", "/status"]
    assert gateway.pre_lane_refused(channel="slack", sender="T0001:U0007", chat_id="D0123",
                                    text="/status") is False
    assert gateway.pre_lane_refused(channel="slack", sender="T0001:U0007", chat_id="C0456",
                                    text="/status") is True


async def test_a_busy_path_refusal_still_goes_out_as_the_command_completed_event(hub, web_chat, store, monkeypatch):
    """Extensions watching ``command.completed`` see a denial whether the registry answered
    it inside the turn or an entry path answered it beside a running one — name and status."""
    from agents.core.extensions.events import EXTENSION_EVENTS

    store({"telegram": {"dm": ["status"]}, "web": {"dm": ["status"]}})
    emitted = []
    monkeypatch.setattr(EXTENSION_EVENTS, "emit", lambda event, **fields: emitted.append((event, fields)))
    hub.orch._turn_lease_max_wait = 30
    assert (await _while_busy(hub, "/sessions")).startswith("⛔ /sessions is admin-only here")
    web_chat.orch._turn_lease_max_wait = 30
    started, release = asyncio.Event(), asyncio.Event()

    async def running_turn():
        async with web_chat.orch.turn_lease() as held:
            assert held
            started.set()
            await release.wait()

    holder = asyncio.create_task(running_turn())
    await asyncio.wait_for(started.wait(), 5)
    try:
        assert (await asyncio.wait_for(web_chat.chat("/jobs"), 5)).startswith("⛔ /jobs is admin-only here")
        assert (await asyncio.wait_for(web_chat.stream("/pause"), 5)).startswith("⛔ /pause is admin-only here")
    finally:
        release.set()
        await holder
    assert emitted == [("command.completed", {"command": "sessions", "status": "refused"}),
                       ("command.completed", {"command": "jobs", "status": "refused"}),
                       ("command.completed", {"command": "pause", "status": "refused"})]


async def test_a_side_question_on_a_route_with_no_conversation_is_judged_first(hub, store):
    """Whether this route has a conversation is not said to a sender who may not ask: the
    refusal comes first, audited, on a route nobody has written to yet."""
    store({"telegram": {"dm": ["status"]}})
    reply = await hub.say("/btw what did I ask?")
    assert reply.startswith("⛔ /btw is admin-only here. You can run: /help, /whoami, /status.")
    assert [row["command"] for row in _denials(hub.orch.audit)] == ["btw"]
    store({"telegram": {"dm": ["btw"]}})                       # allowed: the honest answer
    assert await hub.say("/btw what did I ask?") == "There is no conversation here to ask about yet."
    assert len(_denials(hub.orch.audit)) == 1


@pytest.mark.parametrize("pending_inputs", [False, True])
async def test_a_custom_reset_trigger_is_judged_as_the_owner_command_it_is(hub, store, pending_inputs):
    """``sessions.reset_triggers`` may name texts that are no registry command. A non-owner's
    is the same audited owner-command denial — under its own ``/name``, or ``/new`` (what it
    does) when it is not slash-shaped — on the conversation-change runtime and without it."""
    hub.orch._runtime_settings["sessions.reset_triggers"] = ["/fresh", "start over"]
    hub.orch._runtime_settings["channels.pending_inputs_enabled"] = pending_inputs
    fresh = await hub.say("/fresh")
    assert fresh.startswith("⛔ /fresh is admin-only here. You can run: /help, /whoami. ")
    assert "/fresh is an owner command" in fresh
    before = len(hub.sent)
    await hub.say("start over")                              # plain text: held for the batch window …
    await hub.channel._flush_all_turns()                     # … which the poll loop closes
    over = await _reply_to(hub, GUEST_ID, before)
    assert over.startswith("⛔ /new is admin-only here") and "/new is an owner command" in over
    assert sorted((row["command"], row["reason"]) for row in _denials(hub.orch.audit)) == [
        ("fresh", "owner_tier"), ("new", "owner_tier")]
    # A guest's custom trigger is refused beside a running turn too, never behind it.
    hub.orch._turn_lease_max_wait = 30
    assert (await _while_busy(hub, "/fresh")).startswith("⛔ /fresh is admin-only here")
    assert hub.orch.command_refused_here(channel="telegram", sender=str(GUEST_ID), chat_id=GUEST_ID,
                                         text="/fresh") is True
    assert hub.orch.command_refused_here(channel="telegram", sender=str(OWNER_ID), chat_id=OWNER_ID,
                                         text="/fresh") is False


@pytest.mark.parametrize("pending_inputs", [False, True])
async def test_a_reset_trigger_spelled_like_an_allowed_command_is_still_the_owners(hub, store, pending_inputs):
    """The owner may make a user-tier command's text a reset trigger (``/status``). On a
    channel that text resets the conversation, so a non-owner whose list allows ``/status``
    gets the audited owner-command denial — not the session lifecycle's bare refusal, which
    has no ⛔ line and writes no audit row — and the denial does not offer ``/status`` back.
    The pre-lane probe and the busy path say the same; any other text still runs it."""
    store({"telegram": {"dm": ["status"]}})
    hub.orch._runtime_settings["sessions.reset_triggers"] = ["/new", "/reset", "/status"]
    hub.orch._runtime_settings["channels.pending_inputs_enabled"] = pending_inputs
    refused = await hub.say("/status")
    assert refused.startswith("⛔ /status is admin-only here. You can run: /help, /whoami. "), refused
    assert "/status is an owner command" in refused
    assert [(row["command"], row["reason"]) for row in _denials(hub.orch.audit)] == [("status", "owner_tier")]
    assert hub.orch.command_refused_here(channel="telegram", sender=str(GUEST_ID), chat_id=GUEST_ID,
                                         text="/status") is True
    assert hub.orch.command_refused_here(channel="telegram", sender=str(OWNER_ID), chat_id=OWNER_ID,
                                         text="/status") is False
    hub.orch._turn_lease_max_wait = 30
    assert (await _while_busy(hub, "/status")).startswith("⛔ /status is admin-only here")
    assert len(_denials(hub.orch.audit)) == 2
    # Not the exact trigger text: the user-tier command the list allows, with no audit row.
    assert "backend lm-studio" in await hub.say("/status now")
    assert len(_denials(hub.orch.audit)) == 2


# ── the floor wins over every reset trigger ───────────────────────────────────────


#: The floor as a guest may type it: any casing, the bot's ``@name``, arguments.
FLOOR_SPELLINGS = ("/help", "/HELP", "/Help@NervaBot", "/whoami", "/WhoAmI", "/whoami@NervaBot", "/help me")


def test_the_settings_write_refuses_a_floor_command_as_a_reset_trigger(tmp_path, monkeypatch, store):
    """``/help`` and ``/whoami`` answer every sender, so the Admin settings write refuses
    either — in any casing, with a ``@bot`` suffix or arguments — as a
    ``sessions.reset_triggers`` text, with an error that names the floor, and keeps the
    stored value. A user-tier command's text (``/status``) is still the owner's to use."""
    from fastapi.testclient import TestClient

    import agents.web as web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "h058-settings-token")
    client = TestClient(web.app)
    headers = {"X-Admin-Token": "h058-settings-token"}

    def put(triggers):
        return client.put("/api/admin/settings/sessions", json={"values": {"reset_triggers": triggers}},
                          headers=headers)

    assert put(["/new", "/reset", "/status", "start over"]).status_code == 200
    for floor in FLOOR_SPELLINGS:
        response = put(["/new", "/reset", floor])
        assert response.status_code == 422, floor
        name = "help" if "help" in floor.lower() else "whoami"
        assert response.json()["details"] == [
            f"reset_triggers: {floor!r} is /{name} — /help and /whoami answer every sender and no "
            "setting takes them away, so neither can be a reset trigger"], floor
    assert settings_db.get_value("sessions", "reset_triggers") == ["/new", "/reset", "/status", "start over"]


@pytest.mark.parametrize("pending_inputs", [False, True])
async def test_a_stored_floor_reset_trigger_never_takes_help_or_whoami_away(hub, store, pending_inputs):
    """A value stored before the settings write refused it still names the floor. On a
    channel the floor wins: a guest's /help and /whoami, in every spelling, answer — no
    ⛔ line, no audit row, no reset — the pre-lane probe and the busy path agree, and the
    owner's /help is /help too, not a new conversation."""
    from agents.core.channels.session_lifecycle import RESET_ACK, reset_triggered

    settings_db.put_category("sessions", {"reset_triggers": ["/new", "/reset", *FLOOR_SPELLINGS]})
    hub.orch._runtime_settings["sessions.reset_triggers"] = settings_db.get_value("sessions", "reset_triggers")
    hub.orch._runtime_settings["channels.pending_inputs_enabled"] = pending_inputs
    for text in FLOOR_SPELLINGS:
        reply = await hub.say(text)
        if "help" in text.lower():
            assert "/help — the commands you can use here" in reply, (text, reply)
        else:
            assert reply.splitlines()[:2] == ["You — telegram (DM)", f"Sender ID: {GUEST_ID}"], (text, reply)
        assert hub.orch.command_refused_here(channel="telegram", sender=str(GUEST_ID), chat_id=GUEST_ID,
                                             text=text) is False, text
    owner = await hub.say("/HELP", user=OWNER_ID)
    assert owner != RESET_ACK and "/pause" in owner
    hub.orch._turn_lease_max_wait = 0.01
    assert await _while_busy(hub, "/help") == TURN_BUSY_REPLY      # waits its turn, never refused
    assert _denials(hub.orch.audit) == []
    # The real triggers in the same stored value still are triggers; without the
    # conversation-change runtime the owner's /new resets (the channel's rate limit allows
    # ten messages here, so this is the last one).
    assert [reset_triggered(hub.orch.get_setting, text) for text in ("/new", "/reset", *FLOOR_SPELLINGS)] \
        == [True, True] + [False] * len(FLOOR_SPELLINGS)
    if not pending_inputs:
        assert await hub.say("/new", user=OWNER_ID) == RESET_ACK


async def test_whoami_lists_only_what_the_channel_will_run(hub, web_chat, store):
    """The owner made the user-tier ``/status`` a reset trigger: on a channel a guest's
    ``/status`` is refused as the owner command it is, so /whoami, /help and a denial's
    "You can run" stop offering it there. The web door judges no reset trigger, so it
    still lists and runs it."""
    store({"telegram": {"dm": ["status", "sessions"]}, "web": {"dm": ["status", "sessions"]}})
    hub.orch._runtime_settings["sessions.reset_triggers"] = ["/new", "/reset", "/status"]
    whoami = await hub.say("/whoami")
    assert whoami.splitlines()[-1] == "Slash commands you can run: /help, /whoami, /sessions"
    help_lines = (await hub.say("/help")).splitlines()
    assert [line.split(" —")[0] for line in help_lines if line.startswith("/")] == ["/help", "/sessions", "/whoami"]
    assert (await hub.say("/status")).startswith(
        "⛔ /status is admin-only here. You can run: /help, /whoami, /sessions. ")
    assert (await hub.say("/recap")).startswith(
        "⛔ /recap is admin-only here. You can run: /help, /whoami, /sessions. ")
    # Unreadable triggers: the channel then answers only the floor, and says so.
    from agents.core.channels.session_lifecycle import UNAVAILABLE

    hub.orch._runtime_settings["sessions.reset_triggers"] = "not a list"
    assert (await hub.say("/whoami")).splitlines()[-1] == "Slash commands you can run: /help, /whoami"
    assert await hub.say("/sessions") == UNAVAILABLE
    web_chat.orch.get_setting = lambda key, default=None: (
        ["/new", "/reset", "/status"] if key == "sessions.reset_triggers" else default)
    assert (await web_chat.chat("/whoami")).splitlines()[-1] == \
        "Slash commands you can run: /help, /whoami, /sessions, /status"
    assert "backend lm-studio" in await web_chat.chat("/status")


# ── quick commands are judged again, on the raw typed name ─────────────────────────


async def test_a_quick_command_is_gated_on_its_raw_name_and_its_alias_target_again(hub, store, monkeypatch):
    store(quick_commands={"deploy": {"type": "exec", "command": "echo deploy"},
                          "st": {"type": "alias", "target": "/status"}})
    denied = await hub.say("/deploy")
    assert denied.startswith("⛔ /deploy is admin-only here. You can run: /help, /whoami. ")
    assert "/deploy is an owner command" in denied
    assert [(row["command"], row["reason"]) for row in _denials(hub.orch.audit)] == [("deploy", "owner_tier")]
    asked = []
    original = slash_access.refusal

    async def spy(registry, name, **kwargs):
        asked.append((name, kwargs.get("quick", False)))
        return await original(registry, name, **kwargs)

    monkeypatch.setattr(slash_access, "refusal", spy)
    owner = await hub.say("/st", user=OWNER_ID)
    assert "backend lm-studio" in owner
    assert asked == [("st", True), ("status", False)]   # the raw quick name, then the alias target


# ── the web chat door ─────────────────────────────────────────────────────────────


@pytest.fixture
def web_chat(tmp_path, monkeypatch, store):
    """The real ``POST /chat`` handler over a real ``Orchestrator.handle_input``."""
    from starlette.requests import Request

    import agents.core.orchestrator as module
    from agents import web
    from agents.core.orchestrator import Orchestrator
    from agents.core.security.token_store import TokenStore
    from tests.h441_native_fixture import bind_native

    token = module._active_session.set(module._SESSION_UNSET)
    shared = module._session_is_shared.set(None)
    conversation = ConversationMemory(persist=False)
    conversation.sessions["h058_web"] = []
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "h058_web"
    bind_native(orch, monkeypatch, session_ids=("h058_web",))

    async def add_turn(sid, role, content, agent_id=None, *, channel=None, **kwargs):
        await conversation.add_turn(sid, role, content, agent_id, **kwargs)

    orch.memory = SimpleNamespace(conversation=conversation, add_turn=add_turn,
                                  get_history=conversation.get_history)
    orch.commands = build_default_registry()
    orch.get_setting = lambda key, default=None: default
    orch.llm_router = SimpleNamespace(name="lm-studio")
    orch.agents = {}
    orch.audit = AuditLogger(str(tmp_path / "web-audit.db"))
    orch._title_session = lambda text, channel: None
    orch._begin_chat_outcomes = lambda: None
    monkeypatch.setattr(module, "_begin_project_context", _nothing)
    monkeypatch.setenv("JARVIS_KEEP_AWAKE", "0")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "h058-owner-token")
    token_store = TokenStore(str(tmp_path / "tokens.sqlite3"))
    monkeypatch.setattr(web, "get_token_store", lambda: token_store)
    monkeypatch.setattr(web, "orch", orch)

    async def chat(message, *, owner=False):
        headers = [(b"x-admin-token", b"h058-owner-token")] if owner else []
        request = Request({"type": "http", "method": "POST", "path": "/chat", "headers": headers,
                           "client": ("10.0.0.9", 43123), "scheme": "http"})
        return (await web.chat(web.ChatRequest(message=message), request)).reply

    async def stream(message):
        """The text of the ``end`` event ``POST /chat/stream`` sends (no admin token)."""
        request = Request({"type": "http", "method": "POST", "path": "/chat/stream", "headers": [],
                           "client": ("10.0.0.9", 43123), "scheme": "http"})
        response = await web.chat_stream(web.ChatRequest(message=message), request)
        async for chunk in response.body_iterator:
            event = json.loads(chunk.removeprefix("data: "))
            if event["type"] == "end":
                return event["text"]
        raise AssertionError("the stream ended without an end event")

    yield SimpleNamespace(chat=chat, stream=stream, orch=orch, conversation=conversation)
    orch.checkpoints.close()
    module._active_session.reset(token)
    module._session_is_shared.reset(shared)


async def test_the_web_chat_door_takes_the_same_gate_on_the_cold_path(web_chat, store):
    store({"web": {"dm": ["status"]}})
    assert "backend lm-studio" in await web_chat.chat("/status")
    sessions = await web_chat.chat("/sessions")
    assert sessions.startswith("⛔ /sessions is admin-only here. You can run: /help, /whoami, /status.")
    pause = await web_chat.chat("/pause")
    assert pause.startswith("⛔ /pause is admin-only here") and "owner command" in pause
    whoami = await web_chat.chat("/whoami")
    assert whoami.splitlines()[0] == "You — web (DM)"
    assert whoami.splitlines()[-1] == "Slash commands you can run: /help, /whoami, /status"
    assert "Tier: admin" in await web_chat.chat("/whoami", owner=True)
    assert not (await web_chat.chat("/sessions", owner=True)).startswith("⛔")   # the owner: every command
    assert sorted((row["command"], row["channel"], row["scope"], row["sender"])
                  for row in _denials(web_chat.orch.audit)) == [
        ("pause", "web", "dm", None), ("sessions", "web", "dm", None)]


async def test_a_guests_conversation_change_and_checkpoint_commands_get_the_audited_refusal(web_chat):
    for text in ("/new", "/rollback older"):
        reply = await web_chat.chat(text)
        assert reply.startswith(f"⛔ {text.split()[0]} is admin-only here") and "owner command" in reply
    assert sorted(row["command"] for row in _denials(web_chat.orch.audit)) == ["new", "rollback"]


# ── owner-configurable through the Admin settings ─────────────────────────────────


def test_the_admin_settings_route_round_trips_and_refuses_what_the_gate_cannot_honour(tmp_path, monkeypatch, store):
    from fastapi.testclient import TestClient

    import agents.web as web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "h058-settings-token")
    client = TestClient(web.app)
    headers = {"X-Admin-Token": "h058-settings-token"}
    value = {"telegram": {"dm": ["/status", "voice"], "group": []}, "*": {"dm": ["help"]}}
    assert client.put("/api/admin/settings/commands", json={"values": {slash_access.KEY: value}},
                      headers=headers).status_code == 200
    assert settings_db.get_value("commands", slash_access.KEY) == value
    for bad in ({"telegram": {"dm": ["pause"]}},           # an owner command
                {"telegram": {"dms": ["status"]}},         # an unknown scope
                {"Tele gram": {"dm": ["status"]}},         # not a channel name
                {"telegram": {"dm": ["not a command"]}},
                {"telegram": {"dm": "status"}},
                ["status"]):
        response = client.put("/api/admin/settings/commands", json={"values": {slash_access.KEY: bad}},
                              headers=headers)
        assert response.status_code == 422, bad
    assert settings_db.get_value("commands", slash_access.KEY) == value


def test_the_settings_key_is_declared_with_an_empty_default():
    row = next(r for r in settings_db.DEFAULTS
               if (r["category"], r["key"]) == (slash_access.CATEGORY, slash_access.KEY))
    assert row["value"] == {} and row["kind"] == "json"
    assert "/help and /whoami always" in row["label"]


# ── in front of the kernel, never instead of it ───────────────────────────────────


async def test_the_gate_only_lets_a_command_reach_its_handler_the_handler_still_governs(store):
    """Not listed, /recap never reaches its handler; listed, it reaches it — and an allowed
    command still answers only through its own guards: a guest allowed /recap on the
    owner's shared session is refused by /recap itself, as before."""
    registry = build_default_registry()
    reached = []

    async def history(*_a, **_k):
        raise AssertionError("the shared session must not be read for a guest")

    def shared():
        reached.append(True)
        return True

    orch = SimpleNamespace(commands=registry, on_shared_session=shared,
                           memory=SimpleNamespace(get_history=history), session_id="shared")
    store({"*": {"dm": []}})
    gated = await registry.dispatch("/recap", orch=orch, principal=Principal(channel="widget"))
    assert gated.status == "refused" and gated.reply.startswith("⛔ /recap is admin-only here")
    assert reached == []                                   # the handler was never reached
    store({"*": {"dm": ["recap"]}})
    outcome = await registry.dispatch("/recap", orch=orch, principal=Principal(channel="widget"))
    assert outcome.status == "answered" and "owner" in outcome.reply and reached == [True]


async def test_the_principal_scope_follows_the_adapters_chat_type():
    from tests.test_slash_commands import _bare_orchestrator

    orch, seen = _bare_orchestrator()
    await orch.channel_handler("/status", channel="telegram", chat_id=GROUP_CHAT, sender="7",
                               chat_type="supergroup")
    assert seen["principal"].scope == "group"
    await orch.channel_handler("/status", channel="telegram", chat_id=7, sender="7")
    assert seen["principal"].scope == "dm"
    assert orch._channel_principal("slack", "T1:U1", None, orch._principal_chat_type(
        "slack", {"slack_channel": "D123"})).scope == "dm"
    assert orch._channel_principal("slack", "T1:U1", None, orch._principal_chat_type(
        "slack", {"slack_channel": "C123", "thread_ts": "1.2"})).scope == "group"
    assert orch._channel_principal("discord", "9", None, "thread").scope == "group"
    # The webhook channels report the chat type their provider states.
    from agents.core.channels.webhook_channels import GoogleChatChannel, SignalChannel, TeamsChannel

    def scope(adapter, payload):
        return orch._channel_principal(adapter.channel_id, "u", None, orch._principal_chat_type(
            adapter.channel_id, adapter.parse_inbound(payload))).scope

    teams = {"text": "/status", "from": {"id": "u1"}, "conversation": {"id": "c1"}}
    assert scope(TeamsChannel(), {**teams, "conversation": {"id": "c1", "conversationType": "personal"}}) == "dm"
    assert scope(TeamsChannel(), {**teams, "conversation": {"id": "c1", "conversationType": "groupChat"}}) == "group"
    assert scope(TeamsChannel(), {**teams, "conversation": {"id": "c1", "conversationType": "channel"}}) == "group"
    chat = {"message": {"text": "/status", "sender": {"name": "users/1"}}}
    assert scope(GoogleChatChannel(), {**chat, "space": {"name": "spaces/1", "spaceType": "DIRECT_MESSAGE"}}) == "dm"
    assert scope(GoogleChatChannel(), {**chat, "space": {"name": "spaces/1", "type": "ROOM"}}) == "group"
    assert scope(GoogleChatChannel(), {**chat, "space": {"name": "spaces/1", "spaceType": "SPACE"}}) == "group"
    signal = {"envelope": {"source": "+1555", "dataMessage": {"message": "/status"}}}
    assert scope(SignalChannel(), signal) == "dm"
    assert scope(SignalChannel(), {"envelope": {"source": "+1555", "dataMessage": {
        "message": "/status", "groupInfo": {"groupId": "g1"}}}}) == "group"
    # WhatsApp's Cloud API names the group a participant wrote in.
    from agents.core.channels.webhook_channels import MatrixChannel, WhatsAppChannel

    def whatsapp(**extra):
        return {"entry": [{"changes": [{"value": {"messages": [
            {"from": "40700000000", "type": "text", "text": {"body": "/status"}, **extra}]}}]}]}

    assert scope(WhatsAppChannel(), whatsapp()) == "dm"
    assert scope(WhatsAppChannel(), whatsapp(group_id="120363000000000000")) == "group"
    # A Matrix room event never says whether its room is a DM: the less trusted scope.
    matrix = {"events": [{"type": "m.room.message", "sender": "@u:hs", "room_id": "!r:hs",
                          "content": {"body": "/status"}}]}
    assert scope(MatrixChannel(), matrix) == "group"
    assert orch._channel_principal("matrix", "@u:hs", None, orch._principal_chat_type(
        "matrix", {"room_id": "!r:hs", "chat_type": "private"})).scope == "dm"
    token = bind_turn_principal(Principal(channel="web"))
    try:
        assert (await orch._slash_access_denial("hello there")) is None
        assert (await orch._slash_access_denial("/frobnicate")) is None   # unknown: not judged
    finally:
        reset_turn_principal(token)



class _Homeserver:
    """The Matrix adapter's injected transport, standing in for the homeserver: who this
    bot is, and each room's member events (``None`` = the request fails)."""

    BOT = "@nerva:hs.example"

    def __init__(self):
        self.rooms: dict[str, list | None] = {}
        self.calls: list[str] = []
        self.status = 200

    @staticmethod
    def member(user, membership="join"):
        return {"type": "m.room.member", "state_key": user, "content": {"membership": membership}}

    async def request(self, method, url, headers=None, json=None):
        from urllib.parse import unquote

        assert method == "GET" and headers == {"Authorization": "Bearer matrix-token"}
        self.calls.append(url)
        path = url.removeprefix("https://hs.example/_matrix/client/v3/")
        if path == "account/whoami":
            body = {"user_id": self.BOT}
        else:
            room, _, rest = path.removeprefix("rooms/").partition("/")
            assert rest == "members?not_membership=leave"
            events = self.rooms[unquote(room)]
            if events is None:
                raise OSError("homeserver unreachable")
            body = {"chunk": events}
        return SimpleNamespace(status_code=self.status, json=lambda: body)


async def test_a_matrix_room_is_a_dm_only_when_the_homeserver_proves_it(hub, store):
    """A Matrix room event never says whether its room is a DM. For a command, the adapter
    asks the homeserver it already sends through: a room whose members are exactly the
    sender and this bot, both joined, is a DM, so the DM list applies; a third member —
    joined or only invited — an unreachable or erroring homeserver, and an adapter with no
    homeserver configured are all judged as a group, the less trusted scope. Plain chat is
    never looked up, and this bot's own id is read once."""
    from agents.core.channels.webhook_channels import MatrixChannel

    store({"matrix": {"dm": ["status"], "group": []}})
    homeserver = _Homeserver()
    guest, bot = "@guest:hs.example", _Homeserver.BOT
    homeserver.rooms = {
        "!dm:hs.example": [homeserver.member(guest), homeserver.member(bot),
                           homeserver.member("@gone:hs.example", "leave")],
        "!trio:hs.example": [homeserver.member(guest), homeserver.member(bot),
                             homeserver.member("@third:hs.example")],
        "!invite:hs.example": [homeserver.member(guest), homeserver.member(bot),
                               homeserver.member("@later:hs.example", "invite")],
        "!down:hs.example": None,
    }
    pairing = SimpleNamespace(is_allowed=lambda channel, sender: True,
                              gate_inbound=lambda channel, sender, code=None: {"allowed": True})
    gateway = Gateway(handler=hub.orch.channel_handler, pairing=pairing)
    matrix = MatrixChannel(handler=gateway.route, transport=homeserver,
                           config={"homeserver": "https://hs.example", "token": "matrix-token"})

    async def say(room, text, adapter=matrix):
        return await adapter.handle_inbound({"events": [{
            "type": "m.room.message", "sender": guest, "room_id": room, "content": {"body": text}}]})

    assert "backend lm-studio" in await say("!dm:hs.example", "/status")
    assert (await say("!dm:hs.example", "/whoami")).startswith("You — matrix (DM)")
    assert _denials(hub.orch.audit) == []
    for room in ("!trio:hs.example", "!invite:hs.example", "!down:hs.example"):
        refused = await say(room, "/status")
        assert refused.startswith("⛔ /status is admin-only here. You can run: /help, /whoami. "), room
        assert "allow it in a group here" in refused
    homeserver.status = 403
    assert (await say("!dm:hs.example", "/status")).startswith("⛔ /status is admin-only here")
    unconfigured = MatrixChannel(handler=gateway.route, transport=homeserver)
    calls = len(homeserver.calls)
    assert (await say("!dm:hs.example", "/status", unconfigured)).startswith("⛔ /status is admin-only here")
    assert len(homeserver.calls) == calls                      # nothing to ask, nothing asked
    assert [(row["command"], row["scope"]) for row in _denials(hub.orch.audit)] == [("status", "group")] * 5
    # One whoami for this adapter; one membership read per command; none for plain chat.
    assert [url.rsplit("/", 1)[-1] for url in homeserver.calls].count("whoami") == 1
    assert len(homeserver.calls) == 1 + 6
    homeserver.status = 200
    enriched = await matrix.enrich_inbound({"text": "hello there", "sender": guest, "room_id": "!dm:hs.example"})
    assert "chat_type" not in enriched and len(homeserver.calls) == 7
    # A room id from the payload never leaves its path segment.
    assert "chat_type" not in await matrix.enrich_inbound(
        {"text": "/status", "sender": guest, "room_id": "../../admin"})
    assert len(homeserver.calls) == 7
    assert "rooms/%21dm%3Ahs.example/members" in homeserver.calls[1]


# ── the gate answers before any input or configuration check ─────────────────────


async def test_a_guests_oversized_owner_command_gets_the_audited_denial_not_a_length_reply(hub, web_chat, store):
    """``/kanban``, ``/goal``, ``/subgoal`` and the checkpoint commands refuse a text over the
    2,000-character cap. For a non-owner that check must not answer first: it would say
    nothing about access and write no audit row, so a stranger probing owner commands with
    long arguments would leave no trace. The owner's oversized command keeps its reply."""
    probes = {"kanban": "x", "goal": "y", "subgoal": "s", "rollback": "r", "checkpoints": "c"}
    for name, filler in probes.items():
        reply = await hub.say(f"/{name} " + filler * 2100)
        assert reply.startswith(f"⛔ /{name} is admin-only here. You can run: /help, /whoami. "), reply
        assert f"/{name} is an owner command" in reply and "too long" not in reply
    assert sorted((row["command"], row["reason"]) for row in _denials(hub.orch.audit)) == sorted(
        (name, "owner_tier") for name in probes)
    web = await web_chat.chat("/goal " + "z" * 2100)
    assert web.startswith("⛔ /goal is admin-only here") and "longer than" not in web
    assert [(row["command"], row["channel"]) for row in _denials(web_chat.orch.audit)] == [("goal", "web")]
    # The owner is let through, and only then does the input check answer (no audit row).
    assert await hub.say("/kanban " + "x" * 2100, user=OWNER_ID) == "Kanban command is too long; nothing changed."
    assert await web_chat.chat("/goal " + "z" * 2100, owner=True) == (
        "/goal is longer than 2000 characters; nothing was proposed or added.")
    assert len(_denials(hub.orch.audit)) == len(probes) and len(_denials(web_chat.orch.audit)) == 1


async def test_the_registry_judges_access_before_the_length_check_for_every_capped_command(store, monkeypatch):
    """The same order straight on ``CommandRegistry.dispatch`` (the cold path every entry
    path reaches), with the denial observed as ``command.completed``."""
    from agents.core.extensions.events import EXTENSION_EVENTS

    registry = build_default_registry()
    emitted = []
    monkeypatch.setattr(EXTENSION_EVENTS, "emit", lambda event, **fields: emitted.append((event, fields)))
    capped = ("kanban", "goal", "subgoal", "rollback", "checkpoints")
    for name in capped:
        outcome = await registry.dispatch(f"/{name} " + "q" * 2100, orch=None,
                                          principal=Principal(channel="widget"))
        assert outcome.status == "refused" and outcome.reply.startswith(f"⛔ /{name} is admin-only here")
    assert emitted == [("command.completed", {"command": name, "status": "refused"}) for name in capped]


async def test_a_malformed_quick_command_store_answers_a_guest_with_the_denial_first(hub, store):
    """A stored ``commands.quick_commands`` value that fails validation (written past the
    Admin check) makes the owner's ``/deploy`` say the configuration is invalid. A non-owner
    must get the audited denial instead — on the cold path and beside a running turn — and
    never a reply about the owner's store."""
    store(quick_commands={"deploy": {"type": "exec"}})          # no command: malformed
    denied = await hub.say("/deploy")
    assert denied.startswith("⛔ /deploy is admin-only here. You can run: /help, /whoami. ")
    assert "/deploy is an owner command" in denied and "configuration" not in denied
    assert [(row["command"], row["reason"]) for row in _denials(hub.orch.audit)] == [("deploy", "owner_tier")]
    assert await hub.say("/deploy", user=OWNER_ID) == "Invalid quick-command configuration; nothing changed."
    # The pre-lane probe and the busy path see the stored name too.
    assert hub.orch.command_refused_here(channel="telegram", sender=str(GUEST_ID), chat_id=GUEST_ID,
                                         text="/deploy") is True
    assert hub.orch.command_refused_here(channel="telegram", sender=str(OWNER_ID), chat_id=OWNER_ID,
                                         text="/deploy") is False
    hub.orch._turn_lease_max_wait = 30
    assert (await _while_busy(hub, "/deploy")).startswith("⛔ /deploy is admin-only here")
    # A name the store does not hold is still an unknown command, with no audit row.
    assert (await hub.say("/nothing")).startswith("Unknown command /nothing")
    assert len(_denials(hub.orch.audit)) == 2


# ── refused beside the running work, whatever shape the command has ───────────────


async def test_a_guests_plain_text_reset_trigger_skips_the_telegram_chat_lane(hub, store):
    """A custom ``sessions.reset_triggers`` text need not start with ``/``. A non-owner's is
    refused beside the chat's running turn, like any other command it may not run — not
    queued behind it until that turn ends."""
    from agents.core.channels.chat_lanes import ChatLanes
    from agents.core.channels.session import SessionSource, build_session_key

    hub.orch._runtime_settings["sessions.reset_triggers"] = ["/new", "/reset", "start over"]
    hub.orch._turn_lease_max_wait = 30
    hub.channel._lanes = ChatLanes(name="telegram")
    base = build_session_key(SessionSource(channel="telegram", sender=str(GUEST_ID), thread_id=str(GUEST_ID)))
    started, release = asyncio.Event(), asyncio.Event()

    async def running_turn():
        async with hub.orch.turn_lease(base) as held:
            assert held
            started.set()
            await release.wait()

    hub.channel._lanes.submit(GUEST_ID, running_turn)
    await asyncio.wait_for(started.wait(), 5)
    try:
        before = len(hub.sent)
        await hub.say("start over")                              # held for the batch window …
        await hub.channel._flush_all_turns()                     # … which the poll loop closes
        refused = await _reply_to(hub, GUEST_ID, before)
        assert refused.startswith("⛔ /new is admin-only here") and "/new is an owner command" in refused
        assert not release.is_set()
        assert [(row["command"], row["reason"]) for row in _denials(hub.orch.audit)] == [("new", "owner_tier")]
    finally:
        release.set()
    # Plain chat is never judged a command: the probe says no.
    assert hub.orch.command_refused_here(channel="telegram", sender=str(GUEST_ID), chat_id=GUEST_ID,
                                         text="how are you") is False


async def test_a_refused_telegram_command_never_waits_behind_a_running_side_question(hub, store):
    """A ``/btw`` runs beside the chat's lane, on a lane of its own, while its auxiliary
    model call lasts. A refused command is handed over beside the lane too — on yet another
    lane, so it is answered at once and not after that model call."""
    from agents.core.channels.chat_lanes import ChatLanes

    store({"telegram": {"dm": ["status"]}})
    hub.channel._lanes = ChatLanes(name="telegram")
    started, release = asyncio.Event(), asyncio.Event()

    async def side_question_model_call():
        started.set()
        await release.wait()

    hub.channel._lanes.submit(("side-question", GUEST_ID), side_question_model_call)
    await asyncio.wait_for(started.wait(), 5)
    try:
        before = len(hub.sent)
        await hub.say("/sessions")
        refused = await _reply_to(hub, GUEST_ID, before)
        assert refused.startswith("⛔ /sessions is admin-only here. You can run: /help, /whoami, /status.")
        assert not release.is_set()
    finally:
        release.set()
    assert [row["command"] for row in _denials(hub.orch.audit)] == ["sessions"]


async def test_a_guests_plain_text_reset_trigger_does_not_wait_behind_the_discord_authors_turn(store):
    """The batcher Discord and Slack share asks the hub for plain text too, so a custom reset
    trigger that is no ``/command`` is handed over beside the author's running turn."""
    from agents.core.channels.discord import DiscordChannel
    from tests.test_slash_commands import _bare_orchestrator

    orch, _seen = _bare_orchestrator()
    orch._runtime_settings["sessions.reset_triggers"] = ["/new", "/reset", "start over"]
    gateway = Gateway(handler=None, command_probe=orch.command_refused_here)
    delivered, release = [], asyncio.Event()

    async def handler(text, **_kwargs):
        delivered.append(text)
        if text == "a long question":
            await release.wait()

    channel = DiscordChannel(token="fake", handler=handler, pre_turn_refused=gateway.pre_lane_refused)
    author = SimpleNamespace(id=7, bot=False)

    def message(text):
        return SimpleNamespace(author=author, channel=SimpleNamespace(id=900, parent_id=None),
                               guild=None, content=text, webhook_id=None, edited_at=None)

    running = asyncio.create_task(channel._handle_message(message("a long question")))
    while delivered != ["a long question"]:
        await asyncio.sleep(0.01)
    try:
        await asyncio.wait_for(channel._handle_message(message("start over")), 5)
        assert delivered == ["a long question", "start over"] and not release.is_set()
    finally:
        release.set()
    await asyncio.wait_for(running, 5)
    assert gateway.pre_lane_refused(channel="discord", sender="7", chat_id=900, text="how are you") is False
