"""
action_approvals.py — H10.18 Action-Level Approval (sub-task granularity).

A live queue of pending **tool-call** approvals: an agent can register an action
before executing it, then `await_decision` until a human approves or rejects it
from the HUD — finer-grained than the task-level decision inbox (H6.2). Each item
carries a dry-run preview (H12.5) so the reviewer sees what the call would do.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Optional


class ActionApprovalQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}
        self._events: dict[str, asyncio.Event] = {}

    # ── request ──────────────────────────────────────────────────────────────

    def request(self, action: dict) -> dict:
        """Register a pending tool-call approval and return the queue item."""
        action = action or {}
        action_id = uuid.uuid4().hex[:12]
        tool = action.get("tool", "")
        args = action.get("args") or {}
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
        with self._lock:
            self._items[action_id] = item
            self._events[action_id] = asyncio.Event()
        return dict(item)

    # ── decide ───────────────────────────────────────────────────────────────

    def decide(self, action_id: str, approved: bool, by: str = "user") -> Optional[dict]:
        with self._lock:
            item = self._items.get(action_id)
            if item is None:
                return None
            if item["status"] == "pending":
                item["status"] = "approved" if approved else "rejected"
                item["decided_by"] = by
                item["decided_at"] = time.time()
            event = self._events.get(action_id)
        if event is not None:
            event.set()
        return dict(item)

    async def await_decision(self, action_id: str, timeout: Optional[float] = None) -> str:
        """Block until the action is decided; return its final status ('approved'/
        'rejected'), or 'timeout' if it isn't decided in time."""
        with self._lock:
            item = self._items.get(action_id)
            event = self._events.get(action_id)
        if item is None:
            return "unknown"
        if item["status"] != "pending":
            return item["status"]
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return "timeout"
        return self._items[action_id]["status"]

    # ── queries ──────────────────────────────────────────────────────────────

    def get(self, action_id: str) -> Optional[dict]:
        with self._lock:
            item = self._items.get(action_id)
            return dict(item) if item else None

    def list(self, status: Optional[str] = None) -> list[dict]:
        with self._lock:
            items = [dict(i) for i in self._items.values()]
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
        }

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._events.clear()
