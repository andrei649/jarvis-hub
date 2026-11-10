"""
background_review.py — H20 per-turn learning distiller (the hermes learning loop,
governed the jarvis way).

After a completed turn, one structured-JSON LLM call reviews the exchange and
proposes: bounded **user/agent core facts**, **correction-ledger** entries
(H21.4), and **skill updates**. Code — not the model — then dispatches each
proposal through jarvis governance:

  * core facts     → injection-scanned, deduped, capped, then — as the turn the pass
                     reviews allows (H443, ``review_policy``) — written to the
                     CoreMemory ring, or held as a memory proposal the owner
                     decides (``memory.write_approval``, a turn that read untrusted
                     content, an approval dial on ask), or not kept at all;
  * corrections    → LearningModule.record_correction (pure signal, kept in process
                     memory only: it is not a durable write and is not held);
  * new skills     → SkillLoader.generate_skill → CDX-8 quarantine
                     (PENDING_REVIEW; owner approves via existing endpoint);
  * skill patches  → SkillProposalStore (pending) + optional
                     ActionApprovalQueue request — applied only by the curator
                     after owner approval, hash-checked against drift.

This is deliberately NOT a tool-calling agent fork (hermes's design): a single
structured call is cheaper on a local GPU, and the dispatch surface stays in
audited code instead of free-form tool calls. Review prompts and anti-capture
rules are adapted from hermes-agent `agent/background_review.py`
(Nous Research, MIT) — see LICENSES/THIRD_PARTY.md.

Default-OFF: callers gate on ``cognition.review_enabled`` (master-gated,
Product Posture O26-P2.4). Pure and offline-testable — the LLM call, stores,
loader, clock and settings are all injected.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path

logger = logging.getLogger("jarvis.learning.review")

# ── the review prompt (adapted from hermes-agent, structured-output form) ─────

REVIEW_PROMPT = """\
You are Jarvis's background reviewer. A conversation turn just finished. Decide
what durable knowledge it produced. Most turns produce NOTHING — that is fine;
only real signal counts.

Conversation (recent context, then the turn under review):
{context}

{focus}Signals worth capturing:
  1. USER FACTS — the user revealed persona, preferences, personal details, or
     expectations about how the assistant should behave.
  2. AGENT FACTS — a durable operational fact the assistant should remember
     about its own situation or setup.
  3. CORRECTIONS — the user corrected the assistant's style, approach, format,
     or a factual claim. Capture the original vs the corrected form.
  4. SKILL UPDATES — a non-trivial technique, workflow fix, or pitfall emerged
     that a future session doing this CLASS of task needs. Prefer PATCHING an
     existing skill; CREATE a new one only when no existing skill covers the
     class, and name it at the class level (never a one-off task name).

Do NOT capture (these harden into stale self-imposed constraints):
  - environment-dependent failures (missing binaries, unconfigured creds);
  - negative claims about tools ("X is broken", "cannot use Y");
  - transient errors that resolved within the conversation;
  - one-off task narratives that are not a reusable class of work.

Known skills (patch targets): {skills}

