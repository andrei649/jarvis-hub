"""
Resilience patterns: retry with exponential backoff, circuit breaker, metrics.
"""
import asyncio
import functools
import logging
import time
from typing import Callable, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("jarvis.resilience")


def resilient_call(
    max_retries: int = 3,
    timeout: Optional[float] = 30.0,
    backoff_base: float = 1.0,
    backoff_max: float = 10.0,
    circuit_breaker_key: Optional[str] = None,
    circuit_breaker_threshold: int = 5,
    circuit_breaker_recovery: float = 60.0,
    metrics_agent_id: Optional[str] = None,
    metrics_backend: Optional[str] = None,
):
    """
    Decorator that adds retry logic with exponential backoff, circuit breaker, and metrics.

    ``timeout`` is the per-attempt deadline enforced via ``asyncio.wait_for``. Pass
    ``timeout=None`` to disable that wrapper and ``await`` the call directly, letting
    the wrapped call's own timeout govern. This is required for long-running calls
    whose real budget exceeds the default 30s — e.g. cloud-LLM generation behind a
    120s httpx timeout, which a 30s ``wait_for`` would otherwise clip and retry
    needlessly. (Transport timeouts still surface as ordinary exceptions, so retry +
    backoff + circuit-breaker keep working; only the redundant outer deadline is gone.)
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
                    logger.debug(f"Circuit breaker open for {circuit_breaker_key}")
                    raise RuntimeError(f"Circuit breaker open: {circuit_breaker_key}")
            
            # Track metrics if agent/backend provided
            metrics = get_metrics() if metrics_agent_id and metrics_backend else None
            
            last_exception = None
            start_time = time.time()
            
            for attempt in range(max_retries + 1):
                try:
                    if timeout is None:
                        # No outer deadline — await directly so the wrapped call's own
                        # timeout governs (long LLM calls, streaming-adjacent work).
                        result = await func(*args, **kwargs)
                    else:
                        result = await asyncio.wait_for(
                            func(*args, **kwargs),
                            timeout=timeout
                        )
                    if cb:
                        cb.record_success()
                    if metrics:
                        latency = time.time() - start_time
                        metrics.record_success(metrics_agent_id, metrics_backend, latency)
                    return result
                    
                except asyncio.TimeoutError as e:
                    last_exception = e
                    if cb:
                        cb.record_failure()
                    if metrics:
                        metrics.record_failure(metrics_agent_id, metrics_backend, "timeout")
                        
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
                    last_exception = e
                    error_type = type(e).__name__
                    if cb:
                        cb.record_failure()
                    if metrics:
                        metrics.record_failure(metrics_agent_id, metrics_backend, error_type)
                        
                    if attempt < max_retries:
                        delay = min(backoff_base * (2 ** attempt), backoff_max)
                        logger.debug(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed ({error_type}), "
                            f"retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        # Expected/handled by the caller (which logs anything user-facing) and the
                        # breaker state is exposed via /api/resilience — keep the plumbing quiet.
                        logger.debug(
                            f"All {max_retries + 1} attempts failed, last error: {e}"
                        )
                    
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
            # Log the transition ONCE at WARNING (closed → open). A half-open probe that
            # re-fails is an expected re-open while the backend stays down — keep it at DEBUG
            # so a persistently-unreachable optional backend doesn't flood the log every tick.
            was_tripped = self.state in ("open", "half-open")
            self.state = "open"
            if was_tripped:
                logger.debug(f"Circuit breaker re-opened after {self.failure_count} failures")
            else:
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
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


@dataclass
class ResilienceMetrics:
    """Track success/failure/latency metrics per agent+backend combination."""
    _stats: dict = field(default_factory=dict, init=False)
    
    def record_success(self, agent_id: str, backend: str, latency: float):
        """Record a successful call."""
        key = f"{agent_id}:{backend}"
        if key not in self._stats:
            self._stats[key] = {
                "success": 0,
                "failure": 0,
                "total_latency": 0.0,
                "error_types": {},
            }
        
        self._stats[key]["success"] += 1
        self._stats[key]["total_latency"] += latency
    
    def record_failure(self, agent_id: str, backend: str, error_type: str):
        """Record a failed call."""
        key = f"{agent_id}:{backend}"
        if key not in self._stats:
            self._stats[key] = {
                "success": 0,
                "failure": 0,
                "total_latency": 0.0,
                "error_types": {},
            }
        
        self._stats[key]["failure"] += 1
        self._stats[key]["error_types"][error_type] = (
            self._stats[key]["error_types"].get(error_type, 0) + 1
        )
    
    def get_stats(self) -> dict:
        """Get aggregated stats for all agent+backend combinations."""
        result = {}
        for key, data in self._stats.items():
            total_calls = data["success"] + data["failure"]
            avg_latency = (
                data["total_latency"] / data["success"]
                if data["success"] > 0
                else 0.0
            )
            result[key] = {
                "success": data["success"],
                "failure": data["failure"],
                "total": total_calls,
                "avg_latency": avg_latency,
                "error_types": data["error_types"],
            }
        return result
    
    def reset(self):
        """Reset all metrics."""
        self._stats.clear()


# Global metrics instance
_metrics = ResilienceMetrics()


def get_metrics() -> ResilienceMetrics:
    """Get the global metrics instance."""
    return _metrics
