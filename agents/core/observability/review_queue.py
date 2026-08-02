"""
review_queue.py — H10.25 Human Review Queue.

Flagged traces — low quality score (auto, from H10.23) or manually flagged —
land in a systematic review queue. A reviewer scores them against a rubric,
votes thumbs up/down, and can promote good/bad examples into an eval dataset
(H9.3b). In-memory-fast, JSON-persisted.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from ..persistence import JsonStore

DEFAULT_PATH = data_path("review_queue.json")
RUBRIC_CRITERIA = ["accuracy", "completeness", "tone", "safety"]


class ReviewQueue(JsonStore):
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._items

    def _deserialize(self, raw) -> None:
        self._items = raw if isinstance(raw, dict) else {}

    # ── flagging ─────────────────────────────────────────────────────────────

    def flag(self, trace: dict, reason: str = "manual", score: Optional[float] = None) -> dict:
        """Add a trace to the queue (idempotent per trace_id)."""
        trace = trace if isinstance(trace, dict) else {}
        trace_id = str(trace.get("id") or trace.get("trace_id") or uuid.uuid4().hex[:12])
        with self._lock:
            existing = next((i for i in self._items.values() if i["trace_id"] == trace_id), None)
            if existing:
                return dict(existing)
            item_id = uuid.uuid4().hex[:12]
            item = {
                "id": item_id,
                "trace_id": trace_id,
                "text_preview": (trace.get("text_preview") or trace.get("output_preview") or "")[:200],
                "score": score if score is not None else (trace.get("quality") or {}).get("score"),
                "reason": reason,
                "status": "pending",
                "verdict": None,
                "rubric": {},
                "notes": "",
                "in_dataset": False,
                "created_at": time.time(),
                "reviewed_at": None,
            }
            self._items[item_id] = item
            self._save()
            return dict(item)

    def auto_flag(self, trace: dict, score: float, threshold: float) -> Optional[dict]:
        """Flag the trace only if *score* is below *threshold* (H10.23 hook)."""
        if score is None or score >= threshold:
            return None
        return self.flag(trace, reason=f"auto: score {score} < {threshold}", score=score)

    # ── review ───────────────────────────────────────────────────────────────

    def review(self, item_id: str, verdict: str, rubric: Optional[dict] = None,
               notes: str = "") -> Optional[dict]:
        if verdict not in ("up", "down"):
            raise ValueError("verdict must be 'up' or 'down'")
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return None
            item["verdict"] = verdict
            item["rubric"] = {k: v for k, v in (rubric or {}).items() if k in RUBRIC_CRITERIA}
            item["notes"] = notes or ""
            item["status"] = "reviewed"
            item["reviewed_at"] = time.time()
            self._save()
            return dict(item)

    def to_eval_case(self, item: dict) -> dict:
        """Convert a reviewed item into an eval dataset case.

        Emits the documented DatasetStore contract ({"name","prompt",
        "expect_contains","metadata"}) — the old {"input","expected"} shape was
        unreadable by ``run_dataset``, so a promoted case replayed an EMPTY
        prompt against the live model and scored a fabricated 1.0 (WFL-088).
        ``source`` stays top-level for existing consumers. The preview is the
        flagged turn's truncated text, and for manual flags may be an answer
        rather than a prompt — ``prompt_source`` says so instead of claiming a
        faithful replay.
        """
        return {
            "name": f"review-{item.get('trace_id')}",
            "prompt": item.get("text_preview", ""),
            "expect_contains": None,
            "source": "human_review",
            "metadata": {
                "source": "human_review",
                "verdict": item.get("verdict"),
                "rubric": item.get("rubric", {}),
                "notes": item.get("notes", ""),
                "trace_id": item.get("trace_id"),
                "prompt_source": "trace.text_preview",
            },
        }

    def mark_in_dataset(self, item_id: str) -> Optional[dict]:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return None
            item["in_dataset"] = True
            self._save()
            return dict(item)

    # ── queries ──────────────────────────────────────────────────────────────

    def get(self, item_id: str) -> Optional[dict]:
        with self._lock:
            item = self._items.get(item_id)
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
        reviewed = [i for i in items if i["status"] == "reviewed"]
        return {
            "total": len(items),
            "pending": sum(1 for i in items if i["status"] == "pending"),
            "reviewed": len(reviewed),
            "thumbs_up": sum(1 for i in reviewed if i["verdict"] == "up"),
            "thumbs_down": sum(1 for i in reviewed if i["verdict"] == "down"),
            "in_dataset": sum(1 for i in items if i["in_dataset"]),
            "rubric_criteria": RUBRIC_CRITERIA,
        }

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._save()
