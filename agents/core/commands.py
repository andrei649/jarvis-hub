"""The chat slash-command plane (Hermes absorption, wave 1).

One registry serves every conversational surface — Telegram, the web chat, any channel
that reaches `Orchestrator.handle_input` — so `/status` means the same thing everywhere
and a command that stops the house is gated the same way everywhere. Before this, the
decision-inbox buttons worked on Telegram, but nothing let a person ask what was running,
stop it, or lift the emergency stop from the conversation they were already in.

Commands carry an access tier. `user` commands answer anyone the channel already admitted;
`admin` commands answer only a principal the turn established as the owner (the Telegram
owner allowlist / owner chat, or an admin token on the web endpoint). A non-owner asking
for an owner command is told so — never silently ignored, never quietly obeyed.

Handlers here never perform a privileged effect themselves except through the same
module the HTTP routes call (the e-stop sentinel), and they never reach the model.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("jarvis.commands")

USER = "user"
ADMIN = "admin"

_COMMAND_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_]*)(?:@\w+)?(?:\s+(.*))?$", re.DOTALL)
_MAX_ARGS = 2_000


@dataclass(frozen=True)
class Principal:
    """Who is speaking in this turn, as far as the channel could establish."""

    channel: str = "unknown"
    sender: str | None = None
    admin: bool = False


@dataclass
class CommandContext:
    orch: Any
    principal: Principal
    name: str
    args: str


Handler = Callable[[CommandContext], "str | Awaitable[str]"]


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    handler: Handler
    tier: str = USER
    usage: str = ""

    @property
    def summary(self) -> str:
        usage = f" {self.usage}" if self.usage else ""
        owner = "  (owner)" if self.tier == ADMIN else ""
        return f"/{self.name}{usage} — {self.description}{owner}"


@dataclass(frozen=True)
class CommandOutcome:
    """What dispatch decided, so callers can log and record it honestly."""

    name: str
    status: str  # answered | refused | unknown | failed
    reply: str


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> SlashCommand:
        """Add a command. A name already taken is refused, never overwritten.

        This used to be a plain dict assignment, which made the registry
        last-writer-wins. That was harmless while every caller was in-tree and
        registered once. It stops being harmless the moment an extension can
        declare a command: silently replacing ``/pause`` with third-party code is
        exactly the override Nerva does not offer, and no opt-in flag makes it
        safe. Refusing here is what lets the extension runtime hand a declared
        command straight to this registry without a second, weaker check.
        """
        if command.tier not in (USER, ADMIN):
            raise ValueError(f"unknown command tier {command.tier!r}")
        name = command.name.lower()
        if name in self._commands:
            raise ValueError(f"command already registered: {name}")
        self._commands[name] = command
        return command

    def get(self, name: str) -> SlashCommand | None:
        return self._commands.get(name.lower())

    def visible(self, principal: Principal) -> list[SlashCommand]:
        return [
            command
            for _name, command in sorted(self._commands.items())
            if command.tier == USER or principal.admin
        ]

    @staticmethod
    def parse(text: str) -> tuple[str, str] | None:
        match = _COMMAND_RE.match((text or "").strip())
        if not match:
            return None
        return match.group(1).lower(), (match.group(2) or "").strip()[:_MAX_ARGS]

    async def dispatch(self, text: str, *, orch: Any, principal: Principal) -> CommandOutcome | None:
        """Answer a slash command, or return None when *text* is not one."""
        parsed = self.parse(text)
        if parsed is None:
            return None
        name, args = parsed
        command = self.get(name)
        if command is None:
            return CommandOutcome(name, "unknown", f"Unknown command /{name}. Try /help.")
        if command.tier == ADMIN and not principal.admin:
            return CommandOutcome(
                name,
                "refused",
                f"/{name} is an owner command — send it from the owner's channel or with an admin token.",
            )
        try:
            result = command.handler(CommandContext(orch=orch, principal=principal, name=name, args=args))
            if inspect.isawaitable(result):
                result = await result
            return CommandOutcome(name, "answered", str(result))
        except Exception:
            logger.warning("slash command /%s failed", name, exc_info=True)
            return CommandOutcome(name, "failed", f"/{name} failed — check the hub log.")


# ── the built-in commands ────────────────────────────────────────────────────


def _help(ctx: CommandContext) -> str:
    registry = getattr(ctx.orch, "commands", None)
    commands = registry.visible(ctx.principal) if isinstance(registry, CommandRegistry) else []
    lines = [command.summary for command in commands]
    if not ctx.principal.admin:
        lines.append("Owner commands (/pause, /resume, /stop) answer only the owner's channel.")
    return "\n".join(lines) if lines else "No commands are registered."


def _status(ctx: CommandContext) -> str:
    from agents import __version__
    from agents.core import estop

    orch = ctx.orch
    backend = getattr(getattr(orch, "llm_router", None), "name", None) or "none"
    agents = getattr(orch, "agents", None) or {}
    state = estop.get_state()
    mode = None
    get_setting = getattr(orch, "get_setting", None)
    if callable(get_setting):
        mode = get_setting("autonomy.mode", None)
    lines = [
        f"Nerva {__version__} — backend {backend}, {len(agents)} agents loaded",
        f"autonomy mode: {mode or 'auto'}",
        (
            f"e-stop: ENGAGED since {state.get('engaged_at') or '?'} — {state.get('reason') or 'no reason given'}"
            if state is not None
            else "e-stop: not engaged"
        ),
    ]
    session = getattr(orch, "session_id", None)
    if session:
        lines.append(f"session: {session}")
    return "\n".join(lines)


def _sessions(ctx: CommandContext) -> str:
    checkpoints = getattr(ctx.orch, "checkpoints", None)
    rows = checkpoints.get_sessions(limit=5) if checkpoints is not None else []
    if not rows:
        return "No sessions recorded."
    lines = []
    for row in rows:
        sid = row.get("session_id") or row.get("id") or "?"
        started = row.get("started_at") or ""
        lines.append(f"{sid}  {started}".rstrip())
    return "Recent sessions:\n" + "\n".join(lines)


def _pause(ctx: CommandContext) -> str:
    from agents.core import estop

    who = f"{ctx.principal.channel}:{ctx.principal.sender or 'owner'}"
    reason = ctx.args or f"/{ctx.name} from {who}"
    estop.engage(reason)
    return (
        "Emergency stop engaged: no new autonomous work starts; chat keeps working; "
        "work already in flight finishes — there is no kill for a running step yet. /resume lifts it."
    )


def _resume(ctx: CommandContext) -> str:
    from agents.core import estop

    return "Emergency stop lifted; autonomous work resumes on the next tick." if estop.disengage() else "The emergency stop was not engaged."


def _jobs(ctx: CommandContext) -> str:
    runner = getattr(ctx.orch, "jobs", None)
    if runner is None:
        return "Scheduled jobs are not available on this hub."
    jobs = runner.store.list()
    if not jobs:
        return "No scheduled jobs. The owner can arm one with /remind <when> | <message>."
    lines = []
    for job in jobs:
        state = "paused" if job.paused_reason else ("on" if job.enabled else "off")
        last = f"last {job.last_status} {job.last_run_at}" if job.last_status else "never ran"
        lines.append(f"{job.id} · {state} · {job.schedule_text} · {job.name} ({last})")
    alive = runner.scheduler_alive()
    lines.append("scheduler: alive" if alive else "scheduler: NOT RUNNING — nothing will fire")
    return "\n".join(lines)


def _remind(ctx: CommandContext) -> str:
    runner = getattr(ctx.orch, "jobs", None)
    if runner is None:
        return "Scheduled jobs are not available on this hub."
    when, sep, message = ctx.args.partition("|")
    when, message = when.strip(), message.strip()
    if not sep or not when or not message:
        return "Usage: /remind <when> | <message> — e.g. /remind every weekday at 7 | stand-up in 15 minutes"
    try:
        job = runner.create(
            name=message[:60],
            schedule_text=when,
            action={"type": "remind", "message": message},
            blueprint="reminder",
        )
    except ValueError as exc:
        return f"Could not arm that: {exc}"
    return f"Armed {job.id}: {job.schedule_text} ({job.cron}) — {message}. /jobs lists it; the HUD or `nerva jobs` can pause or delete it."


def build_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(SlashCommand("help", "the commands you can use here", _help))
    registry.register(SlashCommand("status", "backend, agents, autonomy mode, e-stop", _status))
    registry.register(SlashCommand("sessions", "the five most recent sessions", _sessions))
    registry.register(SlashCommand("pause", "engage the emergency stop", _pause, tier=ADMIN, usage="[reason]"))
    registry.register(SlashCommand("stop", "same as /pause — in-flight work still finishes", _pause, tier=ADMIN, usage="[reason]"))
    registry.register(SlashCommand("resume", "lift the emergency stop", _resume, tier=ADMIN))
    registry.register(SlashCommand("jobs", "your scheduled jobs and whether the scheduler is alive", _jobs))
    registry.register(SlashCommand("remind", "arm a reminder: /remind <when> | <message>", _remind, tier=ADMIN, usage="<when> | <message>"))
    return registry
