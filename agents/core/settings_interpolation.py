"""H255 — ``${NAME}`` and ``${env:NAME}`` inside settings values.

Ported from Hermes v2026.8.31 ``hermes_cli/config.py`` (MIT): ``_env_expand_match``,
``_expand_env_vars``, ``_env_ref_snapshot`` and ``_preserve_env_ref_templates``
(config.py:2871-3010; inventory ``22-config-b.md`` → ``config-b.core.env_interpolation``).

A stored string may name an environment variable instead of holding its value, so a
credential stays in the hub's ``.env`` (or the process environment) while the setting
points at it::

    nerva config set plugins.twilio_auth_token '${env:TWILIO_AUTH_TOKEN}'

The rules — Hermes', with Nerva's guards:

* A value is expanded when it is loaded for use (``settings_db.get_value``,
  ``settings_db.read_setting`` and the orchestrator's runtime settings, which
  ``settings_db.interpolated`` expands), against the process environment as it is at that
  moment. The stored row keeps the reference; the views the admin panel, ``nerva config``
  and an export read (``get_all``/``get_category``) show it as written.
* Only strings, recursively inside lists and objects; keys, numbers and booleans are not
  touched. Whitespace inside the braces is ignored. One pass: what a variable holds is
  never expanded again.
* ``${env:NAME}`` that is not set stays as written, and a WARNING names the setting, the
  variable and the ``.env`` it belongs in — once while it stays unset (it warns again if
  it is unset after it was set). A bare ``${NAME}`` that is not set stays as written,
  silently.
* Any other ``${source:…}`` prefix (``${vault:…}``, ``${bitwarden:…}``) stays as written
  and warns once per prefix: a setting names an environment variable, nothing else.
* A load cache that holds expanded values (the orchestrator's runtime settings) keeps a
  :func:`snapshot` of the variables they name and loads again when :func:`changed` says
  one of them moved — a ``.env`` loaded late, a variable rotated in the process.
* A save writes the reference back, never what it expands to (:func:`preserve`): when a
  write carries the value a stored reference expands to — now, or at a load this process
  made before the variable moved — the reference is kept. List items are matched by their
  ``name``, else by position.
* No value is logged or kept: a warning names the setting and the variable, and what
  this module remembers about an expansion is a SHA-256 digest of it.

Some settings are literal by design and are never expanded (``settings_db.LITERAL``,
plus every route-only row): their own guard judged the exact text, or ``${…}`` means
something else there. This module knows nothing of them; ``settings_db`` decides.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from typing import Any

logger = logging.getLogger("jarvis.settings")

_REF = re.compile(r"\$\{([^}]+)\}")
_SOURCE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)\s*:(.*)", re.S)
ENV = "env"
BARE = ""

#: How many templates the preservation memory holds, and expansions per template.
SEEN_TEMPLATES = 512
SEEN_PER_TEMPLATE = 8

_lock = threading.Lock()
_warned_unset: set[tuple[str, str]] = set()
_warned_sources: set[str] = set()
_seen: OrderedDict[str, list[str]] = OrderedDict()


def _safe(text: object, limit: int = 120) -> str:
    return str(text).replace("\r", " ").replace("\n", " ")[:limit]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _parse(inner: str) -> tuple[str, str]:
    """``(source, name)`` for the text inside ``${…}``: ``env`` for ``env:NAME``,
    :data:`BARE` for a plain name, else the prefix (lower-cased)."""
    text = inner.strip()
    match = _SOURCE.fullmatch(text)
    if match is None:
        return BARE, text
    return match.group(1).lower(), match.group(2).strip()


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _walk(value: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {key: _walk(item, fn) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(item, fn) for item in value]
    return value


def has_refs(value: Any) -> bool:
    """Whether any string in *value* holds a ``${…}`` reference."""
    return any(_REF.search(text) for text in _strings(value))


def references(value: Any, environ: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """The environment variables *value* names, in order, each once: ``{"name", "set"}``
    (whether the environment holds it now). Names only, never a value."""
    env = os.environ if environ is None else environ
    out: list[dict[str, Any]] = []
    known: set[str] = set()
    for text in _strings(value):
        for match in _REF.finditer(text):
            source, name = _parse(match.group(1))
            if source not in (ENV, BARE) or not name or name in known:
                continue
            known.add(name)
            out.append({"name": name, "set": name in env})
    return out


def _env_files() -> str:
    """Where a variable a setting names belongs: the .env files the hub's load reads."""
    try:
        from .env_provenance import files

        paths = [str(info["path"]) for info in files().values() if info.get("path")]
    except Exception:  # noqa: BLE001 — naming a file is a courtesy, never a failure
        paths = []
    if paths:
        return " or ".join(paths)
    return "the hub's .env (`nerva config env-path` lists where it is)"


def _warn_unset(setting: str, name: str) -> None:
    key = (setting, name)
    with _lock:
        if key in _warned_unset:
            return
        _warned_unset.add(key)
    if not name:
        logger.warning("setting %s holds ${env:} with no variable name: kept as written",
                       _safe(setting))
        return
    logger.warning(
        "setting %s names ${env:%s}, which is not set: kept as written. Set %s in %s, "
        "or in the hub's process environment", _safe(setting), _safe(name), _safe(name),
        _env_files())


