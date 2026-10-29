"""Request-owned outcome for one completed orchestrator turn.

The context variable carries a mutable collector across the orchestrator's
copied task contexts. Only its first wrapper may publish, and closing it makes
late child writes inert. No last-turn value is retained on an orchestrator.
"""

from __future__ import annotations

import functools
import logging
import math
import threading
import time
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_EXPLANATIONS = {
    'answered': 'A model answer was returned; the requested objective was not verified.',
    'command': 'A command handler returned a response.',
    'refused': 'The turn was handled with a refusal.',
    'partial': 'Only part of the requested turn returned an answer.',
    'timeout': 'An agent reached its deadline before answering.',
    'unavailable': 'A required response source was unavailable.',
    'failed': 'The turn ended after a handled source failure.',
    'pending_approval': 'A proposed action is queued for owner approval; it has not executed.',
}
_MAX_COUNT = 1_000_000
_MAX_VISIBLE_BYTES = 1_000_000_000


@dataclass(frozen=True, slots=True)
class _Completion:
    kind: str
    explanation: str


class TurnOutcomeCollector:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._claimed = False
        self._closed = False
        self._latency_ms: int | None = None
        self._completion: _Completion | None = None
        self._pending_results: dict[str, int] = {}
        self._agent_results: dict[str, str] = {}
        self._proposed = self._queued = self._executed = self._failures = 0
        self._tool_attribution_unknown = False
        self._visible_bytes = 0
        self._file_attempts: list[tuple[str, str, str]] = []
        self._file_attribution_unknown = False
        self._final: dict | None = None

    def claim(self) -> bool:
        with self._lock:
            if self._closed or self._claimed:
                return False
            self._claimed = True
            return True

    def publish(self, latency_ms: int) -> bool:
        with self._lock:
            if (self._closed or not self._claimed or self._latency_ms is not None
                    or type(latency_ms) is not int or latency_ms < 0):
                return False
            self._latency_ms = latency_ms
            return True

    def settle(self, kind: str) -> bool:
        with self._lock:
            if self._closed or self._completion is not None or kind not in _EXPLANATIONS:
                return False
            self._completion = _Completion(kind, _EXPLANATIONS[kind])
            return True

    def accepted_tool_result(self, agent_id: str) -> bool:
        with self._lock:
            if self._closed or self._completion is not None or not isinstance(agent_id, str):
                return False
            if sum(self._pending_results.values()) >= _MAX_COUNT:
                self._tool_attribution_unknown = True
                return False
            self._pending_results[agent_id] = self._pending_results.get(agent_id, 0) + 1
            return True

    def model_completion(self, agent_id: str) -> bool:
        with self._lock:
            if self._closed or self._completion is not None or not isinstance(agent_id, str):
                return False
            self._pending_results.pop(agent_id, None)
            self._agent_results[agent_id] = 'answered'
            return True

    def agent_observation(self, agent_id: str, kind: str) -> bool:
        with self._lock:
            if (self._closed or self._completion is not None
                    or type(agent_id) is not str or not agent_id or len(agent_id) > 128
                    or kind not in {'answered', 'timeout', 'unavailable', 'refused',
                                    'failed', 'pending_approval'}):
                return False
            if agent_id not in self._agent_results and len(self._agent_results) >= 32:
                return False
            # A typed runtime observation takes precedence over the generic
            # process-return signal. A later failed synthesis is handled above it.
            self._agent_results.setdefault(agent_id, kind)
            return True

    def settle_agents(self, synthesis: str = 'none') -> bool:
        with self._lock:
            if synthesis not in {'none', 'returned', 'failed'} or not self._agent_results:
                return False
            results = tuple(self._agent_results.values())
            if synthesis == 'failed':
                kind = 'partial' if 'answered' in results else 'failed'
            elif 'pending_approval' in results:
                kind = 'pending_approval'
            elif all(item == 'answered' for item in results):
                kind = 'answered'
            elif 'answered' in results:
                kind = 'partial'
            elif all(item == 'timeout' for item in results):
                kind = 'timeout'
            elif all(item == 'unavailable' for item in results):
                kind = 'unavailable'
            elif all(item == 'refused' for item in results):
                kind = 'refused'
            else:
                kind = 'failed'
            return self.settle(kind)

    def tool_proposed(self, queued: bool = False) -> bool:
        with self._lock:
            if self._closed or self._completion is not None or self._proposed >= _MAX_COUNT:
                return False
            self._proposed += 1
            if queued:
                self._queued += 1
            return True

    def tool_queued(self) -> bool:
        with self._lock:
            if self._closed or self._completion is not None or self._queued >= _MAX_COUNT:
                return False
            self._queued += 1
            return True

    def tool_executed(self, success: bool | None) -> bool:
        with self._lock:
            if self._closed or self._completion is not None or self._executed >= _MAX_COUNT:
                return False
            self._executed += 1
            if success is False:
                self._failures += 1
            elif success is not True:
                self._tool_attribution_unknown = True
            return True

    def tool_refused(self) -> bool:
        with self._lock:
            if self._closed or self._completion is not None or self._failures >= _MAX_COUNT:
                return False
            self._failures += 1
            return True

    def visible_output(self, piece: str) -> bool:
        with self._lock:
            if self._closed or type(piece) is not str:
                return False
            self._visible_bytes = min(_MAX_VISIBLE_BYTES, self._visible_bytes + len(piece.encode('utf-8')))
            return True

    def file_attempt(self, target_key: str, op: str, outcome: str) -> bool:
        """Record a trusted physical result in completion order, without a path."""
        with self._lock:
            if (self._closed or self._completion is not None
                    or len(self._file_attempts) >= _MAX_COUNT
                    or type(target_key) is not str or len(target_key) != 64
                    or op not in {'write', 'delete'}
                    or outcome not in {'refused', 'unknown', 'applied_unverified', 'verified'}):
                return False
            self._file_attempts.append((target_key, op, outcome))
            return True

    def file_attribution_unknown(self) -> bool:
        with self._lock:
            if self._closed or self._completion is not None:
                return False
            self._file_attribution_unknown = True
            return True

    def progress(self, *, usage: dict | None = None) -> dict | None:
        with self._lock:
            if self._closed:
                return _copy(self._final)
            result: dict = {}
            if self._latency_ms is not None:
                result['latency_ms'] = self._latency_ms
            if self._completion is not None:
                pending = sum(self._pending_results.values())
                result['completion'] = {
                    'kind': self._completion.kind,
                    'explanation': self._completion.explanation,
                    'severity': 'warning' if pending else 'info',
                    'unanswered_tool_results': pending,
                }
            if self._completion is not None or self._proposed or self._queued or self._executed or self._failures:
                result['tools'] = {
                    'proposed': self._proposed,
                    'queued': self._queued,
                    'executed': None if self._tool_attribution_unknown else self._executed,
                    'failures': None if self._tool_attribution_unknown else self._failures,
                    'basis': 'unknown' if self._tool_attribution_unknown else 'observed',
                }
            if self._completion is not None:
                resolved: set[str] = set()
                pending: list[tuple[int, str, str]] = []
                for ordinal, (target, op, outcome) in reversed(list(enumerate(self._file_attempts, 1))):
                    if outcome == 'verified':
                        resolved.add(target)
                    elif target not in resolved:
                        pending.append((ordinal, op, outcome))
                if pending:
                    result['file_mutations'] = [
                        {'attempt': ordinal, 'operation': op, 'outcome': outcome}
                        for ordinal, op, outcome in reversed(pending)
                    ]
                if self._file_attribution_unknown:
                    result['file_mutation_attribution'] = 'unknown'
            if (type(usage) is dict and usage.get('usage_basis') == 'provider_complete'
                    and type(usage.get('output_tokens')) is int
                    and usage['output_tokens'] >= 0):
                result['output'] = {'tokens': usage['output_tokens'], 'basis': 'provider_complete'}
            elif self._visible_bytes:
                result['output'] = {'tokens': max(1, (self._visible_bytes + 3) // 4),
                                    'basis': 'visible_estimate'}
            elif self._completion is not None:
                result['output'] = {'tokens': None, 'basis': 'unknown'}
            return result or None

    def close(self, *, usage: dict | None = None) -> dict | None:
        with self._lock:
            if self._closed:
                return _copy(self._final)
            final = self.progress(usage=usage) if self._latency_ms is not None else None
            self._final = final
            self._closed = True
            if final is not None and 'completion' in final:
                completion = final['completion']
                log = logger.warning if completion['severity'] == 'warning' else logger.info
                log('turn_completion kind=%s unanswered_tool_results=%d',
                    completion['kind'], completion['unanswered_tool_results'])
            return _copy(final)


def _copy(value: dict | None) -> dict | None:
    if value is None:
        return None
    import copy

    return copy.deepcopy(value)


_current: ContextVar[TurnOutcomeCollector | None] = ContextVar("turn_outcome", default=None)
_origins: weakref.WeakValueDictionary[str, TurnOutcomeCollector] = weakref.WeakValueDictionary()
_origins_lock = threading.RLock()


def bind_approval_origin(origin_id: str) -> None:
    """Associate a live authenticated chat context with its request collector."""
    sink = _current.get()
    if sink is not None and type(origin_id) is str and len(origin_id) == 32:
        with _origins_lock:
            _origins[origin_id] = sink


@dataclass(frozen=True, slots=True)
class FileExecutionOrigin:
    origin_id: str
    record: object


_file_execution: ContextVar[FileExecutionOrigin | None] = ContextVar('file_mutation_execution', default=None)


@contextmanager
def file_execution_scope(origin: FileExecutionOrigin | None):
    token = _file_execution.set(origin)
    try:
        yield
    finally:
        _file_execution.reset(token)


def record_file_mutation_result(target_key: str, op: str, outcome: str, attempt_id: str) -> bool:
    """Persist a checked task's attempt and update only its still-live origin turn."""
    origin = _file_execution.get()
    if origin is None:
        sink = _current.get()
        if sink is not None:
            sink.file_attribution_unknown()
        return False
    try:
        if not origin.record(attempt_id, target_key, op, outcome):
            sink = _current.get()
            if sink is not None:
                sink.file_attribution_unknown()
            return False
    except Exception:
        logger.warning('file mutation outcome audit unavailable', exc_info=True)
        sink = _current.get()
        if sink is not None:
            sink.file_attribution_unknown()
        return False
    with _origins_lock:
        sink = _origins.get(origin.origin_id)
    return bool(sink and sink.file_attempt(target_key, op, outcome))


def open_turn_outcome() -> tuple[TurnOutcomeCollector, object]:
    sink = TurnOutcomeCollector()
    return sink, _current.set(sink)


def reset_turn_outcome(token: object) -> None:
    _current.reset(token)


def record_turn_latency(latency_ms: int) -> bool:
    """Publish one already measured duration; useful to non-wrapper callers."""
    sink = _current.get()
    return bool(sink and sink.claim() and sink.publish(latency_ms))


def current_turn_outcome() -> TurnOutcomeCollector | None:
    return _current.get()


def record_turn_completion(kind: str) -> bool:
    sink = _current.get()
    return bool(sink and sink.settle(kind))


def record_accepted_tool_result(agent_id: str) -> bool:
    sink = _current.get()
    return bool(sink and sink.accepted_tool_result(agent_id))


def record_model_completion(agent_id: str) -> bool:
    sink = _current.get()
    return bool(sink and sink.model_completion(agent_id))


def record_agent_observation(agent_id: str, kind: str) -> bool:
    sink = _current.get()
    return bool(sink and sink.agent_observation(agent_id, kind))


def settle_agent_turn(*, synthesis: str = 'none') -> bool:
    sink = _current.get()
    return bool(sink and sink.settle_agents(synthesis))


def record_tool_proposed(*, queued: bool = False) -> bool:
    sink = _current.get()
    return bool(sink and sink.tool_proposed(queued))


def record_tool_queued() -> bool:
    sink = _current.get()
    return bool(sink and sink.tool_queued())


def record_tool_executed(*, success: bool | None) -> bool:
    sink = _current.get()
    return bool(sink and sink.tool_executed(success))


def record_tool_refused() -> bool:
    sink = _current.get()
    return bool(sink and sink.tool_refused())


def record_visible_output(piece: str) -> bool:
    sink = _current.get()
    return bool(sink and sink.visible_output(piece))


def measure_turn_latency(fn):
    """Time one public orchestrator call through its cleanup, on normal return only."""
    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        sink = _current.get()
        owned = sink is None
        token = None
        if sink is None:
            sink, token = open_turn_outcome()
        if not sink.claim():
            return await fn(*args, **kwargs)
        try:
            started = time.perf_counter()
            result = await fn(*args, **kwargs)
            elapsed = (time.perf_counter() - started) * 1000
            if math.isfinite(elapsed):
                sink.publish(max(0, round(elapsed)))
            return result
        finally:
            if owned:
                sink.close()
                reset_turn_outcome(token)

    return wrapped
