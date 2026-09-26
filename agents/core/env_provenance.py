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
"""
from __future__ import annotations

import functools
import hashlib
import io
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path

from .env_config import dotenv_disabled  # python-dotenv's own switch and spellings

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


def _interpolate(value: str, env: Mapping[str, str]) -> str:
    def one(match: re.Match) -> str:
        default = match.group("default")
        result = env.get(match.group("name"), default if default is not None else "")
        return result if result is not None else ""
    return _POSIX_VARIABLE.sub(one, value)


def hub_values(raw, environ: Mapping[str, str]) -> dict[str, str]:
    """What ``load_dotenv(override=False)`` adds to *environ* from a file's raw
    bindings: a key already set is kept, and ``${VAR}`` sees the environment before the
    file's earlier values (python-dotenv's order when it does not override)."""
    seen: dict[str, str | None] = {}
    out: dict[str, str] = {}
    for key, value in raw:                       # every binding in file order, rebinds too
        resolved = None if value is None else _interpolate(value, {**seen, **environ})
        seen[key] = resolved
        if key in environ:
            continue
        if resolved is None:
            out.pop(key, None)                   # a last binding without "=" sets nothing
        else:
            out[key] = resolved
    return out


def after_repo_layer(repo_env, environ: Mapping[str, str]) -> dict[str, str]:
    """The environment the hub has once the repo .env is loaded, without loading it:
    *environ* plus what the file adds. Just *environ* when python-dotenv is switched off
    or missing (only it knows values), or the file cannot be read."""
    merged = dict(environ)
    if dotenv_disabled(merged):
        return merged
    parsed = _file_bindings(repo_env)
    if parsed is None or parsed[1] is None:
        return merged
    merged.update({key: value for key, value in hub_values(parsed[1], merged).items()
                   if key not in FROM_PROCESS_ONLY})
    return merged


def derive(repo_env, home_env, environ: Mapping[str, str]) -> dict[str, dict]:
    """The table for an environment, without loading anything (scripts/doctor.py).

    ``home_env`` may be a callable: it gets the environment the hub would have after
    the repo layer (``after_repo_layer``), so a data home the repo .env names, or
    builds from ``${VAR}``, is followed as the hub follows it. python-dotenv checks its
    switch on every load, so a repo .env that sets ``PYTHON_DOTENV_DISABLED`` stops the
    data-home layer here too. A named pipe is not read."""
    table = {key: {"layer": PROCESS, "shadowed": []} for key in environ}
    merged = dict(environ)
    for layer, source in ((REPO_ENV, repo_env), (USER_ENV, home_env)):
        if dotenv_disabled(merged):
            break
        path = _resolve(source, merged) if layer == USER_ENV else source
        if path is None or (layer == USER_ENV and _same_file(path, repo_env)):
            continue
        keys = env_file_keys(path)
        for key in keys:
            if key not in table:
                table[key] = {"layer": layer, "shadowed": []}
        _shadow(table, layer, keys)
        if layer == REPO_ENV:
            merged = after_repo_layer(path, merged)
    return table


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
    what the files shadow is worked out afresh from the files as they are now. The load
    itself is python-dotenv's public ``load_dotenv``, which checks its switch on every
    call, so a repo .env that sets ``PYTHON_DOTENV_DISABLED`` stops the next layer."""
    from dotenv import load_dotenv

    table: dict[str, dict] = {}
    loaded: dict[str, tuple[str, str]] = {}
    not_set: set[str] = set()
    for key, value in os.environ.items():
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
        before = set(os.environ)
        load_dotenv(stream=io.StringIO(text), override=False, interpolate=True)
        now = dict(os.environ)
        for key in now.keys() - before:
            if key in FROM_PROCESS_ONLY:
                os.environ.pop(key, None)       # recorded, never in effect (see FROM_PROCESS_ONLY)
                not_set.add(key)
                table.setdefault(key, {"layer": layer, "shadowed": []})
                continue
            table[key] = {"layer": layer, "shadowed": []}
            loaded[key] = (layer, _digest(now[key]))
        _shadow(table, layer, _set_keys(_bindings(text)))    # parsed without a second warning
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

        _HUB_LOADED = load_layered_env(REPO_ENV_FILE, _hub_home_env)
    return _HUB_LOADED


def hub_value(key: str, environ: Mapping[str, str] | None = None) -> str | None:
    """The value *key* has in the hub once its .env files are loaded, without loading
    them: the process environment, then the repo .env, then the data-home .env that the
    first two name (``JARVIS_USER_HOME``). For a process that must not load, such as
    ``scripts/runtime_supervisor.py``, whose child would then read every file key as
    the process environment's (review-H273f m3). None when no layer sets it."""
    env = dict(os.environ if environ is None else environ)
    if key in env:
        return env[key]
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
    return hub_values(parsed[1], merged).get(key)


def note_for(key: str, layer: str) -> str:
    """Why a row's layer is not the whole story, or ""."""
    if layer not in (REPO_ENV, USER_ENV):
        return ""
    if key in FROM_PROCESS_ONLY:
        return PROCESS_ONLY_NOTE
    return BEFORE_LOAD_NOTE if key in READ_BEFORE_LOAD else SPLIT_NOTES.get(key, "")


def files() -> dict[str, dict]:
    """The files the last load read, per layer ({} when nothing was loaded)."""
    return {layer: dict(info) for layer, info in _FILES.items()}


def provenance(environ: Mapping[str, str] | None = None) -> dict[str, dict]:
    """The recorded layer of every key now in the environment. A key that appeared
    after the load (or with no load at all, as in tests) is ``runtime``."""
    environ = os.environ if environ is None else environ
    out = {}
    for key in environ:
        row = None if key in _NOT_SET else _TABLE.get(key)
        out[key] = ({"layer": row["layer"], "shadowed": list(row["shadowed"])} if row is not None
                    else {"layer": RUNTIME, "shadowed": []})
    for key in _NOT_SET - set(out):         # a file named it; the load kept it out
        row = _TABLE[key]
        out[key] = {"layer": row["layer"], "shadowed": list(row["shadowed"])}
    return out


__all__ = [
    "FROM_PROCESS_ONLY", "LABELS", "PROCESS_ONLY_NOTE", "PROCESS", "READ_AGAIN_AFTER_LOAD", "READ_BEFORE_LOAD", "REPO_ENV",
    "REPO_ENV_FILE", "RUNTIME", "SPLIT_NOTES", "USER_ENV", "after_repo_layer", "derive", "dotenv_disabled",
    "env_file_keys", "files", "hub_values", "is_fifo", "is_file_or_fifo", "load_hub_env", "load_layered_env",
    "note_for", "provenance", "raw_values", "text_keys",
]

