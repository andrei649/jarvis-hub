"""Task-local request values shared by Gemini routing and generation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace

from .auth_rotation import AuthLease

InvalidateCallback = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class GeminiRequestBinding:
    """Immutable auth and cache selection captured for one request."""

    lease: AuthLease
    session_id: str | None = None
    cache_name: str | None = None
    cached_prefix_count: int = 0
    invalidate_cache: InvalidateCallback | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def without_cache(
        self,
        *,
        lease: AuthLease | None = None,
    ) -> GeminiRequestBinding:
        return replace(
            self,
            lease=lease or self.lease,
            cache_name=None,
            cached_prefix_count=0,
            invalidate_cache=None,
        )


class CachedContentRejected(RuntimeError):
    """Secret-free signal that a provider rejected a bound cache reference."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"cached content rejected ({status_code})")
