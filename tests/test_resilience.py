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
