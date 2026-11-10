"""H273 — where each effective configuration value came from.

Configuration reaches the hub in three layers, and the first one to define a key
wins (python-dotenv's ``override=False``):

1. ``process`` — anything in the environment before the hub started: the shell,
   a systemd ``EnvironmentFile``, ``docker run -e``;
2. ``repo_env`` — ``<repo>/.env`` (a development checkout);
3. ``user_env`` — ``<data home>/.env`` (a packaged install's own configuration,
   ``$JARVIS_USER_HOME``).

``load_layered_env`` does the load ``PluginManager.build`` used to do with two
``load_dotenv`` calls, and records which layer supplied each key and which lower
layers also defined it (``shadowed``: their value is ignored). The table holds key
names and layer labels only, never a value. Each file is read once, a named pipe
included (python-dotenv reads FIFOs, which is how 1Password mounts a ``.env``): the
text read is what ``load_dotenv`` loads and what python-dotenv's own parser names the
keys from, silently, so a bad line is warned about once. The data home can be given as
a callable, resolved after the repo layer is loaded, so a ``JARVIS_USER_HOME`` set
in the repo ``.env`` names it, as it did before.

Key names come from python-dotenv itself whenever it can be imported. The stdlib
port below (python-dotenv 1.2.3's grammar) is the fallback that lets
``scripts/doctor.py`` derive the same table in a broken install (``derive``).

The settings plane is separate: ``settings_db`` reports each stored value as the
declared ``default`` or ``set``.

RB-2 — every hub variable has two spellings, ``NERVA_<X>`` (preferred) and ``JARVIS_<X>``
(deprecated), and the table names it once, under the ``JARVIS_`` name the code reads.
Each layer is folded as it loads (``env_alias.fold``): a ``NERVA_<X>`` a file sets
becomes ``JARVIS_<X>`` in the environment, a higher layer that set the variable under
either spelling still wins, a ``FROM_PROCESS_ONLY`` name is left out under either
spelling, and a file that sets both spellings to different values stops the load.
``spelling`` says which spelling supplied a row.

The values a file sets are worked out here, not by python-dotenv (``layer_values``, one
function for the load and for every prediction, so they cannot disagree): its parser
names the bindings, and a ``${NAME}`` / ``${NAME:-default}`` reference is then looked up
under either spelling of a hub variable, in the environment first and in the file's
earlier lines second, exactly as python-dotenv orders them when it does not override.
The fold takes ``NERVA_<X>`` out of the environment, so python-dotenv's own expansion
would turn ``${NERVA_USER_HOME}/`` into ``/``. A line for a path, an endpoint, a
credential or an allowlist that is built from a reference to nothing stops the load,
and so does a path-typed variable left at the filesystem root (``env_alias``).
"""
from __future__ import annotations

import functools
import hashlib
import io
import logging
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from . import env_alias
from .env_config import dotenv_disabled  # python-dotenv's own switch and spellings

logger = logging.getLogger("nerva.env")

PROCESS, REPO_ENV, USER_ENV, RUNTIME = "process", "repo_env", "user_env", "runtime"
LABELS = {
    PROCESS: "process environment",
    REPO_ENV: "repo .env",
    USER_ENV: "data-home .env",
    RUNTIME: "set while running",
}

