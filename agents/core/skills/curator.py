"""
curator.py — nightly skill curator (H20.5 live wave).

Two passes, both governed and reversible, adapted from hermes-agent
`agent/curator.py` (Nous Research, MIT — see LICENSES/THIRD_PARTY.md):

  1. **Lifecycle** — agent-created, unpinned skills transition
     active → stale (idle > ``learning.curator_stale_days``, default 30)
     → archived (idle > ``learning.curator_archive_days``, default 90;
     the skill directory MOVES to the runtime-data archive — never deleted,
     restorable by moving it back). Bundled / imported / pinned skills are
     never touched (provenance filter, cf. hermes PROTECTED rules).
  2. **Proposals** — owner-approved skill patches (ActionApprovalQueue →
     SkillProposalStore) are applied hash-checked + backed up; rejected
     decisions propagate to the ledger.

Idempotent per calendar day via a reflector-style run ledger. Default-off:
the caller gates on ``cognition.review_enabled``.
"""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from .proposals import CARD_TOOL, STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED
from .usage import STATE_ACTIVE, STATE_ARCHIVED, STATE_STALE, latest_activity_at

logger = logging.getLogger("jarvis.skills.curator")


class SkillCurator:
    """Nightly lifecycle + proposal-application pass over the skill library."""

    def __init__(self, loader, usage, *, proposals=None, approvals=None,
                 get_setting: Callable | None = None,
                 run_store=None, archive_dir: str | Path | None = None,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._loader = loader
        self._usage = usage
        self._proposals = proposals
        self._approvals = approvals
        self._get = get_setting or (lambda k, d=None: d)
        self._run_store = run_store          # ReflectionRunStore-compatible
        self._archive_dir = Path(archive_dir) if archive_dir else None
        self._now = now
        self._last_run: date | None = None
        self._last_result: dict | None = None
        self._apply_lock = threading.Lock()   # two decisions at once apply one after the other

    async def run(self, *, force: bool = False) -> dict:
        """One curator pass. Idempotent per calendar day; never raises."""
        today = self._now().date()
        if not force and self._last_run == today:
            return {"skipped": True, "reason": "already_ran_today"}
        if not force and self._run_store is not None:
            try:
                if self._run_store.get(today) is not None:
                    self._last_run = today
                    return {"skipped": True, "reason": "already_ran_today"}
            except Exception:
                logger.debug("curator run-store read skipped", exc_info=True)

        lifecycle = self._lifecycle_pass()
        proposals = self._proposals_pass()

        self._last_run = today
        result = {"date": today.isoformat(), "lifecycle": lifecycle,
                  "proposals": proposals}
        self._last_result = result
        if self._run_store is not None:
            try:
                self._run_store.record(today, result)
            except Exception:
                logger.debug("curator run-store write skipped", exc_info=True)
        return result

    # ── pass 1: lifecycle ────────────────────────────────────────────────────

    def _lifecycle_pass(self) -> dict:
        stale_days = int(self._get("learning.curator_stale_days", 30) or 30)
        archive_days = int(self._get("learning.curator_archive_days", 90) or 90)
        now = self._now()
        marked_stale, archived, considered = [], [], 0

        for name in list(getattr(self._loader, "skills", {}).keys()):
            try:
                if not self._usage.curatable(name):
                    continue
                considered += 1
                rec = self._usage.get(name) or {}
                anchor = latest_activity_at(rec)
                if anchor is None:
                    created = rec.get("created_at")
                    try:
                        anchor = datetime.fromisoformat(str(created))
                        if anchor.tzinfo is None:
                            anchor = anchor.replace(tzinfo=UTC)
                    except (TypeError, ValueError):
                        continue           # no usable anchor → leave alone
                idle_days = (now - anchor).days
                if idle_days > archive_days:
                    if self._archive_skill(name):
                        archived.append(name)
                elif idle_days > stale_days and rec.get("state") == STATE_ACTIVE:
                    self._usage.set_state(name, STATE_STALE)
                    marked_stale.append(name)
            except Exception:
                logger.debug("curator lifecycle skipped for %s", name, exc_info=True)

        return {"considered": considered, "stale": marked_stale, "archived": archived}

    def _archive_skill(self, name: str) -> bool:
        """Move the skill dir into the runtime archive (never delete)."""
        skill = getattr(self._loader, "skills", {}).get(name)
        if skill is None or self._archive_dir is None:
            return False
        src = Path(skill.path)
        if not src.exists():
            return False
        try:
            self._archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self._archive_dir / src.name
            if dest.exists():
                stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
                dest = self._archive_dir / f"{src.name}-{stamp}"
            shutil.move(str(src), str(dest))
            self._loader.skills.pop(name, None)
            self._usage.set_state(name, STATE_ARCHIVED)
            logger.info("Skill '%s' archived (idle) → %s", name, dest)
            return True
        except Exception:
            logger.warning("skill archive failed for %s", name, exc_info=True)
            return False

    # ── pass 2: apply owner decisions on patch proposals ─────────────────────

    def apply_decisions(self) -> dict:
        """Apply the owner's decisions on skill patch proposals now (H318 review).

        The approval route calls this when a ``skill.patch_proposal`` card is decided, so
        an approved change lands at once. It is not gated by the learning loop's flag or
        the night window, which gate the curator's own lifecycle pass: the owner asked.
        One pass at a time (review-H318b n-1): two overlapping decisions no longer report
        a change the other applied as stale."""
        return self._proposals_pass()

    def _proposals_pass(self) -> dict:
        # The nightly run and a decision's apply both come here, so both take the lock:
        # the night pass took none, and a decision beside it saw the change the night
        # applied reported as not approved (review-H318c n-1).
        with self._apply_lock:
            return self._proposals_pass_locked()

    def _proposals_pass_locked(self) -> dict:
        if self._proposals is None:
            return {"applied": [], "rejected": [], "stale": [], "failed": [], "outcomes": []}
        self._sync_approval_decisions()
        applied, went_stale, failed, outcomes = [], [], [], []
        backup_dir = self._archive_dir or Path(".")
        for rec in self._proposals.list(STATUS_APPROVED):
            try:
                out = self._proposals.apply(rec["id"], self._loader, backup_dir)
            except Exception:
                # One proposal's failure never stops the others' (review-H318d n-4).
                logger.warning("skill proposal %s could not be applied", rec["id"], exc_info=True)
                out = {"ok": False, "reason": "apply_error"}
            # Every outcome is reported, with the state the skill is left in (review-H318b
            # M-1, n-3): "applied" alone hid a skill the change had sandboxed or hidden.
            outcomes.append({"skill": rec["skill"], "proposal_id": rec["id"],
                             **{k: out[k] for k in ("ok", "reason", "state", "problems") if k in out}})
            if out.get("ok"):
                applied.append(rec["skill"])
                if self._usage is not None:
                    self._usage.bump(rec["skill"], "patch")
            elif out.get("reason", "").startswith(("drifted", "skill_missing", "unreadable")):
                went_stale.append(rec["skill"])
            else:
                failed.append(rec["skill"])      # refused (bundled, a rename) or not written
        rejected = [r["skill"] for r in self._proposals.list(STATUS_REJECTED)]
        return {"applied": applied, "rejected": rejected, "stale": went_stale, "failed": failed,
                "outcomes": outcomes}

    def _sync_approval_decisions(self) -> None:
        """Map ActionApprovalQueue decisions back onto the proposal ledger."""
        if self._approvals is None:
            return
        try:
            for status, mark in (("approved", STATUS_APPROVED), ("rejected", STATUS_REJECTED)):
                for item in self._approvals.list(status):
                    if item.get("tool") != CARD_TOOL:
                        continue
                    pid = (item.get("args") or {}).get("proposal_id")
                    if not pid:
                        continue
                    rec = self._proposals.get(pid)
                    # Only the card the proposal queued decides it (review-H318b m-6): a card
                    # anyone with a user token queued naming this id is not the owner's
                    # decision on these bytes.
                    if (rec is not None and rec.get("status") == STATUS_PENDING
                            and rec.get("card") and rec.get("card") == item.get("id")):
                        self._proposals.mark(pid, mark)
        except Exception:
            logger.debug("approval decision sync skipped", exc_info=True)

    def status(self) -> dict:
        return {"available": True,
                "last_run": self._last_run.isoformat() if self._last_run else None,
                "last_result": self._last_result}


__all__ = ["SkillCurator"]
