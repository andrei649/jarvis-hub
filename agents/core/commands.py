"""The chat slash-command plane (Hermes absorption, wave 1).

One registry serves every conversational surface — Telegram, the web chat, any channel
that reaches `Orchestrator.handle_input` — so `/status` means the same thing everywhere
and a command that stops the house is gated the same way everywhere. Before this, the
decision-inbox buttons worked on Telegram, but nothing let a person ask what was running,
stop it, or lift the emergency stop from the conversation they were already in.

Commands carry an access tier. `user` commands answer anyone the channel already admitted;
`admin` commands answer only a principal the turn established as the owner (the Telegram
owner allowlist / owner chat, or an admin token on the web endpoint). A non-owner asking
for an owner command is told so — never silently ignored, never quietly obeyed. Which
user-tier commands a non-owner may run in a DM or a group of each channel is the owner's
`commands.user_allowed_commands` (H058, `slash_access.py`), above a floor of `/help` and
`/whoami` that no setting removes.

Handlers here never perform a privileged effect themselves except through the same
module the HTTP routes call (the e-stop sentinel), and they never reach the model.
"""

from __future__ import annotations

import inspect
import logging
import re
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("jarvis.commands")

USER = "user"
ADMIN = "admin"

_COMMAND_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_]*)(?:@\w+)?(?:\s+(.*))?$", re.DOTALL)
_MAX_ARGS = 2_000


