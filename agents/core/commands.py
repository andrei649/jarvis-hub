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
    #: The conversation the turn came from (a Telegram chat id), when the channel
    #: has one. Per-chat commands such as ``/voice`` act on it; a channel with no
    #: conversation identity leaves it None and those commands say so.
    chat: str | None = None


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
            # Deliberately NOT observed. `name` here is whatever the sender typed, so
            # emitting it would push arbitrary message text through a field that
            # promises to carry command names — a body leak wearing a safe label.
            return CommandOutcome(name, "unknown", f"Unknown command /{name}. Try /help.")
        if command.tier == ADMIN and not principal.admin:
            # Observed: this name came from the registry, not from the sender.
            return self._observed(CommandOutcome(
                name,
                "refused",
                f"/{name} is an owner command — send it from the owner's channel or with an admin token.",
            ))
        try:
            result = command.handler(CommandContext(orch=orch, principal=principal, name=name, args=args))
            if inspect.isawaitable(result):
                result = await result
            return self._observed(CommandOutcome(name, "answered", str(result)))
        except Exception:
            logger.warning("slash command /%s failed", name, exc_info=True)
            return self._observed(CommandOutcome(name, "failed", f"/{name} failed — check the hub log."))

    @staticmethod
    def _observed(outcome: CommandOutcome) -> CommandOutcome:
        """Tell watching extensions a command finished, and hand back the same outcome.

        The name and the status go out; the command's *reply* never does. An
        extension learns that `/status` ran, not what the hub said back — the reply
        can contain anything the handler chose to say, and this surface promises it
        carries no message bodies.
        """
        from .extensions.events import EXTENSION_EVENTS

        EXTENSION_EVENTS.emit("command.completed", command=outcome.name, status=outcome.status)
        return outcome


# ── the built-in commands ────────────────────────────────────────────────────


def _help(ctx: CommandContext) -> str:
    registry = getattr(ctx.orch, "commands", None)
    commands = registry.visible(ctx.principal) if isinstance(registry, CommandRegistry) else []
    lines = [command.summary for command in commands]
    if not ctx.principal.admin:
        lines.append("Owner commands (such as /pause, /resume, /stop, /remind and /refine) answer only "
                     "the owner's channel.")
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
    from agents.core.session_titles import title_fields

    lines = []
    for row in rows:
        sid = row.get("session_id") or row.get("id") or "?"
        started = row.get("started_at") or ""
        title = title_fields(row.get("metadata"))["title"]   # H413
        lines.append(f"{sid}  {started}  {title}".rstrip())
    return "Recent sessions:\n" + "\n".join(lines)


def _usage(ctx: CommandContext) -> str:
    """H373 — what each cloud provider says is left, and any shared 429 hold."""
    from agents.core.llm import quota

    return quota.render(quota.usage())


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
        return ("Usage: /remind <when> | <message> — e.g. /remind every weekday at 7 | stand-up in 15 minutes, "
                "or once: /remind in 30m | stretch, /remind tomorrow at 9 | call the bank")
    try:
        job, _first_run, confirmation = runner.arm(
            name=message[:60],
            schedule_text=when,
            action={"type": "remind", "message": message},
            blueprint="reminder",
        )
    except ValueError as exc:
        return f"Could not arm that: {exc}"
    return (f"Armed {job.id}: {confirmation} — {message}. "
            "/jobs lists it; the HUD or `nerva jobs` can pause or delete it.")


def _voice(ctx: CommandContext) -> str:
    """Per-chat voice mode (Hermes ``/voice``): off, voice-for-voice, or always.

    Set by the chat, for the chat, off by default — speaking a reply hands its
    text to the host's text-to-speech backend, which may be a cloud service, so
    the answer names the backend that would do the speaking.
    """
    from .channels import voice_mode
    from .channels.spoken_reply import SpokenReply

    chat = ctx.principal.chat
    if not chat:
        return (
            "Voice mode is set per chat on a chat channel such as Telegram; "
            "there is no chat here to set it for."
        )
    speaker = SpokenReply()
    engine = (
        f"Replies would be spoken by {speaker.backend_label()}."
        if speaker.is_available
        else "No text-to-speech engine is installed on this host yet, so replies stay text "
        "until one is (pip install edge-tts)."
    )
    usage = "Usage: /voice off | voice | always."
    store = voice_mode.default_store()
    wanted = (ctx.args or "").strip().lower()
    if not wanted:
        mode = store.get(ctx.principal.channel, chat)
        return (
            f"Voice mode here: {mode} — {voice_mode.DESCRIPTIONS[mode]}. {usage} {engine}"
        )
    if wanted not in voice_mode.MODES:
        return f"Unknown voice mode {wanted[:24]!r}. {usage}"
    store.set(ctx.principal.channel, chat, wanted)
    if wanted == voice_mode.OFF:
        return "Voice mode here is now off — text only."
    return f"Voice mode here is now {wanted} — {voice_mode.DESCRIPTIONS[wanted]}. {engine}"


