"""Explicit installed job tool groups; restrictions never confer authority."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType

CATALOG = MappingProxyType({
    'basic': ('echo', 'time'),
    'files': ('file_read', 'file_list', 'file_search', 'file_write', 'file_delete'),
    'terminal': ('terminal_run',),
})


def validate(value):
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) > len(CATALOG)
            or any(not isinstance(item, str) or item not in CATALOG for item in value)
            or len(set(value)) != len(value)):
        raise ValueError('enabled_toolsets must be null or unique known toolset IDs: basic, files, terminal')
    return tuple(value)


def catalog(server):
    registered = {row['name'] for row in server.tools()} if server is not None else set()
    return [{'id': key, 'tools': list(names), 'available': set(names) <= registered}
            for key, names in CATALOG.items()]


def resolve(value, server):
    selected = validate(value)
    if selected is None:
        return None
    installed = {row['id'] for row in catalog(server) if row['available']}
    if any(key not in installed for key in selected):
        raise ValueError('enabled_toolsets contains an unavailable toolset')
    return frozenset(name for key in selected for name in CATALOG[key])


@dataclass
class _Lifetime:
    active: bool = True
    parent: '_Lifetime | None' = None

    def live(self):
        return self.active and (self.parent is None or self.parent.live())


@dataclass(frozen=True)
class _Frame:
    names: frozenset[str]
    lifetime: _Lifetime


_current: ContextVar[_Frame | None] = ContextVar('job_toolset_scope', default=None)


def allows(name: str) -> bool:
    frame = _current.get()
    return frame is None or (frame.lifetime.live() and name in frame.names)


@contextmanager
def toolset_scope(names: frozenset[str] | None):
    parent = _current.get()
    if parent is not None and not parent.lifetime.live():
        raise ValueError('job toolset scope expired')
    if parent is None and names is None:
        yield
        return
    allowed = frozenset(names) if parent is None else (
        parent.names if names is None else parent.names.intersection(names))
    life = _Lifetime(parent=parent.lifetime if parent else None)
    token = _current.set(_Frame(allowed, life))
    try:
        yield
    finally:
        life.active = False
        _current.reset(token)
