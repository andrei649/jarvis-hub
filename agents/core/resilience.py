"""
Resilience patterns: retry with exponential backoff, circuit breaker, metrics.
"""
import asyncio
import functools
import logging
import time
from typing import Callable, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("jarvis.resilience")


def resilient_call(
    max_retries: int = 3,
    timeout: float = 30.0,
    backoff_base: float = 1.0,
    backoff_max: float = 10.0,
    circuit_breaker_key: Optional[str] = None,
    circuit_breaker_threshold: int = 5,
    circuit_breaker_recovery: float = 60.0,
):
    """
    Decorator that adds retry logic with exponential backoff and circuit breaker.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Check circuit breaker if key provided
            cb = None
            if circuit_breaker_key:
                cb = get_circuit_breaker(
                    circuit_breaker_key,
                    failure_threshold=circuit_breaker_threshold,
                    recovery_timeout=circuit_breaker_recovery,
                )
                if cb.is_open():
                    logger.warning(f"Circuit breaker open for {circuit_breaker_key}")
                    raise RuntimeError(f"Circuit breaker open: {circuit_breaker_key}")
            
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        func(*args, **kwargs),
                        timeout=timeout
                    )
                    if cb:
                        cb.record_success()
                    return result
                    
                except asyncio.TimeoutError as e:
                    last_exception = e
                    if cb:
                        cb.record_failure()
                        
                    if attempt < max_retries:
                        delay = min(backoff_base * (2 ** attempt), backoff_max)
                        logger.warning(
                            f"Timeout on attempt {attempt + 1}/{max_retries + 1}, "
                            f"retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {max_retries + 1} attempts timed out")
                        
                except Exception as e:
                    if cb:
                        cb.record_failure()
                    logger.error(f"Non-retryable error: {e}")
                    raise
                    
            raise last_exception
            
        return wrapper
    return decorator


@dataclass
class CircuitBreaker:
    """
    Circuit breaker pattern: prevents cascading failures by stopping calls
    to failing services after a threshold.
    
    States:
    - closed: Normal operation, tracking failures
    - open: Fail fast, don't call the service
    - half-open: After recovery timeout, allow one test call
    """
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    failure_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)
    state: str = field(default="closed", init=False)
    
    def record_success(self):
        """Record a successful call, reset failure count."""
        self.failure_count = 0
        self.state = "closed"
    
    def record_failure(self):
        """Record a failed call, potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures"
            )
    
    def is_open(self) -> bool:
        """Check if circuit is open (should fail fast)."""
        if self.state == "closed":
            return False
            
        if self.state == "open":
            # Check if recovery timeout has passed
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = "half-open"
                logger.info("Circuit breaker transitioned to half-open")
                return False
            return True
            
        # half-open: allow one call
        return False
    
    def reset(self):
        """Manually reset the circuit breaker."""
        self.failure_count = 0
        self.state = "closed"


# Global registry of circuit breakers by key
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    key: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """Get or create a circuit breaker for a given key."""
    if key not in _circuit_breakers:
        _circuit_breakers[key] = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _circuit_breakers[key]