def _raw_command_name(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    match = _COMMAND_RE.fullmatch(text.strip())
    return match.group(1).lower() if match else None


def checkpoint_command_name(text: str) -> str | None:
    """Identify only raw checkpoint commands; recognition grants no authority."""
    name = _raw_command_name(text)
    return name if name in {"rollback", "checkpoints"} else None


def side_question_command_name(text: str) -> str | None:
    """Identify a raw ``/btw`` side question (H414); recognition grants no authority."""
    name = _raw_command_name(text)
    return name if name == "btw" else None


def preappend_command_name(text: str) -> str | None:
    """A command the orchestrator answers *before* the turn is appended, so neither it
    nor its reply becomes a turn: the checkpoint operations and the ``/btw`` side
    question. Callers that prepare a message for the model (notes, ``@file`` refs)
    leave these alone."""
    return checkpoint_command_name(text) or side_question_command_name(text)


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
    #: H058: ``dm`` or ``group`` — which list of ``commands.user_allowed_commands`` a
    #: non-owner's commands are judged against (a channel with no chat type is a DM).
    scope: str = "dm"


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
    status: str  # answered | queued | refused | unknown | failed
    reply: str


def _oversized(name: str, text: str) -> CommandOutcome | None:
    """The refusal for a command whose text is longer than it may be, or None. Asked only
    once the access gate let the sender reach *name* (H058): input checks never answer
    in place of a denial."""
    if len(text.strip()) <= _MAX_ARGS:
        return None
    if name in {"rollback", "checkpoints"}:
        return CommandOutcome(name, "refused", "Checkpoint command is too long; nothing changed.")
    if name == "kanban":
        return CommandOutcome(name, "refused", "Kanban command is too long; nothing changed.")
    if name in {"goal", "subgoal"}:
        # H462: a goal cut short is a different goal — a dropped "must not" line
        # would reach the approval card looking complete.
        return CommandOutcome(
            name, "refused", f"/{name} is longer than {_MAX_ARGS} characters; nothing was proposed or added.")
    return None


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

    def commands(self) -> list[SlashCommand]:
        """Every registered command, by name — tier unfiltered (H058's policy reads it)."""
        return [command for _name, command in sorted(self._commands.items())]

    def visible(self, principal: Principal) -> list[SlashCommand]:
        """What *principal* may run here: every command for the owner; for anyone else
        the user-tier commands ``commands.user_allowed_commands`` allows in this channel
        and scope, and always ``/help`` and ``/whoami`` (H058)."""
        from .slash_access import allowed_names

        allowed = allowed_names(self, principal)
        return [
            command
            for _name, command in sorted(self._commands.items())
            if (command.tier == USER or principal.admin) and (allowed is None or command.name in allowed)
        ]

    @staticmethod
    def parse(text: str) -> tuple[str, str] | None:
        match = _COMMAND_RE.match((text or "").strip())
        if not match:
            return None
        return match.group(1).lower(), (match.group(2) or "").strip()[:_MAX_ARGS]

    async def dispatch(self, text: str, *, orch: Any, principal: Principal,
                       _quick_seen: frozenset[str] = frozenset()) -> CommandOutcome | None:
        """Answer a slash command, or return None when *text* is not one."""
        parsed = self.parse(text)
        if parsed is None:
            return None
        name, args = parsed
        command = self.get(name)
        if command is None:
            from .quick_commands import dispatch_quick

            # A quick command is judged by the access gate inside dispatch_quick, first.
            quick = await dispatch_quick(self, name, args, text=text,
                                         orch=orch, principal=principal, seen=_quick_seen)
            if quick is not None:
                return self._observed(quick)
            oversized = _oversized(name, text)
            if oversized is not None:
                return self._observed(oversized)        # a fixed name, not the sender's text
            # Deliberately NOT observed. `name` here is whatever the sender typed, so
            # emitting it would push arbitrary message text through a field that
            # promises to carry command names — a body leak wearing a safe label.
            return CommandOutcome(name, "unknown", f"Unknown command /{name}. Try /help.")
        from .slash_access import refusal

        # H058, the cold path: the access gate answers first — before any handler, and
        # before the input checks below, so a non-owner's oversized owner command gets the
        # audited denial, not a validation reply that skips the audit log. It stands in
        # front of the kernel kinds handlers cross, never for them.
        denied = await refusal(self, name, orch=orch, principal=principal)
        if denied is not None:
            # Observed: this name came from the registry, not from the sender.
            return self._observed(denied)
        if command.tier == ADMIN and not principal.admin:
            # The tier invariant stands even if the policy above ever misjudged.
            return self._observed(CommandOutcome(
                name,
                "refused",
                f"/{name} is an owner command — send it from the owner's channel or with an admin token.",
            ))
        oversized = _oversized(name, text)
        if oversized is not None:
            return self._observed(oversized)
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
    from .quick_commands import help_lines
    from .slash_access import listed_names

    registry = getattr(ctx.orch, "commands", None)
    commands = registry.visible(ctx.principal) if isinstance(registry, CommandRegistry) else []
    if commands and not ctx.principal.admin:
        # H058: what this door will run — on a channel, not a command whose text is a reset trigger.
        listed = listed_names(registry, ctx.principal, orch=ctx.orch)
        commands = [command for command in commands if listed is None or command.name in listed]
    lines = [command.summary for command in commands]
    if ctx.principal.admin and isinstance(registry, CommandRegistry):
        lines.extend(help_lines(registry))
    if not ctx.principal.admin:
        lines.append("Owner commands (such as /pause, /resume, /stop, /remind and /refine) answer only "
                     "the owner's channel.")
    return "\n".join(lines) if lines else "No commands are registered."


def _whoami(ctx: CommandContext) -> str:
    """H058 — who this hub takes you for here, and the exact commands you can run."""
    from .slash_access import whoami

    registry = getattr(ctx.orch, "commands", None)
    if not isinstance(registry, CommandRegistry):
        registry = CommandRegistry()
    return whoami(registry, ctx.principal, orch=ctx.orch)


def _status(ctx: CommandContext) -> str:
    from agents import __version__
    from agents.core import estop

    orch = ctx.orch
    backend = getattr(getattr(orch, "llm_router", None), "name", None) or "none"
    agents = getattr(orch, "agents", None) or {}
    state = estop.get_state()
    from .autonomy.mode import global_mode

    mode = global_mode(orch)     # H484: what the policy runs, never the raw setting
    lines = [
        f"Nerva {__version__} — backend {backend}, {len(agents)} agents loaded",
        f"autonomy mode: {mode}",
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
    # H440: the sessions nobody continued yet — the newest part of a continued chat, not
    # the parts before it — so every id printed is one to resume. Archived chats are not
    # in this list, as they are not in the HUD's.
    # Third review: as ``GET /sessions`` does, an imported or derived chat is the owner's
    # alone (left out before the limit), and a continued session that was used again is
    # listed — its later turns are in no continuation — and marked as an earlier part.
    owner = bool(ctx.principal.admin)
    rows = (checkpoints.get_sessions(limit=5, archived=False, native_only=not owner, hide_continuations=True)
            if checkpoints is not None else [])
    if not rows:
        return "No sessions recorded."
    from agents.core.session_titles import title_fields

    continued = getattr(checkpoints, "continued_sessions", None)
    continued = continued([row.get("session_id") or row.get("id") for row in rows]) if callable(continued) else set()
    lines = []
    for row in rows:
        sid = row.get("session_id") or row.get("id") or "?"
        started = row.get("started_at") or ""
        # H413: a title is the opening words of the owner's conversation, so only the
        # owner sees it; a widget visitor or a paired guest gets the id and time.
        title = title_fields(row.get("metadata"))["title"] if owner else ""
        note = "  (earlier part, still in use)" if sid in continued else ""
        lines.append(f"{sid}  {started}  {title}".rstrip() + note)
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
        "until one is (pip install edge-tts, or pip install piper-tts for a fully local voice "
        "with its .onnx models in <data>/voice/piper)."
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
    "not_owner": "Only the owner's own turns are reviewed; nothing was read or kept.",
    "no_scope": "The review could not place this turn, so it did not run; nothing was kept.",
    "foreign_history_not_promotable": ("This conversation was imported from another assistant; it is never "
                                       "reviewed into memory or skills."),
    "image_history_not_promotable": ("This conversation holds an image reading; it is never reviewed into "
                                     "memory or skills."),
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
    if any("memory write" in a and "proposed" in a for a in actions):
        lines.append("Nothing was written to memory yet: read the held writes in Long-Term Memory "
                     "(GET /api/memory/proposals) and approve or reject them there or in the Decision Inbox.")
    if any("quarantined" in a for a in actions):
        lines.append("A new skill waits in the pending skills list (SELF-IMPROVEMENT) until you approve it.")
    return "\n".join(lines)


_BTW_SYSTEM = (
    "You answer a side question about a conversation you are shown. Answer from the "
    "conversation only, briefly and plainly; if it does not say, say so. Do not continue "
    "the conversation and do not address its participants."
)
_BTW_NO_MODEL = ("The side question could not be answered: it needs a local model, and none "
                 "answered (side questions never leave this machine).")


async def _btw(ctx: CommandContext) -> str:
    """H414 — Hermes' ``/btw <question>``: a side question ABOUT this conversation,
    answered beside it. The model sees a bounded, redacted snapshot of the session
    (the one ``/refine`` reviews: newest turns first, commands and their replies left
    out, secrets and personal data scrubbed line by line) and the question, once,
    through ``run_oneshot`` on the auxiliary rail — strict-local, job pins excluded,
    the auxiliary consent boundary. The orchestrator dispatches ``/btw`` before the
    turn is appended, so neither the question nor the answer becomes a turn."""
    from agents.core.llm.auxiliary_text import (
        BTW_MAX_TOKENS,
        BTW_QUESTION_CHARS,
        BTW_SNAPSHOT_CHARS,
        run_oneshot,
    )

    question = " ".join((ctx.args or "").split())[:BTW_QUESTION_CHARS]
    if not question:
        return ("Usage: /btw <question> — ask a side question about this conversation "
                "(e.g. /btw what did I ask first?); nothing is added to it.")
    orch = ctx.orch
    # As /recap: a turn with no session of its own runs on the owner's shared one, and
    # only the owner may ask about it. No probe counts as shared (fail closed).
    probe = getattr(orch, "on_shared_session", None)
    shared = bool(probe()) if callable(probe) else True
    if shared and not ctx.principal.admin:
        return "This conversation is the owner's: /btw answers about it only for the owner."
    memory = getattr(orch, "memory", None)
    session = getattr(orch, "session_id", None)
    if memory is None or not session:
        return "There is no conversation here to ask about yet."
    router = getattr(orch, "llm_router", None)
    if router is None:
        return _BTW_NO_MODEL
    from agents.core.day_report import default_redactor
    from agents.core.learning.background_review import REFINE_TURN_CHARS, conversation_snapshot
    from agents.core.llm.data_handling import DataHandlingRefused
    from agents.core.llm.job_selection import SelectionError

    turns = await memory.get_history(session)
    # Redact each turn's WHOLE content before anything is cut: cutting first can split a
    # key so that no pattern matches and its prefix survives (the Redactor's own rule).
    # The snapshot then bounds each turn and the total, over text that is already clean;
    # the redactor also folds whitespace, so a turn cannot forge a role line.
    # Only the newest window that can fill the snapshot is redacted (a long history is not
    # scanned whole on the event loop); each turn kept in it is redacted in full first.
    redact = default_redactor()
    window, used = [], 0
    for turn in reversed(list(turns or [])):
        if not isinstance(turn, dict) or turn.get("content") is None or not str(turn["content"]).strip():
            continue
        content = str(turn["content"])
        if turn.get("agent_id") == "commands" or (
                turn.get("role") == "user" and CommandRegistry.parse(content.strip()) is not None):
            continue
        clean = redact(content, limit=max(1, len(content)))
        window.append(dict(turn, content=clean))
        used += min(len(clean), REFINE_TURN_CHARS) + 16
        if used > BTW_SNAPSHOT_CHARS:
            break
    transcript = conversation_snapshot(window[::-1], limit=BTW_SNAPSHOT_CHARS, per_turn=REFINE_TURN_CHARS)
    if not transcript:
        return "There is no conversation here to ask about yet."
    prompt = f"Conversation:\n{transcript}\n\nQuestion about this conversation: {question}"
    try:
        answer = await run_oneshot(router, prompt, system=_BTW_SYSTEM, purpose="btw",
                                   max_tokens=BTW_MAX_TOKENS, temperature=0.2)
    except SelectionError:
        return "A job model pin is in force for this turn, and side questions do not run under one."
    except DataHandlingRefused as exc:
        return f"The side question could not be answered: {exc}"
    except Exception:
        logger.warning("/btw: the local model did not answer", exc_info=True)
        return _BTW_NO_MODEL
    answer = str(answer or "").strip()
    return answer or "The local model gave no answer to that."


async def _recap(ctx: CommandContext) -> str:
    """H441 — Hermes' ``/recap``: this conversation's last exchanges, rendered from the
    stored turns with no model call; tools a reply used show as a count. ``/recap 20``
    shows more exchanges (at most 50)."""
    orch = ctx.orch
    # A turn with no session of its own (a widget visitor, a webhook, an MCP caller)
    # runs on the owner's shared one: only the owner reads it back. An orchestrator
    # without the probe counts as shared (fail closed).
    probe = getattr(orch, "on_shared_session", None)
    shared = bool(probe()) if callable(probe) else True
    if shared and not ctx.principal.admin:
        return "This conversation is the owner's: /recap reads it back only for the owner."
    memory = getattr(orch, "memory", None)
    session = getattr(orch, "session_id", None)
    if memory is None or not session:
        return "There is no conversation here to recap yet."
    from agents.core.memory.recap import DEFAULT_EXCHANGES, render_recap

    arg = (ctx.args or "").strip()
    exchanges = int(arg) if arg.isascii() and arg.isdigit() and int(arg) > 0 else DEFAULT_EXCHANGES
    turns = await memory.get_history(session)
    # The /recap line itself is the conversation's newest turn: it is not recapped.
    parsed = CommandRegistry.parse(str(turns[-1].get("content", ""))) if turns else None
    if parsed and parsed[0] == "recap" and turns[-1].get("role") == "user":
        turns = turns[:-1]
    return render_recap(turns, exchanges=exchanges)["text"]


async def _kanban(ctx: CommandContext) -> str:
    from .kanban.cli import execute_command

    try:
        argv = shlex.split(ctx.args or "")
    except ValueError:
        return "kanban: invalid quoted arguments"
    result = await execute_command(ctx.orch, argv, ctx.principal,
                                   session_id=getattr(ctx.orch, "session_id", None), owner_command=ctx)
    return result["output"]


async def _project(ctx: CommandContext) -> str:
    from .kanban.projects_cli import execute_command

    try:
        argv = shlex.split(ctx.args or "")
    except ValueError:
        return "project: invalid quoted arguments"
    result = await execute_command(ctx.orch, argv, ctx.principal,
                                   session_id=getattr(ctx.orch, "session_id", None), owner_command=ctx)
    return result["output"]


def _personality(ctx: CommandContext) -> str:
    """H592 — Hermes' ``/personality``: switch this conversation's style preset.

    ``/personality`` lists presets and what is in force; ``<name>`` sets this
    conversation's preset; ``none`` runs it on the plain SOUL; ``default`` forgets the
    choice (follow the hub-wide default); ``global <name|none>`` sets or clears that
    default. Nothing here writes a SOUL file or a prompt version.
    """
    from . import safe_mode
    from .cognition import personality_presets as pp

    store = pp.default_store()
    session = getattr(ctx.orch, "session_id", None)
    usage = "Usage: /personality [<name> | none | default | global <name|none>]."
    untouched = "The SOUL and its version history are untouched."
    words = (ctx.args or "").split()
    wanted = words[0].lower() if words else ""
    suspended = safe_mode.enabled()
    if not wanted or wanted == "list":
        rows = []
        for preset in pp.catalog():
            state = " (blocked by the injection scan)" if preset.blocked else ""
            rows.append(f"- {preset.name} [{preset.source}]{state}")
        builtins = set(pp.BUILTIN_PRESETS)
        for name, why in pp.ignored_files().items():
            instead = "; the built-in is used" if name in builtins else ""
            rows.append(f"- {name}.md [owner file] (ignored: {why}{instead})")
        own = store.get_session(session) if session else None
        current = store.effective(session) if session else store.get_global()
        lines = [
            f"Personality here: {current or 'none (plain SOUL)'}"
            + (" — this conversation's choice" if own else (" — the hub-wide default" if current else "")),
            f"Hub-wide default: {store.get_global() or 'none'}",
            "Presets:", *rows,
            f"Add your own as {pp.presets_dir()}/<name>.md. {usage}",
        ]
        if suspended:
            lines.insert(0, "Safe mode is on: no personality overlay is applied (every turn runs on "
                            "the plain SOUL) and the choices below cannot be changed until the hub "
                            "restarts without safe mode.")
        return "\n".join(lines)
    if suspended:
        safe_mode.note("personality_overlays")
        return ("Safe mode is on: personality overlays are suspended and cannot be changed; "
                "nothing changed. Restart the hub without safe mode to use /personality.")
    if wanted == "global":
        target = words[1].lower() if len(words) > 1 else ""
        if target in (pp.NONE, pp.DEFAULT, "off"):
            store.set_global(None)
            return f"Hub-wide default personality cleared. {untouched}"
        preset = pp.resolve(target)
        refusal = _personality_refusal(preset, target, usage)
        if refusal:
            return refusal
        store.set_global(preset.name)
        return (f"Hub-wide default personality is now {preset.name}; a conversation's own choice "
                f"still wins. {untouched}")
    if not session:
        return "There is no conversation here to set a personality for."
    if wanted in (pp.NONE, "off"):
        store.set_session(session, pp.NONE)
        return f"This conversation now runs on the plain SOUL, with no personality overlay. {untouched}"
    if wanted in (pp.DEFAULT, "reset"):
        store.set_session(session, None)
        fallback = store.get_global()
        return (f"This conversation's personality choice is cleared; it follows the hub-wide default "
                f"({fallback or 'none'}). {untouched}")
    preset = pp.resolve(wanted)
    refusal = _personality_refusal(preset, wanted, usage)
    if refusal:
        return refusal
    store.set_session(session, preset.name)
    return (f"Personality for this conversation is now {preset.name} ({preset.source}) — from the next "
            f"reply. /personality none drops it. {untouched}")


def _personality_refusal(preset, wanted: str, usage: str) -> str:
    if preset is None:
        return f"Unknown personality {wanted[:32]!r}; nothing changed. /personality lists them. {usage}"
    if preset.blocked:
        return (f"The personality file {preset.name}.md was blocked by the injection scan; "
                "nothing changed. Edit the file and try again.")
    return ""


def _bundles(ctx: CommandContext) -> str:
    """H026 — Hermes' ``/bundles``: the skill bundles, and how each is loaded into a turn."""
    from .skills import bundles

    loader = getattr(ctx.orch, "skills", None)
    try:
        return bundles.list_reply((getattr(loader, "skills", None) or {}).values())
    except OSError:
        logger.warning("/bundles: the skill bundles could not be read", exc_info=True)
        return "The skill bundles could not be read."


def _bundle(ctx: CommandContext) -> str:
    """H026 — ``/bundle <name> [instruction]``. The orchestrator loads the bundle into the
    owner's turn before the registry is asked (``Orchestrator._begin_bundle_load``); the
    registry answers only where no turn loads one (an alias, a surface without skills)."""
    return ("/bundle <name> [instruction] loads every skill of a bundle into a conversation turn: "
            "send it as a message of its own. /bundles lists the bundles.")


def _looser_note(approval_mode, orch, *, still: bool) -> str:
    """The agents whose own override lets them ask less than the global mode, or ""."""
    looser = approval_mode.looser_overrides(orch)
    if not looser:
        return ""
    names = ", ".join(f"{agent}: {mode}" for agent, mode in sorted(looser.items()))
    verb = "still asks less" if still else "asks less than the global mode"
    if still:
        return (f"A per-agent override {verb} than this for: {names}. "
                "Change one with the HUD's per-agent mode control.")
    return f"A per-agent override {verb} for: {names}."


async def _approvals(ctx: CommandContext) -> str:
    """H484 — Hermes' ``/approvals``: show or set the approval dial (``autonomy.mode``).

    Bare shows the mode; ``auto``, ``ask`` or ``off`` sets it (Hermes' ``smart`` and
    ``manual`` are read as ``auto`` and ``ask``). Every position only adds asking — there
    is no word here that silences approvals, and ``off`` is the strictest position. The
    write is the audited one the admin route makes (``autonomy.mode.set_global_mode``);
    the owner is re-checked here, at the side-effect boundary, as well as by the tier.
    A reply states only what holds: the mode the live policy runs after the write."""
    import asyncio

    from .autonomy import mode as approval_mode

    usage = f"Usage: /approvals [{approval_mode.USAGE}]"
    current = approval_mode.global_mode(ctx.orch)
    words = (ctx.args or "").split()

    def recalled(still: bool) -> str:
        count = getattr(getattr(ctx.orch, "autonomy_queue", None), "recalled_waiting", None)
        try:
            waiting = int(count()) if callable(count) else 0
        except Exception:  # noqa: BLE001 — a count that cannot be read is not reported
            waiting = 0
        if not waiting:
            return ""
        tasks = "1 task" if waiting == 1 else f"{waiting} tasks"
        verb = ("is" if waiting == 1 else "are") + (" still" if still else "")
        return (f"{tasks} recalled by off {verb} waiting in your inbox"
                + ("; they do not resume by themselves." if still else "."))

    if not words:
        lines = [f"Approval mode: {current} — {approval_mode.meaning(current)}."]
        overrides = approval_mode.agent_modes(ctx.orch)
        if overrides:
            listed = ", ".join(f"{agent}: {mode}" for agent, mode in sorted(overrides.items()))
            lines.append(f"Per-agent overrides: {listed}."
                         + (" None applies while the global mode is off." if current == "off" else ""))
        looser = _looser_note(approval_mode, ctx.orch, still=False)
        if looser:
            lines.append(looser)
        if recalled(False):
            lines.append(recalled(False))
        lines.append("No position turns approvals off: the kernel's owner-approval floor asks "
                     f"in every mode. {usage}")
        return "\n".join(lines)
    if not ctx.principal.admin:
        return "Only the owner can change the approval mode; nothing changed."
    wanted = approval_mode.parse_requested(words[0]) if len(words) == 1 else None
    if wanted is None:
        return f"{usage}\nApproval mode remains {current}; nothing changed."
    actor = f"{ctx.principal.channel}:{ctx.principal.sender or 'owner'}"
    try:
        result = await asyncio.to_thread(
            approval_mode.set_global_mode, ctx.orch, wanted, actor=actor, surface="chat")
    except Exception:  # noqa: BLE001 — a store that refused the write: say what still holds
        logger.warning("/approvals: the mode could not be saved", exc_info=True)
        return (f"Approval mode remains {approval_mode.global_mode(ctx.orch)}; "
                "the requested value did not become effective.")
    live = approval_mode.global_mode(ctx.orch)
    if live != wanted:
        return (f"Approval mode remains {live}; the requested value did not become effective: "
                f"the settings store holds {live} (another write, or a store that could not be "
                "read back). The stricter mode stays in force.")
    lines = [f"Approval mode: {live} (persistent setting) — {approval_mode.meaning(live)}."]
    if live == "off":
        lines.append("This is the strictest position, and no per-agent override loosens it: Nerva has "
                     "no position that turns approvals off. Work approved by anything but you (the "
                     "policy, the smart reviewer, a standing consent) returns to your inbox instead of "
                     "running, and waits there until you decide it — also after you leave off.")
    looser = _looser_note(approval_mode, ctx.orch, still=True)
    if looser:
        lines.append(looser)
    if result["was"] == "off" and live != "off" and recalled(True):
        lines.append(recalled(True))
    if not result["audited"]:
        lines.append("The change is in effect, but it could not be recorded in the audit log.")
    return "\n".join(lines)


_MEMORY_USAGE = "Usage: /memory pending | approve <id|all> | reject <id|all> | approval [on|off]"


def _memory_age(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return "?"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h"
    return f"{int(seconds // 86400)} d"


async def _memory(ctx: CommandContext) -> str:
    """H443 — Hermes' ``/memory pending | approve | reject | approval``: the memory writes the
    post-turn review (or a /refine) holds for the owner. Owner-only and DM-only: a group
    never reads or decides the owner's held facts, and a non-owner is refused here as well
    as by the tier. A decision goes through the same settle path as the HUD and the API
    (the proposal's own card, applied once); switching approval goes through the audited
    writer the route uses. A fact's text is shown only where it came from, or on the
    hub's own screen (the verbose notification rule); elsewhere, counts."""
    import asyncio

    from .action_origin import OPERATOR_TURN_CHANNELS
    from .learning import memory_proposals as mp
    from .learning.review_policy import STAGE_REASONS

    if not ctx.principal.admin:
        return "Only the owner can read or decide held memory writes; nothing changed."
    if ctx.principal.scope != "dm":
        return ("Held memory writes are the owner's: /memory answers only in a direct conversation "
                "with you, never in a group. Nothing was read or changed.")
    orch = ctx.orch
    store = getattr(orch, "memory_proposals", None)
    words = (ctx.args or "").split()
    sub = words[0].lower() if words else "pending"
    if sub == "approval":
        if len(words) == 1:
            on = await asyncio.to_thread(mp.write_approval_required)
            return (f"Memory write approval is {'on' if on else 'off'}: the post-turn review and /refine "
                    + ("ask before they write memory." if on else
                       "write on their own, except from a conversation that read untrusted content or "
                       "was not watched from its start.")
                    + " The model's memory tool and /api/memory/remember are not held by it.")
        wanted = {"on": True, "off": False}.get(words[1].lower()) if len(words) == 2 else None
        if wanted is None:
            return _MEMORY_USAGE
        actor = f"{ctx.principal.channel}:{ctx.principal.sender or 'owner'}"
        try:
            await asyncio.to_thread(mp.set_write_approval, wanted, audit=getattr(orch, "intent_log", None),
                                    actor=actor)
        except Exception:
            logger.warning("/memory approval: the gate could not be changed", exc_info=True)
            now = await asyncio.to_thread(mp.write_approval_required)
            return (f"Memory write approval stays {'on' if now else 'off'}: the change or its audit "
                    "record could not be saved.")
        now = await asyncio.to_thread(mp.write_approval_required)
        return f"Memory write approval is now {'on' if now else 'off'}."
    if store is None:
        return "Held memory writes are not available on this hub."
    settle = getattr(orch, "settle_memory_proposals", None)
    if callable(settle):
        await settle()
    records = await asyncio.to_thread(store.list)
    waiting = [rec for rec in records if rec.get("status") in (mp.STATUS_PENDING, mp.STATUS_APPLYING)]
    if sub == "pending" and len(words) == 1:
        stats = await asyncio.to_thread(store.stats)
        if not waiting:
            lines = ["No memory writes are waiting for you."]
        else:
            lines = [f"{len(waiting)} memory write proposal(s) wait for you "
                     f"(oldest {_memory_age(stats.get('oldest_pending_age_s'))}):"]
        here = str(ctx.principal.channel or "").strip().lower()
        local = here in OPERATOR_TURN_CHANNELS
        current = str(getattr(orch, "session_id", "") or "default")
        for rec in waiting[:20]:
            ops = rec.get("operations") or []
            why = STAGE_REASONS.get(str(rec.get("reason")), str(rec.get("reason") or "held"))
            lines.append(f"- {rec['id']}: {len(ops)} fact(s), {why}"
                         + (" [approved, retrying]" if rec.get("status") == mp.STATUS_APPLYING else ""))
            if local or rec.get("session_id") == current:
                for op in ops[:12]:
                    text = " ".join(str(op.get("text") or "").split())
                    lines.append(f"    {mp.TARGET_LABELS.get(op.get('target'), op.get('target'))}: "
                                 f"\u201c{text[:80]}{'\u2026' if len(text) > 80 else ''}\u201d")
        if len(waiting) > 20:
            lines.append(f"\u2026 and {len(waiting) - 20} more (Long-Term Memory in the HUD lists them all).")
        if stats.get("dropped_at_cap"):
            lines.append(f"{stats['dropped_at_cap']} held write(s) were not kept because "
                         f"{stats.get('max_pending')} were already waiting.")
        if waiting:
            lines.append("Decide with /memory approve <id|all> or /memory reject <id|all>.")
        return "\n".join(lines)
    if sub in ("approve", "reject") and len(words) == 2:
        approved = sub == "approve"
        target = words[1]
        chosen = [rec["id"] for rec in waiting if rec.get("status") == mp.STATUS_PENDING] if target == "all" \
            else [target]
        if not chosen:
            return "No memory writes are waiting for you; nothing changed."
        decide = getattr(orch, "decide_memory_proposal", None)
        if not callable(decide):
            return "Held memory writes cannot be decided on this hub; nothing changed."
        by = f"{ctx.principal.channel}:{ctx.principal.sender or 'owner'}"
        lines = []
        for pid in chosen[:mp.MAX_PENDING]:
            if not ctx.principal.admin:          # the owner, re-checked at the write
                return "Only the owner can decide held memory writes."
            result = await decide(pid, approved, by=by)
            reason = str(result.get("reason") or "")
            if reason == "unknown_proposal":
                lines.append(f"- {pid}: no such held write")
            elif approved and result.get("applied"):
                lines.append(f"- {pid}: approved, {result.get('written', 0)} written")
            elif approved and result.get("status") == mp.STATUS_FAILED:
                lines.append(f"- {pid}: approved, nothing written (memory is off, or every fact was refused)")
            elif not approved and result.get("status") == mp.STATUS_REJECTED:
                lines.append(f"- {pid}: rejected, nothing written")
            elif reason == "apply_incomplete":
                lines.append(f"- {pid}: approved, not written yet (a memory file was busy); it is retried")
            elif reason.startswith("not_pending:"):
                # Decided elsewhere first (the HUD, another command): say how, not "not decided".
                status = reason.split(":", 1)[1]
                done = {mp.STATUS_APPLIED: "approved and written", mp.STATUS_APPLYING: "approved, being written",
                        mp.STATUS_REJECTED: "rejected", mp.STATUS_EXPIRED: "expired",
                        mp.STATUS_FAILED: "approved, nothing written"}.get(status, status or "closed")
                lines.append(f"- {pid}: already decided ({done})")
            else:
                lines.append(f"- {pid}: not decided ({reason or result.get('status') or 'unknown'})")
        return "\n".join(lines)
    return _MEMORY_USAGE


def build_default_registry() -> CommandRegistry:
    from .checkpoint_commands import checkpoint_command
    from .goal_commands import goal_command, subgoal_command

    registry = CommandRegistry()
    registry.register(SlashCommand("help", "the commands you can use here", _help))
    registry.register(SlashCommand("whoami", "your platform, scope, sender id, tier and the commands you can run",
                                   _whoami))
    registry.register(SlashCommand("status", "backend, agents, autonomy mode, e-stop", _status))
    registry.register(SlashCommand("approvals", "show or set how much runs without asking (the approval mode)",
                                   _approvals, tier=ADMIN, usage="[auto|ask|off]"))
    registry.register(SlashCommand("sessions", "the five most recent sessions", _sessions))
    registry.register(SlashCommand("new", "start a fresh conversation and save this one", _session_change, tier=ADMIN))
    registry.register(SlashCommand("reset", "same as /new", _session_change, tier=ADMIN))
    registry.register(SlashCommand("undo", "remove the last exchange while preserving history", _session_change, tier=ADMIN))
    registry.register(SlashCommand("recap", "this conversation's last exchanges, with no model call", _recap, usage="[exchanges]"))
    registry.register(SlashCommand("btw", "ask a side question about this conversation; nothing is added to it",
                                   _btw, usage="<question>"))
    registry.register(SlashCommand("usage", "cloud provider quota left, and any 429 hold", _usage, tier=ADMIN))
    registry.register(SlashCommand("pause", "engage the emergency stop", _pause, tier=ADMIN, usage="[reason]"))
    registry.register(SlashCommand("stop", "same as /pause — in-flight work still finishes", _pause, tier=ADMIN, usage="[reason]"))
    registry.register(SlashCommand("resume", "lift the emergency stop", _resume, tier=ADMIN))
    registry.register(SlashCommand("jobs", "your scheduled jobs and whether the scheduler is alive", _jobs))
    registry.register(SlashCommand("remind", "arm a reminder: /remind <when> | <message>", _remind, tier=ADMIN, usage="<when> | <message>"))
    registry.register(SlashCommand("voice", "spoken replies in this chat: off, voice-for-voice, or always", _voice, usage="[off|voice|always]"))
    registry.register(SlashCommand("personality", "switch this conversation's personality preset", _personality,
                                   tier=ADMIN, usage="[<name>|none|default|global <name|none>]"))
    registry.register(SlashCommand("refine", "review this conversation now for memories and skill changes", _refine, tier=ADMIN, usage="[focus]"))
    registry.register(SlashCommand("memory", "memory writes waiting for your approval: pending, approve, reject, approval",
                                   _memory, tier=ADMIN, usage="pending | approve <id|all> | reject <id|all> | approval [on|off]"))
    registry.register(SlashCommand("bundles", "your skill bundles, and how to load one into a turn", _bundles,
                                   tier=ADMIN))
    registry.register(SlashCommand("bundle", "load every skill of a bundle into this turn (/<bundle> works too)",
                                   _bundle, tier=ADMIN, usage="<name> [instruction]"))
    registry.register(SlashCommand("checkpoints", "checkpoint previews and approved owner operations",
                                   checkpoint_command, tier=ADMIN,
                                   usage="[status|list|diff|restore|prune|clear|clear-legacy]"))
    registry.register(SlashCommand("rollback", "list checkpoints or request an approved restore",
                                   checkpoint_command, tier=ADMIN, usage="[checkpoint]"))
    registry.register(SlashCommand("kanban", "manage your task boards", _kanban,
                                   tier=ADMIN, usage="<action> [arguments]"))
    registry.register(SlashCommand("project", "manage your projects and folders", _project,
                                   tier=ADMIN, usage="<action> [arguments]"))
    registry.register(SlashCommand("goal", "propose a goal for a work run; it waits for your approval",
                                   goal_command, tier=ADMIN,
                                   usage="<text> | status | pause | resume | stop [run id]"))
    registry.register(SlashCommand("subgoal", "add an acceptance criterion to the running goal",
                                   subgoal_command, tier=ADMIN,
                                   usage="[run id] <criterion> | remove <N> | clear"))
    return registry


async def _session_change(ctx: CommandContext) -> str:
    change = getattr(ctx.orch, "_direct_session_command", None)
    if change is None:
        return "Conversation change unavailable; nothing was applied."
    result = await change(f"/{ctx.name}", ctx.principal.channel, None)
    return result or "Conversation change unavailable; nothing was applied."
