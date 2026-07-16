# tests/test_resilience.py
import logging
import pytest
import asyncio
import time
from agents.core.resilience import resilient_call


@pytest.mark.asyncio
async def test_timeout_exhaustion_logs_quietly_with_context(caplog):
    """A fully-timed-out call is expected-and-handled plumbing (the circuit
    breaker WARNs the closed->open transition once, and state is exposed via
    /api/resilience). The final exhaustion must not add a bare context-free
    ERROR on top — real-world 2026-07-08, embedding/plugin timeouts on a fresh
    install spammed `ERROR: All 3 attempts timed out` and looked broken. It
    should log quietly and name the wrapped call so it stays diagnosable."""
    async def always_times_out():
        raise asyncio.TimeoutError("nope")

    wrapped = resilient_call(max_retries=1, backoff_base=0.0)(always_times_out)
    with caplog.at_level(logging.DEBUG, logger="jarvis.resilience"), \
            pytest.raises(asyncio.TimeoutError):
        await wrapped()

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], \
        "timeout exhaustion must not log at ERROR"
    assert any(
        "timed out" in r.getMessage() and "always_times_out" in r.getMessage()
        for r in caplog.records
    ), "exhaustion should be logged with the wrapped function name for diagnosis"


@pytest.mark.asyncio
async def test_resilient_call_final_error_log_omits_exception_message(caplog):
    sentinel = "PROVIDER_EXCEPTION_SENTINEL_f731"

    async def fails_with_secret():
        raise RuntimeError(sentinel)

    wrapped = resilient_call(max_retries=0)(fails_with_secret)
    with caplog.at_level(logging.DEBUG, logger="jarvis.resilience"), \
            pytest.raises(RuntimeError, match=sentinel):
        await wrapped()

    assert sentinel not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "fails_with_secret" in caplog.text

@pytest.mark.asyncio
async def test_resilient_call_retries_on_timeout():
    call_count = 0
    
    async def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise asyncio.TimeoutError("Simulated timeout")
        return "success"
    
    wrapped = resilient_call(max_retries=3, timeout=1.0)(flaky_function)
    result = await wrapped()
    
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_resilient_call_exponential_backoff():
    call_times = []
    
    async def always_fails():
        call_times.append(time.time())
        raise asyncio.TimeoutError("Always fails")
    
    wrapped = resilient_call(max_retries=2, backoff_base=0.1, backoff_max=1.0)(always_fails)
    
    with pytest.raises(asyncio.TimeoutError):
        await wrapped()
    
    assert len(call_times) == 3  # initial + 2 retries
    
    # Check delays: ~0.1s, ~0.2s (with some tolerance)
    delay1 = call_times[1] - call_times[0]
    delay2 = call_times[2] - call_times[1]
    
    # asyncio.sleep() always waits at least the requested duration, so the lower
    # bounds reliably verify that exponential backoff happened (~0.1s then ~0.2s).
    # The upper bounds are loosened well beyond realistic scheduling jitter: the
    # original tight caps (<=0.15 / <=0.30) flaked on loaded CI runners where a
    # 0.1s sleep can wake at ~0.16s. The generous caps still catch gross
    # regressions (backoff_max=1.0, so a single delay should never near a second).
    assert 0.08 <= delay1 < 1.0  # first retry ~0.1s (backoff_base)
    assert 0.15 <= delay2 < 1.5  # second retry ~0.2s (exponential growth)


@pytest.mark.asyncio
async def test_resilient_call_retries_on_all_exceptions():
    call_count = 0
    
    async def raises_value_error():
        nonlocal call_count
        call_count += 1
        raise ValueError("Non-retryable")
    
    wrapped = resilient_call(max_retries=3)(raises_value_error)
    
    with pytest.raises(ValueError):
        await wrapped()
    
    assert call_count == 4  # Retried 3 times after initial failure


from agents.core.resilience import CircuitBreaker, ResilienceMetrics, get_metrics

@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    
    # Simulate 3 failures
    for _ in range(3):
        cb.record_failure()
    
    assert cb.is_open() is True
    assert cb.state == "open"

@pytest.mark.asyncio
async def test_circuit_breaker_closes_on_success():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    
    assert cb.is_open() is False
    assert cb.state == "closed"

