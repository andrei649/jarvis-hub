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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .proposals import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED
from .usage import STATE_ACTIVE, STATE_ARCHIVED, STATE_STALE, latest_activity_at

logger = logging.getLogger("jarvis.skills.curator")


class SkillCurator:
    """Nightly lifecycle + proposal-application pass over the skill library."""

    def __init__(self, loader, usage, *, proposals=None, approvals=None,
                 get_setting: Optional[Callable] = None,
                 run_store=None, archive_dir: "str | Path | None" = None,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._loader = loader
        self._usage = usage
        self._proposals = proposals
        self._approvals = approvals
        self._get = get_setting or (lambda k, d=None: d)
        self._run_store = run_store          # ReflectionRunStore-compatible
        self._archive_dir = Path(archive_dir) if archive_dir else None
        self._now = now
        self._last_run: Optional[date] = None
        self._last_result: Optional[dict] = None

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
                            anchor = anchor.replace(tzinfo=timezone.utc)
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

    def _proposals_pass(self) -> dict:
        if self._proposals is None:
            return {"applied": [], "rejected": [], "stale": []}
        self._sync_approval_decisions()
        applied, went_stale = [], []
        backup_dir = self._archive_dir or Path(".")
        for rec in self._proposals.list(STATUS_APPROVED):
            out = self._proposals.apply(rec["id"], self._loader, backup_dir)
            if out.get("ok"):
                applied.append(rec["skill"])
                if self._usage is not None:
                    self._usage.bump(rec["skill"], "patch")
            elif out.get("reason", "").startswith(("drifted", "skill_missing", "unreadable")):
                went_stale.append(rec["skill"])
        rejected = [r["skill"] for r in self._proposals.list(STATUS_REJECTED)]
        return {"applied": applied, "rejected": rejected, "stale": went_stale}

    def _sync_approval_decisions(self) -> None:
        """Map ActionApprovalQueue decisions back onto the proposal ledger."""
        if self._approvals is None:
            return
        try:
            for status, mark in (("approved", STATUS_APPROVED), ("rejected", STATUS_REJECTED)):
                for item in self._approvals.list(status):
                    if item.get("tool") != "skill.patch_proposal":
                        continue
                    pid = (item.get("args") or {}).get("proposal_id")
                    if not pid:
                        continue
                    rec = self._proposals.get(pid)
                    if rec is not None and rec.get("status") == STATUS_PENDING:
                        self._proposals.mark(pid, mark)
        except Exception:
            logger.debug("approval decision sync skipped", exc_info=True)

    def status(self) -> dict:
        return {"available": True,
                "last_run": self._last_run.isoformat() if self._last_run else None,
                "last_result": self._last_result}


__all__ = ["SkillCurator"]
