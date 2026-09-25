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

import difflib
import logging
import threading
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
STATUS_SUPERSEDED = "superseded"
_VALID = {STATUS_PENDING, STATUS_APPROVED, STATUS_APPLIED, STATUS_REJECTED, STATUS_STALE,
          STATUS_SUPERSEDED}
CARD_TOOL = "skill.patch_proposal"


def unified_diff(current: str, proposed: str, name: str = "SKILL.md") -> str:
    """The whole change, as the owner reviews it: built from the ledger, never from a card."""
    return "".join(difflib.unified_diff(current.splitlines(keepends=True), proposed.splitlines(keepends=True),
                                        fromfile=f"{name} (now)", tofile=f"{name} (proposed)"))


def _shipped(path) -> bool:
    """Where a shipped skill lives (review-H318c n-6), as the apply refuses it."""
    try:
        from agents.core.skills.loader import _shipped_location

        return _shipped_location(Path(path))
    except Exception:
        return False


def _card_exists(queue, card: str) -> bool:
    getter = getattr(queue, "get", None)
    if not callable(getter):
        return True                      # a queue that cannot say keeps the card it has
    try:
        return getter(card) is not None
    except Exception:
        return True


def _pending_cards(queue, proposal_id: str) -> list[str]:
    lister = getattr(queue, "list", None)
    if not callable(lister):
        return []
    try:
        items = lister("pending")
    except Exception:
        return []
    return [str(i.get("id")) for i in items
            if i.get("tool") == CARD_TOOL and (i.get("args") or {}).get("proposal_id") == proposal_id]


def _withdraw(queue, card: str) -> None:
    try:
        queue.decide(card, False, by="superseded")
    except Exception:
        logger.debug("card %s not withdrawn", card, exc_info=True)


def _snapshot(path: Path):
    from agents.core.skills.signing import source_snapshot

    return source_snapshot(path)


def _only_manifest_changed(before, after, proposed: bytes) -> bool:
    """``after`` is ``before`` with SKILL.md replaced by the ``proposed`` bytes, and nothing
    else."""
    if before is None or after is None:
        return False
    old = {f.relative_path: (f.kind, f.content) for f in before.files if f.relative_path != "SKILL.md"}
    new = {f.relative_path: (f.kind, f.content) for f in after.files if f.relative_path != "SKILL.md"}
    manifest = [f.content for f in after.files if f.relative_path == "SKILL.md"]
    return old == new and manifest == [proposed]


