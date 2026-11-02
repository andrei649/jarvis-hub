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
        gateway = Gateway(handler=orch.channel_handler, pairing=pairing,
                          interrupt_handler=orch.interrupt_channel_message)
        channel = TelegramChannel(token="fake", allowed_user_ids=[OWNER_ID, GUEST_ID], pairing=pairing,
                                  group_policy=GroupPolicy(require_mention=False),
                                  pre_turn_interrupt=gateway.pre_lane_interrupt)
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


async def test_unconfigured_a_guest_keeps_the_user_tier_and_never_an_owner_command(hub):
    status = await hub.say("/status")
    assert "backend lm-studio" in status
    denied = await hub.say("/pause")
    assert denied.startswith("⛔ /pause is admin-only here. You can run: /help, /whoami, ")
    assert "/status" in denied and "Use /whoami for the full list." in denied
    assert "/pause is an owner command" in denied
    owner = await hub.say("/status", user=OWNER_ID)
    assert "backend lm-studio" in owner


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
    assert slash_access.allowed_names(registry, Principal(channel="discord", sender="9", scope="group")) \
        == ["help", "whoami", "btw", "jobs", "recap", "sessions", "status", "voice"]


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


async def test_the_preview_shows_twelve_commands_then_points_at_whoami():
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


# ── quick commands are judged again, on the raw typed name ─────────────────────────


async def test_a_quick_command_is_gated_on_its_raw_name_and_its_alias_target_again(hub, store, monkeypatch):
    store(quick_commands={"deploy": {"type": "exec", "command": "echo deploy"},
                          "st": {"type": "alias", "target": "/status"}})
    denied = await hub.say("/deploy")
    assert denied.startswith("⛔ /deploy is admin-only here. You can run: /help, /whoami, ")
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

    yield SimpleNamespace(chat=chat, orch=orch, conversation=conversation)
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
    """An allowed command still answers only through its own guards: a guest allowed
    /recap on the owner's shared session is refused by /recap itself, as before."""
    store({"*": {"dm": ["recap"]}})
    registry = build_default_registry()

    async def history(*_a, **_k):
        raise AssertionError("the shared session must not be read for a guest")

    orch = SimpleNamespace(commands=registry, on_shared_session=lambda: True,
                           memory=SimpleNamespace(get_history=history), session_id="shared")
    outcome = await registry.dispatch("/recap", orch=orch, principal=Principal(channel="widget"))
    assert outcome.status == "answered" and "owner" in outcome.reply


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
    token = bind_turn_principal(Principal(channel="web"))
    try:
        assert (await orch._slash_access_denial("hello there")) is None
        assert (await orch._slash_access_denial("/frobnicate")) is None   # unknown: not judged
    finally:
        reset_turn_principal(token)