# The hub loads its .env files before anything else it starts (``load_hub_env``: serve.py
# before it builds the server, the lifespan before its boot guards), so only what is read
# while agents.web is imported comes first. Importing it freezes these into module
# constants (the ASGI root path, the rate limit, CORS, CSP, the router's auto-deep switch,
# the analytics cap, the graph's Neo4j defaults) or locates the hub's own files with them.
# Log redaction is decided before the load on purpose: only the boot environment can lower
# it. A .env value for any of them is recorded but not in effect: they belong in the
# process environment. The list is measured, not remembered: the H273 review tests spy on
# the environment while the hub is imported and started, and fail on a Nerva name read
# before the load that is in none of these lists.
READ_BEFORE_LOAD = frozenset({
    "JARVIS_APP_ROOT", "JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_PROFILE", "JARVIS_ROOT_PATH",
    "JARVIS_RATE_LIMIT", "JARVIS_CORS_ORIGINS", "JARVIS_CSP", "JARVIS_DISABLE_CSP",
    "JARVIS_AUTO_DEEP", "JARVIS_ANALYTICS_MAX_EVENTS",
    "NEO4J_URL", "NEO4J_USER", "NEO4J_PASSWORD", "JARVIS_LOG_REDACTION",
})
# What locates the hub's own files. A file cannot move them: the stores opened while the
# hub was imported would stay under one root and the rest would follow the file, so a .env
# value is recorded, with the note, and never put in the environment.
FROM_PROCESS_ONLY = frozenset({"JARVIS_APP_ROOT", "JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_PROFILE"})
# A name a file may set that the hub also reads before any file can: the file's value
# reaches only what runs after the load.
SPLIT_NOTES = {
    "JARVIS_USER_HOME": ("it names the data home and its .env, but when JARVIS_HOME is not set the stores "
                         "the hub opened while it was imported stay under the default root: set it in the "
                         "process environment"),
}
# Optional SDKs can construct shared TLS contexts while they are imported. Their
# presence/version varies by installation, unlike the mandatory reads above.
# Later HTTP clients can still read a file-provided value, so neither a universal
# before-load nor a universal read-again classification would be accurate.
OPTIONAL_SPLIT_NOTES = {
    "SSL_CERT_FILE": ("optional aiohttp-based transports may cache TLS trust before the .env files "
                      "are loaded; a later .env value affects clients created afterward but not "
                      "those cached contexts: set it in the process environment for consistent trust"),
}
# Read while the hub is imported and read again once the .env files are loaded, so a .env
# value is in effect: DEV_MODE (app_state.dev_mode, ENV-039), the admin and user tokens
# (every guard reads them per request, the MCP transport too, and the bind guard runs after
# the load), the OAuth client ids (PluginManager.build calls oauth.init_from_env after the
# load, on the module the OAuth routes use) and the trusted proxies (proxy_trust reads the
# environment on every call). Measured too: each is read after the load, and no name in
# READ_BEFORE_LOAD is (tests/test_h273d_provenance_review.py).
READ_AGAIN_AFTER_LOAD = frozenset({
    "DEV_MODE", "JARVIS_ADMIN_TOKEN", "JARVIS_USER_TOKEN",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET",
    "JARVIS_TRUSTED_PROXIES", "JARVIS_TRUSTED_PROXY",
})
BEFORE_LOAD_NOTE = ("the hub reads it before the .env files are loaded: the .env value is not in effect, "
                    "so set it in the process environment")
PROCESS_ONLY_NOTE = ("it locates the hub's own files, so the load leaves a .env value out on purpose (the "
                     "stores would split between two roots): the .env value is not in effect, so set it in "
                     "the process environment")

# Substrings that mark an environment variable as a credential (matched in its lower-cased
# name). ``/api/admin/env`` masks such a value, ``/api/admin/env/sources`` flags it, and a
# setting outside the declared credential settings never expands a reference to one (H255).
SECRET_HINTS = ("key", "token", "secret", "password", "passwd", "pass", "client_id")
# The hub's own namespace. A credential in it (the admin and user tokens, the at-rest
# cipher key, the audit and backup keys) is never expanded into any setting (H255).
HUB_PREFIXES = ("JARVIS_", "NERVA_")


def masked(key: str) -> bool:
    """Whether *key* names a credential: ``/api/admin/env`` never returns its value."""
    lowered = str(key).lower()
    return any(hint in lowered for hint in SECRET_HINTS)


def hub_credential(key: str) -> bool:
    """Whether *key* is one of the hub's own credentials (a masked name in its namespace)."""
    return masked(key) and str(key).upper().startswith(HUB_PREFIXES)


_TABLE: dict[str, dict] = {}
_FILES: dict[str, dict] = {}   # what the last load read, per layer: {"path", "kind", "present", "read"}
_NOT_SET: set[str] = set()     # FROM_PROCESS_ONLY names a file set and the load took back out
# Per key a load set: the layer and a digest of the value it set (never the value). A
# later load keeps that attribution only while the environment still holds that value.
_LOADED: dict[str, tuple[str, str]] = {}

# python-dotenv 1.2.3's grammar (dotenv/parser.py), ported for key names only. A
# binding is optional whitespace and ``export``, a single-quoted or unquoted key,
# ``=`` and a value (quoted values may span lines; a backslash always escapes the
# character after it), then an optional comment and the end of the line. Anything
# else on the line makes the whole binding an error, which dotenv skips to the end of
# that line. A key with no ``=`` is parsed with no value, and a key is set only when
# its last binding has one.
_MULTILINE_WS = re.compile(r"\s*")
_WS = re.compile(r"[^\S\r\n]*")
_EXPORT = re.compile(r"(?:export[^\S\r\n]+)?")
_SINGLE_QUOTED_KEY = re.compile(r"'([^']+)'")
_UNQUOTED_KEY = re.compile(r"([^=\#\s]+)")
_EQUAL_SIGN = re.compile(r"(=[^\S\r\n]*)")
_SINGLE_QUOTED_VALUE = re.compile(r"'((?:\\.|[^'\\])*)'", re.DOTALL)
_DOUBLE_QUOTED_VALUE = re.compile(r'"((?:\\.|[^"\\])*)"', re.DOTALL)
_UNQUOTED_VALUE = re.compile(r"([^\r\n]*)")
_COMMENT = re.compile(r"(?:[^\S\r\n]*#[^\r\n]*)?")
_END_OF_LINE = re.compile(r"[^\S\r\n]*(?:\r\n|\n|\r|$)")
_REST_OF_LINE = re.compile(r"[^\r\n]*(?:\r|\n|\r\n)?")


