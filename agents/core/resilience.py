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
):
    """
    Decorator that adds retry logic with exponential backoff to async functions.
    
    Args:
        max_retries: Maximum number of retry attempts
        timeout: Timeout per attempt in seconds
        backoff_base: Base delay for exponential backoff (seconds)
        backoff_max: Maximum delay cap (seconds)
        circuit_breaker_key: Optional key for circuit breaker state tracking
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        func(*args, **kwargs),
                        timeout=timeout
                    )
                    return result
                    
                except asyncio.TimeoutError as e:
                    last_exception = e
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
                    # Non-retryable errors fail immediately
                    logger.error(f"Non-retryable error: {e}")
                    raise
                    
            raise last_exception
            
        return wrapper
    return decorator
