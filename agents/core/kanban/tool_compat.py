"""Small namespace/config/redaction seams for the pinned Hermes tool handlers."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from .context import require_context


class _Registry:
    def __init__(self):
        self.entries: dict[str, dict[str, Any]] = {}

    def register(self, *, name, schema, handler, **kwargs):
        self.entries[name] = {"schema": schema, "handler": handler, **kwargs}

    def get_schema(self, name):
        return self.entries[name]["schema"]


registry = _Registry()
_PROFILES: ContextVar[tuple[str, ...]] = ContextVar("nerva_kanban_profiles", default=())


@contextmanager
def profiles_scope(names):
    token = _PROFILES.set(tuple(names))
    try:
        yield
    finally:
        _PROFILES.reset(token)


def list_profile_names():
    return _PROFILES.get()


def profile_exists(name):
    return name in _PROFILES.get()


def no_cache_check_fn(fn):
    return fn


def tool_error(message):
    import json
    return json.dumps({"ok": False, "error": str(message)})


def redact_sensitive_text(text, *, force=False):
    from agents.core.security.log_redaction import SecretRedactionFilter
    return SecretRedactionFilter().redact_text(text)


def load_config():
    require_context()
    return {"kanban": {"auto_subscribe_on_create": False}}


def cfg_get(config, *keys, default=None):
    value = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def current_profile_name(default=None):
    return require_context().profile


def _current_origin_session_id():
    return require_context().session_id