class _Unparsable(Exception):
    pass


def _need(pattern: re.Pattern, text: str, pos: int) -> re.Match:
    match = pattern.match(text, pos)
    if match is None:
        raise _Unparsable
    return match


def _port_keys(text: str) -> list[str]:
    """The stdlib parse: every key in first-seen order, kept when its last binding
    has a value."""
    text = text.removeprefix("\ufeff")
    last_has_value: dict[str, bool] = {}
    pos = 0
    while pos < len(text):
        start = pos
        try:
            pos = _MULTILINE_WS.match(text, pos).end()
            if pos >= len(text):
                break
            pos = _EXPORT.match(text, pos).end()
            key = None
            if text[pos:pos + 1] != "#":
                match = _need(_SINGLE_QUOTED_KEY if text[pos:pos + 1] == "'" else _UNQUOTED_KEY, text, pos)
                key, pos = match.group(1), match.end()
            pos = _WS.match(text, pos).end()
            has_value = text[pos:pos + 1] == "="
            if has_value:
                pos = _EQUAL_SIGN.match(text, pos).end()
                first = text[pos:pos + 1]
                if first == "'":
                    pos = _need(_SINGLE_QUOTED_VALUE, text, pos).end()
                elif first == '"':
                    pos = _need(_DOUBLE_QUOTED_VALUE, text, pos).end()
                elif first not in ("", "\n", "\r"):
                    pos = _UNQUOTED_VALUE.match(text, pos).end()
            pos = _COMMENT.match(text, pos).end()
            pos = _need(_END_OF_LINE, text, pos).end()
            if key is not None:
                last_has_value[key] = has_value
        except _Unparsable:
            pos = _REST_OF_LINE.match(text, pos).end()
        if pos <= start:
            pos = start + 1
    return [key for key, has_value in last_has_value.items() if has_value]


def _bindings(text: str) -> tuple:
    """Every binding of a ``.env`` text in file order, a rebound key each time it is bound:
    ``(key, raw value or None)``. python-dotenv's own ``parse_stream``, which the load
    resolves in this order and which logs nothing (``load_dotenv`` warns on a bad line
    once). Raises ImportError without python-dotenv."""
    from dotenv.parser import parse_stream

    return tuple((binding.key, binding.value) for binding in parse_stream(io.StringIO(text))
                 if binding.key is not None)


def _parse_and_warn(text: str) -> tuple:
    """The load's one parse of a file: ``_bindings``' answer, and python-dotenv's warning
    for every line its parser cannot read (the load used to get it from ``load_dotenv``)."""
    from dotenv.parser import parse_stream

    out = []
    for binding in parse_stream(io.StringIO(text)):
        if binding.error:
            logger.warning("python-dotenv could not parse statement starting at line %s",
                           binding.original.line)
        if binding.key is not None:
            out.append((binding.key, binding.value))
    return tuple(out)


def _set_keys(bindings) -> list[str]:
    """The keys the bindings leave set, in first-binding order (as python-dotenv's dict
    keeps them): a key's last binding decides, and one without ``=`` sets nothing."""
    last: dict = {}
    for key, value in bindings:
        last[key] = value
    return [key for key, value in last.items() if value is not None]


def text_keys(text: str) -> list[str]:
    """The keys a ``.env`` text sets, in python-dotenv's order, without their values:
    python-dotenv's own parse when it can be imported, else the stdlib port."""
    try:
        return _set_keys(_bindings(text))
    except ImportError:
        return _port_keys(text)


def is_file_or_fifo(path) -> bool:
    """What python-dotenv will read: a regular file, or a named pipe."""
    try:
        return os.path.isfile(path) or stat.S_ISFIFO(os.stat(path).st_mode)
    except (OSError, ValueError, TypeError):
        return False


def is_fifo(path) -> bool:
    try:
        return stat.S_ISFIFO(os.stat(path).st_mode)
    except (OSError, ValueError, TypeError):
        return False


def env_file_keys(path) -> list[str]:
    """The keys a ``.env`` file sets, as python-dotenv parses them, without their
    values. A named pipe is not read (reading one consumes it, or blocks with no
    writer); a file that cannot be read as UTF-8 sets nothing here."""
    parsed = _file_bindings(path)
    return [] if parsed is None else list(parsed[0])


