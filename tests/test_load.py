"""Load test: 15 parallel agent requests, verify <30s total.

Run: python -m pytest tests/test_load.py -v --no-header -q
"""
import sys, os, time, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from core.agent import Agent
from core.router import IntentRouter


class _FakeConfig:
    def __init__(self):
        self.llm_backend = "mock"


class _FakeBackend:
    async def generate(self, model="", prompt="", system=""):
        await asyncio.sleep(0.5)
        return "[mock reply]"


class _FakeRouter(IntentRouter):
    def __init__(self):
        super().__init__(_FakeConfig())
        self._agents = {}

    def select_backend(self, agent_id, prompt):
        return _FakeBackend(), {"backend": "mock"}

    def detect(self):
        pass

    @property
    def backend(self):
        return _FakeBackend()

    @property
    def name(self):
        return "mock"


AGENTS = [
    "jarvis", "friday", "pepper", "vision", "frigga",
    "ultron", "hercules", "jerome", "hephaestus", "veronica",
    "steve", "athena", "howard", "gecko", "stark",
]


@pytest.mark.asyncio
async def test_15_agents_under_30s():
    router = _FakeRouter()
    start = time.time()

    async def run_one(aid):
        agent = Agent(aid, {"name": aid.capitalize()}, router)
        agent.guardrails = None
        return await agent.process("hello", {})

    results = await asyncio.gather(*[run_one(aid) for aid in AGENTS])
    elapsed = time.time() - start

    assert elapsed < 30, f"Load test took {elapsed:.2f}s — exceeds 30s limit"
    assert len(results) == 15
    assert all("[mock reply]" in r for r in results), "Some agents didn't get mock responses"


@pytest.mark.asyncio
async def test_sequential_baseline():
    """Sequential baseline for comparison."""
    router = _FakeRouter()
    start = time.time()
    for aid in AGENTS:
        agent = Agent(aid, {"name": aid.capitalize()}, router)
        agent.guardrails = None
        await agent.process("hello", {})
    elapsed = time.time() - start
    assert elapsed < 80, f"Sequential took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_load_with_failures():
    """Test system handles 50 parallel requests with simulated failure rate."""
    import random
    from agents.core.resilience import resilient_call, get_metrics

    metrics = get_metrics()
    metrics.reset()

    async def flaky_operation():
        if random.random() < 0.1:
            raise asyncio.TimeoutError("Simulated failure")
        await asyncio.sleep(0.1)
        return "success"

    wrapped = resilient_call(
        max_retries=2,
        timeout=5.0,
        metrics_agent_id="load-test",
        metrics_backend="test",
    )(flaky_operation)

    tasks = [wrapped() for _ in range(50)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes = sum(1 for r in results if r == "success")
    failures = sum(1 for r in results if isinstance(r, Exception))

    assert successes >= 45, f"Expected at least 45 successes, got {successes}"

    stats = metrics.get_stats()
    assert "load-test:test" in stats
    assert stats["load-test:test"]["total"] >= 50
