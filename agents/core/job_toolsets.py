"""Explicit installed job tool groups; restrictions never confer authority."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType

CATALOG = MappingProxyType({
    'basic': ('echo', 'time'),
    'files': ('file_read', 'file_list', 'file_search', 'file_write', 'file_delete'),
    'terminal': ('terminal_run',),
    'video': ('video_analyze',),
    'web': ('web_search', 'web_extract'),
    'recall': ('session_search', 'search_memory'),
    'code': ('execute_code',),
    'skills': ('skills_list', 'skill_view', 'skill_propose'),
    'planning': ('desktop_plan', 'operator_plan'),
    'desktop': ('desktop_run',),
    'osint': ('osint_enrich',),
    'image': ('image_generate',),
    'voice': ('speak',),
    'notes': ('memory',),
    'checklist': ('todo',),
    'canvas': ('canvas_point',),
    'cronjob': ('cronjob',),
})


def validate(value):
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) > len(CATALOG)
            or any(not isinstance(item, str) or item not in CATALOG for item in value)
            or len(set(value)) != len(value)):
        raise ValueError('enabled_toolsets must be null or unique known toolset IDs')
    return tuple(value)


def validate_policy_setting(key, value):
    if key == 'platform_toolsets':
        if (not isinstance(value, dict) or set(value) - {'cron'}
                or ('cron' in value and (value['cron'] is None or validate(value['cron']) is None))):
            raise ValueError('platform_toolsets must contain only a cron list of known toolset IDs')
    elif key == 'disabled_toolsets':
        if validate(value) is None:
            raise ValueError('disabled_toolsets must list unique known toolset IDs')
    else:
        raise ValueError('unknown scheduled policy setting')


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


@dataclass(frozen=True)
class JobToolPolicy:
    source: str
    allowed_names: frozenset[str]
    removed_names: frozenset[str]


def resolve_job_policy(options, server, settings=None):
    """Resolve a scheduled model's exact offer bound from one strict settings read."""
    from .settings_db import read_job_tool_policy

    saved = read_job_tool_policy() if settings is None else settings
    for key in ('platform_toolsets', 'disabled_toolsets'):
        validate_policy_setting(key, saved[key])
    if type(saved['allow_agent_scheduling']) is not bool:
        raise ValueError('allow_agent_scheduling must be true or false')
    registered = {row['name'] for row in server.tools()} if server is not None else set()
    if options.get('enabled_toolsets') is not None:
        source, selected = 'job', validate(options['enabled_toolsets'])
    elif 'cron' in saved['platform_toolsets']:
        source, selected = 'cron', validate(saved['platform_toolsets']['cron'])
    else:
        source, selected = 'legacy', None
    if selected is None:
        offered = registered
    else:
        offered = set()
        for group in selected:
            members = set(CATALOG[group])
            if not members <= registered:
                raise ValueError('enabled_toolsets contains an unavailable toolset')
            offered.update(members)
    removed = {name for group in saved['disabled_toolsets'] for name in CATALOG[group]}
    removed.update({'messaging', 'clarify'})
    if not saved['allow_agent_scheduling']:
        removed.add('cronjob')
    return JobToolPolicy(source, frozenset(offered - removed), frozenset(offered & removed))


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
