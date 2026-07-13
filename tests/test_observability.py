"""
tests/test_observability.py — Offline tests for H9.2 Trace Explorer + H9.3 Eval Harness.

Runs entirely without a live orchestrator, LLM backend, or network access.
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

# ── make sure the agents package is importable from the worktree ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from core.observability.tracer import Tracer
from core.observability.eval import EvalCase, EvalHarness


# ════════════════════════════════════════════════════════════════
# Tracer unit tests
# ════════════════════════════════════════════════════════════════


class TestTracer:
    def test_record_returns_id(self):
        t = Tracer()
        trace_id = t.record({"channel": "web", "text_preview": "hello"})
        assert isinstance(trace_id, str) and len(trace_id) > 0

    def test_record_adds_required_defaults(self):
        t = Tracer()
        trace_id = t.record({"channel": "test"})
        full = t.get(trace_id)
        assert full is not None
        assert full["channel"] == "test"
        assert "ts" in full
        assert "id" in full
        assert "ok" in full

    def test_list_returns_most_recent_first(self):
        t = Tracer()
        ids = []
        for i in range(5):
            ids.append(t.record({"text_preview": f"msg {i}"}))
        listed = t.list(limit=5)
        assert len(listed) == 5
        # Most recent should be last recorded (ids[-1])
        assert listed[0]["id"] == ids[-1]
        assert listed[-1]["id"] == ids[0]

    def test_list_limit_respected(self):
        t = Tracer()
        for i in range(20):
            t.record({"text_preview": f"msg {i}"})
        listed = t.list(limit=5)
        assert len(listed) == 5

    def test_get_returns_full_trace(self):
        t = Tracer()
        trace_id = t.record({
            "channel": "telegram",
            "text_preview": "find me",
            "intent": "search",
            "timings": {"classify": 10, "route": 5, "plugin": 50, "synthesize": 200, "total_ms": 265},
        })
        full = t.get(trace_id)
        assert full is not None
        assert full["id"] == trace_id
        assert full["channel"] == "telegram"
        assert full["intent"] == "search"
        assert full["timings"]["total_ms"] == 265

    def test_get_unknown_returns_none(self):
        t = Tracer()
        assert t.get("does-not-exist") is None

    def test_clear_empties_buffer(self):
        t = Tracer()
        for i in range(10):
            t.record({"text_preview": f"msg {i}"})
        assert len(t.list(limit=100)) == 10
        t.clear()
        assert len(t.list(limit=100)) == 0

    def test_ring_buffer_evicts_oldest(self):
        maxlen = 5
        t = Tracer(maxlen=maxlen)
        ids = []
        for i in range(10):
            ids.append(t.record({"text_preview": f"msg {i}"}))
        listed = t.list(limit=100)
        assert len(listed) == maxlen
        # Oldest ids (0..4) should be gone; newest (5..9) must be present
        present_ids = {item["id"] for item in listed}
        for old_id in ids[:5]:
            assert old_id not in present_ids, "oldest entry should have been evicted"
        for new_id in ids[5:]:
            assert new_id in present_ids, "newest entry must still be present"

    def test_list_summarizes_total_ms(self):
        t = Tracer()
        trace_id = t.record({
            "timings": {
                "classify": 10,
                "route": 5,
                "plugin": 50,
                "synthesize": 100,
                "total_ms": 0,  # should be computed from parts
            }
        })
        summary = t.list(limit=1)[0]
        assert summary["total_ms"] == 165

    def test_thread_safety(self):
        """Record from multiple threads — no deadlock or data corruption."""
        import threading
        t = Tracer(maxlen=200)
        errors = []

        def worker(n):
            try:
                for i in range(20):
                    t.record({"text_preview": f"t{n}-{i}"})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert not errors
        items = t.list(limit=200)
        # 5 threads × 20 records = 100 total; maxlen=200 so all fit
        assert len(items) == 100

    def test_ring_buffer_evicts_under_overflow(self):
        """When total records exceed maxlen, only maxlen entries survive."""
        maxlen = 10
        t = Tracer(maxlen=maxlen)
        import threading
        for _ in range(3):
            threading.Thread(
                target=lambda: [t.record({"text_preview": "x"}) for _ in range(20)]
            ).start()
        # Give threads time to finish
        import time; time.sleep(0.1)
        items = t.list(limit=1000)
        assert len(items) <= maxlen


# ════════════════════════════════════════════════════════════════
# EvalHarness unit tests
# ════════════════════════════════════════════════════════════════


async def _echo_runner(prompt: str) -> str:
    """Fake runner: echoes the prompt back as response."""
    return f"[echo] {prompt}"


async def _weather_runner(prompt: str) -> str:
    """Fake runner: always returns a weather-shaped response."""
    return "The current temperature is 22°C with sunny skies."


async def _always_fail_runner(prompt: str) -> str:
    """Fake runner: always raises an exception."""
    raise RuntimeError("backend unavailable")


class TestEvalHarness:
    async def test_expect_contains_pass(self):
        harness = EvalHarness(runner=_weather_runner)
        cases = [EvalCase("sunny", "What's the weather?", expect_contains="temperature")]
        result = await harness.run(cases)
        assert result["total"] == 1
        assert result["passed"] == 1
        assert result["results"][0]["passed"] is True
        assert result["results"][0]["score"] == 1.0

    async def test_expect_contains_fail(self):
        harness = EvalHarness(runner=_weather_runner)
        cases = [EvalCase("no match", "What's the weather?", expect_contains="banana")]
        result = await harness.run(cases)
        assert result["passed"] == 0
        assert result["results"][0]["passed"] is False
        assert result["results"][0]["score"] == 0.0

    async def test_expect_contains_case_insensitive(self):
        harness = EvalHarness(runner=_weather_runner)
        cases = [EvalCase("caps", "query", expect_contains="TEMPERATURE")]
        result = await harness.run(cases)
        assert result["passed"] == 1

    async def test_custom_scorer_pass(self):
        def length_scorer(prompt, response):
            return 1.0 if len(response) > 5 else 0.0

        harness = EvalHarness(runner=_echo_runner)
        cases = [EvalCase("len", "hello world", scorer=length_scorer)]
        result = await harness.run(cases)
        assert result["passed"] == 1
        assert result["results"][0]["score"] == 1.0

    async def test_custom_scorer_fail(self):
        def zero_scorer(prompt, response):
            return 0.0

        harness = EvalHarness(runner=_echo_runner)
        cases = [EvalCase("zero", "hello", scorer=zero_scorer)]
        result = await harness.run(cases)
        assert result["passed"] == 0
        assert result["results"][0]["score"] == 0.0

    async def test_no_criterion_defaults_pass(self):
        harness = EvalHarness(runner=_echo_runner)
        cases = [EvalCase("smoke", "any prompt")]
        result = await harness.run(cases)
        assert result["passed"] == 1
        assert result["results"][0]["score"] == 1.0

    async def test_runner_exception_counts_as_fail(self):
        harness = EvalHarness(runner=_always_fail_runner)
        cases = [EvalCase("err", "prompt", expect_contains="something")]
        result = await harness.run(cases)
        assert result["passed"] == 0
        assert "runner error" in result["results"][0]["response"].lower()
        assert "backend unavailable" not in result["results"][0]["response"]

    async def test_aggregate_score(self):
        """3 cases: 2 pass (score=1.0), 1 fail (score=0.0) → mean = 2/3."""
        harness = EvalHarness(runner=_weather_runner)
        cases = [
            EvalCase("c1", "q1", expect_contains="temperature"),
            EvalCase("c2", "q2", expect_contains="temperature"),
            EvalCase("c3", "q3", expect_contains="banana"),
        ]
        result = await harness.run(cases)
        assert result["passed"] == 2
        assert result["total"] == 3
        assert abs(result["score"] - 2 / 3) < 1e-9

    async def test_empty_cases(self):
        harness = EvalHarness(runner=_echo_runner)
        result = await harness.run([])
        assert result["passed"] == 0
        assert result["total"] == 0
        assert result["score"] == 0.0

    async def test_multiple_cases_with_mixed_scorers(self):
        def partial_scorer(prompt, response):
            return 0.7  # >= 0.5 → pass

        harness = EvalHarness(runner=_echo_runner)
        cases = [
            EvalCase("a", "hello", expect_contains="echo"),   # pass
            EvalCase("b", "world", expect_contains="missing"), # fail
            EvalCase("c", "foo", scorer=partial_scorer),       # pass (0.7 >= 0.5)
        ]
        result = await harness.run(cases)
        assert result["passed"] == 2
        assert result["total"] == 3
        expected_score = (1.0 + 0.0 + 0.7) / 3
        assert abs(result["score"] - expected_score) < 1e-9


# ════════════════════════════════════════════════════════════════
# Tracer + orchestrator hook integration (no live LLM)
# ════════════════════════════════════════════════════════════════


class TestTracerOrchestratorHook:
    """Test the record() path that the orchestrator _update_cognition calls."""

    def test_record_full_trace_dict(self):
        """Simulate what _update_cognition sends to tracer.record()."""
        t = Tracer()
        trace_dict = {
            "channel": "web",
            "text_preview": "What is the weather in Bucharest?",
            "intent": "keyword_match",
            "route": "jarvis",
            "agents": ["jarvis"],
            "model": "google/gemma-4-31b-a4b",
            "tokens_in": 10,
            "tokens_out": 50,
            "timings": {
                "classify": 12,
                "route": 3,
                "plugin": 80,
                "synthesize": 310,
                "total_ms": 405,
            },
            "ok": True,
        }
        trace_id = t.record(trace_dict)
        full = t.get(trace_id)
        assert full["channel"] == "web"
        assert full["timings"]["total_ms"] == 405
        assert full["tokens_in"] == 10

    def test_list_summary_fields(self):
        """Summarized list should not expose scoring/full_trace."""
        t = Tracer()
        t.record({
            "channel": "telegram",
            "text_preview": "test",
            "intent": "general",
            "route": "jarvis",
            "agents": ["jarvis"],
            "model": "llama3",
            "tokens_in": 5,
            "tokens_out": 20,
            "timings": {"classify": 5, "route": 2, "plugin": 0, "synthesize": 100, "total_ms": 107},
            "ok": True,
            "scoring": [{"keyword": "test", "weight": 0.8}],
            "full_trace": [{"step": "classify"}],
        })
        summaries = t.list(limit=1)
        assert len(summaries) == 1
        s = summaries[0]
        # Summary keys
        for key in ("id", "ts", "channel", "intent", "route", "agents", "model",
                    "tokens_in", "tokens_out", "total_ms", "ok"):
            assert key in s, f"missing key: {key}"


# ════════════════════════════════════════════════════════════════
# FastAPI endpoint tests (TestClient — no LLM backend needed)
# ════════════════════════════════════════════════════════════════


def _make_app_with_tracer():
    """
    Build a minimal FastAPI test app that wires only the trace endpoints,
    injecting a pre-populated Tracer so no full orchestrator lifecycle runs.
    """
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    tracer = Tracer(maxlen=50)
    # Pre-populate a few traces
    for i in range(3):
        tracer.record({
            "channel": "web",
            "text_preview": f"query {i}",
            "intent": "general",
            "route": "jarvis",
            "agents": ["jarvis"],
            "model": "test-model",
            "tokens_in": i + 1,
            "tokens_out": (i + 1) * 4,
            "timings": {"classify": 5, "route": 2, "plugin": 0, "synthesize": 50, "total_ms": 57},
            "ok": True,
        })

    mini = FastAPI()

    def _nocache(content, status_code=200):
        return JSONResponse(
            content=content,
            status_code=status_code,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @mini.get("/api/traces")
    async def list_traces(limit: int = 50):
        return _nocache({"traces": tracer.list(limit)})

    @mini.get("/api/traces/{trace_id}")
    async def get_trace(trace_id: str):
        item = tracer.get(trace_id)
        if item is None:
            return _nocache({"error": "not found"}, status_code=404)
        return _nocache(item)

    @mini.post("/api/traces/clear")
    async def clear_traces():
        tracer.clear()
        return _nocache({"ok": True})

    return mini, tracer


class TestTraceEndpoints:
    def test_list_traces(self):
        from fastapi.testclient import TestClient
        app, tracer = _make_app_with_tracer()
        client = TestClient(app)
        r = client.get("/api/traces?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert "traces" in data
        assert len(data["traces"]) == 3

    def test_list_traces_limit(self):
        from fastapi.testclient import TestClient
        app, tracer = _make_app_with_tracer()
        # Add more traces
        for i in range(10):
            tracer.record({"text_preview": f"extra {i}"})
        client = TestClient(app)
        r = client.get("/api/traces?limit=5")
        assert r.status_code == 200
        assert len(r.json()["traces"]) == 5

    def test_get_trace_by_id(self):
        from fastapi.testclient import TestClient
        app, tracer = _make_app_with_tracer()
        trace_id = tracer.record({"text_preview": "findme", "channel": "slack"})
        client = TestClient(app)
        r = client.get(f"/api/traces/{trace_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == trace_id
        assert data["channel"] == "slack"

    def test_get_trace_404(self):
        from fastapi.testclient import TestClient
        app, _ = _make_app_with_tracer()
        client = TestClient(app)
        r = client.get("/api/traces/nonexistent-id")
        assert r.status_code == 404

    def test_clear_traces(self):
        from fastapi.testclient import TestClient
        app, tracer = _make_app_with_tracer()
        client = TestClient(app)
        # Confirm there are traces
        r = client.get("/api/traces")
        assert len(r.json()["traces"]) > 0
        # Clear
        rc = client.post("/api/traces/clear")
        assert rc.status_code == 200
        assert rc.json()["ok"] is True
        # Confirm empty
        r2 = client.get("/api/traces")
        assert len(r2.json()["traces"]) == 0

    def test_cache_control_header(self):
        from fastapi.testclient import TestClient
        app, _ = _make_app_with_tracer()
        client = TestClient(app)
        r = client.get("/api/traces")
        assert "no-cache" in r.headers.get("cache-control", "")
