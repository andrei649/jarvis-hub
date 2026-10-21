"""Request-local conversation identity shared by provider adapters."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_session: ContextVar[str | None] = ContextVar('llm_session', default=None)


def current_session() -> str | None:
    return _session.get()


@contextmanager
def session_scope(session_id: str | None):
    token = _session.set(str(session_id) if session_id else None)
    try:
        yield
    finally:
        _session.reset(token)


# The canonical override is immutable. Only its lifetime is shared with inherited
# tasks, allowing request completion to revoke an explicit override everywhere.


@dataclass
class _ReasoningLifetime:
    active: bool = True
    parent: '_ReasoningLifetime | None' = None

    def is_active(self):
        return self.active and (self.parent is None or self.parent.is_active())


@dataclass(frozen=True)
class _ReasoningFrame:
    effort: str | None
    lifetime: _ReasoningLifetime


_reasoning: ContextVar[_ReasoningFrame | None] = ContextVar('invocation_reasoning', default=None)
_job_reasoning: ContextVar[_ReasoningFrame | None] = ContextVar('required_job_reasoning', default=None)


def ensure_reasoning_active():
    from .reasoning_effort import ReasoningEffortRefused
    frame = _reasoning.get()
    if frame is not None and not frame.lifetime.is_active():
        raise ReasoningEffortRefused()


def selected_reasoning(default):
    ensure_reasoning_active()
    frame = _reasoning.get()
    return frame.effort if frame is not None and frame.effort is not None else default


@contextmanager
def reasoning_scope(effort: str | None):
    from .reasoning_effort import LADDER
    if effort is not None and (type(effort) is not str or effort not in LADDER):
        raise ValueError('reasoning must be a canonical effort level')
    ensure_reasoning_active()
    parent = _reasoning.get()
    frame = (_ReasoningFrame(effort, _ReasoningLifetime(parent=parent.lifetime if parent else None))
             if effort is not None or parent is not None else None)
    token = _reasoning.set(frame)
    try:
        yield
    finally:
        if frame is not None:
            frame.lifetime.active = False
        _reasoning.reset(token)


def required_job_reasoning() -> str | None:
    """An explicit scheduled pin, separate from ordinary chat reasoning choices."""
    from .reasoning_effort import ReasoningEffortRefused

    frame = _job_reasoning.get()
    if frame is not None and not frame.lifetime.is_active():
        raise ReasoningEffortRefused()
    return frame.effort if frame is not None else None


@contextmanager
def job_reasoning_scope(effort: str | None):
    """Apply a job pin without letting a nested absent job shed its parent pin."""
    inherited = _job_reasoning.get()
    if effort is None and inherited is not None:
        required_job_reasoning()
        yield
        return
    with reasoning_scope(effort):
        token = _job_reasoning.set(_reasoning.get() if effort is not None else None)
        try:
            yield
        finally:
            _job_reasoning.reset(token)


# H681 — per-request generation overrides for a delegated sub-agent. A child can ask
# for its own completion budget, temperature and extra OpenAI-compatible body keys;
# they hold for every generation the child makes, and for nothing else. The frame
# records which of them a provider actually applied, so a child whose route could
# not take one is told so rather than left to assume it.

OVERRIDE_KEYS = ('max_tokens', 'temperature', 'extra_body')
MAX_TOKENS_LIMIT = 65536
TEMPERATURE_LIMIT = 2.0
EXTRA_BODY_MAX_BYTES = 4096
#: The only keys ``extra_body`` may set: sampling and output-shape knobs. An allow-list,
#: not a deny-list, because a provider body has many keys that reach what the hub owns
#: — reasoning (``include_reasoning``, ``chat_template_kwargs``), paid tools that send
#: the prompt elsewhere (``plugins``, ``web_search_options``), price (``service_tier``),
#: retention (``store``), routing and data policy (``provider``, ``transforms``) — and a
#: new one appears with every provider release.
ALLOWED_BODY_KEYS = frozenset({
    'top_p', 'top_k', 'min_p', 'seed', 'stop', 'frequency_penalty', 'presence_penalty',
    'repetition_penalty', 'logit_bias', 'response_format', 'user',
})


@dataclass
class RequestOverrides:
    max_tokens: int | None = None
    temperature: float | None = None
    extra_body: dict | None = None
    applied: set = None
    dropped: set = None             # asked for, but a backend or a budget sent something else

    def __post_init__(self):
        if self.applied is None:
            self.applied = set()
        if self.dropped is None:
            self.dropped = set()

    def taken(self) -> set:
        """What every request of the child actually carried."""
        return self.applied - self.dropped

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in OVERRIDE_KEYS if getattr(self, k) is not None}

    def requested(self) -> set:
        return {k for k in OVERRIDE_KEYS if getattr(self, k) is not None}


def validate_overrides(value) -> RequestOverrides | None:
    """A bounded, private copy of *value*, or None when it asks for nothing. Raises
    ValueError naming what is wrong."""
    import copy
    import json
    import math

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('overrides must be an object')
    unknown = sorted(str(k) for k in value if k not in OVERRIDE_KEYS)
    if unknown:
        raise ValueError(f'unknown override(s) {unknown}; allowed: {list(OVERRIDE_KEYS)}')
    out = RequestOverrides()
    if value.get('max_tokens') is not None:
        mt = value['max_tokens']
        if type(mt) is not int or not 1 <= mt <= MAX_TOKENS_LIMIT:
            raise ValueError(f'max_tokens must be an integer from 1 to {MAX_TOKENS_LIMIT}')
        out.max_tokens = mt
    if value.get('temperature') is not None:
        t = value['temperature']
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) \
                or not 0 <= t <= TEMPERATURE_LIMIT:
            raise ValueError(f'temperature must be a number from 0 to {TEMPERATURE_LIMIT:g}')
        out.temperature = float(t)
    if value.get('extra_body') is not None:
        body = value['extra_body']
        if not isinstance(body, dict):
            raise ValueError('extra_body must be an object')
        for key in body:
            if key not in ALLOWED_BODY_KEYS:
                raise ValueError(f'extra_body may not set {key!r}; it takes only {sorted(ALLOWED_BODY_KEYS)}')
        try:
            encoded = json.dumps(body, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError('extra_body must be plain JSON') from exc
        if len(encoded.encode()) > EXTRA_BODY_MAX_BYTES:
            raise ValueError(f'extra_body is larger than {EXTRA_BODY_MAX_BYTES} bytes')
        out.extra_body = copy.deepcopy(body) or None
    return out if out.requested() else None


_overrides: ContextVar[RequestOverrides | None] = ContextVar('request_overrides', default=None)


def current_overrides() -> RequestOverrides | None:
    return _overrides.get()


@contextmanager
def request_overrides_scope(overrides: RequestOverrides | None):
    token = _overrides.set(overrides)
    try:
        yield overrides
    finally:
        _overrides.reset(token)


def apply_generation_overrides(max_tokens, temperature):
    """``(max_tokens, temperature)`` with the request's overrides in place of each one
    it sets; unchanged outside a scope."""
    frame = _overrides.get()
    if frame is None:
        return max_tokens, temperature
    if frame.max_tokens is not None:
        max_tokens = frame.max_tokens
        frame.applied.add('max_tokens')
    if frame.temperature is not None:
        temperature = frame.temperature
        frame.applied.add('temperature')
    return max_tokens, temperature


def merge_extra_body(payload: dict) -> dict:
    """Merge the request's ``extra_body`` into an OpenAI-compatible *payload*, one level
    deep (a dict value updates the payload's dict of that name), never over a key the
    hub owns. Unchanged outside a scope."""
    import copy

    frame = _overrides.get()
    if frame is None or not frame.extra_body:
        return payload
    for key, value in frame.extra_body.items():
        if key not in ALLOWED_BODY_KEYS:               # validated already; kept as a floor
            continue
        value = copy.deepcopy(value)
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    frame.applied.add('extra_body')
    return payload


def note_sent(name: str, value) -> None:
    """A backend or a budget reports the value it actually sends for override *name*
    (None: not sent). One that differs from the override marks it dropped, so the
    child's record never claims a value the provider did not get."""
    frame = _overrides.get()
    if frame is None or name not in ('max_tokens', 'temperature'):
        return
    wanted = getattr(frame, name)
    if wanted is not None and value != wanted:
        frame.dropped.add(name)


def reconcile_payload(payload: dict, max_tokens_key: str = 'max_tokens',
                      temperature_key: str = 'temperature') -> None:
    """``note_sent`` for both generation overrides, read from a finished request body."""
    note_sent('max_tokens', payload.get(max_tokens_key))
    note_sent('temperature', payload.get(temperature_key))
