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

import re
import threading
import time
from collections import deque
from typing import Callable, Optional

LATENCY_BUDGET_MS = 8000.0
DEFAULT_THRESHOLD = 0.6
DEFAULT_PERSONA_THRESHOLD = 0.7
DEFAULT_WINDOW = 50

_COMMON_FORBIDDEN = {
    "no ai disclaimers": ["as an ai", "as a language model"],
    "no flattery": ["great question", "excellent question"],
    "no hedging": ["i think", "perhaps", "maybe"],
    "no preambles": ["sure", "of course", "happy to help"],
}


def _norm_phrase(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def persona_profile_from_soul(soul_text: str, *, version=None) -> dict:
    """Extract a lightweight deterministic persona profile from SOUL prose.

    The hot-path quality rail should not carry full SOUL text in traces. This
    profile keeps only version metadata plus explicit forbidden phrases inferred
    from the SOUL's "Forbidden patterns" style bullets.
    """
    forbidden: set[str] = set()
    for raw_line in str(soul_text or "").splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line:
            continue
        if "forbidden" in lower or lower.startswith("- no ") or lower.startswith("* no "):
            for quoted in re.findall(r'"([^"]{2,80})"', line):
                phrase = _norm_phrase(quoted)
                if phrase:
                    forbidden.add(phrase)
            for marker, phrases in _COMMON_FORBIDDEN.items():
                if marker in lower:
                    forbidden.update(phrases)
    return {
        "source": "soul",
        "version": version,
        "forbidden": sorted(forbidden),
        "required": [],
        "required_any": [],
        "anchors": [],
    }


def _resolve_persona_profile(trace: dict) -> Optional[dict]:
    profile = trace.get("persona_profile")
    if isinstance(profile, dict):
        return profile
    soul_text = trace.get("soul_text") or trace.get("agent_soul")
    if soul_text:
        return persona_profile_from_soul(soul_text, version=trace.get("soul_version"))
    return None


def evaluate_persona_consistency(trace: dict) -> Optional[dict]:
    """Score assistant output against optional persona profile metadata.

    Returns None when no profile is present so legacy traces are scored exactly
    as before. When present, the score is deterministic and offline: it checks
    explicit required phrases/anchors and penalizes forbidden SOUL phrases in
    the assistant reply.
    """
    profile = _resolve_persona_profile(trace)
    if not profile:
        return None
    if "output_preview" in trace:
        text = trace.get("output_preview") or ""
    else:
        text = trace.get("text_preview") or ""
    norm_text = _norm_phrase(text)

    forbidden = [_norm_phrase(p) for p in profile.get("forbidden", [])]
    forbidden_hits = [p for p in forbidden if p and p in norm_text]

    required = [_norm_phrase(p) for p in profile.get("required", [])]
    required_hits = [p for p in required if p and p in norm_text]
    required_score = (len(required_hits) / len(required)) if required else 1.0

    required_any = [_norm_phrase(p) for p in profile.get("required_any", [])]
    required_any_met = any(p and p in norm_text for p in required_any) if required_any else True
    required_any_score = 1.0 if required_any_met else 0.4

    anchors = [_norm_phrase(p) for p in profile.get("anchors", [])]
    anchor_hits = [p for p in anchors if p and p in norm_text]
    anchor_score = (len(anchor_hits) / min(len(anchors), 3)) if anchors else 1.0
    anchor_score = min(1.0, anchor_score)

    score = min(required_score, required_any_score, anchor_score)
    if forbidden_hits:
        score -= min(0.8, 0.35 * len(forbidden_hits))
    score = round(max(0.0, min(1.0, score)), 3)
    return {
        "score": score,
        "version": profile.get("version") or trace.get("soul_version"),
        "source": profile.get("source") or "trace",
        "forbidden_hits": forbidden_hits,
        "required_hits": required_hits,
        "required_any_met": bool(required_any_met),
        "anchor_hits": anchor_hits,
    }


def evaluate_heuristics(trace: dict) -> dict:
    """Return {signal: score in [0,1]} for a trace (no LLM)."""
    # O26-P0.4 (F4): non_empty / no_error judge the RESPONSE. Fall back to the
    # request text only for legacy traces that carry no output_preview KEY at
    # all — an empty reply must score non_empty=0, not borrow the user's text.
    if "output_preview" in trace:
        text = trace.get("output_preview") or ""
    else:
        text = trace.get("text_preview") or ""
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
    persona = evaluate_persona_consistency(trace)
    if persona is not None:
        signals["persona"] = persona["score"]
    heuristic = round(sum(signals.values()) / len(signals), 3)
    judge_score = None
    if judge is not None:
        try:
            judge_score = round(max(0.0, min(1.0, float(judge(trace)))), 3)
        except Exception:
            judge_score = None
    score = round((heuristic + judge_score) / 2, 3) if judge_score is not None else heuristic
    return {
        "score": score,
        "heuristic": heuristic,
        "judge": judge_score,
        "signals": signals,
        "persona": persona,
    }


class QualityMonitor:
    def __init__(self, window: int = DEFAULT_WINDOW, threshold: float = DEFAULT_THRESHOLD,
                 judge: Optional[Callable[[dict], float]] = None,
                 persona_threshold: float = DEFAULT_PERSONA_THRESHOLD) -> None:
        self.window = window
        self.threshold = threshold
        self.persona_threshold = persona_threshold
        self._judge = judge
        self._lock = threading.Lock()
        self._scores: deque = deque(maxlen=window)

    def record(self, trace: dict) -> dict:
        """Evaluate *trace*, store the score, and return the evaluation."""
        result = score_trace(trace, self._judge)
        entry = {
            "trace_id": trace.get("id", ""),
            "score": result["score"],
            "ts": trace.get("ts") or time.time(),
        }
        persona = result.get("persona")
        if persona is not None:
            entry["persona_score"] = persona["score"]
            entry["soul_version"] = persona.get("version")
            entry["agent"] = trace.get("route") or (trace.get("agents") or [""])[0]
        with self._lock:
            self._scores.append(entry)
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
            persona_scores = [s["persona_score"] for s in self._scores
                              if s.get("persona_score") is not None]
        alerting = avg is not None and avg < self.threshold
        persona_avg = (round(sum(persona_scores) / len(persona_scores), 3)
                       if persona_scores else None)
        persona_alerting = persona_avg is not None and persona_avg < self.persona_threshold
        return {
            "alerting": alerting,
            "avg_score": avg,
            "threshold": self.threshold,
            "n": n,
            "persona_alerting": persona_alerting,
            "persona_avg_score": persona_avg,
            "persona_threshold": self.persona_threshold,
        }

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            items = list(self._scores)
        return items[-max(1, limit):][::-1]

    def stats(self) -> dict:
        with self._lock:
            scores = [s["score"] for s in self._scores]
            persona_scores = [s["persona_score"] for s in self._scores
                              if s.get("persona_score") is not None]
        persona_avg = (round(sum(persona_scores) / len(persona_scores), 3)
                       if persona_scores else None)
        return {
            "n": len(scores),
            "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "threshold": self.threshold,
            "alerting": bool(scores) and (sum(scores) / len(scores) < self.threshold),
            "persona": {
                "n": len(persona_scores),
                "avg_score": persona_avg,
                "threshold": self.persona_threshold,
                "alerting": persona_avg is not None and persona_avg < self.persona_threshold,
            },
        }

    def set_threshold(self, threshold: float) -> None:
        self.threshold = max(0.0, min(1.0, float(threshold)))