@pytest.mark.asyncio
async def test_circuit_breaker_half_open_after_timeout():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open() is True
    
    await asyncio.sleep(0.15)  # Wait for recovery timeout
    
    # Calling is_open() triggers the state transition
    assert cb.is_open() is False
    assert cb.state == "half-open"


@pytest.mark.asyncio
async def test_resilient_call_with_circuit_breaker():
    call_count = 0
    
    async def always_fails():
        nonlocal call_count
        call_count += 1
        raise asyncio.TimeoutError("Always fails")
    
    wrapped = resilient_call(
        max_retries=0,  # No retries for clarity
        circuit_breaker_key="test-key",
        circuit_breaker_threshold=2,
    )(always_fails)
    
    # First two calls should fail and open circuit
    for _ in range(2):
        with pytest.raises(asyncio.TimeoutError):
            await wrapped()
    
    # Third call should fail fast (circuit open)
    with pytest.raises(RuntimeError, match="Circuit breaker open"):
        await wrapped()
    
    assert call_count == 2  # Only 2 actual calls, third was blocked


from agents.core.resilience import ResilienceMetrics

def test_metrics_tracking():
    metrics = ResilienceMetrics()
    
    metrics.record_success("agent:jarvis", "backend:gemini", 1.5)
    metrics.record_success("agent:jarvis", "backend:gemini", 2.0)
    metrics.record_failure("agent:jarvis", "backend:gemini", "timeout")
    metrics.record_failure("agent:friday", "backend:local", "connection_error")
    
    stats = metrics.get_stats()
    
    assert stats["agent:jarvis:backend:gemini"]["success"] == 2
    assert stats["agent:jarvis:backend:gemini"]["failure"] == 1
    assert stats["agent:friday:backend:local"]["failure"] == 1
    assert stats["agent:jarvis:backend:gemini"]["avg_latency"] == 1.75

def test_metrics_reset():
    metrics = ResilienceMetrics()
    
    metrics.record_success("test", "backend", 1.0)
    metrics.reset()
    
    stats = metrics.get_stats()
    assert len(stats) == 0


@pytest.mark.asyncio
async def test_resilient_call_records_metrics():
    call_count = 0
    
    async def succeeds_on_second_try():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise asyncio.TimeoutError("First attempt fails")
        return "success"
    
    wrapped = resilient_call(
        max_retries=1,
        metrics_agent_id="test-agent",
        metrics_backend="test-backend",
    )(succeeds_on_second_try)
    
    result = await wrapped()
    assert result == "success"
    
    stats = get_metrics().get_stats()
    key = "test-agent:test-backend"
    
    assert key in stats
    assert stats[key]["success"] == 1
    assert stats[key]["failure"] == 1
    assert stats[key]["avg_latency"] > 0


@pytest.mark.asyncio
async def test_resilient_call_timeout_none_does_not_clip_long_call():
    # A call that outlasts a short asyncio.wait_for must still complete when
    # timeout=None — the wrapper is bypassed so the call's own budget governs.
    async def slow():
        await asyncio.sleep(0.2)
        return "done"

    # Control: a tight outer timeout clips it.
    with pytest.raises(asyncio.TimeoutError):
        await resilient_call(max_retries=0, timeout=0.05)(slow)()

    # timeout=None: no clip, the call finishes.
    assert await resilient_call(max_retries=0, timeout=None)(slow)() == "done"


@pytest.mark.asyncio
async def test_resilient_call_timeout_none_still_retries_on_exception():
    # Retry/backoff keeps working without the asyncio.wait_for wrapper: a transport
    # error (an ordinary exception, like httpx.ReadTimeout) is retried.
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("transient")
        return "ok"

    wrapped = resilient_call(max_retries=3, timeout=None, backoff_base=0.01, backoff_max=0.02)(flaky)
    assert await wrapped() == "ok"
    assert calls == 3


def test_resilience_public_endpoint():
    """Test that /api/resilience returns expected structure without auth."""
    from fastapi.testclient import TestClient
    from agents import web
    client = TestClient(web.app)
    resp = client.get("/api/resilience")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "metrics" in data
    assert isinstance(data["metrics"], dict)
    assert "circuit_breakers" in data
    assert isinstance(data["circuit_breakers"], dict)