def _warn_source(source: str, setting: str) -> None:
    with _lock:
        if source in _warned_sources:
            return
        _warned_sources.add(source)
    logger.warning(
        "setting %s holds a ${%s:…} reference: kept as written. A setting names only an "
        "environment variable, as ${env:NAME}; put the value in the hub's .env or "
        "environment and name it there", _safe(setting), _safe(source, 40))


def _remember(setting: str, template: str, expanded: str) -> None:
    key = _digest(setting + "\0" + template)
    seen = _digest(expanded)
    with _lock:
        digests = _seen.get(key)
        if digests is None:
            digests = _seen[key] = []
            while len(_seen) > SEEN_TEMPLATES:
                _seen.popitem(last=False)
        else:
            _seen.move_to_end(key)
        if seen not in digests:
            digests.append(seen)
            del digests[:-SEEN_PER_TEMPLATE]


def _was_expansion(setting: str, template: str, value: str) -> bool:
    with _lock:
        return _digest(value) in _seen.get(_digest(setting + "\0" + template), ())


def _expand_text(text: str, setting: str, env: Mapping[str, str], *, quiet: bool = False) -> str:
    if "${" not in text:
        return text

    def one(match: re.Match) -> str:
        source, name = _parse(match.group(1))
        if source in (ENV, BARE):
            if name and name in env:
                if not quiet:
                    _warned_unset.discard((setting, name))   # warn again if it goes away
                return env[name]
            if source == ENV and not quiet:
                _warn_unset(setting, name)
            return match.group(0)
        if not quiet:
            _warn_source(source, setting)
        return match.group(0)

    out = _REF.sub(one, text)
    if not quiet and out != text:
        _remember(setting, text, out)
    return out


def expand(value: Any, *, setting: str, environ: Mapping[str, str] | None = None) -> Any:
    """*value* with every ``${NAME}`` / ``${env:NAME}`` the environment holds replaced, a
    copy (*value* is not changed). *setting* (``category.key``) names it in a warning."""
    env = os.environ if environ is None else environ
    return _walk(value, lambda text: _expand_text(text, setting, env))


def snapshot(names: Iterable[str], environ: Mapping[str, str] | None = None) -> dict[str, str | None]:
    """What each variable in *names* holds now, as a digest (None when it is unset): the
    key a load cache compares with :func:`changed`. Never a value."""
    env = os.environ if environ is None else environ
    return {name: (_digest(env[name]) if name in env else None) for name in names}


def changed(snap: Mapping[str, str | None], environ: Mapping[str, str] | None = None) -> bool:
    """Whether a variable in *snap* holds something else now (set, unset or rotated)."""
    env = os.environ if environ is None else environ
    for name, digest in snap.items():
        now = env.get(name)
        if (None if now is None else _digest(now)) != digest:
            return True
    return False


_NO_MATCH = object()


def _expands_to(template: str, value: str, setting: str, env: Mapping[str, str]) -> bool:
    return (_expand_text(template, setting, env, quiet=True) == value
            or _was_expansion(setting, template, value))


def _old_item(item: Any, index: int, old: list, setting: str, env: Mapping[str, str]) -> Any:
    """The stored list item *item* stands for: the one with its ``name`` when the list's
    items are named, else the one at its position."""
    named = [o for o in old if isinstance(o, dict) and isinstance(o.get("name"), str)]
    if named and isinstance(item, dict) and isinstance(item.get("name"), str):
        for candidate in named:
            name = candidate["name"]
            if name == item["name"] or ("${" in name and _expands_to(name, item["name"], setting, env)):
                return candidate
        return _NO_MATCH
    return old[index] if index < len(old) else _NO_MATCH


def _keep(new: Any, old: Any, setting: str, env: Mapping[str, str]) -> Any:
    if isinstance(old, str):
        if (isinstance(new, str) and new and new != old and "${" in old
                and _expands_to(old, new, setting, env)):
            return old
        return new
    if isinstance(old, dict) and isinstance(new, dict):
        return {key: (_keep(item, old[key], setting, env) if key in old else item)
                for key, item in new.items()}
    if isinstance(old, list) and isinstance(new, list):
        out = []
        for index, item in enumerate(new):
            match = _old_item(item, index, old, setting, env)
            out.append(item if match is _NO_MATCH else _keep(item, match, setting, env))
        return out
    return new


def preserve(new: Any, old: Any, *, setting: str, environ: Mapping[str, str] | None = None) -> Any:
    """What a write of *new* over the stored *old* should store: *new*, with every string
    that is what a stored ``${…}`` reference expands to (now, or at an earlier load in this
    process) put back as the reference. An empty string is written as it is: it is never a
    secret, and it is how a reference is cleared."""
    env = os.environ if environ is None else environ
    if not has_refs(old):
        return new
    return _keep(new, old, setting, env)


def reset() -> None:
    """Forget the warnings given and the expansions seen (tests)."""
    with _lock:
        _warned_unset.clear()
        _warned_sources.clear()
        _seen.clear()


__all__ = ["changed", "expand", "has_refs", "preserve", "references", "reset", "snapshot"]
