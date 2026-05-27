"""
loop.py — DSPy-style learning loop for Jarvis agents.

Tracks agent interactions, analyzes failure patterns, and generates
optimized prompts to improve agent performance over time.
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

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


class LearningLoop:
    MIN_FAILURES_FOR_OPTIMIZATION = 3
    ANALYSIS_WINDOW = 100

    def __init__(self, db_path: str = "memory_logs/learning/"):
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.interactions: list[InteractionRecord] = []
        self._load()

    def record(
        self,
        agent_id: str,
        task: str,
        response: str,
        success: bool,
        latency: float,
        error: str = None,
        metadata: dict = None,
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
        )
        self.interactions.append(record)
        self._append(record)
        logger.debug(f"Recorded interaction for {agent_id}: {'OK' if success else 'FAIL'} ({latency:.2f}s)")

    def get_agent_records(self, agent_id: str, last_n: int = None) -> list[InteractionRecord]:
        records = [r for r in self.interactions if r.agent_id == agent_id]
        if last_n:
            records = records[-last_n:]
        return records

    def get_failure_rate(self, agent_id: str, last_n: int = 50) -> float:
        records = self.get_agent_records(agent_id, last_n)
        if not records:
            return 0.0
        return sum(1 for r in records if not r.success) / len(records)

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

    def get_stats(self) -> dict:
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
            "optimizations_available": optimizable,
        }