@functools.lru_cache(maxsize=16)
def _parse_cached(path: str, mtime_ns: int, size: int, inode: int, ctime_ns: int):
    """One parse per file content: its keys (python-dotenv's, else the stdlib port's)
    and its raw bindings (``None`` without python-dotenv, which alone knows values)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        raw = _bindings(text)
    except ImportError:
        return tuple(_port_keys(text)), None
    return tuple(_set_keys(raw)), raw


def _file_bindings(path):
    """``(keys, raw bindings or None)`` for a regular file, parsed once while it is
    unchanged; ``None`` for anything else (a named pipe is never read here)."""
    if path is None or not os.path.isfile(path):
        return None
    try:
        info = os.stat(path)
        real = os.path.realpath(path)
    except (OSError, ValueError, TypeError):
        return None
    # A rewrite can keep the size and put the mtime back; the inode and the change time
    # still move, so the key holds them too.
    return _parse_cached(real, info.st_mtime_ns, info.st_size, info.st_ino, info.st_ctime_ns)


def _same_file(a, b) -> bool:
    try:
        return a is not None and b is not None and os.path.samefile(a, b)
    except (OSError, ValueError, TypeError):
        return False


def _resolve(source, *args):
    return source(*args) if callable(source) else source


def _shadow(table: dict[str, dict], layer: str, keys) -> None:
    for key in keys:
        row = table.get(key)
        if row is not None and row["layer"] != layer and layer not in row["shadowed"]:
            row["shadowed"].append(layer)


# python-dotenv's own ${VAR} / ${VAR:-default} syntax (dotenv/variables.py).
_POSIX_VARIABLE = re.compile(r"\$\{(?P<name>[^\}:]*)(?::-(?P<default>[^\}]*))?\}")


_UNSET = object()


def _expand(value: str, look, nothing: list[str]) -> str:
    """*value* with every ``${NAME}`` / ``${NAME:-default}`` replaced, as python-dotenv
    replaces them: ``look(name)`` is what defines the name (``_UNSET``: nothing does, so
    the default, else ""). *nothing* collects the names that came to nothing with no
    default to cover them: not defined, or defined blank."""
    def one(match: re.Match) -> str:
        name, default = match.group("name"), match.group("default")
        found = look(name)
        if found is _UNSET:
            found = default
            if default is None:
                nothing.append(name)
        elif default is None and not str(found if found is not None else "").strip():
            nothing.append(name)
        return found if found is not None else ""
    return _POSIX_VARIABLE.sub(one, value)


def _interpolate(value: str, env: Mapping[str, str]) -> str:
    """python-dotenv's own expansion of one value against one mapping (no second
    spelling): the reference ``_expand`` is checked against."""
    return _expand(value, lambda name: env.get(name, _UNSET), [])


class LayerValues(NamedTuple):
    """What one file's bindings come to against an environment (``layer_values``)."""

    values: dict[str, str]              # what the file adds, as spelled: a key already set is kept
    empty: dict[str, tuple[str, ...]]   # key -> the names it references that expanded to nothing


def _referenced(name: str, seen: Mapping[str, str | None], seen_set: Mapping[str, str],
                environ: Mapping[str, str]):
    """What ``${name}`` stands for: the environment first, then the file's earlier lines
    (python-dotenv's order when it does not override), a hub variable under either
    spelling in both (RB-2, the one pair rule). ``_UNSET`` when nothing defines it."""
    value = env_alias.lookup(environ, name)
    if value is not None:
        return value
    if env_alias.preferred_name(name) is None:
        return seen.get(name, _UNSET)            # a binding with no "=" is None: python-dotenv reads ""
    value = env_alias.lookup(seen_set, name)
    return _UNSET if value is None else value


def layer_values(raw, environ: Mapping[str, str]) -> LayerValues:
    """What a file's raw bindings add to *environ* — THE computation, for the load and
    for every prediction. A key already set is kept (``override=False``); a reference
    sees the environment before the file's earlier values, and a hub variable under
    either spelling. ``empty`` names, per key, the references that came to nothing: a name
    nothing defines and no ``:-default`` covers, or one that is defined blank."""
    seen: dict[str, str | None] = {}
    seen_set: dict[str, str] = {}
    out: dict[str, str] = {}
    empty: dict[str, tuple[str, ...]] = {}
    for key, value in raw:                       # every binding in file order, rebinds too
        nothing: list[str] = []
        resolved = None if value is None else _expand(
            value, lambda name: _referenced(name, seen, seen_set, environ), nothing)
        seen[key] = resolved
        if resolved is None:
            seen_set.pop(key, None)
        else:
            seen_set[key] = resolved
        if key in environ:
            continue
        if resolved is None:
            out.pop(key, None)                   # a last binding without "=" sets nothing
            empty.pop(key, None)
        else:
            out[key] = resolved
            empty[key] = tuple(dict.fromkeys(nothing))
    return LayerValues(out, {key: names for key, names in empty.items() if names})


