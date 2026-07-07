"""
proposals.py — governed skill-patch proposals (H20.5 live wave).

A patch proposed by the background reviewer never touches the live skill.
It lands here as a *pending* record anchored to the content-hash of the
SKILL.md it was computed against (agents/core/skill_drift.py). The owner
approves (ActionApprovalQueue / HUD); the nightly curator then applies
approved proposals — re-checking the hash so a skill that drifted in the
meantime marks the proposal ``stale`` instead of clobbering newer content.
Applying backs up the old SKILL.md next to the runtime data, so every apply
is reversible.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agents.core.persistence import JsonStore
from agents.core.skill_drift import manifest_hash

logger = logging.getLogger("jarvis.skills.proposals")

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_STALE = "stale"
_VALID = {STATUS_PENDING, STATUS_APPROVED, STATUS_APPLIED, STATUS_REJECTED, STATUS_STALE}


class SkillProposalStore(JsonStore):
    """Durable ledger of skill-patch proposals."""

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path)

    def _serialize(self):
        return {"proposals": self._items}

    def _deserialize(self, raw) -> None:
        items = raw.get("proposals", {}) if isinstance(raw, dict) else {}
        self._items = items if isinstance(items, dict) else {}

    def propose(self, skill: str, current_content: str, proposed_content: str,
                origin: str = "background_review") -> dict | None:
        """Record a pending proposal; dedupe identical pending ones."""
        skill = str(skill or "").strip()
        proposed = str(proposed_content or "").strip()
        if not skill or not proposed:
            return None
        original_hash = manifest_hash(current_content or "")
        proposed_hash = manifest_hash(proposed)
        if proposed_hash == original_hash:
            return None                      # no-op change
        with self._lock:
            for rec in self._items.values():
                if (rec.get("skill") == skill and rec.get("status") == STATUS_PENDING
                        and rec.get("proposed_hash") == proposed_hash):
                    return dict(rec)         # identical pending proposal exists
            pid = f"sp-{uuid.uuid4().hex[:10]}"
            rec = {"id": pid, "skill": skill, "origin": origin,
                   "original_hash": original_hash, "proposed_hash": proposed_hash,
                   "proposed": proposed, "status": STATUS_PENDING,
                   "ts": time.time()}
            self._items[pid] = rec
            self._save()
            return dict(rec)

    def get(self, proposal_id: str) -> dict | None:
        with self._lock:
            rec = self._items.get(proposal_id)
            return dict(rec) if rec else None

    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            out = [dict(r) for r in self._items.values()
                   if status is None or r.get("status") == status]
        return sorted(out, key=lambda r: r.get("ts", 0.0))

    def mark(self, proposal_id: str, status: str) -> dict | None:
        if status not in _VALID:
            return None
        with self._lock:
            rec = self._items.get(proposal_id)
            if rec is None:
                return None
            rec["status"] = status
            rec["decided_ts"] = time.time()
            self._save()
            return dict(rec)

    # ── apply (curator-driven, owner-approved) ───────────────────────────────

    def apply(self, proposal_id: str, loader, backup_dir: str | Path) -> dict:
        """Apply an APPROVED proposal to its skill's SKILL.md.

        Hash-checked (drift ⇒ ``stale``), backed up (reversible), then the
        skill is reloaded so the new manifest is live. Returns a summary dict;
        never raises.
        """
        rec = self.get(proposal_id)
        if rec is None:
            return {"ok": False, "reason": "unknown_proposal"}
        if rec["status"] != STATUS_APPROVED:
            return {"ok": False, "reason": f"not_approved:{rec['status']}"}
        skill = getattr(loader, "skills", {}).get(rec["skill"])
        if skill is None:
            self.mark(proposal_id, STATUS_STALE)
            return {"ok": False, "reason": "skill_missing"}
        skill_md = Path(skill.path) / "SKILL.md"
        try:
            current = skill_md.read_text(encoding="utf-8")
        except Exception:
            self.mark(proposal_id, STATUS_STALE)
            return {"ok": False, "reason": "unreadable_skill"}
        if manifest_hash(current) != rec["original_hash"]:
            self.mark(proposal_id, STATUS_STALE)
            return {"ok": False, "reason": "drifted_since_proposal"}
        try:
            backup_root = Path(backup_dir)
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup = backup_root / f"{rec['skill']}-{stamp}.SKILL.md"
            backup.write_text(current, encoding="utf-8")
            skill_md.write_text(rec["proposed"], encoding="utf-8")
        except Exception:
            logger.warning("proposal apply failed for %s", rec["skill"], exc_info=True)
            return {"ok": False, "reason": "write_failed"}
        try:
            loader._load_skill(Path(skill.path))     # refresh manifest in place
        except Exception:
            logger.debug("skill reload after patch skipped", exc_info=True)
        self.mark(proposal_id, STATUS_APPLIED)
        logger.info("Skill '%s' patched via approved proposal %s (backup: %s)",
                    rec["skill"], proposal_id, backup)
        return {"ok": True, "skill": rec["skill"], "backup": str(backup)}

    def stats(self) -> dict:
        with self._lock:
            by = {}
            for r in self._items.values():
                by[r.get("status", "?")] = by.get(r.get("status", "?"), 0) + 1
            return {"total": len(self._items), "by_status": by}


__all__ = ["SkillProposalStore", "STATUS_PENDING", "STATUS_APPROVED",
           "STATUS_APPLIED", "STATUS_REJECTED", "STATUS_STALE"]
