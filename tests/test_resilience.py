# tests/test_resilience.py
import pytest
import asyncio
import time
from agents.core.resilience import resilient_call

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
    
    assert 0.08 <= delay1 <= 0.15  # ~0.1s
    assert 0.15 <= delay2 <= 0.30  # ~0.2s


@pytest.mark.asyncio
async def test_resilient_call_fails_immediately_on_non_retryable():
    call_count = 0
    
    async def raises_value_error():
        nonlocal call_count
        call_count += 1
        raise ValueError("Non-retryable")
    
    wrapped = resilient_call(max_retries=3)(raises_value_error)
    
    with pytest.raises(ValueError):
        await wrapped()
    
    assert call_count == 1  # Failed immediately, no retries


from agents.core.resilience import CircuitBreaker

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
