"""
bench.py — Lightweight benchmark system for Jarvis agents.

Port of OpenJarvis's benchmark system (EnergyBenchmark, LatencyBenchmark, ThroughputBenchmark)
to pure Python. Measures:
- Latency per agent call
- Token throughput (estimated)
- Success/failure rates
"""

import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("jarvis.bench")


@dataclass
class BenchmarkSample:
    agent_id: str
    latency: float
    success: bool
    output_length: int
    timestamp: float
    model: str = ""


@dataclass
class BenchmarkResult:
    agent_id: str
    samples: int = 0
    mean_latency: float = 0.0
    median_latency: float = 0.0
    p95_latency: float = 0.0
    min_latency: float = 0.0
    max_latency: float = 0.0
    success_rate: float = 0.0
    throughput_tps: float = 0.0
    model: str = ""


class LatencyBenchmark:
    def __init__(self, window_size: int = 100):
        self.samples: list[BenchmarkSample] = []
        self.window_size = window_size

    def record(self, agent_id: str, latency: float, success: bool, output_length: int = 0, model: str = ""):
        self.samples.append(BenchmarkSample(
            agent_id=agent_id,
            latency=latency,
            success=success,
            output_length=output_length,
            timestamp=time.time(),
            model=model,
        ))
        if len(self.samples) > self.window_size * 10:
            self.samples = self.samples[-self.window_size * 5:]

    def get_results(self, agent_id: Optional[str] = None, last_n: int = 50) -> list[BenchmarkResult]:
        filtered = [s for s in self.samples if agent_id is None or s.agent_id == agent_id]
        if not filtered:
            return []

        filtered = filtered[-last_n:]

        latencies = [s.latency for s in filtered if s.latency > 0]
        if not latencies:
            return []

        success_count = sum(1 for s in filtered if s.success)
        total_chars = sum(s.output_length for s in filtered if s.success)
        total_time = sum(s.latency for s in filtered if s.success)

        sorted_lat = sorted(latencies)
        p95_idx = int(len(sorted_lat) * 0.95)

        tps = total_chars / total_time if total_time > 0 else 0.0

        return [BenchmarkResult(
            agent_id=filtered[0].agent_id,
            samples=len(filtered),
            mean_latency=statistics.mean(latencies),
            median_latency=statistics.median(latencies),
            p95_latency=sorted_lat[p95_idx] if p95_idx < len(sorted_lat) else sorted_lat[-1],
            min_latency=min(latencies),
            max_latency=max(latencies),
            success_rate=success_count / len(filtered) if filtered else 0.0,
            throughput_tps=tps,
            model=filtered[0].model,
        )]

    def get_summary(self) -> dict:
        total = len(self.samples)
        if total == 0:
            return {"total_samples": 0, "agents_tracked": 0}

        agents = set(s.agent_id for s in self.samples)
        success = sum(1 for s in self.samples if s.success)
        mean_lat = statistics.mean([s.latency for s in self.samples if s.latency > 0]) if any(s.latency > 0 for s in self.samples) else 0.0

        return {
            "total_samples": total,
            "agents_tracked": len(agents),
            "successful": success,
            "failed": total - success,
            "overall_mean_latency": round(mean_lat, 3),
        }
