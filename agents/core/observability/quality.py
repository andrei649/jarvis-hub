"""
quality.py — H10.23 Live Quality Monitor.

Runs lightweight evaluators on each live request trace (H9.2) and attaches a
quality score, then tracks a rolling average and raises an alert when it drops
below a threshold.

Two evaluator tiers:
* **Heuristic** (always on, offline) — ok flag, non-empty answer, no error marker,
  latency within budget.
* **LLM-as-judge** (optional, injected) — a `judge_fn(trace) -> float in [0,1]`
  blended with the heuristic score when provided.

The monitor keeps an in-memory ring of recent scores; it's the live-quality
signal, not durable history (that's the trace store).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

LATENCY_BUDGET_MS = 8000.0
DEFAULT_THRESHOLD = 0.6
DEFAULT_WINDOW = 50


def evaluate_heuristics(trace: dict) -> dict:
    """Return {signal: score in [0,1]} for a trace (no LLM)."""
    text = trace.get("text_preview") or trace.get("output_preview") or ""
    timings = trace.get("timings", {}) or {}
    total_ms = timings.get("total_ms", 0) or 0
    signals = {
        "ok": 1.0 if trace.get("ok", True) else 0.0,
        "non_empty": 1.0 if str(text).strip() else 0.0,
        "no_error": 0.0 if "[error" in str(text).lower() else 1.0,
        "latency": 1.0 if total_ms <= LATENCY_BUDGET_MS else round(
            max(0.0, LATENCY_BUDGET_MS / total_ms), 3),
    }
    return signals


def score_trace(trace: dict, judge: Optional[Callable[[dict], float]] = None) -> dict:
    """Score a trace: heuristic mean, optionally blended 50/50 with an LLM judge."""
    signals = evaluate_heuristics(trace)
    heuristic = round(sum(signals.values()) / len(signals), 3)
    judge_score = None
    if judge is not None:
        try:
            judge_score = round(max(0.0, min(1.0, float(judge(trace)))), 3)
        except Exception:
            judge_score = None
    score = round((heuristic + judge_score) / 2, 3) if judge_score is not None else heuristic
    return {"score": score, "heuristic": heuristic, "judge": judge_score, "signals": signals}


class QualityMonitor:
    def __init__(self, window: int = DEFAULT_WINDOW, threshold: float = DEFAULT_THRESHOLD,
                 judge: Optional[Callable[[dict], float]] = None) -> None:
        self.window = window
        self.threshold = threshold
        self._judge = judge
        self._lock = threading.Lock()
        self._scores: deque = deque(maxlen=window)

    def record(self, trace: dict) -> dict:
        """Evaluate *trace*, store the score, and return the evaluation."""
        result = score_trace(trace, self._judge)
        with self._lock:
            self._scores.append({
                "trace_id": trace.get("id", ""),
                "score": result["score"],
                "ts": trace.get("ts") or time.time(),
            })
        return result

    def rolling_avg(self, n: Optional[int] = None) -> Optional[float]:
        with self._lock:
            scores = [s["score"] for s in self._scores]
        if not scores:
            return None
        if n:
            scores = scores[-n:]
        return round(sum(scores) / len(scores), 3)

    def check_alert(self) -> dict:
        """Alert when the rolling average sits below the threshold."""
        avg = self.rolling_avg()
        with self._lock:
            n = len(self._scores)
        alerting = avg is not None and avg < self.threshold
        return {"alerting": alerting, "avg_score": avg, "threshold": self.threshold, "n": n}

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            items = list(self._scores)
        return items[-max(1, limit):][::-1]

    def stats(self) -> dict:
        with self._lock:
            scores = [s["score"] for s in self._scores]
        return {
            "n": len(scores),
            "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "threshold": self.threshold,
            "alerting": bool(scores) and (sum(scores) / len(scores) < self.threshold),
        }

    def set_threshold(self, threshold: float) -> None:
        self.threshold = max(0.0, min(1.0, float(threshold)))
