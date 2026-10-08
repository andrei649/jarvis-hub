"""Short-lived, one-use image review handles bound to a selected turn route.

Only digests and deadlines survive preparation. The prompt, credential, image
bytes and selected backend object stay outside this store. A refused claim burns
the handle, so a changed route always needs a fresh owner review.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


class VisionReviewRefused(ValueError):
    """A review is missing, expired, or no longer describes this turn."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _Review:
    fingerprint: str
    session: str
    expires_at: float


def _digest(parts: object) -> str:
    try:
        encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise VisionReviewRefused("vlm_review_invalid") from exc
    if len(encoded) > 32_768:
        raise VisionReviewRefused("vlm_review_invalid")
    return hashlib.sha256(b"nerva-vision-review-v1\0" + encoded).hexdigest()


class VisionReviewStore:
    """Process-local review authority; a worker restart invalidates old handles."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 ttl_seconds: float = 60, max_pending: int = 256):
        if not 0 < ttl_seconds <= 300 or not 0 < max_pending <= 4096:
            raise ValueError("invalid vision review limits")
        self._clock = clock
        self._ttl = ttl_seconds
        self._max = max_pending
        self._lock = threading.Lock()
        self._reviews: dict[str, _Review] = {}

    @staticmethod
    def _fingerprint(session_id: str, agent_id: str, prompt: str,
                     model: str, route: str, binding: tuple) -> tuple[str, str]:
        if not all(isinstance(value, str) and value for value in
                   (session_id, agent_id, prompt, model, route)) or not isinstance(binding, tuple):
            raise VisionReviewRefused("vlm_review_invalid")
        return (_digest((session_id, agent_id, prompt, model, route, binding)),
                _digest((session_id,)))

    def issue(self, *, session_id: str, agent_id: str, prompt: str,
              model: str, route: str, binding: tuple) -> str:
        fingerprint, session = self._fingerprint(
            session_id, agent_id, prompt, model, route, binding)
        now = self._clock()
        with self._lock:
            self._reviews = {token: review for token, review in self._reviews.items()
                             if review.expires_at > now}
            if len(self._reviews) >= self._max:
                raise VisionReviewRefused("vlm_review_capacity")
            token = secrets.token_urlsafe(32)
            while token in self._reviews:
                token = secrets.token_urlsafe(32)
            self._reviews[token] = _Review(fingerprint, session, now + self._ttl)
        return token

    def consume(self, token: str, *, session_id: str, agent_id: str, prompt: str,
                model: str, route: str, binding: tuple) -> None:
        if not isinstance(token, str) or not 1 <= len(token) <= 128:
            raise VisionReviewRefused("vlm_review_unavailable")
        fingerprint, _session = self._fingerprint(
            session_id, agent_id, prompt, model, route, binding)
        with self._lock:
            review = self._reviews.pop(token, None)
        if review is None:
            raise VisionReviewRefused("vlm_review_unavailable")
        if review.expires_at <= self._clock():
            raise VisionReviewRefused("vlm_review_expired")
        if not hmac.compare_digest(review.fingerprint, fingerprint):
            raise VisionReviewRefused("vlm_destination_changed")

    def cancel(self, token: str, *, session_id: str) -> None:
        if not isinstance(token, str) or not 1 <= len(token) <= 128:
            raise VisionReviewRefused("vlm_review_unavailable")
        session = _digest((session_id,))
        with self._lock:
            review = self._reviews.get(token)
            if review is None:
                return
            if not hmac.compare_digest(review.session, session):
                raise VisionReviewRefused("vlm_destination_changed")
            del self._reviews[token]
