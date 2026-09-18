"""Ephemeral provider output owned by one revocable tool-runtime invocation."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .request_context import current_session
from .responses_dialect import ResponsesRefused, encoded

KEY = '_provider_replay'


class ReplayRefused(ResponsesRefused):
    pass


@dataclass(eq=False, repr=False)
class _Lifetime:
    active: bool = True
    expected: list = field(default_factory=list)
    parent: object = None

    def is_active(self):
        return self.active and (self.parent is None or self.parent.is_active())


_scope: ContextVar[_Lifetime | None] = ContextVar('provider_replay_scope', default=None)


@contextmanager
def replay_scope(*, enabled=True):
    parent = _scope.get()
    if parent is not None and not parent.is_active():
        raise ReplayRefused()
    if not enabled and parent is None:
        yield
        return
    life = _Lifetime(parent=parent)
    token = _scope.set(life)
    try:
        yield
    finally:
        life.active = False
        life.expected.clear()
        _scope.reset(token)


def active_replay(*, required=False):
    life = _scope.get()
    if (life is not None and not life.is_active()) or (required and life is None):
        raise ReplayRefused()
    return life


def projection(message):
    return encoded({'content': message.get('content', ''), 'tool_calls': message.get('tool_calls', [])})


@dataclass(frozen=True, repr=False, eq=False)
class ProviderReplay:
    provider: str
    model: str
    owner: object
    lifetime: _Lifetime
    session: str | None
    items: bytes
    projected: bytes

    def __repr__(self):
        return '<provider replay>'

    def check(self, message, *, owner=None, provider=None, model=None):
        life = active_replay(required=True)
        if (life is not self.lifetime or self.session != current_session()
                or (owner is not None and self.owner is not owner)
                or (provider is not None and self.provider != provider)
                or (model is not None and self.model != model)
                or message.get('role') != 'assistant' or self.projected != projection(message)):
            raise ReplayRefused()


def remember(envelope):
    life = active_replay(required=True)
    if envelope.lifetime is not life:
        raise ReplayRefused()
    life.expected.append(envelope)


def validate_history(messages, *, owner, provider, model):
    life = active_replay()
    found = []
    for message in messages:
        envelope = message.get(KEY)
        if envelope is not None:
            if not isinstance(envelope, ProviderReplay):
                raise ReplayRefused()
            envelope.check(message, owner=owner, provider=provider, model=model)
            found.append(envelope)
        elif message.get('tool_calls'):
            # Native calls cannot be reconstructed after losing their opaque output.
            raise ReplayRefused()
    if found != (life.expected if life is not None else []):
        raise ReplayRefused()


def replay_size(messages):
    total = 0
    for message in messages:
        if KEY in message:
            envelope = message[KEY]
            if not isinstance(envelope, ProviderReplay):
                raise ReplayRefused()
            envelope.check(message)
            total += len(envelope.items)
    return total
