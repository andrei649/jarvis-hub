"""review_policy.py — H443: what a post-turn review inherits from the turn it reviews,
what it replays, and what it tells the owner afterwards.

**Inheritance.** The review runs after the turn, in a task of its own, so the turn's
context is gone by the time it writes. :class:`ReviewScope` is that context, taken while
the turn still holds it: who spoke (the principal), on which surface, whether the turn
or its conversation read untrusted content, and whether the turn's own posture was
offered the ``memory`` and ``skill_propose`` tools (asked of the tool-profile resolver
itself, so a toolset the owner disabled, or a posture the tool is withheld from, is
withheld from the review too). The review can do nothing the turn could not:

==========================================  =========================================
the turn                                    the review's memory writes
==========================================  =========================================
not the owner's (a guest, a non-admin       the review does not run
token, a job, a webhook, a workflow, an
internal channel)
the owner's, at the operator surface,       written, or held for approval when
clean, ``memory`` offered                   ``memory.write_approval`` is on or the
                                            approval dial is ``ask``
the owner's, but it read untrusted content  never written: held for the owner's
(an inbound channel, web text, a flagged    approval, marked as such
recall, an attached file), or its
conversation is not clean (an earlier turn
did, a guest wrote in it, it was not
watched from its start), or its posture is
not offered ``memory``; and a local turn
with no principal bound (the terminal)
approval dial ``off``                       the per-turn review does not run; a
                                            ``/refine`` holds its writes
==========================================  =========================================

**Replay.** Hermes replays the whole conversation on the main chat model and a compact
digest on a cheaper one. The review here is one strict-local call on the auxiliary rail's
``review`` task: with no ``NERVA_AUX_REVIEW_MODEL`` override it runs on the active local
chat model and reads the conversation whole, newest turns first, as far as one call
carries (:func:`replay_budget`: what the local backend says its window for that model is,
less the answer and the prompt, at most :data:`FULL_REPLAY_CHARS`; a backend that reports
no window gets :data:`UNKNOWN_WINDOW_CHARS`, the bound the review always had). Pointed at
a different model it reads the last :data:`DIGEST_TAIL_TURNS` turns verbatim under a
digest of the older ones (Hermes's ``USER: …`` / ``ASSISTANT[tools: …]: …`` lines, cut
short), in two thirds and one third of the same budget. The digest is cut from the stored
turns by code — no model writes it — so it holds nothing the turns did not.

**Notifications.** ``display.memory_notifications`` (``off`` | ``on`` | ``verbose``)
decides only the line the owner reads beside a later reply; the writes are decided by the
table above. ``on`` names what happened without content; ``verbose`` adds a short preview
of each fact and what was not kept, and why.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("jarvis.learning.review")

NOTIFY_SETTING = "display.memory_notifications"
NOTIFY_MODES: tuple[str, ...] = ("off", "on", "verbose")
NOTIFY_DEFAULT = "on"
#: The whole conversation, as much as one local review call reads at most.
FULL_REPLAY_CHARS = 24_000
#: What a review reads on a backend that does not report its context window (the cap the
#: review's whole context had before H443), and the least it is given on a small one.
UNKNOWN_WINDOW_CHARS = 6_000
MIN_REPLAY_CHARS = 2_000
#: A token is taken as three characters, and the prompt's fixed part as this many tokens.
CHARS_PER_TOKEN = 3
PROMPT_OVERHEAD_TOKENS = 900
#: The digest replay: the newest turns verbatim, the older ones as short digest lines.
DIGEST_TAIL_TURNS = 24
DIGEST_TAIL_CHARS = 8_000
DIGEST_OLDER_CHARS = 4_000
REPLAY_TURN_CHARS = 2_000
DIGEST_USER_CHARS = 300
DIGEST_ASSISTANT_CHARS = 200
DIGEST_HEADER = ("[Earlier conversation digest: older turns cut short to bound the review's cost on its "
                 "own model. Recent turns follow verbatim below.]")
PREVIEW_CHARS = 80
#: The legs a review has, each one a tool the reviewed turn's posture must have been offered.
LEG_TOOLS: dict[str, str] = {"memory": "memory", "skills": "skill_propose"}


@dataclass(frozen=True)
class ReviewScope:
    """What the review inherits from the turn (see the module docstring)."""

    session_id: str
    #: The turn's principal is the owner (an admin credential, a paired owner sender).
    owner: bool = False
    #: No principal was bound and the turn came in on an operator channel (the local
    #: voice loop, the terminal): the hub's own machine, nobody it can name.
    local_unbound: bool = False
    #: The turn read untrusted content, or its conversation is not on the clean list
    #: (an earlier turn did, or it was not watched from its first turn).
    tainted: bool = True
    #: The turn's posture was offered the ``memory`` tool / the ``skill_propose`` tool.
    memory_offered: bool = False
    skills_offered: bool = False
    #: The approval dial as the turn ran (``auto`` | ``ask`` | ``off``).
    mode: str = "ask"
    channel: str = ""

    @property
    def admitted(self) -> bool:
        """Whether this turn is reviewed at all."""
        return self.owner or self.local_unbound

    def describe(self) -> dict:
        return {"owner": self.owner, "local_unbound": self.local_unbound, "tainted": self.tainted,
                "memory_offered": self.memory_offered, "skills_offered": self.skills_offered,
                "mode": self.mode, "channel": self.channel}


def memory_disposition(scope: ReviewScope | None, *, write_approval: bool) -> tuple[str, str]:
    """``(what, why)`` for the memory leg: ``write`` it, ``stage`` it for the owner, or
    ``drop`` it. *scope* None is a reviewer driven directly with no turn (a unit under
    test): only the gate decides. Every unknown resolves to the stricter side."""
    if scope is None:
        return ("stage", "write_approval") if write_approval else ("write", "")
    if not scope.admitted:
        return "drop", "not_owner"
    if scope.tainted:
        return "stage", "untrusted_content"
    if not scope.owner:
        return "stage", "no_principal"
    if not scope.memory_offered:
        return "stage", "memory_tool_withheld"
    if scope.mode != "auto":
        return "stage", f"approval_mode_{scope.mode}"
    if write_approval:
        return "stage", "write_approval"
    return "write", ""


STAGE_REASONS: dict[str, str] = {
    "write_approval": "memory write approval is on",
    "untrusted_content": "the conversation read untrusted content, or was not watched from its start",
    "no_principal": "the turn had no owner signed in",
    "memory_tool_withheld": "the turn was not offered the memory tool",
    "approval_mode_ask": "the approval dial is on ask",
    "approval_mode_off": "the approval dial is off",
}


# ── replay ───────────────────────────────────────────────────────────────────

def replay_mode(router: Any) -> str:
    """``full`` when the review runs on the active local chat model, ``digest`` when the
    auxiliary rail's ``review`` task is pointed at another one. Decided from the rail's
    own resolution; a rail that cannot resolve reads ``digest`` (the smaller replay)."""
    try:
        from ..llm.auxiliary_text import resolve_auxiliary_model

        active = getattr(router, "active_model", None)
        if not isinstance(active, str) or not active.strip():
            return "digest"
        return "full" if resolve_auxiliary_model("review", active) == active else "digest"
    except Exception:
        logger.debug("review replay: the review model could not be resolved; digest replay", exc_info=True)
        return "digest"


def replay_budget(router: Any, max_tokens: int) -> int:
    """How many characters of conversation one review call may carry: the window the
    local backend reports for the review's model (read, never probed), less the answer's
    *max_tokens* and the prompt's fixed part; :data:`UNKNOWN_WINDOW_CHARS` when it reports
    none or cannot be asked. Between :data:`MIN_REPLAY_CHARS` and :data:`FULL_REPLAY_CHARS`."""
    try:
        from ..llm.auxiliary_text import resolve_auxiliary_model
        from ..llm.effective_window import resolve_effective_window

        model = resolve_auxiliary_model("review", getattr(router, "active_model", None))
        window = resolve_effective_window(router.local_backend, model)
        tokens = window.tokens if window.valid else None
    except Exception:
        tokens = None
    if type(tokens) is not int or tokens <= 0:
        return UNKNOWN_WINDOW_CHARS
    answer = max_tokens if type(max_tokens) is int and max_tokens > 0 else 512
    room = (tokens - answer - PROMPT_OVERHEAD_TOKENS) * CHARS_PER_TOKEN
    return max(MIN_REPLAY_CHARS, min(FULL_REPLAY_CHARS, room))


def _conversation_turns(turns: Any) -> list[dict]:
    """The stored turns that are conversation: commands and their replies left out."""
    from ..commands import CommandRegistry

    kept: list[dict] = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        content = turn.get("content")
        if content is None or not str(content).strip():
            continue
        if turn.get("agent_id") == "commands" or (
                turn.get("role") == "user" and CommandRegistry.parse(str(content).strip()) is not None):
            continue
        kept.append(turn)
    return kept


def _verbatim(turns: list[dict], limit: int) -> tuple[list[str], int]:
    """The newest of *turns* as ``role: content`` lines within *limit* characters, oldest
    first, and how many turns were taken (contiguous from the end)."""
    lines: list[str] = []
    used = 0
    for turn in reversed(turns):
        line = f"{turn.get('role') or '?'}: {str(turn.get('content'))[:REPLAY_TURN_CHARS]}"
        sep = 1 if lines else 0
        if used + sep + len(line) > limit:
            break
        lines.append(line)
        used += sep + len(line)
    return list(reversed(lines)), len(lines)


def _digest_line(turn: dict) -> str:
    text = " ".join(str(turn.get("content") or "").split())
    if turn.get("role") == "user":
        return f"USER: {text[:DIGEST_USER_CHARS]}"
    tools = [str(name) for name in (turn.get("tools") or []) if isinstance(name, str)][:8]
    label = f"ASSISTANT[tools: {', '.join(tools)}]" if tools else "ASSISTANT"
    return f"{label}: {text[:DIGEST_ASSISTANT_CHARS]}"


def build_replay(turns: Any, mode: str, budget: int = FULL_REPLAY_CHARS) -> dict:
    """The conversation as the review reads it, within *budget* characters: ``{"text",
    "mode", "verbatim", "digested", "omitted", "window"}`` (``window``: the stored turns
    the text was cut from). ``full`` keeps the newest turns whole. ``digest`` keeps the
    newest :data:`DIGEST_TAIL_TURNS` verbatim (two thirds of the budget, at most
    :data:`DIGEST_TAIL_CHARS`) under one-line digests of the older turns, the newest of
    those first to go in (the rest, at most :data:`DIGEST_OLDER_CHARS`). Anything else
    reads as digest."""
    kept = _conversation_turns(turns)
    budget = max(0, min(FULL_REPLAY_CHARS, budget if type(budget) is int else UNKNOWN_WINDOW_CHARS))
    if mode == "full":
        lines, taken = _verbatim(kept, budget)
        return {"text": "\n".join(lines), "mode": "full", "verbatim": taken, "digested": 0,
                "omitted": len(kept) - taken, "window": kept[len(kept) - taken:]}
    tail_chars = min(DIGEST_TAIL_CHARS, budget * 2 // 3)
    older_chars = min(DIGEST_OLDER_CHARS, budget - tail_chars) - len(DIGEST_HEADER) - 1
    lines, taken = _verbatim(kept[-DIGEST_TAIL_TURNS:], tail_chars)
    older = kept[:len(kept) - taken]
    digest: list[str] = []
    used = 0
    for turn in reversed(older):
        line = _digest_line(turn)
        if used + 1 + len(line) > older_chars:
            break
        digest.append(line)
        used += 1 + len(line)
    digest.reverse()
    parts = ([DIGEST_HEADER, *digest] if digest else []) + lines
    return {"text": "\n".join(parts), "mode": "digest", "verbatim": taken, "digested": len(digest),
            "omitted": len(older) - len(digest),
            "window": older[len(older) - len(digest):] + kept[len(kept) - taken:]}


# ── notifications ────────────────────────────────────────────────────────────

def notification_mode(get_setting: Callable[[str, Any], Any] | None) -> str:
    """``display.memory_notifications`` as stored. A value that is not one of the three,
    or a read that fails, is ``on``: the line that carries no content."""
    try:
        raw = get_setting(NOTIFY_SETTING, NOTIFY_DEFAULT) if callable(get_setting) else NOTIFY_DEFAULT
    except Exception:
        return NOTIFY_DEFAULT
    if raw is False:                      # a YAML 1.1 bare ``off``
        return "off"
    return raw if isinstance(raw, str) and raw in NOTIFY_MODES else NOTIFY_DEFAULT


def _preview(text: Any) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= PREVIEW_CHARS else flat[:PREVIEW_CHARS - 1].rstrip() + "…"


def notification_lines(result: Any, mode: str, label: str = "Background review") -> str:
    """The one line a review leaves for the owner, or "" (nothing happened, the mode is
    ``off``, or the pass did not run). ``on`` joins the pass's actions, which name rings,
    counts and skills and never a fact. ``verbose`` adds each written or proposed fact's
    preview and what was found and not kept."""
    if mode not in ("on", "verbose") or not isinstance(result, dict) or not result.get("ran"):
        return ""
    actions = [str(a).strip() for a in result.get("actions") or [] if str(a or "").strip()]
    if mode == "verbose":
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        extra: list[str] = []
        for kind, mark in (("written", "➕"), ("proposed", "⏳")):
            for row in details.get(kind) or []:
                if isinstance(row, dict) and row.get("text"):
                    extra.append(f"{mark} {row.get('label') or row.get('target')}: “{_preview(row['text'])}”")
        for row in details.get("skipped") or []:
            if isinstance(row, dict) and row.get("count"):
                extra.append(f"{row['count']} not kept ({row.get('why') or 'refused'})")
        actions += extra
    return f"{label}: {'; '.join(actions)}" if actions else ""


class ReviewNotice(str):
    """A review's line as it waits for a reply that can show it: the text is the ``on``
    line (what happened, no content), :attr:`verbose` the same with the previews. Which
    one is shown, if any, is decided where it is shown."""

    verbose: str

    def __new__(cls, on: str, verbose: str = ""):
        instance = super().__new__(cls, on)
        instance.verbose = verbose or on
        return instance


def review_notice(result: Any, label: str = "Background review") -> ReviewNotice | None:
    """The notice a pass leaves, or None for a pass that did not run, did nothing and
    skipped nothing. A pass that only found facts it did not keep has no ``on`` line (the
    text is empty: nothing happened) and a ``verbose`` one that says what and why."""
    line = notification_lines(result, "on", label)
    verbose = notification_lines(result, "verbose", label)
    if not line and not verbose:
        return None
    notice = ReviewNotice(line, verbose)
    notice.verbose = verbose
    return notice


__all__ = [
    "DIGEST_HEADER", "DIGEST_TAIL_TURNS", "FULL_REPLAY_CHARS", "LEG_TOOLS", "NOTIFY_DEFAULT", "NOTIFY_MODES",
    "NOTIFY_SETTING", "STAGE_REASONS", "UNKNOWN_WINDOW_CHARS", "ReviewNotice", "ReviewScope", "build_replay",
    "memory_disposition", "replay_budget", "review_notice",
    "notification_lines", "notification_mode", "replay_mode",
]