def hub_values(raw, environ: Mapping[str, str]) -> dict[str, str]:
    """What the load adds to *environ* from a file's raw bindings (``layer_values``): a
    key already set is kept, and ``${VAR}`` sees the environment before the file's earlier
    values (python-dotenv's order when it does not override)."""
    return layer_values(raw, environ).values


def _built_from_nothing(values: LayerValues, folded: env_alias.Fold) -> dict[str, tuple[str, ...]]:
    """The hub variables this layer puts in effect that name a path, an endpoint, a
    credential or an allowlist and were built from a reference to nothing:
    ``{variable as spelled: the names referenced}``."""
    out = {}
    for name, used in folded.spelling.items():
        if name in FROM_PROCESS_ONLY:            # recorded, never in effect
            continue
        if values.empty.get(used) and env_alias.reference_sensitive(name):
            out[used] = values.empty[used]
    return out


def _in_effect(folded: env_alias.Fold) -> dict[str, str]:
    """What a layer puts in effect, each hub variable under the name the file spelled it
    (so a refusal names the line the operator wrote)."""
    return {folded.spelling.get(key, key): value for key, value in folded.values.items()
            if key not in FROM_PROCESS_ONLY}


def _nothing_message(found: Mapping[str, tuple[str, ...]], where: str) -> str:
    lines = "; ".join(f"{key} references {', '.join('${' + name + '}' for name in names)}"
                      for key, names in sorted(found.items()))
    return (f"Refusing to start: in {where}, {lines} — and nothing sets "
            f"{'it' if sum(map(len, found.values())) == 1 else 'them'}.\n"
            "A reference to a variable that is not set expands to nothing, so a directory becomes "
            "\"/\", an address or a credential becomes empty, an allowlist loses its entry. Set the "
            "variable it names (NERVA_<X> and JARVIS_<X> are one variable), give the reference a "
            "default (${NAME:-value}), or write the value out.")


def after_repo_layer(repo_env, environ: Mapping[str, str]) -> dict[str, str]:
    """The environment the hub has once the repo .env is loaded, without loading it:
    *environ* plus what the file adds. Just *environ* when python-dotenv is switched off
    or missing (only it knows values), or the file cannot be read."""
    merged = env_alias.normalized(environ)
    if dotenv_disabled(merged):
        return merged
    parsed = _file_bindings(repo_env)
    if parsed is None or parsed[1] is None:
        return merged
    folded = _layer_fold(parsed[1], merged)
    merged.update({key: value for key, value in folded.values.items()
                   if key not in FROM_PROCESS_ONLY})
    env_alias._record(merged, {key: used for key, used in folded.spelling.items()
                               if key not in FROM_PROCESS_ONLY})
    return merged


def _layer_fold(raw, environ: Mapping[str, str]) -> env_alias.Fold:
    """What a file's raw bindings add to a canonical *environ*, both spellings of a hub
    variable folded into one (RB-2): ``layer_values``, then ``env_alias.fold``."""
    return env_alias.fold(layer_values(raw, environ).values, environ)


def derive(repo_env, home_env, environ: Mapping[str, str]) -> dict[str, dict]:
    """The table for an environment, without loading anything (scripts/doctor.py).

    ``home_env`` may be a callable: it gets the environment the hub would have after
    the repo layer (``after_repo_layer``), so a data home the repo .env names, or
    builds from ``${VAR}``, is followed as the hub follows it. python-dotenv checks its
    switch on every load, so a repo .env that sets ``PYTHON_DOTENV_DISABLED`` stops the
    data-home layer here too. A named pipe is not read. Both spellings of a hub variable
    are one row, under its ``JARVIS_`` name (RB-2); ``derive_alias`` names the spelling
    behind each and the pairs the hub's load would refuse."""
    merged = env_alias.normalized(environ)
    table = {key: {"layer": PROCESS, "shadowed": []} for key in merged if key != env_alias.MARKER}
    for layer, source in ((REPO_ENV, repo_env), (USER_ENV, home_env)):
        if dotenv_disabled(merged):
            break
        path = _resolve(source, merged) if layer == USER_ENV else source
        if path is None or (layer == USER_ENV and _same_file(path, repo_env)):
            continue
        keys = list(dict.fromkeys(env_alias.canonical(key) for key in env_file_keys(path)))
        for key in keys:
            if key not in table:
                table[key] = {"layer": layer, "shadowed": []}
        _shadow(table, layer, keys)
        if layer == REPO_ENV:
            merged = after_repo_layer(path, merged)
    return table


