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

import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date

logger = logging.getLogger("jarvis.learning.review")

# ── the review prompt (adapted from hermes-agent, structured-output form) ─────

REVIEW_PROMPT = """\
You are Jarvis's background reviewer. A conversation turn just finished. Decide
what durable knowledge it produced. Most turns produce NOTHING — that is fine;
only real signal counts.

Conversation (recent context, then the turn under review):
{context}

Signals worth capturing:
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
    if not raw:
        return empty
    try:
        start, end = raw.find("{"), raw.rfind("}") + 1
        if not (0 <= start < end):
            return empty
        data = json.loads(raw[start:end])
        if not isinstance(data, dict):
            return empty
    except Exception:
        return empty

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
        self.last_result: dict | None = None

    # ── cadence / budget gate ────────────────────────────────────────────────

    def should_run(self) -> tuple[bool, str]:
        """Local-GPU cost policy: cadence knob + a per-day review budget."""
        self._turns_since += 1
        today = date.today().isoformat()
        if today != self._day:
            self._day, self._day_count = today, 0
        budget = int(self._get("learning.review_daily_budget", 20) or 20)
        if self._day_count >= budget:
            return False, "daily_budget"
        cadence = str(self._get("learning.review_cadence", "every_turn") or "every_turn")
        if cadence == "every_n_turns":
            n = max(1, int(self._get("learning.review_every_n", 3) or 3))
            if self._turns_since < n:
                return False, "cadence_n"
        elif cadence == "idle_gap":
            gap = float(self._get("learning.review_idle_gap_s", 90) or 90)
            if self._last_run_ts is not None and (self._now() - self._last_run_ts) < gap:
                return False, "cadence_idle"
        return True, "ok"

    # ── the review pass ──────────────────────────────────────────────────────

    async def run(self, user_text: str, assistant_text: str, history: str = "") -> dict:
        """One review pass. Never raises — failures return a summary dict."""
        self._turns_since = 0
        self._last_run_ts = self._now()
        self._day_count += 1
        context = "\n".join(part for part in (
            history.strip(),
            f"user: {user_text.strip()}" if user_text else "",
            f"assistant: {assistant_text.strip()}" if assistant_text else "",
        ) if part)
        skills_list = ", ".join(sorted(self._skill_names())[:40]) or "(none)"
        prompt = REVIEW_PROMPT.format(context=context[:6000], skills=skills_list)

        try:
            raw = await self._llm(prompt)
        except Exception as e:
            logger.debug("background review LLM call failed: %s", e)
            result = {"ran": False, "reason": "llm_error", "actions": []}
            self.last_result = result
            return result

        review = parse_review_json(raw)
        actions: list[str] = []
        counts = {"facts": 0, "blocked": 0, "corrections": 0,
                  "skills_new": 0, "skill_patches": 0}
        max_facts = max(0, int(self._get("learning.review_max_facts", 3) or 3))

        living = self._living() if callable(self._living) else self._living
        self._put_facts(review["user_facts"][:max_facts],
                        getattr(living, "user_core", None),
                        "User profile", actions, counts)
        self._put_facts(review["agent_facts"][:max_facts],
                        getattr(living, "core", None),
                        "Core memory", actions, counts)

        for corr in review["corrections"][:max_facts]:
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
                if self._dispatch_new_skill(update, actions):
                    counts["skills_new"] += 1
            else:
                if self._dispatch_patch(update, actions):
                    counts["skill_patches"] += 1

        result = {"ran": True, "nothing": review["nothing"] and not actions,
                  "actions": actions, "counts": counts, "ts": time.time()}
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

    def _dispatch_new_skill(self, update, actions) -> bool:
        """New skills ride the existing CDX-8 quarantine pipeline unchanged."""
        if self._skills is None or not hasattr(self._skills, "generate_skill"):
            return False
        try:
            name = self._skills.generate_skill(
                "background_review", update["task"], update["steps"] or ["(captured from review)"])
            if name:
                actions.append(f"Skill '{name}' proposed (quarantined, pending review)")
                return True
        except Exception:
            logger.debug("skill generation from review skipped", exc_info=True)
        return False

    def _dispatch_patch(self, update, actions) -> bool:
        """Patches never touch the live skill — they land as pending proposals."""
        if self._proposals is None:
            return False
        name = update["name"]
        skill = getattr(self._skills, "skills", {}).get(name) if self._skills else None
        if skill is None:
            logger.debug("review patch for unknown skill %r skipped", name)
            return False
        if self._detect(update["content"]):
            logger.warning("review skill patch blocked (injection-flagged): %s", name)
            return False
        try:
            current = (skill.path / "SKILL.md").read_text(encoding="utf-8")
        except Exception:
            logger.debug("could not read current SKILL.md for %s", name, exc_info=True)
            return False
        try:
            prop = self._proposals.propose(name, current, update["content"],
                                           origin="background_review")
            if prop is None:
                return False
            if self._approvals is not None:
                try:
                    # ActionApprovalQueue persists tool/args — proposal_id rides
                    # in args so the curator can map the decision back.
                    self._approvals.request({
                        "tool": "skill.patch_proposal",
                        "args": {"skill": name, "proposal_id": prop["id"]},
                        "agent": "background_review",
                        "summary": f"Background review proposes a patch to skill '{name}'",
                    })
                except Exception:
                    logger.debug("approval request for patch skipped", exc_info=True)
            actions.append(f"Skill '{name}' patch proposed (pending approval)")
            return True
        except Exception:
            logger.debug("skill patch proposal skipped", exc_info=True)
            return False

    def status(self) -> dict:
        return {"available": True, "last_result": self.last_result,
                "reviews_today": self._day_count, "day": self._day}


__all__ = ["BackgroundReviewer", "REVIEW_PROMPT", "parse_review_json"]
