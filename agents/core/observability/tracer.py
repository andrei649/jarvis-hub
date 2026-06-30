"""
tracer.py — H9.2 in-memory ring-buffer trace store.

Captures per-request trace dicts (id, ts, channel, intent, timings, tokens …)
and exposes list/get/clear.  Thread-safe via threading.Lock.
"""

from __future__ import annotations

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

    def __init__(self, maxlen: int = 500, *, model_info=None) -> None:
        self._buf: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        # H23.2 (opt-in): a resolver ``(model_id) -> fingerprint dict | None`` used to
        # stamp each trace's ``model_info``. ``None`` (the default) → no enrichment,
        # so ``model_info`` stays ``{}`` and behavior is byte-identical.
        self._model_info = model_info

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
        entry.setdefault("cost", 0.0)
        entry.setdefault("timings", {})
        entry.setdefault("ok", True)
        entry.setdefault("text_preview", "")
        entry.setdefault("model_info", {})
        # H23.2: stamp the model fingerprint when a resolver is wired (opt-in) and the
        # caller didn't already supply one. Best-effort — a resolver hiccup never
        # breaks tracing.
        if self._model_info is not None and entry.get("model") and not entry["model_info"]:
            try:
                info = self._model_info(entry["model"])
                if info:
                    entry["model_info"] = dict(info)
            except Exception:
                pass
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
            "cost": t.get("cost", 0.0),
            "total_ms": total_ms,
            "ok": t.get("ok", True),
            "model_info": t.get("model_info", {}),
        }

    # ── H10.24 cost rollups (derived from per-trace `cost`) ─────────────────

    def cost_by_agent(self) -> list[dict]:
        """Total $ cost + calls per routed agent, highest cost first."""
        with self._lock:
            items = list(self._buf)
        agg: dict[str, dict] = {}
        for t in items:
            agent = t.get("route") or (t.get("agents") or [""])[0] or "unknown"
            row = agg.setdefault(agent, {"agent_id": agent, "calls": 0, "cost": 0.0})
            row["calls"] += 1
            row["cost"] = round(row["cost"] + float(t.get("cost", 0.0)), 6)
        return sorted(agg.values(), key=lambda x: x["cost"], reverse=True)

    def cost_by_day(self) -> list[dict]:
        """Total $ cost + calls per UTC day, most-recent day first."""
        from datetime import datetime, timezone
        with self._lock:
            items = list(self._buf)
        agg: dict[str, dict] = {}
        for t in items:
            day = datetime.fromtimestamp(
                t.get("ts", 0) or 0, tz=timezone.utc
            ).strftime("%Y-%m-%d")
            row = agg.setdefault(day, {"day": day, "calls": 0, "cost": 0.0})
            row["calls"] += 1
            row["cost"] = round(row["cost"] + float(t.get("cost", 0.0)), 6)
        return sorted(agg.values(), key=lambda x: x["day"], reverse=True)

    def cost_summary(self) -> dict:
        with self._lock:
            items = list(self._buf)
        return {
            "calls": len(items),
            "total_cost": round(sum(float(t.get("cost", 0.0)) for t in items), 6),
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
