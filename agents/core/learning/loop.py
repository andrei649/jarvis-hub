"""
loop.py — DSPy-style learning loop for Jarvis agents.

Tracks agent interactions, analyzes failure patterns, and generates
optimized prompts to improve agent performance over time.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.learning")


@dataclass
class InteractionRecord:
    agent_id: str
    task: str
    response: str
    success: bool
    latency: float
    timestamp: float
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    route_name: str = ""


class LearningLoop:
    MIN_FAILURES_FOR_OPTIMIZATION = 3
    ANALYSIS_WINDOW = 100

    # Routing health thresholds.
    HEALTH_WINDOW = 20          # recent interactions used to score an agent
    UNHEALTHY_WINDOW = 10       # recent interactions used to flag an agent
    UNHEALTHY_MIN_SAMPLE = 4    # need at least this many records before flagging
    UNHEALTHY_FAILURE_RATE = 0.5

    # Default bench-promotion rules: bench_agent -> when to suggest activation.
    # `source` is the active agent whose query volume triggers the bench agent.
    DEFAULT_PROMOTION_RULES = {
        "bruce": {"source": "vision", "threshold": 20, "window_days": 30},
    }

    def __init__(self, db_path: str = None, promotion_rules: dict = None):
        self.db_path = Path(db_path) if db_path is not None else data_path("learning")
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.interactions: list[InteractionRecord] = []
        # Per-agent index over `interactions` so the per-turn routing path
        # (rank_candidates → health_score/is_unhealthy per candidate) is
        # O(agent window) instead of O(total lifetime history) per lookup.
        self._by_agent: dict[str, list[InteractionRecord]] = {}
        self._index_len = 0
        self.promotion_rules: dict = promotion_rules or dict(self.DEFAULT_PROMOTION_RULES)
        self._load()

    def _agent_index(self) -> dict[str, list[InteractionRecord]]:
        """Return the per-agent index, rebuilding it if `interactions` was
        replaced/loaded out from under it (record() keeps it in sync inline)."""
        if self._index_len != len(self.interactions):
            self._by_agent = {}
            for r in self.interactions:
                self._by_agent.setdefault(r.agent_id, []).append(r)
            self._index_len = len(self.interactions)
        return self._by_agent

    def set_promotion_rules(self, rules: dict):
        """Replace promotion rules (e.g. derived from agents.yaml `bench:`)."""
        if rules:
            self.promotion_rules = dict(rules)

    def record(
        self,
        agent_id: str,
        task: str,
        response: str,
        success: bool,
        latency: float,
        error: str = None,
        metadata: dict = None,
        route_name: str = "",
    ):
        record = InteractionRecord(
            agent_id=agent_id,
            task=task,
            response=response,
            success=success,
            latency=latency,
            timestamp=time.time(),
            error=error,
            metadata=metadata or {},
            route_name=route_name,
        )
        self.interactions.append(record)
        # Keep the per-agent index in sync incrementally (only when it's already
        # current — otherwise _agent_index() rebuilds it on next read).
        if self._index_len == len(self.interactions) - 1:
            self._by_agent.setdefault(agent_id, []).append(record)
            self._index_len += 1
        self._append(record)
        logger.debug(f"Recorded interaction for {agent_id}: {'OK' if success else 'FAIL'} ({latency:.2f}s)")

    def get_agent_records(self, agent_id: str, last_n: int = None) -> list[InteractionRecord]:
        records = self._agent_index().get(agent_id, [])
        if last_n:
            records = records[-last_n:]
        return list(records)

    def get_failure_rate(self, agent_id: str, last_n: int = 50) -> float:
        records = self.get_agent_records(agent_id, last_n)
        if not records:
            return 0.0
        return sum(1 for r in records if not r.success) / len(records)

    def get_success_rate(self, agent_id: str, last_n: int = HEALTH_WINDOW) -> float:
        records = self.get_agent_records(agent_id, last_n)
        if not records:
            return 1.0  # untracked agents are assumed healthy (don't penalize)
        return sum(1 for r in records if r.success) / len(records)

    def interaction_count(self, agent_id: str, window_seconds: float = None, now: float = None) -> int:
        """Count interactions for an agent, optionally within a recent time window."""
        now = now if now is not None else time.time()
        count = 0
        for r in self._agent_index().get(agent_id, []):
            if window_seconds is not None and (now - r.timestamp) > window_seconds:
                continue
            count += 1
        return count

    # ── Routing health (live loop → routing) ──────────────────────────────
    def health_score(self, agent_id: str, last_n: int = HEALTH_WINDOW) -> float:
        """0..1 score used to rank candidate agents for routing."""
        return self.get_success_rate(agent_id, last_n)

    def is_unhealthy(self, agent_id: str) -> bool:
        """True if an agent is failing often enough to be bypassed when an
        alternative exists. Requires a minimum sample so new agents aren't flagged."""
        records = self.get_agent_records(agent_id, self.UNHEALTHY_WINDOW)
        if len(records) < self.UNHEALTHY_MIN_SAMPLE:
            return False
        failure_rate = sum(1 for r in records if not r.success) / len(records)
        return failure_rate >= self.UNHEALTHY_FAILURE_RATE

    def rank_candidates(self, agent_ids: list[str], last_n: int = HEALTH_WINDOW) -> list[str]:
        """Stable-sort candidates by health (best first). Ties keep input order."""
        indexed = list(enumerate(agent_ids))
        indexed.sort(key=lambda pair: (-self.health_score(pair[1], last_n), pair[0]))
        return [aid for _, aid in indexed]

    # ── Bench-agent promotion suggestions ─────────────────────────────────
    def suggest_promotions(self, active_ids=None, now: float = None) -> list[dict]:
        """Suggest activating bench agents whose source agent crossed its volume
        threshold. Skips bench agents that are already active."""
        active = set(active_ids or [])
        now = now if now is not None else time.time()
        suggestions = []
        for bench_id, rule in self.promotion_rules.items():
            if bench_id in active:
                continue
            source = rule.get("source")
            if not source:
                continue
            threshold = int(rule.get("threshold", 20))
            window_days = int(rule.get("window_days", 30))
            count = self.interaction_count(source, window_seconds=window_days * 86400, now=now)
            if count >= threshold:
                suggestions.append({
                    "bench_agent": bench_id,
                    "source_agent": source,
                    "count": count,
                    "threshold": threshold,
                    "window_days": window_days,
                    "reason": f"{count} interactions to {source} in {window_days}d ≥ {threshold}",
                })
        return suggestions

    def get_failure_patterns(self, agent_id: str) -> list[tuple[str, int]]:
        failures = [r for r in self.interactions if r.agent_id == agent_id and not r.success]
        if not failures:
            return []
        error_counts: dict[str, int] = {}
        for f in failures:
            err = f.error or "unknown"
            error_counts[err] = error_counts.get(err, 0) + 1
        return sorted(error_counts.items(), key=lambda x: -x[1])[:5]

    def get_slowest_queries(self, agent_id: str, n: int = 3) -> list[InteractionRecord]:
        records = [r for r in self.interactions if r.agent_id == agent_id and r.success]
        records.sort(key=lambda r: -r.latency)
        return records[:n]

    def optimize_prompt(self, agent_id: str) -> Optional[str]:
        failures = [r for r in self.interactions if r.agent_id == agent_id and not r.success]
        if len(failures) < self.MIN_FAILURES_FOR_OPTIMIZATION:
            return None

        patterns = self.get_failure_patterns(agent_id)
        slow = self.get_slowest_queries(agent_id, 3)
        rate = self.get_failure_rate(agent_id)

        lines = []
        if patterns:
            lines.append(f"- Common errors: {', '.join(f'{err} ({c}x)' for err, c in patterns)}")
        if rate > 0:
            lines.append(f"- Failure rate ({self.ANALYSIS_WINDOW} recent): {rate:.0%}")
        if slow:
            lines.append(f"- Slowest queries: {', '.join(f'{r.latency:.1f}s' for r in slow)}")

        if not lines:
            return None

        return (
            f"[OPTIMIZATION SUGGESTION for {agent_id} — {len(failures)} failures analyzed]\n"
            + "\n".join(lines)
        )

    def _append(self, record: InteractionRecord):
        path = self.db_path / f"{record.agent_id}.jsonl"
        record_dict = asdict(record)
        record_dict["metadata"] = dict(record_dict.get("metadata", {}))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record_dict, ensure_ascii=False) + "\n")

    def _load(self):
        for path in sorted(self.db_path.glob("*.jsonl")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            self.interactions.append(InteractionRecord(**data))
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")
        logger.info(f"Loaded {len(self.interactions)} interaction records from {self.db_path}")

    def get_route_counts(self) -> dict[str, int]:
        """Return count of interactions per route_name."""
        counts: dict[str, int] = {}
        for r in self.interactions:
            if r.route_name:
                counts[r.route_name] = counts.get(r.route_name, 0) + 1
        return counts

    def get_stats(self, active_ids=None) -> dict:
        total = len(self.interactions)
        successes = sum(1 for r in self.interactions if r.success)
        agents = set(r.agent_id for r in self.interactions)
        optimizable = sum(
            1
            for a in agents
            if len([r for r in self.interactions if r.agent_id == a and not r.success])
            >= self.MIN_FAILURES_FOR_OPTIMIZATION
        )
        return {
            "total_interactions": total,
            "successful": successes,
            "failed": total - successes,
            "agents_tracked": len(agents),
            # The IDS, not just the count. `/learning/stats` wanted these and did
            # `list(stats.get("agents_tracked", ...))` — over an int — so it raised
            # TypeError on every single call and its `except Exception` returned a
            # body of zeros. The endpoint had never once reported real data, and
            # nothing noticed because zeros look like a quiet system.
            "agent_ids": sorted(agents),
            "optimizations_available": optimizable,
            "promotion_suggestions": self.suggest_promotions(active_ids),
        }
