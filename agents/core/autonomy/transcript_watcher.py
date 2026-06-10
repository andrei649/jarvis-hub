"""
transcript_watcher.py — H12.25 Meeting transcript → governed tasks.

Turns a meeting transcript / notes into action items and drops each into the
autonomy **approval queue** (never creates anything directly). On approval, a
downstream executor routes the task to Notion / Todoist — so the creation of an
external task is always a human-gated step (`autonomy_level="ask"`), exactly like
the rest of H6 autonomy.

Extraction is **high-precision** (checkbox lines, explicit "action item:/todo:/
next step:" prefixes, and "<Name> will/to <verb>" assignments) to avoid turning
ordinary discussion into tasks. Pure-Python, offline-testable; the enqueue sink
is injected so it works with or without a live queue.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

logger = logging.getLogger("jarvis.autonomy.transcript")

# Explicit task markers at the start of a line → the remainder is the task.
_PREFIX_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\[[ x]?\]\s*)?"                       # optional bullet / checkbox
    r"(?:action item|action|todo|to-do|ai|next step|follow[\s-]?up)\s*[:\-]\s*"
    r"(?P<task>.+)$",
    re.IGNORECASE,
)
# Bare checkbox line ("- [ ] do the thing") with no keyword prefix.
_CHECKBOX_RE = re.compile(r"^\s*(?:[-*]\s*)?\[[ x]?\]\s*(?P<task>.+)$")
# "<Name> will/to <verb...>" — an assignment we can attribute.
_ASSIGN_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:@)?(?P<who>[A-Z][\w.-]{1,30})\s+(?:will|to|should|needs? to)\s+"
    r"(?P<task>.+)$",
)

_VALID_TARGETS = ("todoist", "notion")
_MAX_ITEMS = 100   # bound a single transcript


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".")


def extract_action_items(transcript: str) -> list[dict]:
    """Extract `{text, assignee}` action items from a transcript (deduped, ordered)."""
    items: list[dict] = []
    seen: set[str] = set()
    for line in (transcript or "").splitlines():
        assignee = ""
        task = ""
        m = _PREFIX_RE.match(line) or _CHECKBOX_RE.match(line)
        if m:
            task = m.group("task")
            a = _ASSIGN_RE.match(task)          # prefix may still name an owner
            if a:
                assignee, task = a.group("who"), a.group("task")
        else:
            a = _ASSIGN_RE.match(line)
            if a:
                assignee, task = a.group("who"), a.group("task")
        task = _clean(task)
        if not task or len(task) < 3:
            continue
        key = task.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({"text": task, "assignee": assignee})
        if len(items) >= _MAX_ITEMS:
            break
    return items


class TranscriptWatcher:
    """Extracts action items and enqueues them as governed (ask-tier) tasks."""

    def __init__(self, enqueue: Optional[Callable] = None, agent: str = "scribe",
                 target: str = "todoist") -> None:
        # enqueue(agent, kind, title, payload=, risk_tier=, autonomy_level=, origin=) -> id
        self._enqueue = enqueue
        self.agent = agent
        self.target = target if target in _VALID_TARGETS else "todoist"

    def ingest(self, transcript: str, source: str = "", target: Optional[str] = None) -> dict:
        """Extract action items → approval queue. Returns extracted + enqueued ids.

        With no enqueue sink this is a **preview** (extraction only, nothing queued).
        """
        tgt = target if target in _VALID_TARGETS else self.target
        items = extract_action_items(transcript)
        # Transcripts are untrusted input. The tasks are already hard-gated to
        # ask-tier (nothing auto-executes), but flag any prompt-injection patterns
        # so the owner SEES the taint on the approval card — an informed human gate.
        injection_flags: list = []
        try:
            from ..security.quarantine import detect_injection
            injection_flags = detect_injection(transcript)
        except Exception:
            injection_flags = []
        enqueued = []
        for item in items:
            title = item["text"][:120]
            payload = {
                "system": tgt,
                "text": item["text"],
                "assignee": item["assignee"],
                "source": source,
                "action": "create_task",
                "injection_flags": injection_flags,
                "untrusted_source": True,
            }
            if self._enqueue is None:
                enqueued.append({"title": title, "queued": False, **item})
                continue
            try:
                task_id = self._enqueue(
                    self.agent, "create_task", f"Task from {source or 'transcript'}: {title}",
                    payload=payload, risk_tier=3, autonomy_level="ask", origin="generated")
                enqueued.append({"title": title, "task_id": task_id, "queued": True, **item})
            except Exception:
                logger.warning("transcript task enqueue failed", exc_info=True)
                enqueued.append({"title": title, "queued": False, **item})
        return {"source": source, "target": tgt, "count": len(items),
                "injection_flags": injection_flags, "suspicious": bool(injection_flags),
                "items": enqueued}
