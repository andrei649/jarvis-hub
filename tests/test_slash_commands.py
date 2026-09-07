"""The chat slash-command plane (Hermes absorption, wave 1).

One registry answers `/status`, `/sessions`, `/help`, `/pause`, `/stop`, `/resume` on every
conversational surface. Owner commands answer only a principal the turn established as the
owner — the Telegram owner allowlist or owner chat, or an admin token on the web door — and a
non-owner asking is told so, never silently ignored and never quietly obeyed. A command never
reaches the model.

Hermetic: bare orchestrator doubles, the e-stop module monkeypatched, no model.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import commands as commands_module
from agents.core import estop
from agents.core.channels.manager import ChannelManager
from agents.core.commands import (
    ADMIN,
    CommandContext,
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
)
from agents.core.orchestrator import Orchestrator, current_principal

OWNER = Principal(channel="telegram", sender="42", admin=True)
GUEST = Principal(channel="telegram", sender="7", admin=False)


@pytest.fixture
def estop_state(monkeypatch):
    state = {"engaged": None}

    def engage(reason=None):
        state["engaged"] = {"reason": reason, "engaged_at": "t0"}

    def disengage():
        was = state["engaged"] is not None
        state["engaged"] = None
        return was

    monkeypatch.setattr(estop, "engage", engage)
    monkeypatch.setattr(estop, "disengage", disengage)
    monkeypatch.setattr(estop, "get_state", lambda: state["engaged"])
    return state


def _orch():
    orch = SimpleNamespace(
        commands=build_default_registry(),
        llm_router=SimpleNamespace(name="lm-studio"),
        agents={"jarvis": object(), "friday": object()},
        get_setting=lambda key, default=None: {"autonomy.mode": "ask"}.get(key, default),
        session_id="s-1",
        checkpoints=SimpleNamespace(get_sessions=lambda limit=5: [{"session_id": "s-1", "started_at": "2026-09-07"}]),
    )
    return orch


# ── the registry ─────────────────────────────────────────────────────────────


def test_parse_recognises_commands_and_only_commands():
    parse = CommandRegistry.parse
    assert parse("/status") == ("status", "")
    assert parse("/pause   house is on fire ") == ("pause", "house is on fire")
    assert parse("/Status@nerva_bot") == ("status", "")
    assert parse("hello /status") is None
    assert parse("/etc/hosts") is None
    assert parse("") is None


@pytest.mark.asyncio
async def test_unknown_commands_get_a_hint_not_the_model():
    outcome = await build_default_registry().dispatch("/frobnicate now", orch=_orch(), principal=GUEST)
    assert outcome.status == "unknown" and "/help" in outcome.reply


@pytest.mark.asyncio
async def test_not_a_command_is_none():
    assert await build_default_registry().dispatch("what time is it", orch=_orch(), principal=GUEST) is None


@pytest.mark.asyncio
async def test_help_lists_what_the_principal_may_use():
    registry = build_default_registry()
    guest = await registry.dispatch("/help", orch=_orch(), principal=GUEST)
    owner = await registry.dispatch("/help", orch=_orch(), principal=OWNER)
    assert "/status" in guest.reply and "/pause" not in guest.reply.split("Owner commands")[0]
    assert "Owner commands" in guest.reply
    assert "/pause [reason] — engage the emergency stop  (owner)" in owner.reply
    assert "/resume" in owner.reply


@pytest.mark.asyncio
async def test_owner_commands_refuse_a_guest_and_say_why(estop_state):
    outcome = await build_default_registry().dispatch("/pause", orch=_orch(), principal=GUEST)
    assert outcome.status == "refused" and "owner command" in outcome.reply
    assert estop_state["engaged"] is None


@pytest.mark.asyncio
async def test_pause_and_resume_drive_the_real_estop_module(estop_state):
    registry = build_default_registry()
    paused = await registry.dispatch("/pause the plumber is here", orch=_orch(), principal=OWNER)
    assert paused.status == "answered" and "Emergency stop engaged" in paused.reply
    assert estop_state["engaged"]["reason"] == "the plumber is here"

    status = await registry.dispatch("/status", orch=_orch(), principal=GUEST)
    assert "ENGAGED" in status.reply and "the plumber is here" in status.reply

    resumed = await registry.dispatch("/resume", orch=_orch(), principal=OWNER)
    assert "lifted" in resumed.reply and estop_state["engaged"] is None
    again = await registry.dispatch("/resume", orch=_orch(), principal=OWNER)
    assert "was not engaged" in again.reply


@pytest.mark.asyncio
async def test_stop_is_honest_about_in_flight_work(estop_state):
    outcome = await build_default_registry().dispatch("/stop", orch=_orch(), principal=OWNER)
    assert "in flight finishes" in outcome.reply and estop_state["engaged"]["reason"] == "/stop from telegram:42"


@pytest.mark.asyncio
async def test_status_and_sessions_read_the_orchestrator(estop_state):
    registry = build_default_registry()
    status = await registry.dispatch("/status", orch=_orch(), principal=GUEST)
    assert "backend lm-studio, 2 agents loaded" in status.reply
    assert "autonomy mode: ask" in status.reply and "e-stop: not engaged" in status.reply
    sessions = await registry.dispatch("/sessions", orch=_orch(), principal=GUEST)
    assert "s-1  2026-09-07" in sessions.reply


@pytest.mark.asyncio
async def test_a_failing_handler_is_reported_not_raised():
    registry = CommandRegistry()

    def boom(ctx: CommandContext) -> str:
        raise RuntimeError("no")

    registry.register(SlashCommand("boom", "explodes", boom))
    outcome = await registry.dispatch("/boom", orch=None, principal=GUEST)
    assert outcome.status == "failed" and "/boom failed" in outcome.reply


def test_registry_rejects_unknown_tiers():
    with pytest.raises(ValueError):
        CommandRegistry().register(SlashCommand("x", "x", lambda ctx: "", tier="root"))
    assert ADMIN == "admin"


# ── the orchestrator wires it before skills and the model ───────────────────


def _bare_orchestrator():
    orch = Orchestrator.__new__(Orchestrator)
    orch._channel_sessions = {}
    orch._runtime_settings = {"autonomy.owner_chat_id": "-500"}
    orch.session_id = "shared"
    orch.channel_manager = ChannelManager()
    orch._delivery_router = SimpleNamespace(
        resolve=lambda source, text="": SimpleNamespace(send=False, target=None)
    )
    orch.commands = build_default_registry()
    orch.channels = {"telegram": SimpleNamespace(allowed_users=[42])}
    orch.llm_router = SimpleNamespace(name="lm-studio")
    orch.agents = {}
    orch.checkpoints = SimpleNamespace(get_sessions=lambda limit=5: [])
    seen = {}

    async def fake_handle_input(text, channel="voice", agent_override=None):
        seen["principal"] = current_principal()
        outcome = await orch._dispatch_command(text)
        if outcome is not None:
            return outcome.reply
        return "model reply"

    orch.handle_input = fake_handle_input

    class _Memory:
        async def new_session(self, session_id=None):
            return f"session:{session_id}"

        async def resume_session(self, session_id):
            return False

        async def add_turn(self, *args, **kwargs):
            return None

    orch.memory = _Memory()
    return orch, seen


@pytest.mark.asyncio
async def test_the_telegram_owner_is_the_admin_principal_and_a_guest_is_not(estop_state):
    orch, seen = _bare_orchestrator()

    reply = await orch.channel_handler("/pause", channel="telegram", chat_id=1, sender="42")
    assert "Emergency stop engaged" in reply
    assert seen["principal"] == Principal(channel="telegram", sender="42", admin=True)

    reply = await orch.channel_handler("/resume", channel="telegram", chat_id=1, sender="7")
    assert "owner command" in reply
    assert seen["principal"].admin is False
    assert estop_state["engaged"] is not None  # the guest changed nothing

    # The owner chat id is the other way to be the owner.
    reply = await orch.channel_handler("/resume", channel="telegram", chat_id=-500, sender="7")
    assert "lifted" in reply


@pytest.mark.asyncio
async def test_the_principal_is_reset_after_the_turn(estop_state):
    orch, _seen = _bare_orchestrator()
    await orch.channel_handler("/status", channel="telegram", chat_id=1, sender="42")
    assert current_principal() == Principal()


@pytest.mark.asyncio
async def test_a_command_never_reaches_the_model_and_a_message_still_does():
    orch, _seen = _bare_orchestrator()
    assert "/status" in await orch.channel_handler("/help", channel="web")
    assert await orch.channel_handler("hello", channel="web") == "model reply"


def test_the_default_registry_names_the_first_wave():
    assert {c.name for c in build_default_registry().visible(OWNER)} == {
        "help", "status", "sessions", "pause", "stop", "resume", "jobs", "remind",
    }
    assert {c.name for c in build_default_registry().visible(GUEST)} == {"help", "status", "sessions", "jobs"}
    assert commands_module.USER == "user"


# ── the web door decides the principal the way the admin routes do ──────────


def _request(host="127.0.0.1", headers=None):
    return SimpleNamespace(headers=dict(headers or {}), client=SimpleNamespace(host=host))


def test_the_web_principal_mirrors_the_admin_guard(monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "_admin_credential_ok", lambda supplied: supplied == "good")

    # A credential decides first.
    monkeypatch.setattr(web, "_admin_configured", lambda: True)
    assert web._web_principal(_request(headers={"x-admin-token": "good"})).admin is True
    assert web._web_principal(_request(headers={"x-admin-token": "bad"})).admin is False
    assert web._web_principal(_request()).admin is False  # configured, none presented

    # The fresh-box posture: no credential configured → a direct localhost origin is the owner …
    monkeypatch.setattr(web, "_admin_configured", lambda: False)
    assert web._web_principal(_request()).admin is True
    assert web._web_principal(_request(host="10.0.0.9")).admin is False
    # … but not through an untrusted proxy, which the admin guard also refuses
    # (Hermes absorption 5b: "untrusted" = the peer is outside JARVIS_TRUSTED_PROXIES).
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("JARVIS_TRUSTED_PROXY", raising=False)
    assert web._web_principal(_request(headers={"x-forwarded-for": "127.0.0.1"})).admin is False
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1/32")
    assert web._web_principal(_request(headers={"x-forwarded-for": "127.0.0.1"})).admin is False
    principal = web._web_principal(_request())
    assert principal.channel == "web" and principal.sender is None


# ── /jobs and /remind ────────────────────────────────────────────────────────


class _Runner:
    def __init__(self, jobs=(), alive=True, error=None):
        self._jobs = list(jobs)
        self._alive = alive
        self._error = error
        self.store = SimpleNamespace(list=lambda: list(self._jobs))
        self.created = []

    def scheduler_alive(self):
        return self._alive

    def create(self, **kwargs):
        if self._error:
            raise ValueError(self._error)
        self.created.append(kwargs)
        job = SimpleNamespace(id="job1", schedule_text=kwargs["schedule_text"], cron="0 7 * * 1-5", name=kwargs["name"])
        return job


@pytest.mark.asyncio
async def test_jobs_lists_the_owners_jobs_and_the_scheduler_state():
    job = SimpleNamespace(id="j1", paused_reason=None, enabled=True, schedule_text="every day at 9", name="water", last_status="ok", last_run_at="t")
    orch = _orch()
    orch.jobs = _Runner([job], alive=False)
    outcome = await build_default_registry().dispatch("/jobs", orch=orch, principal=GUEST)
    assert "j1 · on · every day at 9 · water (last ok t)" in outcome.reply
    assert "NOT RUNNING" in outcome.reply
    orch.jobs = _Runner([])
    assert "No scheduled jobs" in (await build_default_registry().dispatch("/jobs", orch=orch, principal=GUEST)).reply
    orch.jobs = None
    assert "not available" in (await build_default_registry().dispatch("/jobs", orch=orch, principal=GUEST)).reply


@pytest.mark.asyncio
async def test_remind_arms_a_reminder_for_the_owner_only():
    orch = _orch()
    orch.jobs = _Runner()
    registry = build_default_registry()
    refused = await registry.dispatch("/remind every weekday at 7 | stand-up", orch=orch, principal=GUEST)
    assert refused.status == "refused" and orch.jobs.created == []

    armed = await registry.dispatch("/remind every weekday at 7 | stand-up in 15", orch=orch, principal=OWNER)
    assert armed.status == "answered" and "Armed job1" in armed.reply and "0 7 * * 1-5" in armed.reply
    assert orch.jobs.created == [
        {"name": "stand-up in 15", "schedule_text": "every weekday at 7", "action": {"type": "remind", "message": "stand-up in 15"}, "blueprint": "reminder"}
    ]

    usage = await registry.dispatch("/remind every day at 9", orch=orch, principal=OWNER)
    assert usage.reply.startswith("Usage: /remind")
    orch.jobs = _Runner(error="that fires ~1440× a day")
    bad = await registry.dispatch("/remind every minute | x", orch=orch, principal=OWNER)
    assert "Could not arm that" in bad.reply and "1440" in bad.reply
