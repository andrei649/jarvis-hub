"""H391 turn compaction decisions, kept separate from provider and storage code."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock

_active: ContextVar["TurnCompaction | None"] = ContextVar("h391_turn_compaction", default=None)


class TurnLifetime:
    def __init__(self):
        self._lock = Lock()
        self._active = True

    def close(self):
        with self._lock:
            self._active = False

    @contextmanager
    def transaction(self):
        with self._lock:
            yield self._active


@dataclass
class TurnCompaction:
    session_id: str
    enabled: bool
    max_attempts: int
    previous: "TurnCompaction | None" = field(default=None, repr=False)
    threshold_tokens: int = 0
    current_user_index: int = -1
    attempts: "CompressionAttempts" = field(init=False)
    _warned: bool = False
    lifetime: TurnLifetime = field(default_factory=TurnLifetime)
    _route_key: tuple | None = None

    def __post_init__(self):
        self.attempts = CompressionAttempts(self.max_attempts)
        prior = self.previous
        if (prior is not None and prior.session_id == self.session_id
                and prior.enabled and self.enabled
                and prior.max_attempts == self.max_attempts):
            self._warned = prior._warned
            self.threshold_tokens = prior.threshold_tokens
            self._route_key = prior._route_key
        self.previous = None

    def bind_route(self, instance: str, model: str, window: int, threshold: int) -> None:
        key = (str(instance), str(model), int(window))
        if self._route_key is not None and self._route_key != key:
            self.attempts = CompressionAttempts(self.max_attempts)
            self._warned = False
        self._route_key = key
        self.threshold_tokens = threshold

    def warn_blocked(self, reason: str, *, tokens: int, threshold: int) -> bool:
        if self._warned or tokens < threshold or threshold <= 0:
            return False
        from .turn_notices import record_turn_notice

        safe_reason = reason if reason in {
            "disabled", "cooldown", "checkpoint", "no_progress", "attempt_limit",
            "unavailable", "hard_window", "timeout", "handoff",
        } else "unavailable"
        message = (f"Context is over the compression threshold (~{tokens:,} tokens >= "
                   f"{threshold:,}), but compression is blocked ({safe_reason}). "
                   "The model may stop responding. Start a new session or retry compression.")
        accepted = record_turn_notice("context_overflow_blocked", message)
        if not accepted:
            logging.getLogger("jarvis.context").warning(message)
        self._warned = True
        return True

    def pressure_below_threshold(self) -> None:
        """A local estimate cannot prove that a provider accepted the shorter prompt."""

    def observe_usage(self, usage, *, provider_succeeded: bool) -> bool:
        if not self.enabled or self.threshold_tokens <= 0 or usage is None:
            return False
        categories = (getattr(usage, "input_tokens", None),
                      getattr(usage, "cache_read", None),
                      getattr(usage, "cache_write", None))
        if any(type(value) is not int or value < 0 for value in categories):
            return False
        prompt_tokens = sum(categories)
        if (provider_succeeded is True
                and getattr(usage, "prompt_counts_complete", None) is True
                and 0 < prompt_tokens < self.threshold_tokens):
            self._warned = False
        return self.attempts.rearm(
            prompt_tokens=prompt_tokens, threshold_tokens=self.threshold_tokens,
            counts_complete=getattr(usage, "prompt_counts_complete", None),
            provider_succeeded=provider_succeeded,
        )

    def guard_request(self, *, prompt: str, system: str, model: str,
                      window_tokens: int | None, max_tokens: int) -> None:
        """Refuse a request whose conservative input charge cannot fit on the wire."""
        known_window = type(window_tokens) is int and window_tokens > 0
        if not self.enabled and not known_window:
            return
        from .context_compressor import window_for
        from .conversation_clock import CONTEXT_REFUSED_REPLY, CompactionClockRefused
        from .llm.tokenizer import estimate_tokens

        capacity = window_tokens if known_window else window_for(model)
        reserve = max_tokens if type(max_tokens) is int and max_tokens > 0 else 0
        ceiling = min(int(capacity * 0.85), capacity - reserve)
        charged = max((len(prompt) + len(system)) // 4,
                      estimate_tokens(prompt) + estimate_tokens(system))
        if not self.enabled and charged >= max(1, int(capacity * 0.6)):
            self.warn_blocked("disabled", tokens=charged,
                              threshold=max(1, int(capacity * 0.6)))
        if charged > ceiling:
            if self.enabled:
                self.warn_blocked("hard_window", tokens=charged, threshold=ceiling)
            raise CompactionClockRefused(CONTEXT_REFUSED_REPLY)


@contextmanager
def compaction_scope(state):
    token = _active.set(state)
    try:
        yield
    finally:
        state.lifetime.close()
        _active.reset(token)


def active_compaction() -> TurnCompaction | None:
    return _active.get()

def preflight_worth_estimating(rows, *, threshold_tokens, protect_first, protect_last):
    if len(rows) > protect_first + protect_last + 1:
        return True
    return sum(len(str(row.get("content", ""))) // 4 for row in rows) >= threshold_tokens


def idle_should_compact(*, enabled, after_seconds, gap_seconds, tokens, floor_tokens, cooldown):
    return (enabled is True and after_seconds > 0 and gap_seconds >= after_seconds
            and tokens > floor_tokens and not cooldown)


def material_progress(original_len, new_len, original_tokens, new_tokens):
    return (new_len < original_len or
            (original_tokens > 0 and new_tokens < original_tokens * 0.95))


@dataclass
class CompressionAttempts:
    max_attempts: int
    used: int = 0
    completed_pending: bool = False

    def take(self):
        if self.completed_pending or self.used >= max(1, min(10, self.max_attempts)):
            return False
        self.used += 1
        return True

    def mark_completed(self):
        self.completed_pending = True

    def rearm(self, *, prompt_tokens, threshold_tokens, counts_complete, provider_succeeded):
        if not (self.used and self.completed_pending and provider_succeeded is True
                and counts_complete is True and type(prompt_tokens) is int
                and 0 < prompt_tokens < threshold_tokens):
            return False
        self.used = 0
        self.completed_pending = False
        return True


def reanchor_current_user(rows, *, turn_id):
    if not turn_id:
        return -1
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        if (row.get("role") == "user" and row.get("turn_id") == turn_id
                and not row.get("synthetic_handoff") and not row.get("foreign_origin")):
            return index
    return -1


def restore_actionable_user(rows, current):
    if current is None or current.get("role") != "user" or current.get("synthetic_handoff"):
        return None
    index = reanchor_current_user(rows, turn_id=current.get("turn_id"))
    if index == len(rows) - 1:
        return list(rows)
    return [*rows, dict(current)]