def derive_alias(repo_env, home_env, environ: Mapping[str, str]) -> tuple[dict, dict, dict]:
    """RB-2, without loading anything (the doctor): ``(spellings, conflicts, unsafe)``.

    ``spellings`` maps a hub variable (its ``JARVIS_`` name) to the spelling that supplies
    the value the hub would have — a variable missing from it was not set by any layer.
    ``conflicts`` maps a layer to the hub variables it sets under both spellings with
    different values, which the hub's load refuses to start on; ``{}`` when there is
    none. ``unsafe`` maps a layer to the variables the load refuses for the other reason:
    a path, endpoint, credential or allowlist built from a ``${...}`` reference to
    nothing, or a path-typed variable left at the filesystem root. Names only. Follows
    the files as ``derive`` does; without python-dotenv (only it knows values) a file
    that names both spellings counts as the preferred one."""
    conflicts: dict[str, list[str]] = {}
    unsafe: dict[str, list[str]] = {}
    found = env_alias.conflicts(environ)
    if found:
        conflicts[PROCESS] = found
    rooted = env_alias.unsafe_paths(environ)
    if rooted:
        unsafe[PROCESS] = rooted
    merged = env_alias.normalized(environ)
    preferred = env_alias.preferred_supplied(merged)
    spellings = {key: (env_alias.preferred_name(key) if key in preferred else key)
                 for key in merged if env_alias.preferred_name(key)}
    for layer, source in ((REPO_ENV, repo_env), (USER_ENV, home_env)):
        if dotenv_disabled(merged):
            break
        path = _resolve(source, merged) if layer == USER_ENV else source
        if path is None or (layer == USER_ENV and _same_file(path, repo_env)):
            continue
        parsed = _file_bindings(path)
        if parsed is not None and parsed[1] is not None:
            values = layer_values(parsed[1], merged)
            folded = env_alias.fold(values.values, merged)
            if folded.refused:
                conflicts[layer] = sorted(folded.refused)
            bad = set(_built_from_nothing(values, folded)) | set(env_alias.unsafe_paths(_in_effect(folded)))
            if bad:
                unsafe[layer] = sorted(bad)
            for key, used in folded.spelling.items():
                spellings.setdefault(key, used)
        elif parsed is not None:
            for key in sorted(parsed[0], key=lambda name: not name.startswith(env_alias.PREFERRED_PREFIX)):
                if env_alias.preferred_name(key):
                    spellings.setdefault(env_alias.canonical(key), key)
        if layer == REPO_ENV:
            merged = after_repo_layer(path, merged)
    return spellings, conflicts, unsafe


