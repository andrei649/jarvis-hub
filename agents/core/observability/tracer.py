"""
tracer.py — H9.2 in-memory ring-buffer trace store.

Captures per-request trace dicts (id, ts, channel, intent, timings, tokens …)
and exposes list/get/clear.  Thread-safe via threading.Lock.
"""

import threading
import time
import uuid
from collections import deque
from typing import Optional

try:
    from ..llm.tokenizer import estimate_tokens
except Exception:
    def estimate_tokens(text: str) -> int:  # type: ignore[misc]
        return len(text) // 4 + 1


class Tracer:
    """Ring-buffer store for request traces.

    Parameters
    ----------
    maxlen:
        Maximum number of trace dicts retained.  When the buffer is full the
        oldest entry is evicted automatically (collections.deque semantics).
    """

    def __init__(self, maxlen: int = 500) -> None:
        self._buf: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    # ── write ──────────────────────────────────────────────────────────────

    def record(self, trace: dict) -> str:
        """Assign an id + ts to *trace*, push it, and return the id."""
        trace_id = trace.get("id") or str(uuid.uuid4())
        ts = trace.get("ts") or time.time()
        entry = dict(trace)
        entry["id"] = trace_id
        entry["ts"] = ts
        # Ensure required keys have defaults so consumers never KeyError.
        entry.setdefault("channel", "unknown")
        entry.setdefault("intent", "")
        entry.setdefault("route", "")
        entry.setdefault("agents", [])
        entry.setdefault("model", "")
        entry.setdefault("tokens_in", 0)
        entry.setdefault("tokens_out", 0)
        entry.setdefault("timings", {})
        entry.setdefault("ok", True)
        entry.setdefault("text_preview", "")
        with self._lock:
            self._buf.append(entry)
        return trace_id

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    # ── read ───────────────────────────────────────────────────────────────

    def list(self, limit: int = 50) -> list[dict]:
        """Return up to *limit* traces, most-recent first (summarized)."""
        with self._lock:
            items = list(self._buf)
        items.reverse()
        items = items[:max(1, limit)]
        return [self._summarize(t) for t in items]

    def get(self, trace_id: str) -> Optional[dict]:
        """Return the full trace dict for *trace_id*, or None."""
        with self._lock:
            for entry in self._buf:
                if entry.get("id") == trace_id:
                    return dict(entry)
        return None

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _summarize(t: dict) -> dict:
        timings = t.get("timings", {})
        total_ms = timings.get("total_ms", 0)
        if not total_ms:
            total_ms = (
                timings.get("classify", 0)
                + timings.get("route", 0)
                + timings.get("plugin", 0)
                + timings.get("synthesize", 0)
            )
        return {
            "id": t["id"],
            "ts": t["ts"],
            "channel": t.get("channel", ""),
            "text_preview": t.get("text_preview", ""),
            "intent": t.get("intent", ""),
            "route": t.get("route", ""),
            "agents": t.get("agents", []),
            "model": t.get("model", ""),
            "tokens_in": t.get("tokens_in", 0),
            "tokens_out": t.get("tokens_out", 0),
            "total_ms": total_ms,
            "ok": t.get("ok", True),
        }

    # ── convenience factory ────────────────────────────────────────────────

    @staticmethod
    def build_from_cognition(
        text: str,
        channel: str,
        last_cognition: dict,
        synthesized: str,
        t_classify: int,
        t_route: int,
        t_plugin: int,
        t_synthesize: int,
        model: str = "",
    ) -> dict:
        """Build a trace dict from orchestrator _update_cognition data."""
        decision = last_cognition.get("decision", {})
        agents = decision.get("agents_selected", [])
        intent = decision.get("source", "")
        route = agents[0] if agents else ""
        total_ms = t_classify + t_route + t_plugin + t_synthesize
        return {
            "channel": channel,
            "text_preview": text[:120],
            "intent": intent,
            "route": route,
            "agents": agents,
            "model": model,
            "tokens_in": estimate_tokens(text),
            "tokens_out": estimate_tokens(synthesized),
            "timings": {
                "classify": t_classify,
                "route": t_route,
                "plugin": t_plugin,
                "synthesize": t_synthesize,
                "total_ms": total_ms,
            },
            "ok": True,
        }
