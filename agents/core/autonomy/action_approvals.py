"""
action_approvals.py — H10.18 Action-Level Approval (sub-task granularity).

A live queue of pending **tool-call** approvals: an agent can register an action
before executing it, then `await_decision` until a human approves or rejects it
from the HUD — finer-grained than the task-level decision inbox (H6.2). Each item
carries a dry-run preview (H12.5) so the reviewer sees what the call would do.

H277: an optional approval judge (``approval_judge.ApprovalJudge``, attached by the
orchestrator; off unless ``JARVIS_ROLE_APPROVAL_JUDGE_MODEL`` is set) scores a queued item
*after* ``request`` returned — the card is shown at once and annotated with
``item["judge"]`` when the judge answers. The annotation is advisory: ``decide``,
``await_decision`` and every gate ignore it, a failed or late judgement leaves the item
(and the file) exactly as it was, and the first answer is the only one. With an intent log
attached, each judgement and each decision is one signed audit row that names the judge.
At most :data:`JUDGE_MAX_CONCURRENT` judge calls run at once and at most
:data:`JUDGE_MAX_PENDING` are in flight or waiting; past that an item is not judged (no
annotation; ``judge_status_public()["skipped_busy"]`` counts it). An action queued with a
taint mark (on itself, its metadata, a nested argument, or an untrusted turn origin) is
stored with ``tainted: True`` only when a judge is configured; a non-local judge never sees it.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from ..persistence import JsonStore
from .advisory_judgements import (
    JUDGE_MAX_CONCURRENT as JUDGE_MAX_CONCURRENT,
)
from .advisory_judgements import (
    JUDGE_MAX_PENDING as JUDGE_MAX_PENDING,
)
from .advisory_judgements import (
    AdvisoryJudgements,
)
from .approval_grouping import OwnerRegistrationContext, member_snapshot, registration_fingerprint
from .decision_reasons import normalize_reason

logger = logging.getLogger("jarvis.autonomy.action_approvals")




class ActionApprovalQueue(AdvisoryJudgements, JsonStore):
    """Pending tool-call approvals. Persists items when given a *path* (A7);
    in-memory (path=None) otherwise. asyncio.Events are runtime-only and are
    re-created lazily for items reloaded from disk."""

    _items: dict[str, dict]
    _events: dict[str, asyncio.Event]

    def __init__(self, path: "str | Path | None" = None) -> None:
        self._init_judgements()
        self._judge_import_warned = False
        super().__init__(path)

    def _serialize(self):
        return self._items

    def _deserialize(self, raw) -> None:
        self._items = raw if isinstance(raw, dict) else {}
        self._events = {}                 # events are not persisted
        self._registration_namespace = next((
            metadata['namespace'] for item in self._items.values()
            if isinstance(item, dict)
            and (metadata := self._group_metadata(item)) is not None
        ), uuid.uuid4().hex)

    # ── request ──────────────────────────────────────────────────────────────

    def request(self, action: dict, *, grouping_context: OwnerRegistrationContext | None = None) -> dict:
        """Register a pending tool-call approval and return the queue item."""
        action = action or {}
        fingerprint = registration_fingerprint(action, grouping_context, self._registration_namespace)
        if fingerprint is not None:
            # Caller-owned argument dictionaries must not mutate grouped snapshots.
            action = copy.deepcopy(action)
        action_id = uuid.uuid4().hex[:12]
        tool = action.get("tool", "")
        args = action.get("args") or {}
        tainted = False
        try:
            if self._judge is not None and self._judge.status().configured:
                from .approval_judge import action_is_tainted

                tainted = action_is_tainted(action)
        except ImportError:
            if not self._judge_import_warned:
                self._judge_import_warned = True
                logger.warning("approval judge import unavailable; requests continue without it")
        except Exception:  # noqa: BLE001 — advisory setup never fails a request
            logger.debug("approval judge taint check unavailable", exc_info=True)
        try:
            from .dry_run import preview_task
            preview = preview_task({"kind": tool, "title": action.get("summary", tool),
                                    "payload": args, "risk_tier": action.get("risk_tier", 2)})
        except Exception:
            preview = {}
        item = {
            "id": action_id,
            "tool": tool,
            "args": args,
            "agent": action.get("agent", ""),
            "task_id": action.get("task_id"),
            "summary": action.get("summary") or preview.get("summary", tool),
            "preview": preview,
            "status": "pending",
            "decided_by": None,
            "created_at": time.time(),
            "decided_at": None,
        }
        if tainted:
            item["tainted"] = True      # H277 review F4: a non-local judge never sees it
        with self._lock:
            backups = []
            if fingerprint is not None:
                siblings = [entry for entry in self._items.values()
                            if entry.get('status') == 'pending'
                            and (metadata := self._group_metadata(entry)) is not None
                            and metadata['namespace'] == self._registration_namespace
                            and metadata['fingerprint'] == fingerprint]
                backups = [(entry, copy.deepcopy(entry)) for entry in siblings]
                group_id = siblings[0]['_grouping']['id'] if siblings else uuid.uuid4().hex
                snapshot = uuid.uuid4().hex
                item['_grouping'] = {'id': group_id, 'snapshot': snapshot,
                                     'namespace': self._registration_namespace,
                                     'fingerprint': fingerprint, 'member_snapshot': member_snapshot(item)}
                for sibling in siblings:
                    sibling['_grouping']['snapshot'] = snapshot
            self._items[action_id] = item
            self._events[action_id] = asyncio.Event()
            self._save_changes_locked(backups, added=action_id)
        try:
            self._schedule_judge(item)
        except Exception:  # noqa: BLE001 — the judge is advisory: it never fails a request
            logger.debug("approval judge not scheduled for %s", action_id, exc_info=True)
        return self._public_item(item)

    # ── decide ───────────────────────────────────────────────────────────────

    def decide(self, action_id: str, approved: bool, by: str = "user",
               reason: str | None = None) -> Optional[dict]:
        human_reason = normalize_reason(reason)
        changed = False
        with self._lock:
            item = self._items.get(action_id)
            if item is None:
                return None
            if item["status"] == "pending":
                backups = self._backup_group_locked(item)
                item["status"] = "approved" if approved else "rejected"
                item["decided_by"] = by
                item["decided_at"] = time.time()
                if human_reason is not None:
                    item["human_reason"] = human_reason
                self._rotate_group_snapshot_locked(item)
                self._save_changes_locked(backups)
                changed = True
            event = self._events.get(action_id)
            decided = self._public_item(item)
        self._clear_judge_pending(action_id)
        if event is not None:
            event.set()
        if changed:
            self._audit_row(by, "action_approval.decided", "the owner's decision on a queued tool call",
                            action_id, {"tool": decided.get("tool", ""), "agent": decided.get("agent", ""),
                                        "approved": bool(approved), "by": by,
                                        "judge": (decided.get("judge") or {}).get("judge"),
                                        **({"human_reason": human_reason} if human_reason is not None else {})})
        return decided

    async def await_decision(self, action_id: str, timeout: Optional[float] = None) -> str:
        """Block until the action is decided; return its final status ('approved'/
        'rejected'), or persist terminal 'expired' when its wait deadline wins."""
        with self._lock:
            item = self._items.get(action_id)
            if item is None:
                return "unknown"
            if item["status"] != "pending":
                return item["status"]
            # re-create the event lazily (e.g. for an item reloaded from disk).
            event = self._events.get(action_id)
            if event is None:
                event = self._events[action_id] = asyncio.Event()
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # The same lock as decide(): only the winner may close a pending card.
            with self._lock:
                item = self._items.get(action_id)
                if item is not None and item.get("status") == "pending":
                    backups = self._backup_group_locked(item)
                    item["status"] = "expired"
                    item["expired_at"] = time.time()
                    self._rotate_group_snapshot_locked(item)
                    self._save_changes_locked(backups)
                status = item.get("status", "unknown") if item is not None else "unknown"
            self._clear_judge_pending(action_id)
            event.set()  # every waiter observes the same durable terminal state
            return status
        # B1: guard against a concurrent clear() between the await and the read.
        with self._lock:
            return self._items.get(action_id, {}).get("status", "unknown")

    # ── queries ──────────────────────────────────────────────────────────────

    def _public_item(self, item: dict) -> dict:
        out = copy.deepcopy(item) if '_grouping' in item else dict(item)
        out.pop('_grouping', None)
        with self._judge_lock:
            if item["id"] in self._judge_pending and item.get("status") == "pending":
                out["judge_pending"] = True
        return out

    @staticmethod
    def _group_metadata(item: dict) -> dict | None:
        metadata = item.get('_grouping')
        if not isinstance(metadata, dict):
            return None
        for key in ('id', 'snapshot', 'namespace'):
            value = metadata.get(key)
            if (not isinstance(value, str) or len(value) != 32
                    or any(ch not in '0123456789abcdef' for ch in value)):
                return None
        value = metadata.get('fingerprint')
        if (not isinstance(value, str) or len(value) != 64
                or any(ch not in '0123456789abcdef' for ch in value)):
            return None
        if metadata.get('member_snapshot') != member_snapshot(item):
            return None
        return metadata

    def _group_members_locked(self, group_id: str) -> list[dict]:
        members = [item for item in self._items.values()
                   if item.get('status') == 'pending'
                   and (metadata := self._group_metadata(item)) is not None
                   and metadata['id'] == group_id]
        members.sort(key=lambda item: (item['created_at'], item['id']))
        if members:
            first = members[0]['_grouping']
            if any(any(item['_grouping'][key] != first[key]
                       for key in ('id', 'snapshot', 'namespace', 'fingerprint')) for item in members):
                return []  # malformed/mismatched persisted context never forms a group
        return members

    def _rotate_group_snapshot_locked(self, item: dict) -> None:
        metadata = self._group_metadata(item)
        if metadata is None:
            return
        snapshot = uuid.uuid4().hex
        for member in self._group_members_locked(metadata['id']):
            member['_grouping']['snapshot'] = snapshot

    def _backup_group_locked(self, item: dict) -> list[tuple[dict, dict]]:
        metadata = self._group_metadata(item)
        members = self._group_members_locked(metadata['id']) if metadata else []
        return [(member, copy.deepcopy(member)) for member in members or [item]]

    def _save_changes_locked(self, backups: list[tuple[dict, dict]], *, added: str | None = None) -> None:
        """Publish in-memory changes only if the durable atomic write succeeds."""
        try:
            self._save()
        except Exception:
            for item, original in backups:
                item.clear()
                item.update(original)
            if added is not None:
                self._items.pop(added, None)
                self._events.pop(added, None)
            raise

    def pending_groups(self) -> list[dict]:
        """Optional card projection. Machine lists and per-caller IDs remain complete."""
        with self._lock:
            identifiers = {metadata['id'] for item in self._items.values()
                           if item.get('status') == 'pending'
                           and (metadata := self._group_metadata(item)) is not None}
            groups = []
            for identifier in identifiers:
                members = self._group_members_locked(identifier)
                if len(members) > 1:
                    groups.append({'id': identifier, 'leader_id': members[0]['id'],
                                   'count': len(members),
                                   'member_ids': [member['id'] for member in members],
                                   'snapshot': members[0]['_grouping']['snapshot']})
            groups.sort(key=lambda group: self._items[group['leader_id']]['created_at'])
            return groups

    def reject_group(self, group_id: str, *, snapshot: str, member_ids: list[str],
                     by: str = 'user', reason: str | None = None) -> list[dict] | None:
        """Reject an exact current group, all or none; never grant any approval."""
        human_reason = normalize_reason(reason)
        with self._lock:
            members = self._group_members_locked(group_id)
            if (len(members) < 2 or [item['id'] for item in members] != member_ids
                    or members[0]['_grouping']['snapshot'] != snapshot):
                return None
            before = [dict(item) for item in members]
            events = [self._events.get(item['id']) for item in members]
            now = time.time()
            for item in members:
                item.update(status='rejected', decided_by=by, decided_at=now)
                if human_reason is not None:
                    item['human_reason'] = human_reason
            try:
                self._save()
            except Exception:
                for item, original in zip(members, before, strict=True):
                    item.clear()
                    item.update(original)
                raise
            decided = [self._public_item(item) for item in members]
        for item, event in zip(decided, events, strict=True):
            self._clear_judge_pending(item['id'])
            if event is not None:
                event.set()
            self._audit_row(by, 'action_approval.decided', "the owner's decision on a queued tool call",
                            item['id'], {'tool': item.get('tool', ''), 'agent': item.get('agent', ''),
                                         'approved': False, 'by': by, 'group_id': group_id,
                                         'judge': (item.get('judge') or {}).get('judge'),
                                         **({'human_reason': human_reason} if human_reason is not None else {})})
        return decided

    def _clear_judge_pending(self, action_id: str) -> None:
        with self._judge_lock:
            self._judge_pending.discard(action_id)

    def get(self, action_id: str) -> Optional[dict]:
        with self._lock:
            item = self._items.get(action_id)
            return self._public_item(item) if item else None

    def list(self, status: Optional[str] = None) -> list[dict]:
        with self._lock:
            items = [self._public_item(i) for i in self._items.values()]
        if status:
            items = [i for i in items if i["status"] == status]
        items.sort(key=lambda i: i["created_at"], reverse=True)
        return items

    def stats(self) -> dict:
        with self._lock:
            items = list(self._items.values())
        return {
            "total": len(items),
            "pending": sum(1 for i in items if i["status"] == "pending"),
            "approved": sum(1 for i in items if i["status"] == "approved"),
            "rejected": sum(1 for i in items if i["status"] == "rejected"),
            "expired": sum(1 for i in items if i["status"] == "expired"),
        }

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._events.clear()
            self._save()
        with self._judge_lock:
            self._judge_pending.clear()

    # ── H277: the advisory approval judge ────────────────────────────────────

    def annotate(self, action_id: str, annotation: dict) -> Optional[dict]:
        """Store the first judgement on a still-pending item; ``None`` (and nothing written)
        when the item is gone, already decided, or already judged."""
        with self._lock:
            item = self._items.get(action_id)
            if item is None or item.get("status") != "pending" or "judge" in item:
                return None
            item["judge"] = dict(annotation)
            self._save()
            return dict(annotation)

    def _pending_snapshot(self, action_id: str) -> Optional[dict]:
        """Re-read persisted and live state at dispatch; unreadable disk fails closed."""
        from .approval_judge import normalise_snapshot

        with self._lock:
            item = self._items.get(action_id)
            if not item or item.get("status") != "pending" or "judge" in item:
                return None
            if self.path is not None:
                try:
                    persisted = json.loads(self.path.read_text(encoding="utf-8")).get(action_id)
                except (OSError, ValueError, AttributeError):
                    return None
                if (not isinstance(persisted, dict) or persisted.get("status") != "pending"
                        or "judge" in persisted):
                    return None
                # Both views must allow the call; disk edits may add new taint.
                from .approval_judge import action_is_tainted

                if action_is_tainted(persisted):
                    item = {**item, "tainted": True}
            return normalise_snapshot(item)

    def _record_judgement(self, snapshot: dict, stored: dict) -> None:
        from .approval_judge import rationale_sha256

        action_id = snapshot["id"]
        self._audit_row("approval_judge", "action_approval.judged", "", action_id, {
            "tool": snapshot.get("tool", ""), "agent": snapshot.get("agent", ""),
            "score": stored.get("score"), "flags": list(stored.get("flags") or []),
            "truncated": bool(stored.get("truncated")),
            "judge": stored.get("judge"), "rationale_sha256": rationale_sha256(stored)})

    def _audit_row(self, actor: str, action: str, why: str, action_id: str, metadata: dict) -> None:
        audit = self._audit
        if audit is None:
            return
        if action == "action_approval.judged":
            from .approval_judge import ADVISORY_WHY

            why = ADVISORY_WHY
        try:
            audit.record(actor=str(actor or "user"), action=action, why=why,
                         cause=f"action_approval:{action_id}", metadata=metadata)
        except Exception:  # noqa: BLE001 — the audit is best effort; a decision never fails on it
            logger.warning("action approval audit row failed for %s", action_id, exc_info=True)
