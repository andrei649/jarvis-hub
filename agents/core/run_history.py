"""
run_history.py — H10.17 Per-Agent Run History.

A persisted, per-agent timeline of recent runs (input/output previews, latency,
success/failure, cost, route) so the HUD can show "what has this agent been
doing lately". Complementary to the global trace explorer (H9.2, request-scoped)
and the learning log (H4.x, scoring-scoped): this is a compact, agent-indexed
ring kept on disk.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from .config import RUN_HISTORY_MAX_PER_AGENT as MAX_PER_AGENT  # Q4: centralized limit
from .persistence import JsonStore

DEFAULT_PATH = data_path("run_history.json")


class RunHistory(JsonStore):
    def __init__(self, path: str | Path = DEFAULT_PATH, max_per_agent: int = MAX_PER_AGENT) -> None:
        self.max_per_agent = max_per_agent
        super().__init__(path)

    def _serialize(self):
        return {a: list(d) for a, d in self._runs.items()}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._runs = {aid: deque(runs, maxlen=self.max_per_agent) for aid, runs in raw.items()}


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

    def locality(self, since: float | None = None) -> dict:
        """% of recorded runs served on-device vs cloud, from the route field.

        The brand's north-star counter-metric (MOONSHOT §6: "% tasks served
        locally vs cloud"). A route is local unless it starts with "cloud" or is
        a known cloud route ("claude"); unrouted/empty rows are 'unknown' and
        excluded from the percentage so the meter never fabricates a split.

        ``since`` (epoch seconds) restricts the split to runs recorded at/after
        that instant, so a windowed report (the north-star's trailing 7 days)
        never presents the all-time aggregate as a period metric. ``None`` keeps
        the all-time behavior (the /api/analytics/locality board)."""
        with self._lock:
            snapshot = [
                r
                for runs in self._runs.values()
                for r in runs
                if since is None or float(r.get("ts", 0.0)) >= since
            ]
        local = cloud = unknown = 0
        for r in snapshot:
            route = str(r.get("route", "")).lower()
            if not route:
                unknown += 1
            elif route.startswith("cloud") or route in ("claude", "gemini"):
                cloud += 1
            else:  # local, local-deep, local-fallback, ollama-howard, …
                local += 1
        decided = local + cloud
        return {
            "local": local, "cloud": cloud, "unknown": unknown, "total": len(snapshot),
            "local_pct": round(100 * local / decided) if decided else None,
        }

    def clear(self, agent_id: Optional[str] = None) -> None:
        with self._lock:
            if agent_id:
                self._runs.pop(agent_id.strip(), None)
            else:
                self._runs.clear()
            self._save()
