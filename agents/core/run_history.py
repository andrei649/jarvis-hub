"""
run_history.py — H10.17 Per-Agent Run History.

A persisted, per-agent timeline of recent runs (input/output previews, latency,
success/failure, cost, route) so the HUD can show "what has this agent been
doing lately". Complementary to the global trace explorer (H9.2, request-scoped)
and the learning log (H4.x, scoring-scoped): this is a compact, agent-indexed
ring kept on disk.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path("memory_logs/run_history.json")
MAX_PER_AGENT = 100


class RunHistory:
    def __init__(self, path: str | Path = DEFAULT_PATH, max_per_agent: int = MAX_PER_AGENT) -> None:
        self.path = Path(path)
        self.max_per_agent = max_per_agent
        self._lock = threading.Lock()
        self._runs: dict[str, deque] = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for agent_id, runs in raw.items():
                    self._runs[agent_id] = deque(runs, maxlen=self.max_per_agent)
            except Exception:
                self._runs = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        snapshot = {a: list(d) for a, d in self._runs.items()}
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ── write ──────────────────────────────────────────────────────────────

    def record(
        self,
        agent_id: str,
        input_text: str = "",
        output_text: str = "",
        latency_ms: float = 0.0,
        ok: bool = True,
        cost: float = 0.0,
        route: str = "",
        ts: Optional[float] = None,
    ) -> dict:
        agent_id = (agent_id or "").strip()
        if not agent_id:
            return {}
        entry = {
            "ts": ts or time.time(),
            "input_preview": (input_text or "")[:160],
            "output_preview": (output_text or "")[:160],
            "latency_ms": round(float(latency_ms), 1),
            "ok": bool(ok),
            "cost": round(float(cost), 6),
            "route": route,
        }
        with self._lock:
            dq = self._runs.get(agent_id)
            if dq is None:
                dq = deque(maxlen=self.max_per_agent)
                self._runs[agent_id] = dq
            dq.append(entry)
            self._save()
        return dict(entry)

    # ── read ───────────────────────────────────────────────────────────────

    def list(self, agent_id: str, limit: int = 50) -> list[dict]:
        """Return up to *limit* runs for an agent, most-recent first."""
        with self._lock:
            dq = self._runs.get((agent_id or "").strip())
            items = list(dq) if dq else []
        items.reverse()
        return items[:max(1, limit)]

    def agents(self) -> list[dict]:
        """Per-agent rollup: run count, last run, success rate, avg latency."""
        with self._lock:
            snapshot = {a: list(d) for a, d in self._runs.items()}
        out = []
        for agent_id, runs in snapshot.items():
            if not runs:
                continue
            n = len(runs)
            oks = sum(1 for r in runs if r.get("ok"))
            out.append({
                "agent_id": agent_id,
                "runs": n,
                "last_ts": max(r["ts"] for r in runs),
                "ok_rate": round(oks / n, 3),
                "avg_latency_ms": round(sum(r.get("latency_ms", 0) for r in runs) / n, 1),
                "total_cost": round(sum(r.get("cost", 0.0) for r in runs), 6),
            })
        out.sort(key=lambda r: r["last_ts"], reverse=True)
        return out

    def clear(self, agent_id: Optional[str] = None) -> None:
        with self._lock:
            if agent_id:
                self._runs.pop(agent_id.strip(), None)
            else:
                self._runs.clear()
            self._save()