Respond with ONLY valid JSON (no markdown fences, no explanation):
{{
  "user_facts": ["short durable fact about the user"],
  "agent_facts": ["short durable operational fact"],
  "corrections": [{{"original": "...", "corrected": "..."}}],
  "skill_updates": [
    {{"kind": "patch", "name": "existing-skill-name", "content": "full improved SKILL.md body"}},
    {{"kind": "new", "task": "class-level task description", "steps": ["step 1", "step 2"]}}
  ],
  "nothing": false
}}
Set "nothing": true (with empty lists) when there is no real signal."""


#: H465 — how much of a conversation an on-demand review reads: the newest turns whole,
#: each cut at REFINE_TURN_CHARS, up to this many characters in all.
REFINE_SNAPSHOT_CHARS = 12_000
REFINE_TURN_CHARS = 2_000
REFINE_FOCUS_CHARS = 200
#: An on-demand review runs inside the /refine command's turn, which holds the session's
#: turn lease: it is bounded below the lease's wait (180 s), so a message sent meanwhile
#: is answered busy for at most this long, never forever (review-H465 m-5).
REFINE_TIMEOUT_S = 150.0


def conversation_snapshot(turns, limit: int = REFINE_SNAPSHOT_CHARS,
                          per_turn: int = REFINE_TURN_CHARS) -> str:
    """A conversation as ``role: content`` lines for an on-demand review (H465).

    The newest turns are kept first, each cut at ``per_turn`` characters, until the next
    one would pass ``limit``; they are returned oldest first, contiguous (a turn too long
    for what is left ends the snapshot rather than being skipped). Slash commands and the
    hub's replies to them are not conversation, so neither is kept: ``/refine`` on a chat
    of commands only has nothing to review. A copy: the session is only read, never
    changed."""
    from ..commands import CommandRegistry

    lines: list[str] = []
    used = 0
    for turn in reversed(list(turns or [])):
        if not isinstance(turn, dict):
            continue
        content = turn.get("content")
        if content is None or not str(content).strip():
            continue
        if turn.get("agent_id") == "commands" or (
                turn.get("role") == "user" and CommandRegistry.parse(str(content).strip()) is not None):
            continue
        line = f"{turn.get('role') or '?'}: {str(content)[:per_turn]}"
        sep = 1 if lines else 0
        if used + sep + len(line) > limit:
            break
        lines.append(line)
        used += sep + len(line)
    return "\n".join(reversed(lines))


def _focus_line(focus: str) -> str:
    text = " ".join(str(focus or "").split())[:REFINE_FOCUS_CHARS]
    return f"Focus for this review: {text}\n\n" if text else ""


#: Corrections one review may record, apart from the facts' cap (review-H465d nit 3: a
#: review_max_facts of 0 also switched corrections off, and the reply said "nothing").
MAX_CORRECTIONS = 3

#: A bracketed ``[… error …]``, closed on its own line and by its own bracket: an unclosed
#: ``[Note: I hit an error …``, or one a later ``[1]`` or link would close, is prose
#: (review-H465e nit 7, review-H465f nit 3).
_BACKEND_ERROR = re.compile(r'\[(?:[A-Za-z][^\]\[{"\n]{0,80})?error[^\]\[\n]*\]', re.IGNORECASE)


#: H443 — what a skill proposal from a conversation that is not clean carries, on its
#: approval card and in the pass's action line.
_UNCLEAN = ", from a conversation that read untrusted content or was not watched from its start"


def _shipped(path) -> bool:
    try:
        from agents.core.skills.loader import _shipped_location

        return bool(path) and _shipped_location(Path(path))
    except Exception:
        return False


def _degraded(raw: object) -> bool:
    """A backend's failure reply, not a review: the local degraded message (``⚠️``) or a
    bracketed ``[… error: …]``. A reply that merely starts with ``[`` (a JSON array, an
    ``[analysis]`` preamble) is the model's answer, and is parsed (review-H465c nit 2)."""
    if not isinstance(raw, str):
        return False
    return raw.startswith("⚠️") or bool(_BACKEND_ERROR.match(raw))


def _thinking_exhausted(raw: object) -> bool:
    from ..llm.base import THINKING_EXHAUSTED_REPLY

    return raw == THINKING_EXHAUSTED_REPLY


def _default_detect(text: str) -> list:
    try:
        from ..security.quarantine import detect_injection
        return detect_injection(text)
    except Exception:                                    # pragma: no cover
        return []


def parse_review_json(raw: str) -> dict:
    """Extract the reviewer's JSON defensively (reflector-style). Never raises."""
    empty = {"user_facts": [], "agent_facts": [], "corrections": [],
             "skill_updates": [], "nothing": True}
    keys = ("user_facts", "agent_facts", "corrections", "skill_updates", "nothing")
    # An answer with no readable JSON object is not a review that found nothing: a reply
    # cut off by the token cap looks exactly like this (review-H465b m-2).
    unparsed = {**empty, "unparsed": True}
    if not raw:
        return unparsed
    try:
        start, end = raw.find("{"), raw.rfind("}") + 1
        if not (0 <= start < end):
            return unparsed
        data = json.loads(raw[start:end])
        if not isinstance(data, dict):
            return unparsed
    except Exception:
        return unparsed
    if not any(key in data for key in keys):
        return unparsed               # {} or {"error": …}: not a review (review-H465c nit 1)

    def _str_list(key):
        vals = data.get(key)
        return [str(v).strip() for v in vals if str(v or "").strip()] if isinstance(vals, list) else []

    corrections = []
    for c in data.get("corrections") or []:
        if isinstance(c, dict) and str(c.get("corrected") or "").strip():
            corrections.append({"original": str(c.get("original") or "").strip(),
                                "corrected": str(c.get("corrected") or "").strip()})
    updates = []
    for u in data.get("skill_updates") or []:
        if not isinstance(u, dict):
            continue
        kind = str(u.get("kind") or "").strip().lower()
        if kind == "patch" and str(u.get("name") or "").strip() and str(u.get("content") or "").strip():
            updates.append({"kind": "patch", "name": str(u["name"]).strip(),
                            "content": str(u["content"]).strip()})
        elif kind == "new" and str(u.get("task") or "").strip():
            steps = u.get("steps")
            steps = [str(s).strip() for s in steps if str(s or "").strip()] if isinstance(steps, list) else []
            updates.append({"kind": "new", "task": str(u["task"]).strip(), "steps": steps})
    return {
        "user_facts": _str_list("user_facts"),
        "agent_facts": _str_list("agent_facts"),
        "corrections": corrections,
        "skill_updates": updates,
        "nothing": bool(data.get("nothing", False)),
    }


class BackgroundReviewer:
    """Per-turn learning distiller — cadence-gated, budgeted, fail-quiet.

    Everything is injected so the reviewer is offline-testable:
      llm_call   async (prompt: str) -> str      (strict-local in production)
      living     LivingMemory or callable -> it  (core + user_core rings)
      skills     SkillLoader or None              (generate_skill quarantine path)
      learning   LearningModule or None           (correction ledger, H21.4)
      proposals  SkillProposalStore or None       (patch proposals, curator-applied)
      approvals  ActionApprovalQueue or None      (owner approval surface, H10.18)
    """

    def __init__(self, llm_call: Callable[[str], Awaitable[str]],
                 living=None, skills=None, learning=None,
                 proposals=None, approvals=None,
                 get_setting: Callable | None = None,
                 detect: Callable[[str], list] | None = None,
                 now: Callable[[], float] = time.monotonic,
                 audit=None, memory_proposals=None,
                 write_approval: Callable[[], bool] | None = None,
                 require_scope: bool = False):
        self._llm = llm_call
        self._living = living
        #: H443 — the ledger of memory writes held for the owner (or a callable returning
        #: it); None: a write that must be held is not kept at all.
        self._memory_proposals = memory_proposals
        #: H443 — whether ``memory.write_approval`` is on, read per pass off the event
        #: loop. The hub passes the settings store's own read; a reviewer built without
        #: one that requires a scope reads the store too, and only a bare unit reads off.
        if write_approval is None and require_scope:
            from .memory_proposals import write_approval_required as write_approval
        self._write_approval = write_approval or (lambda: False)
        #: H443 — the hub's reviewer refuses a pass that names no turn scope: what the
        #: review may write is inherited from the turn, never assumed.
        self._require_scope = bool(require_scope)
        #: H422 — the intent log (or a callable returning it) that records a fact a curated
        #: ring refused (``memory.write_refused``); None records nothing, the log line stays.
        self._audit = audit
        self._skills = skills
        self._learning = learning
        self._proposals = proposals
        self._approvals = approvals
        self._get = get_setting or (lambda k, d=None: d)
        self._detect = detect or _default_detect
        self._now = now
        self._turns_since = 0
        self._last_run_ts: float | None = None
        self._day = ""
        self._day_count = 0
        self._on_demand = False
        self._in_flight = 0
        self.last_result: dict | None = None
        self._warned_budget: object = None
        self._quiet_day = ""          # the day a per-turn cut-off was last logged
        self._day_cut_offs = 0        # today's per-turn passes the model cut off
        self._demand_unit_day: str | None = None

    def _budget(self) -> int:
        """The day's review budget. 0 means no reviews. A value that is not a number, or
        is outside the declared 0..1000 (a hand-edited -3 is not "reviews off"), is named
        in the log once and the default used (review-H465 nit 4, review-H465e nit 2)."""
        from agents.core.settings_db import bounded_learning_int

        raw = self._get("learning.review_daily_budget", 20)
        if raw is None or raw == "":
            return 20
        value = bounded_learning_int("review_daily_budget", raw, -1)
        if value == 0:
            try:
                zero = float(raw) == 0
            except (TypeError, ValueError):
                zero = True
            if not zero:                 # a hand-edited -0.5 or 0.9 is not "reviews off"
                value = -1               # (review-H465f nit 5)
        if value < 0:
            if self._warned_budget != repr(raw):      # once per value (NaN != NaN, its repr is equal)
                self._warned_budget = repr(raw)
                logger.warning("learning.review_daily_budget %r is not a number from 0 to 1000; "
                               "20 is used", raw)
            return 20
        return value

    def _number(self, key: str, default: int) -> int:
        """A declared learning knob whose 0 is a real value (no facts kept, no idle gap):
        only an unset or unreadable one falls back to *default* (review-H465c m-2)."""
        from agents.core.settings_db import bounded_learning_int

        # Out of its declared bounds (a row written before them, restored or edited by
        # hand) reads as the default, as an unreadable one does (review-H465d nit 4).
        return bounded_learning_int(key.removeprefix("learning."), self._get(key, default), default)

    def _roll_day(self) -> None:
        today = date.today().isoformat()
        if today != self._day:
            self._day, self._day_count, self._day_cut_offs = today, 0, 0

    # ── cadence / budget gate ────────────────────────────────────────────────

    def should_run(self) -> tuple[bool, str]:
        """Local-GPU cost policy: cadence knob + a per-day review budget."""
        self._turns_since += 1
        if self._on_demand:
            return False, "on_demand"
        self._roll_day()
        if self._day_count >= self._budget():
            return False, "daily_budget"
        return (False, refused) if (refused := self._cadence_refusal()) else (True, "ok")

    def _cadence_refusal(self) -> str:
        """Why the per-turn cadence says not yet, or "". Asked where a turn is admitted and
        again where its pass starts: turns that end in one burst were all admitted before
        any pass reset the count (review-H465e nit 6)."""
        cadence = str(self._get("learning.review_cadence", "every_turn") or "every_turn")
        if cadence == "every_n_turns":
            if self._turns_since < self._number("learning.review_every_n", 3):
                return "cadence_n"
        elif cadence == "idle_gap":
            gap = self._number("learning.review_idle_gap_s", 90)
            if self._last_run_ts is not None and (self._now() - self._last_run_ts) < gap:
                return "cadence_idle"
        return ""

    # ── the review pass ──────────────────────────────────────────────────────

    async def run_on_demand(self, history: str, *, focus: str = "", scope=None) -> dict:
        """H465 — the review the owner asked for (``/refine [focus]``), over a snapshot.

        It skips the cadence gate (the owner asked now) but spends the daily budget like
        any pass, keeps the strict-local model, and runs one at a time: a request while a
        review runs is refused ``busy``, not queued, and a per-turn pass that would start
        while it runs is skipped (``run`` refuses it, ``on_demand``). The review is bounded
        at REFINE_TIMEOUT_S, below the turn lease's wait. A review that times out or is
        cancelled costs no budget."""
        if (refused := self._scope_refusal(scope)):
            return {"ran": False, "reason": refused, "actions": []}
        if self._on_demand or self._in_flight:
            return {"ran": False, "reason": "busy", "actions": []}
        self._roll_day()
        budget = self._budget()
        if budget == 0:
            return {"ran": False, "reason": "reviews_off", "actions": []}
        if self._day_count >= budget:
            # When per-turn passes the model cut off spent most of the day, the budget is
            # not what to raise: the reply names the token cap (review-H465d m-1). One
            # cut-off among real reviews is not that (review-H465e m-1).
            cut = self._day_cut_offs
            reason = "daily_budget_cut_off" if cut and 2 * cut >= self._day_count else "daily_budget"
            return {"ran": False, "reason": reason, "actions": []}
        self._on_demand = True
        self._demand_unit_day = None      # set by _run on the day it spends the unit
        try:
            # The per-turn cadence is the per-turn reviews' own: an owner's /refine
            # neither resets it nor delays the next one (review-H465 nit 3).
            return await asyncio.wait_for(
                self.run("", "", history=history, focus=focus, context_chars=REFINE_SNAPSHOT_CHARS,
                         cadence=False, on_demand=True, scope=scope),
                timeout=REFINE_TIMEOUT_S)
        except TimeoutError:
            self._refund_demand_unit()                              # no review was had
            result = {"ran": False, "reason": "llm_timeout", "actions": []}
            self.last_result = result
            return result
        except asyncio.CancelledError:
            self._refund_demand_unit()                              # review-H465b nit 6
            raise
        finally:
            self._on_demand = False

    def _refund_demand_unit(self) -> None:
        """Give back the unit a /refine that timed out or was cancelled spent, on the day
        _run spent it: never one it did not spend, never the next day's (review-H465f
        nit 1: the day taken before _run rolled could only differ where it was wrong)."""
        day, self._demand_unit_day = self._demand_unit_day, None
        if day is not None and day == self._day:
            self._day_count = max(0, self._day_count - 1)

    def _scope_refusal(self, scope) -> str:
        """H443 — why this pass may not run at all for the turn it names, or "": the hub's
        reviewer needs a scope, and a turn that is not the owner's is not reviewed (no
        model call, no budget spent)."""
        if scope is None:
            return "no_scope" if self._require_scope else ""
        return "" if getattr(scope, "admitted", False) is True else "not_owner"

    async def run(self, user_text: str, assistant_text: str, history: str = "", *,
                  focus: str = "", context_chars: int = 6000, cadence: bool = True,
                  on_demand: bool = False, scope=None) -> dict:
        """One review pass. Never raises — failures return a summary dict.

        The exclusion is taken here, not only where a pass is spawned (review-H465b m-1):
        a per-turn pass spawned before a /refine started waits on the memory lock and can
        enter only after the /refine set its flag, so it is refused ``on_demand`` then."""
        if (refused := self._scope_refusal(scope)):
            return {"ran": False, "reason": refused, "actions": []}
        if self._on_demand and not on_demand:
            return {"ran": False, "reason": "on_demand", "actions": []}
        self._in_flight += 1
        try:
            return await self._run(user_text, assistant_text, history, focus=focus,
                                   context_chars=context_chars, cadence=cadence, on_demand=on_demand,
                                   scope=scope)
        finally:
            self._in_flight -= 1

    async def _run(self, user_text: str, assistant_text: str, history: str, *,
                   focus: str, context_chars: int, cadence: bool, on_demand: bool, scope=None) -> dict:
        # Who the pass's proposals and approval cards name, passed down rather than kept
        # on the instance, so no other pass can read it (review-H465b m-1).
        label = "refine" if on_demand else "background_review"
        self._roll_day()
        if not on_demand and self._day_count >= self._budget():
            # Checked again where the unit is spent: passes spawned in one burst all saw
            # budget left in should_run (review-H465d nit 6).
            return {"ran": False, "reason": "daily_budget", "actions": []}
        if cadence and (refused := self._cadence_refusal()):
            return {"ran": False, "reason": refused, "actions": []}
        if cadence:
            # A pass uses up the turns that admitted it and no more: in a burst, the turns
            # after it still count toward the next pass (review-H465f nit 2).
            every_n = str(self._get("learning.review_cadence", "every_turn") or "") == "every_n_turns"
            self._turns_since = (max(0, self._turns_since - self._number("learning.review_every_n", 3))
                                 if every_n else 0)
            self._last_run_ts = self._now()
        self._day_count += 1
        if on_demand:
            self._demand_unit_day = self._day
        # The day this pass spent its unit on: a pass still waiting on the model at
        # midnight refunds or counts against that day, never the next (review-H465e nit 4).
        spent_day = self._day
        context = "\n".join(part for part in (
            history.strip(),
            f"user: {user_text.strip()}" if user_text else "",
            f"assistant: {assistant_text.strip()}" if assistant_text else "",
        ) if part)
        skills_list = ", ".join(sorted(self._skill_names())[:40]) or "(none)"
        prompt = REVIEW_PROMPT.format(context=context[:context_chars], skills=skills_list,
                                      focus=_focus_line(focus))

        try:
            raw = await self._llm(prompt)
        except asyncio.CancelledError:
            # H403: a new user turn on the session cancels its in-flight per-turn review
            # so the model is free for the reply. No review was had: the unit goes back,
            # on the day it was spent. A /refine cut short is refunded by run_on_demand
            # (its wait_for cancels this coroutine too): one refund, not two.
            if not on_demand and self._day == spent_day:
                self._day_count = max(0, self._day_count - 1)
            raise
        except Exception as e:
            logger.debug("background review LLM call failed: %s", e)
            raw = None
        if _thinking_exhausted(raw):
            # The model answered but spent its tokens thinking: that is not "no model"
            # (review-H465b m-2).
            return self._cut_off("review_cut_off", on_demand, spent_day)
        review = parse_review_json(raw) if isinstance(raw, str) else None
        if raw is None or review is None or (_degraded(raw) and review.get("unparsed")):
            # A local backend that is configured but down answers with a degraded reply
            # instead of raising: that is no review, and it costs no budget (review-H465 M-1).
            # A reply that parses as a review is the model's answer, whatever it opens
            # with (review-H465d nit 1: "[{... error ...}]" is a review).
            if self._day == spent_day:
                self._day_count = max(0, self._day_count - 1)
            result = {"ran": False, "reason": "llm_error", "actions": []}
            self.last_result = result
            return result

        if review.get("unparsed"):
            # Cut off by the token cap or malformed: nothing can be kept, and it is not
            # "nothing worth keeping" (review-H465b m-2).
            return self._cut_off("review_unparsed", on_demand, spent_day)
        actions: list[str] = []
        counts = {"facts": 0, "blocked": 0, "corrections": 0,
                  "skills_new": 0, "skill_patches": 0, "proposed": 0}
        #: H443 — what a verbose notification previews (the facts written or held) and
        #: what was found and not kept. The facts' text lives here only: never in
        #: ``actions``, and ``status()`` leaves it out.
        details: dict = {"written": [], "proposed": [], "skipped": []}
        max_facts = self._number("learning.review_max_facts", 3)

        living = self._living() if callable(self._living) else self._living
        # H422: the owner's memory switch (memory.core_enabled, which no product posture
        # sets) keeps every writer out of the curated rings, this one too. Read after the
        # model answered, before any write, so an `off` taken while it thought holds.
        switched_off = living is not None and not self._rings_on()
        if (living is None or switched_off) and on_demand:
            # Said to the owner who asked, not dropped silently (review-H465 m-3), counting
            # only facts the injection scan would let through (review-H465b nit 5). The
            # per-turn pass stays quiet: memory being off is not news every turn.
            found = sum(1 for fact in review["user_facts"][:max_facts] + review["agent_facts"][:max_facts]
                        if not self._detect(fact))
            if found:
                why = ("the owner's memory switch is off (memory.core_enabled; `nerva memory on`)"
                       if switched_off else "living memory is off (cognition.memory_enabled)")
                actions.append(f"{found} fact(s) found but not kept: {why}")
        if switched_off:
            living = None
        # H443: what the memory leg may do is inherited from the turn (and read from the
        # settings store, off the event loop, after the model answered): write, hold for
        # the owner, or keep nothing.
        disposition, why_held = await asyncio.to_thread(self._memory_disposition, scope)
        rings = (("user", review["user_facts"][:max_facts], getattr(living, "user_core", None), "User profile"),
                 ("memory", review["agent_facts"][:max_facts], getattr(living, "core", None), "Core memory"))
        if disposition == "write":
            # H423: a ring put waits for the ring file's lock (up to LOCK_TIMEOUT_S per
            # fact), so the writes run in a worker thread and never stall the event loop.
            for target, facts, store, ring_label in rings:
                await asyncio.to_thread(self._put_facts, facts, store, ring_label, actions, counts,
                                        label, on_demand, details, target)
        elif disposition == "stage":
            await asyncio.to_thread(self._stage_facts, rings, scope, why_held, label, actions, counts, details)
        else:
            dropped = sum(len(facts) for _target, facts, _store, _label in rings)
            if dropped:
                details["skipped"].append({"count": dropped, "why": "the turn is not the owner's"})

        if not max_facts and on_demand:
            found = sum(1 for fact in review["user_facts"] + review["agent_facts"] if not self._detect(fact))
            if found:
                actions.append(f"{found} fact(s) found but not kept: learning.review_max_facts is 0")
        for corr in review["corrections"][:MAX_CORRECTIONS]:
            if self._detect(f"{corr['original']} {corr['corrected']}"):
                counts["blocked"] += 1          # an injected "correction" is no correction
                continue
            try:
                if self._learning is not None:
                    self._learning.record_correction(corr["original"], corr["corrected"])
                    counts["corrections"] += 1
            except Exception:
                logger.debug("correction record skipped", exc_info=True)
        if counts["corrections"]:
            actions.append(f"{counts['corrections']} correction(s) recorded")
        if counts["blocked"]:
            # Facts and corrections the injection scan refused: neither written nor held.
            details["skipped"].append({"count": counts["blocked"], "why": "flagged as a prompt injection"})

        skill_updates = review["skill_updates"][:2]
        if scope is not None and getattr(scope, "skills_offered", False) is not True:
            # H443: the turn's posture was not offered the skill tools, so its review
            # proposes no skill either.
            if skill_updates:
                details["skipped"].append({"count": len(skill_updates),
                                           "why": "the turn was not offered the skill tools"})
            skill_updates = []
        # H443: a skill change proposed from a conversation that is not clean says so
        # where the owner decides it (it is quarantined or waits for approval either way).
        unclean = scope is not None and getattr(scope, "tainted", True) is not False
        for update in skill_updates:
            if update["kind"] == "new":
                if self._dispatch_new_skill(update, actions, label, unclean):
                    counts["skills_new"] += 1
            else:
                if self._dispatch_patch(update, actions, label, unclean):
                    counts["skill_patches"] += 1

        result = {"ran": True, "nothing": review["nothing"] and not actions,
                  "actions": actions, "counts": counts, "ts": time.time(), "details": details}
        self.last_result = result
        return result

    def _cut_off(self, reason: str, on_demand: bool, spent_day: str) -> dict:
        """A generation that ran and gave no usable review. The owner who asked (/refine)
        gets the unit back; a per-turn pass spends it, since the model did run to its
        token cap, so the daily budget still caps local GPU use when a model always
        truncates (review-H465c m-1). The per-turn case is logged once a day."""
        if self._day == spent_day:            # a day that is over has nothing left to count
            if on_demand:
                self._day_count = max(0, self._day_count - 1)
            else:
                self._day_cut_offs += 1
                if self._quiet_day != self._day:
                    self._quiet_day = self._day
                    logger.info("learning review: %s (logged once a day)",
                                "the local model spent its answer thinking; raise learning.review_max_tokens"
                                if reason == "review_cut_off" else
                                "the local model's review was cut off or malformed; if it was cut off, "
                                "raise learning.review_max_tokens")
        result = {"ran": False, "reason": reason, "actions": []}
        self.last_result = result
        return result

    # ── dispatch helpers (all fail-quiet) ────────────────────────────────────

    def _skill_names(self) -> list:
        try:
            return list(getattr(self._skills, "skills", {}).keys())
        except Exception:
            return []

    def _rings_on(self) -> bool:
        """H422 — the owner's memory switch as this reviewer's settings read it (fails
        closed: a switch that cannot be read keeps the facts out)."""
        from agents.core.memory_tool import switched_on

        return switched_on(self._get)

    def _audit_log(self):
        """The intent log this reviewer records refusals in (None: none)."""
        audit = self._audit
        if audit is not None and not callable(getattr(audit, "record", None)) and callable(audit):
            try:
                audit = audit()
            except Exception:
                logger.debug("review: the intent log could not be resolved", exc_info=True)
                return None
        return audit

    def _memory_disposition(self, scope) -> tuple[str, str]:
        """H443 — ``(write | stage | drop, why)`` for this pass's facts. Blocking (the
        gate is read from the settings store). A gate that cannot be read is on."""
        from .review_policy import memory_disposition

        try:
            gate = self._write_approval() is not False
        except Exception:
            logger.warning("review: memory.write_approval could not be read; writes are held", exc_info=True)
            gate = True
        return memory_disposition(scope, write_approval=gate)

    def _stage_facts(self, rings, scope, why: str, actor: str, actions, counts, details) -> None:
        """H443 — hold this pass's facts for the owner instead of writing them: one
        proposal, one approval card. Checked before it is staged as a write is before it
        lands (the injection scan, the fact's length, a fact the ring already holds or
        that already waits), so the owner is not asked about a write that would be
        refused. Blocking: run off the event loop. Nothing is written to a ring here."""
        from .memory_proposals import TARGET_LABELS
        from .review_policy import STAGE_REASONS

        store = self._memory_proposals() if callable(self._memory_proposals) else self._memory_proposals
        operations: list[dict] = []
        skipped = {"memory_off": 0, "too_long": 0}
        try:
            waiting = store.pending_texts() if store is not None else set()
        except Exception:
            waiting = set()
        for target, facts, ring, _label in rings:
            for fact in facts:
                text = " ".join(str(fact or "").split())
                if not text:
                    continue
                if self._detect(text):
                    counts["blocked"] += 1
                    logger.warning("review fact blocked (injection-flagged): %.60s…", text)
                    continue
                if ring is None or not hasattr(ring, "put"):
                    skipped["memory_off"] += 1
                    continue
                limit = getattr(ring, "fact_max_chars", None)
                if isinstance(limit, int) and len(text) > limit:
                    skipped["too_long"] += 1
                    continue
                try:
                    if text in ring.list() or (target, text) in waiting:
                        continue                  # already kept, or already waiting
                except Exception:
                    logger.debug("review: a ring could not be listed before staging", exc_info=True)
                operations.append({"target": target, "text": text})
        if skipped["too_long"]:
            details["skipped"].append({"count": skipped["too_long"], "why": "longer than one fact may be"})
        if skipped["memory_off"] and scope is not None:
            details["skipped"].append({"count": skipped["memory_off"], "why": "memory is off"})
        if not operations:
            return
        queue = self._approvals
        if store is None or queue is None:
            details["skipped"].append({"count": len(operations),
                                       "why": "they need your approval and the approval queue is not available"})
            actions.append(f"{len(operations)} fact(s) found but not kept: they need approval and "
                           "the approval queue is not available")
            return
        try:
            record = store.propose(operations, origin=actor,
                                   session_id=str(getattr(scope, "session_id", "") or ""),
                                   reason=why, tainted=bool(getattr(scope, "tainted", False)))
        except Exception:
            logger.warning("review: the held memory write could not be saved; nothing was kept", exc_info=True)
            record = None
        if record is None:
            details["skipped"].append({"count": len(operations), "why": "the approval list is full or unavailable"})
            actions.append(f"{len(operations)} fact(s) found but not kept: the list of memory writes "
                           "waiting for approval is full or could not be saved")
            return
        try:
            store.queue_card(record["id"], queue, agent=actor)
        except Exception:
            # The proposal is saved; it gets its card at the next settle.
            logger.warning("review: the approval card for %s could not be queued yet", record["id"], exc_info=True)
        held = record["operations"]
        counts["proposed"] += len(held)
        for op in held:
            details["proposed"].append({"target": op["target"], "label": TARGET_LABELS.get(op["target"], op["target"]),
                                        "text": op["text"]})
        actions.append(f"{len(held)} memory write{'s' if len(held) != 1 else ''} proposed "
                       f"(pending approval: {STAGE_REASONS.get(why, why)})")

    def _put_facts(self, facts, store, label, actions, counts, actor: str = "background_review",
                   on_demand: bool = False, details: dict | None = None, target: str = "") -> None:
        from agents.core.cognition.memory import CoreMemoryOverBudget
        from agents.core.memory_tool import note_ring_refusal

        if store is None or not hasattr(store, "put"):
            return
        added = 0
        refused: list = []
        for fact in facts:
            if self._detect(fact):
                counts["blocked"] += 1
                logger.warning("review fact blocked (injection-flagged): %.60s…", fact)
                continue
            try:
                # Content comparison (not len) so ring-dedupe (list unchanged)
                # is not miscounted as a write, while ring-full rotation is.
                before = store.list() if hasattr(store, "list") else None
                changed = store.put(fact)
                if isinstance(changed, bool):
                    # H423: put rereads the ring file first, so only its own answer says
                    # whether this fact changed it.
                    added += int(changed)
                    if changed and details is not None:
                        details["written"].append({"target": target, "label": label, "text": str(fact)})
                    continue
                after = store.list() if hasattr(store, "list") else None
                if before is None or after != before:
                    added += 1
                    if details is not None:
                        details["written"].append({"target": target, "label": label, "text": str(fact)})
            except CoreMemoryOverBudget as exc:
                # H422: the ring refuses a fact past its character budget, its cap or the
                # per-fact limit, as Hermes's store refuses its own background review; no
                # curated fact rotates out to make room. Logged with the ring's usage and
                # recorded in the intent log; the other facts are still tried.
                refused.append(exc)
                note_ring_refusal(self._audit_log(), actor, exc)
            except Exception:
                # H423: a ring held by another writer, or hand-edited past reading back,
                # is not written over; the fact is not kept.
                logger.warning("core fact write skipped", exc_info=True)
        if added:
            counts["facts"] += added
            actions.append(f"{label} updated (+{added})")
        if refused and details is not None:
            details["skipped"].append({"count": len(refused),
                                       "why": f"the {label.lower()} ring is full or the fact too long"})
        if refused and on_demand:
            # Said to the owner who asked (/refine); the per-turn pass stays quiet, as it
            # does for a switched-off memory (the log line and the intent log keep it).
            full = [exc for exc in refused if exc.reason != "fact_too_long"]
            if full:
                last = full[-1]
                actions.append(f"{len(full)} fact(s) found but not kept: the {last.target} ring is full "
                               f"({last.usage}); remove or replace entries first")
            long = [exc for exc in refused if exc.reason == "fact_too_long"]
            if long:
                actions.append(f"{len(long)} fact(s) found but not kept: longer than the "
                               f"{long[0].fact_max_chars:,}-character limit for one fact")

    def _dispatch_new_skill(self, update, actions, label: str = "background_review",
                            unclean: bool = False) -> bool:
        """New skills ride the existing CDX-8 quarantine pipeline unchanged."""
        if self._skills is None or not hasattr(self._skills, "generate_skill"):
            return False
        try:
            # H349: the background review is the agent's own initiative (curated).
            name = self._skills.generate_skill(
                label, update["task"], update["steps"] or ["(captured from review)"],
                write_origin="background_review")
            if name:
                actions.append(f"Skill '{name}' proposed (quarantined, pending review)" + (_UNCLEAN if unclean else ""))
                return True
        except Exception:
            logger.debug("skill generation from review skipped", exc_info=True)
        return False

    def _dispatch_patch(self, update, actions, label: str = "background_review", unclean: bool = False) -> bool:
        """Patches never touch the live skill — they land as pending proposals."""
        if self._proposals is None:
            return False
        name = update["name"]
        skill = getattr(self._skills, "skills", {}).get(name) if self._skills else None
        if skill is None:
            logger.debug("review patch for unknown skill %r skipped", name)
            return False
        if not getattr(skill, "external", True) or _shipped(getattr(skill, "path", "")):
            # A bundled skill is product source, by its load or by where it lives; the apply
            # refuses it (review-H318b M-1, review-H318c n-6).
            logger.debug("review patch for bundled skill %r skipped", name)
            return False
        if self._detect(update["content"]):
            logger.warning("review skill patch blocked (injection-flagged): %s", name)
            return False
        from ..skills.validate import validate_skill_md

        problems = validate_skill_md(str(update["content"] or "").strip())
        if problems:
            # H350 — never a card for a change the apply would refuse.
            logger.info("review skill patch for %s skipped: not a valid SKILL.md (%s)", name,
                        "; ".join(str(p) for p in problems))
            return False
        try:
            current = (skill.path / "SKILL.md").read_text(encoding="utf-8")
        except Exception:
            logger.debug("could not read current SKILL.md for %s", name, exc_info=True)
            return False
        try:
            prop = self._proposals.propose(name, current, update["content"],
                                           origin=label)
            if prop is None:
                return False
            supersede = getattr(self._proposals, "supersede_older", None)
            if callable(supersede):
                # This pass's own older proposal goes, even when the text re-sent was
                # another origin's first (review-H318e n-2).
                supersede(prop, self._approvals, origin=label)
            if self._approvals is not None:
                try:
                    # The proposal's one card, bound to it in the ledger: only that card's
                    # decision is the owner's (review-H318b m-6), and a proposal that
                    # already has a card gets no second one (m-1).
                    self._proposals.queue_card(
                        prop["id"], self._approvals, agent=label,
                        summary=(f"/refine proposes a patch to skill '{name}'" if label == "refine"
                                 else f"Background review proposes a patch to skill '{name}'")
                        + (_UNCLEAN if unclean else ""))
                except Exception:
                    logger.debug("approval request for patch skipped", exc_info=True)
            actions.append(f"Skill '{name}' patch proposed (pending approval)" + (_UNCLEAN if unclean else ""))
            return True
        except Exception:
            logger.debug("skill patch proposal skipped", exc_info=True)
            return False

    def status(self) -> dict:
        # H443: the facts a pass wrote or held are not part of the status (it is read by
        # routes a user token reaches); the counts and the action lines are.
        last = self.last_result
        if isinstance(last, dict) and "details" in last:
            last = {key: value for key, value in last.items() if key != "details"}
        return {"available": True, "last_result": last,
                "reviews_today": self._day_count, "cut_offs_today": self._day_cut_offs, "day": self._day}


def action_summary(result, label: str = "Background review") -> str:
    """H403 — the one-line review action summary the owner sees (Hermes prints one after
    its fork): what the pass did, ``"; "``-joined, or "" for a pass that did not run or
    changed nothing — nothing is not news beside every reply."""
    if not isinstance(result, dict) or not result.get("ran"):
        return ""
    actions = [str(a).strip() for a in result.get("actions") or [] if str(a or "").strip()]
    return f"{label}: {'; '.join(actions)}" if actions else ""


__all__ = ["BackgroundReviewer", "REVIEW_PROMPT", "action_summary", "parse_review_json"]