_REFINE_REFUSALS = {
    "turn_in_flight": "A turn is still running in this conversation; try /refine again when it has answered.",
    "busy": "A review is already running; try again in a moment.",
    "daily_budget": "Today's review budget (learning.review_daily_budget) is spent; try again tomorrow.",
    "reviews_off": "Reviews are switched off: learning.review_daily_budget is 0.",
    "daily_budget_cut_off": ("At least half of today's review budget went to reviews the local model cut off or "
                             "left malformed; if they were cut off, raise learning.review_max_tokens "
                             "rather than the budget, or try again tomorrow."),
    "llm_error": ("The review could not run: it needs a local model, and none answered "
                  "(reviews never leave this machine)."),
    "llm_timeout": ("The local model did not finish the review in time; nothing was kept. "
                    "Try again, or with a narrower focus."),
    "review_cut_off": ("The local model spent its whole answer on thinking and wrote no review; nothing was "
                       "kept. Raise learning.review_max_tokens, or try a narrower focus."),
    "review_unparsed": ("The local model's review was cut off or malformed, so nothing was kept. Raise "
                        "learning.review_max_tokens, or try a narrower focus."),
    "empty_conversation": "There is no conversation here to review yet.",
    "unavailable": "The learning reviewer is not available on this hub.",
}


async def _refine(ctx: CommandContext) -> str:
    """H465 — Hermes' ``/refine [focus]``: review this conversation for durable memories
    and skill changes now, and say what was kept. A changed skill is a proposal that waits
    in the Decision Inbox, a new one waits in the pending skills list; facts land in the
    living memory (the reply says so when it is off). It runs whether or not the per-turn
    learning loop is on."""
    refine = getattr(ctx.orch, "refine", None)
    if refine is None:
        return _REFINE_REFUSALS["unavailable"]
    focus = " ".join((ctx.args or "").split())[:200]
    result = await refine(focus=focus)
    if not result.get("ran"):
        return _REFINE_REFUSALS.get(str(result.get("reason")), "The review did not run.")
    actions = [str(a) for a in result.get("actions") or []]
    if not actions:
        return "Reviewed this conversation: nothing worth keeping."
    head = f"Reviewed this conversation (focus: {focus}):" if focus else "Reviewed this conversation:"
    lines = [head, *[f"- {a}" for a in actions]]
    if any("patch proposed" in a for a in actions):
        lines.append("A skill change waits for your approval in the Decision Inbox.")
    if any("quarantined" in a for a in actions):
        lines.append("A new skill waits in the pending skills list (SELF-IMPROVEMENT) until you approve it.")
    return "\n".join(lines)


async def _recap(ctx: CommandContext) -> str:
    """H441 — Hermes' ``/recap``: this conversation's last exchanges, rendered from the
    stored turns with no model call; tools a reply used show as a count. ``/recap 20``
    shows more exchanges (at most 50)."""
    orch = ctx.orch
    memory = getattr(orch, "memory", None)
    session = getattr(orch, "session_id", None)
    if memory is None or not session:
        return "There is no conversation here to recap yet."
    from agents.core.memory.recap import DEFAULT_EXCHANGES, render_recap

    arg = (ctx.args or "").strip()
    exchanges = int(arg) if arg.isdigit() and int(arg) > 0 else DEFAULT_EXCHANGES
    turns = await memory.get_history(session)
    # The /recap line itself is the conversation's newest turn: it is not recapped.
    if turns and turns[-1].get("role") == "user" and str(turns[-1].get("content", "")).lstrip().startswith("/recap"):
        turns = turns[:-1]
    return render_recap(turns, exchanges=exchanges)["text"]


def build_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(SlashCommand("help", "the commands you can use here", _help))
    registry.register(SlashCommand("status", "backend, agents, autonomy mode, e-stop", _status))
    registry.register(SlashCommand("sessions", "the five most recent sessions", _sessions))
    registry.register(SlashCommand("recap", "this conversation's last exchanges, with no model call", _recap, usage="[exchanges]"))
    registry.register(SlashCommand("usage", "cloud provider quota left, and any 429 hold", _usage, tier=ADMIN))
    registry.register(SlashCommand("pause", "engage the emergency stop", _pause, tier=ADMIN, usage="[reason]"))
    registry.register(SlashCommand("stop", "same as /pause — in-flight work still finishes", _pause, tier=ADMIN, usage="[reason]"))
    registry.register(SlashCommand("resume", "lift the emergency stop", _resume, tier=ADMIN))
    registry.register(SlashCommand("jobs", "your scheduled jobs and whether the scheduler is alive", _jobs))
    registry.register(SlashCommand("remind", "arm a reminder: /remind <when> | <message>", _remind, tier=ADMIN, usage="<when> | <message>"))
    registry.register(SlashCommand("voice", "spoken replies in this chat: off, voice-for-voice, or always", _voice, usage="[off|voice|always]"))
    registry.register(SlashCommand("refine", "review this conversation now for memories and skill changes", _refine, tier=ADMIN, usage="[focus]"))
    return registry