def raw_values(path) -> dict[str, str | None]:
    """A file's bindings as written (no ``${VAR}`` expansion; ``None`` for a key with no
    ``=``), for the doctor's checks on names; {} without python-dotenv or for anything
    but a readable regular file."""
    parsed = _file_bindings(path)
    return {} if parsed is None or parsed[1] is None else dict(parsed[1])


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def load_layered_env(repo_env, home_env) -> dict[str, dict]:
    """Load the repo .env, then the data-home .env, into ``os.environ`` (a key already
    set is kept), and record where every key came from. Returns the table.

    ``home_env`` may be a callable, called after the repo layer is loaded. A key a
    previous load in this process put in the environment keeps that attribution while
    the environment still holds the value that load set (anything else set it since);
    what the files shadow is worked out afresh from the files as they are now. The
    bindings are python-dotenv's (its parser, once per file, a bad line warned about
    once); the values are ``layer_values``' (RB-2: a reference is resolved under either
    spelling). python-dotenv's switch is checked before every file, so a repo .env that
    sets ``PYTHON_DOTENV_DISABLED`` stops the next layer."""
    # RB-2 — the process layer first: a NERVA_<X> still spelled that way (set since the
    # package was imported) is folded onto JARVIS_<X>; a variable set twice, differently,
    # or a path left at the filesystem root stops the load before any file is read.
    env_alias.normalize_process_env()
    env_alias.refuse_conflicts()
    env_alias.refuse_unsafe_paths()
    table: dict[str, dict] = {}
    loaded: dict[str, tuple[str, str]] = {}
    not_set: set[str] = set()
    for key, value in os.environ.items():
        if key == env_alias.MARKER:
            continue
        prior = _LOADED.get(key)
        if prior is not None and prior[1] == _digest(value):
            table[key] = {"layer": prior[0], "shadowed": []}
            loaded[key] = prior
        else:
            table[key] = {"layer": PROCESS, "shadowed": []}
    files: dict[str, dict] = {}
    repo_path = None
    for layer, source in ((REPO_ENV, repo_env), (USER_ENV, home_env)):
        path = _resolve(source)
        if layer == REPO_ENV:
            repo_path = path
        present = path is not None and is_file_or_fifo(path)
        info = {"path": str(path) if path is not None else None,
                "kind": ("fifo" if is_fifo(path) else "file") if present else "absent",
                "present": present, "read": False}
        files[layer] = info
        if not present:
            continue
        if layer == USER_ENV and _same_file(path, repo_path):
            info["kind"] = "same file as the repo .env"
            continue
        if dotenv_disabled(os.environ):
            info["kind"] = "disabled"
            continue
        with open(path, encoding="utf-8") as stream:   # once: a pipe cannot be read twice
            text = stream.read()
        info["read"] = True
        before = dict(os.environ)
        raw = _parse_and_warn(text)             # parsed once; a bad line is warned about here
        values = layer_values(raw, before)
        added = dict(values.values)
        added.pop(env_alias.MARKER, None)       # the hub's own note of spellings: no file writes it
        # RB-2 — both spellings of a hub variable are one key of this layer. A file that
        # sets them differently is refused here, by name, before any of it is in effect;
        # so is a path, endpoint, credential or allowlist built from a reference to
        # nothing, and a path-typed variable left at the filesystem root.
        where = f"the {LABELS[layer]}"
        folded = env_alias.fold(added, before)
        if folded.refused:
            raise env_alias.ConfigurationRefused(env_alias.conflict_message(sorted(folded.refused), where))
        nothing = _built_from_nothing(values, folded)
        if nothing:
            raise env_alias.ConfigurationRefused(_nothing_message(nothing, where))
        env_alias.refuse_unsafe_paths(_in_effect(folded), where=where)
        for key, value in folded.values.items():
            if key in FROM_PROCESS_ONLY:
                os.environ.pop(key, None)       # recorded, never in effect (see FROM_PROCESS_ONLY)
                not_set.add(key)
                table.setdefault(key, {"layer": layer, "shadowed": []})
                continue
            os.environ[key] = value
            table[key] = {"layer": layer, "shadowed": []}
            loaded[key] = (layer, _digest(value))
        env_alias._record(os.environ, {key: used for key, used in folded.spelling.items()
                                       if key not in FROM_PROCESS_ONLY})
        # a hub variable shadows under its JARVIS_ name
        _shadow(table, layer, [env_alias.canonical(key) for key in _set_keys(raw)])
    _TABLE.clear()
    _TABLE.update({key: {"layer": row["layer"], "shadowed": list(row["shadowed"])} for key, row in table.items()})
    _FILES.clear()
    _FILES.update(files)
    _LOADED.clear()
    _LOADED.update(loaded)
    _NOT_SET.clear()
    _NOT_SET.update(not_set)
    return {key: {"layer": row["layer"], "shadowed": list(row["shadowed"])} for key, row in _TABLE.items()}


#: The hub's own .env files: the repo's (a development checkout) and the data home's,
#: named when the load reaches it.
REPO_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_HUB_LOADED: dict[str, dict] | None = None


def _hub_home_env():
    from .paths import ensure_user_home

    home = ensure_user_home()         # a first-run home is scaffolded before its .env is read
    return home / ".env" if home is not None else None


#: H689b — why a profile's load leaves the shared files out (``files()`` reports it).
PROFILE_NOT_READ = "not read by a profile: it reads only its own .env"


def profile_env_file(environ: Mapping[str, str] | None = None) -> Path | None:
    """H689b — the one ``.env`` a profile's hub reads, ``<profile root>/.env``; None for the
    default hub (no profile, blank or ``default``). A refused profile name raises, as
    ``data_root`` does: its hub never falls back to the shared files."""
    from .paths import data_root, profile_error, profile_name

    refused = profile_error(environ)
    if refused:
        raise RuntimeError(refused)
    if not profile_name(environ):
        return None
    return data_root(environ) / ".env"


def load_hub_env() -> dict[str, dict]:
    """The hub's own load of its .env files, before anything else it starts reads.

    serve.py calls it before it builds the server and runs its guards, the lifespan
    before its boot guards, the coordinator (``scripts/coordinator.py``, the systemd
    ``jarvis-runtime`` unit) before it builds its Orchestrator, the reality-evidence
    harness before its own, and ``PluginManager.build`` for any other entry.
    ``scripts/install_smoke.py`` does not load before it builds its isolated hub (a temp
    data root, built on purpose from the process environment); its PluginManager.build
    loads afterwards, as for any entry (review-H273f n3). The first
    call in a process loads and the others return its table: a named pipe is read once.
    Log redaction is imported first, so its switch stays the boot environment's."""
    global _HUB_LOADED
    if _HUB_LOADED is None:
        from .security import log_redaction  # noqa: F401  (snapshots JARVIS_LOG_REDACTION)

        # H689b — a profile's hub reads its own root's .env and neither shared file: its
        # credentials (provider keys, bot tokens, the admin token) are the profile's.
        profile_env = profile_env_file()
        if profile_env is None:
            _HUB_LOADED = load_layered_env(REPO_ENV_FILE, _hub_home_env)
        else:
            _HUB_LOADED = load_layered_env(None, profile_env)
            _FILES[REPO_ENV] = {"path": None, "kind": PROFILE_NOT_READ, "present": False, "read": False}
    return _HUB_LOADED


