"""
background_review.py — H20 per-turn learning distiller (the hermes learning loop,
governed the jarvis way).

After a completed turn, one structured-JSON LLM call reviews the exchange and
proposes: bounded **user/agent core facts**, **correction-ledger** entries
(H21.4), and **skill updates**. Code — not the model — then dispatches each
proposal through jarvis governance:

  * core facts     → injection-scanned, deduped, capped, then CoreMemory ring
                     (autonomous: bounded, user-visible, user-forgettable);
  * corrections    → LearningModule.record_correction (pure signal);
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
                 now: Callable[[], float] = time.monotonic):
        self._llm = llm_call
        self._living = living
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

    async def run_on_demand(self, history: str, *, focus: str = "") -> dict:
        """H465 — the review the owner asked for (``/refine [focus]``), over a snapshot.

        It skips the cadence gate (the owner asked now) but spends the daily budget like
        any pass, keeps the strict-local model, and runs one at a time: a request while a
        review runs is refused ``busy``, not queued, and a per-turn pass that would start
        while it runs is skipped (``run`` refuses it, ``on_demand``). The review is bounded
        at REFINE_TIMEOUT_S, below the turn lease's wait. A review that times out or is
        cancelled costs no budget."""
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
                         cadence=False, on_demand=True),
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

    async def run(self, user_text: str, assistant_text: str, history: str = "", *,
                  focus: str = "", context_chars: int = 6000, cadence: bool = True,
                  on_demand: bool = False) -> dict:
        """One review pass. Never raises — failures return a summary dict.

        The exclusion is taken here, not only where a pass is spawned (review-H465b m-1):
        a per-turn pass spawned before a /refine started waits on the memory lock and can
        enter only after the /refine set its flag, so it is refused ``on_demand`` then."""
        if self._on_demand and not on_demand:
            return {"ran": False, "reason": "on_demand", "actions": []}
        self._in_flight += 1
        try:
            return await self._run(user_text, assistant_text, history, focus=focus,
                                   context_chars=context_chars, cadence=cadence, on_demand=on_demand)
        finally:
            self._in_flight -= 1

    async def _run(self, user_text: str, assistant_text: str, history: str, *,
                   focus: str, context_chars: int, cadence: bool, on_demand: bool) -> dict:
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
                  "skills_new": 0, "skill_patches": 0}
        max_facts = self._number("learning.review_max_facts", 3)

        living = self._living() if callable(self._living) else self._living
        if living is None and on_demand:
            # Said to the owner who asked, not dropped silently (review-H465 m-3), counting
            # only facts the injection scan would let through (review-H465b nit 5). The
            # per-turn pass stays quiet: memory being off is not news every turn.
            found = sum(1 for fact in review["user_facts"][:max_facts] + review["agent_facts"][:max_facts]
                        if not self._detect(fact))
            if found:
                actions.append(f"{found} fact(s) found but not kept: living memory is off "
                               "(cognition.memory_enabled)")
        self._put_facts(review["user_facts"][:max_facts],
                        getattr(living, "user_core", None),
                        "User profile", actions, counts)
        self._put_facts(review["agent_facts"][:max_facts],
                        getattr(living, "core", None),
                        "Core memory", actions, counts)

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

        for update in review["skill_updates"][:2]:
            if update["kind"] == "new":
                if self._dispatch_new_skill(update, actions, label):
                    counts["skills_new"] += 1
            else:
                if self._dispatch_patch(update, actions, label):
                    counts["skill_patches"] += 1

        result = {"ran": True, "nothing": review["nothing"] and not actions,
                  "actions": actions, "counts": counts, "ts": time.time()}
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

    def _put_facts(self, facts, store, label, actions, counts) -> None:
        if store is None or not hasattr(store, "put"):
            return
        added = 0
        for fact in facts:
            if self._detect(fact):
                counts["blocked"] += 1
                logger.warning("review fact blocked (injection-flagged): %.60s…", fact)
                continue
            try:
                # Content comparison (not len) so ring-dedupe (list unchanged)
                # is not miscounted as a write, while ring-full rotation is.
                before = store.list() if hasattr(store, "list") else None
                store.put(fact)
                after = store.list() if hasattr(store, "list") else None
                if before is None or after != before:
                    added += 1
            except Exception:
                logger.debug("core fact write skipped", exc_info=True)
        if added:
            counts["facts"] += added
            actions.append(f"{label} updated (+{added})")

    def _dispatch_new_skill(self, update, actions, label: str = "background_review") -> bool:
        """New skills ride the existing CDX-8 quarantine pipeline unchanged."""
        if self._skills is None or not hasattr(self._skills, "generate_skill"):
            return False
        try:
            name = self._skills.generate_skill(
                label, update["task"], update["steps"] or ["(captured from review)"])
            if name:
                actions.append(f"Skill '{name}' proposed (quarantined, pending review)")
                return True
        except Exception:
            logger.debug("skill generation from review skipped", exc_info=True)
        return False

    def _dispatch_patch(self, update, actions, label: str = "background_review") -> bool:
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
                                 else f"Background review proposes a patch to skill '{name}'"))
                except Exception:
                    logger.debug("approval request for patch skipped", exc_info=True)
            actions.append(f"Skill '{name}' patch proposed (pending approval)")
            return True
        except Exception:
            logger.debug("skill patch proposal skipped", exc_info=True)
            return False

    def status(self) -> dict:
        return {"available": True, "last_result": self.last_result,
                "reviews_today": self._day_count, "cut_offs_today": self._day_cut_offs, "day": self._day}


__all__ = ["BackgroundReviewer", "REVIEW_PROMPT", "parse_review_json"]