class SkillProposalStore(JsonStore):
    """Durable ledger of skill-patch proposals."""

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path)
        self._card_lock = threading.Lock()

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

    def mark(self, proposal_id: str, status: str, reason: str = "") -> dict | None:
        if status not in _VALID:
            return None
        with self._lock:
            rec = self._items.get(proposal_id)
            if rec is None:
                return None
            rec["status"] = status
            rec["decided_ts"] = time.time()
            if reason:
                rec["reason"] = reason
            self._save()
            return dict(rec)

    # ── the approval card (one per proposal, bound to it) ────────────────────

    def queue_card(self, proposal_id: str, queue, *, agent: str, summary: str) -> str | None:
        """Queue the proposal's one approval card and bind it to the proposal.

        Only the bound card decides the proposal (review-H318b m-6: any user token can
        queue a card naming a proposal id). A proposal that already has its card gets no
        second one, whoever proposed the same text (m-1), unless that card is gone from
        the queue (a reset or cleared queue): then it gets a new one, or it could never be
        decided (review-H318c m-6). Binding a card withdraws the unbound cards naming the
        proposal (n-3), and a proposal superseded while its card was queued gets that card
        withdrawn, not bound (n-4). The card carries no diff: what the owner reviews is
        built from the ledger (``describe``)."""
        with self._card_lock:
            rec = self.get(proposal_id)
            if rec is None or rec.get("status") != STATUS_PENDING:
                return None
            if rec.get("card") and _card_exists(queue, rec["card"]):
                return rec["card"]
            item = queue.request({"tool": CARD_TOOL, "agent": agent, "summary": summary,
                                  "args": {"skill": rec["skill"], "proposal_id": proposal_id}})
            card = str((item or {}).get("id") or "")
            if not card:
                return None
            with self._lock:
                live = self._items.get(proposal_id)
                bound = live is not None and live.get("status") == STATUS_PENDING
                if bound:
                    live["card"] = card
                    self._save()
            if not bound:
                _withdraw(queue, card)
                return None
            for other in _pending_cards(queue, proposal_id):
                if other != card:
                    _withdraw(queue, other)
            return card

    def supersede_older(self, record: dict, queue=None, origin: str | None = None) -> None:
        """One pending change per skill per origin: ``record`` supersedes the older ones
        its origin proposed for the same skill (review-H318 m-3), whichever path proposed
        it, the tool, the background review or /refine (review-H318c n-2)."""
        # The caller's origin: a re-sent text returns the record another origin proposed
        # first, and the caller's own older proposal must still go (review-H318d n-3).
        origin = record.get("origin") if origin is None else origin
        for older in self.list(STATUS_PENDING):
            if (older.get("id") != record.get("id") and older.get("skill") == record.get("skill")
                    and older.get("origin") == origin):
                self.supersede(older["id"], queue)

    def supersede(self, proposal_id: str, queue=None) -> None:
        """A newer proposal replaces this one: marked superseded, its card withdrawn, so
        approving the old card cannot look like it did something (review-H318b m-1)."""
        rec = self.mark(proposal_id, STATUS_SUPERSEDED)
        card = (rec or {}).get("card")
        if card and queue is not None:
            try:
                queue.decide(card, False, by="superseded")
            except Exception:
                logger.debug("superseded card %s not withdrawn", card, exc_info=True)

    def describe(self, rec: dict, loader) -> dict:
        """A proposal as the owner reviews it: the whole diff against the live SKILL.md,
        whether the skill drifted since, and what the change would do beyond the text."""
        out = {k: rec.get(k) for k in ("id", "skill", "origin", "status", "ts", "card", "reason")}
        skill = getattr(loader, "skills", {}).get(rec.get("skill"))
        if skill is None:
            return {**out, "diff": "", "drifted": True, "flags": ["the skill is gone"]}
        try:
            current = (Path(skill.path) / "SKILL.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return {**out, "diff": "", "drifted": True, "flags": ["the skill cannot be read"]}
        flags = []
        naming = getattr(loader, "manifest_name", None)
        if callable(naming):
            try:
                if naming(Path(skill.path), rec.get("proposed", "")) != rec.get("skill"):
                    flags.append("renames the skill")
            except Exception:
                flags.append("its header cannot be read")
        if not getattr(skill, "external", True) or _shipped(skill.path):
            flags.append("a bundled skill: it cannot be changed here")
        return {**out, "diff": unified_diff(current, rec.get("proposed", "")),
                "drifted": manifest_hash(current) != rec.get("original_hash"), "flags": flags}

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
        # A bundled skill is product source: an edit would unbundle it, and with its code
        # it would stop loading (review-H318b M-1). It is refused, never half-applied.
        standing_of = getattr(loader, "owner_standing", None)
        try:
            standing = standing_of(skill) if callable(standing_of) else {}
        except Exception:
            # An unreadable SKILL.sig (not UTF-8, say) is this proposal's trouble, never the
            # pass's (review-H318d n-4).
            logger.warning("skill '%s': its standing could not be read", rec["skill"], exc_info=True)
            return {"ok": False, "reason": "unreadable_skill"}
        if standing.get("bundled"):
            self.mark(proposal_id, STATUS_REJECTED, reason="bundled")
            return {"ok": False, "reason": "bundled_skill"}
        if standing.get("key_missing"):
            # A keyed SKILL.sig the missing key cannot renew: applying would leave it over
            # new bytes, and the skill would fail as tampered once the key is back
            # (review-H318c m-4). The proposal stays approved for when the key is present.
            return {"ok": False, "reason": "signing_key_missing"}
        naming = getattr(loader, "manifest_name", None)
        if callable(naming) and naming(Path(skill.path), rec["proposed"]) != rec["skill"]:
            self.mark(proposal_id, STATUS_REJECTED, reason="renames")
            return {"ok": False, "reason": "renames_skill"}
        skill_md = Path(skill.path) / "SKILL.md"
        # Bytes in and out, never text mode: Windows would write "\r\n" for "\n", so the
        # bytes on disk would never equal the approved text, and a rollback would rewrite
        # the old file's line ends and break the signature it restores (review-H318d MAJOR-1).
        try:
            current_raw = skill_md.read_bytes()
            current = current_raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except Exception:
            self.mark(proposal_id, STATUS_STALE)
            return {"ok": False, "reason": "unreadable_skill"}
        proposed_raw = rec["proposed"].encode("utf-8")
        if manifest_hash(current) != rec["original_hash"]:
            self.mark(proposal_id, STATUS_STALE)
            return {"ok": False, "reason": "drifted_since_proposal"}
        try:
            backup_root = Path(backup_dir)
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            # Named by the skill's directory, never its manifest name (review-H318b m-5: a
            # name like ../../x escaped the archive), and unique within the second.
            backup = backup_root / f"{Path(skill.path).name}-{stamp}-{uuid.uuid4().hex[:6]}.SKILL.md"
            backup.write_bytes(current_raw)
            skill_md.write_bytes(proposed_raw)
        except Exception:
            logger.warning("proposal apply failed for %s", rec["skill"], exc_info=True)
            return {"ok": False, "reason": "write_failed"}
        restore = getattr(loader, "restore_standing", None)
        if callable(restore) and (standing.get("signed") or standing.get("approved")):
            # The renewal covers the bytes checked here, never a later read: the tree after
            # the write must be the tree the standing was judged on with only SKILL.md
            # replaced by the approved bytes, or a write in between would ride into the
            # vouch (review-H318c m-1). A failed or refused renewal puts back the old
            # SKILL.md and the old SKILL.sig, whose signature and approval still hold, and
            # says why (m-3; review-H318d m-1: a signature renewed before the approval failed
            # was left over the old text). The proposal is then stale, not retried every pass.
            sig = Path(skill.path) / "SKILL.sig"
            old_sig = sig.read_bytes() if sig.is_file() else None
            reason = ""
            try:
                after = _snapshot(Path(skill.path))
                if not _only_manifest_changed(standing.get("snapshot"), after, proposed_raw):
                    reason = "changed_during_apply"
                else:
                    restore(Path(skill.path), standing, snapshot=after)
            except Exception:
                logger.warning("skill '%s': its signature or approval could not be renewed",
                               rec["skill"], exc_info=True)
                reason = "standing_not_renewed"
            if reason:
                try:
                    skill_md.write_bytes(current_raw)
                    if old_sig is None:
                        sig.unlink(missing_ok=True)
                    else:
                        sig.write_bytes(old_sig)
                except Exception:
                    # The new text stays: say so, with where the old one is (review-H318d n-2).
                    logger.warning("skill '%s': the old SKILL.md could not be put back (backup: %s)",
                                   rec["skill"], backup, exc_info=True)
                    reason = "rollback_failed"
                self.mark(proposal_id, STATUS_STALE, reason=reason)
                logger.warning("approved proposal %s for skill '%s' not applied: %s",
                               proposal_id, rec["skill"], reason)
                return {"ok": False, "reason": reason, "backup": str(backup)}
        try:
            loader._load_skill(Path(skill.path), discovery_root=Path(skill.path).parent)
        except Exception:
            logger.debug("skill reload after patch skipped", exc_info=True)
        self.mark(proposal_id, STATUS_APPLIED)
        live = getattr(loader, "skills", {}).get(rec["skill"])
        gate = getattr(loader, "catalog_gate", None)
        state = "hidden" if live is None else ((gate(live) if callable(gate) else "") or "shown")
        logger.info("Skill '%s' patched via approved proposal %s (backup: %s, now %s)",
                    rec["skill"], proposal_id, backup, state)
        return {"ok": True, "skill": rec["skill"], "backup": str(backup), "state": state}

    def stats(self) -> dict:
        with self._lock:
            by = {}
            for r in self._items.values():
                by[r.get("status", "?")] = by.get(r.get("status", "?"), 0) + 1
            return {"total": len(self._items), "by_status": by}


__all__ = ["CARD_TOOL", "SkillProposalStore", "STATUS_PENDING", "STATUS_APPROVED",
           "STATUS_APPLIED", "STATUS_REJECTED", "STATUS_STALE", "STATUS_SUPERSEDED", "unified_diff"]