def hub_value(key: str, environ: Mapping[str, str] | None = None) -> str | None:
    """The value *key* has in the hub once its .env files are loaded, without loading
    them: the process environment, then the repo .env, then the data-home .env that the
    first two name (``JARVIS_USER_HOME``); for a profile, the process environment, then
    the profile's own .env (H689b). For a process that must not load, such as
    ``scripts/runtime_supervisor.py``, whose child would then read every file key as
    the process environment's (review-H273f m3). None when no layer sets it."""
    key = env_alias.canonical(key)                                   # RB-2: either spelling
    env = env_alias.normalized(os.environ if environ is None else environ)
    if key in env:
        return env[key]
    try:
        profile_env = profile_env_file(env)
    except RuntimeError:                   # a refused profile name: its hub does not start
        return None
    if profile_env is not None:            # H689b — a profile's own .env, nothing shared
        if dotenv_disabled(env) or key in FROM_PROCESS_ONLY:
            return None
        parsed = _file_bindings(profile_env)
        if parsed is None or parsed[1] is None:
            return None
        return _layer_fold(parsed[1], env).values.get(key)
    merged = after_repo_layer(REPO_ENV_FILE, env)
    if key in merged:
        return merged[key]
    home = (merged.get("JARVIS_USER_HOME") or "").strip()
    if not home or dotenv_disabled(merged) or key in FROM_PROCESS_ONLY:
        return None
    path = Path(home).expanduser() / ".env"
    if _same_file(path, REPO_ENV_FILE):
        return None
    parsed = _file_bindings(path)
    if parsed is None or parsed[1] is None:
        return None
    return _layer_fold(parsed[1], merged).values.get(key)


def spelling(key: str, environ: Mapping[str, str] | None = None) -> dict:
    """RB-2 — for a hub variable, which spelling supplied the value in effect:
    ``{"spelling", "preferred", "deprecated"}`` (names and a flag, never a value);
    ``{}`` for a name with one spelling."""
    return env_alias.spelling_info(key, environ)


def note_for(key: str, layer: str) -> str:
    """Why a row's layer is not the whole story, or ""."""
    if layer not in (REPO_ENV, USER_ENV):
        return ""
    if key in FROM_PROCESS_ONLY:
        return PROCESS_ONLY_NOTE
    return BEFORE_LOAD_NOTE if key in READ_BEFORE_LOAD else SPLIT_NOTES.get(
        key, OPTIONAL_SPLIT_NOTES.get(key, ""))


def files() -> dict[str, dict]:
    """The files the last load read, per layer ({} when nothing was loaded)."""
    return {layer: dict(info) for layer, info in _FILES.items()}


def provenance(environ: Mapping[str, str] | None = None) -> dict[str, dict]:
    """The recorded layer of every key now in the environment. A key that appeared
    after the load (or with no load at all, as in tests) is ``runtime``."""
    environ = os.environ if environ is None else environ
    out = {}
    for key in environ:
        if key == env_alias.MARKER:        # RB-2: the hub's own note of spellings, not configuration
            continue
        row = None if key in _NOT_SET else _TABLE.get(key)
        out[key] = ({"layer": row["layer"], "shadowed": list(row["shadowed"])} if row is not None
                    else {"layer": RUNTIME, "shadowed": []})
    for key in _NOT_SET - set(out):         # a file named it; the load kept it out
        row = _TABLE[key]
        out[key] = {"layer": row["layer"], "shadowed": list(row["shadowed"])}
    return out


__all__ = [
    "FROM_PROCESS_ONLY", "HUB_PREFIXES", "LABELS", "SECRET_HINTS", "PROCESS_ONLY_NOTE", "PROCESS", "READ_AGAIN_AFTER_LOAD", "READ_BEFORE_LOAD", "REPO_ENV",
    "REPO_ENV_FILE", "RUNTIME", "SPLIT_NOTES", "OPTIONAL_SPLIT_NOTES", "USER_ENV", "after_repo_layer", "derive", "derive_alias", "dotenv_disabled",
    "env_file_keys", "files", "hub_credential", "hub_values", "is_fifo", "is_file_or_fifo", "layer_values", "load_hub_env",
    "load_layered_env", "masked", "note_for", "profile_env_file", "provenance", "raw_values", "spelling", "text_keys",
]

