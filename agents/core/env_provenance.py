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
included (python-dotenv reads FIFOs, which is how 1Password mounts a ``.env``), and
the same parse sets the variables and names the keys. The data home can be given as
a callable, resolved after the repo layer is loaded, so a ``JARVIS_USER_HOME`` set
in the repo ``.env`` names it, as it did before.

Key names come from python-dotenv itself whenever it can be imported. The stdlib
port below (python-dotenv 1.2.3's grammar) is the fallback that lets
``scripts/doctor.py`` derive the same table in a broken install (``derive``).

The settings plane is separate: ``settings_db`` reports each stored value as the
declared ``default`` or ``set``.
"""
from __future__ import annotations

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

# serve.py reads these to build the server before any .env file is loaded, so a
# .env value for them is recorded but never in effect.
READ_BEFORE_LOAD = frozenset({"JARVIS_HOST", "JARVIS_PORT", "JARVIS_LOG_LEVEL", "JARVIS_SHUTDOWN_TIMEOUT"})
BEFORE_LOAD_NOTE = "serve.py reads it before the .env files are loaded: the .env value is not in effect"

_TABLE: dict[str, dict] = {}
_FILES: dict[str, dict] = {}   # what the last load read, per layer: {"path", "kind"}

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


def text_keys(text: str) -> list[str]:
    """The keys a ``.env`` text sets, in python-dotenv's order, without their values:
    python-dotenv's own parse when it can be imported, else the stdlib port."""
    try:
        from dotenv import dotenv_values
    except Exception:
        return _port_keys(text)
    return [key for key, value in dotenv_values(stream=io.StringIO(text), interpolate=False).items()
            if value is not None]


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
    if path is None or not os.path.isfile(path):
        return []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return text_keys(text)




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


def derive(repo_env, home_env, environ: Mapping[str, str]) -> dict[str, dict]:
    """The table for an environment, without loading anything (scripts/doctor.py).

    ``home_env`` may be a callable: it gets the environment the hub would have after
    the repo layer (``environ`` plus the repo .env's values, first wins, from
    python-dotenv when it can be imported), so a data home named in the repo .env is
    followed as the hub follows it. A named pipe is not read."""
    table = {key: {"layer": PROCESS, "shadowed": []} for key in environ}
    if dotenv_disabled(environ):
        return table
    merged = dict(environ)
    for layer, source in ((REPO_ENV, repo_env), (USER_ENV, home_env)):
        path = _resolve(source, merged) if layer == USER_ENV else source
        if path is None or (layer == USER_ENV and _same_file(path, repo_env)):
            continue
        keys = env_file_keys(path)
        for key in keys:
            if key not in table:
                table[key] = {"layer": layer, "shadowed": []}
        _shadow(table, layer, keys)
        if layer == REPO_ENV:
            merged.update({key: value for key, value in file_values(path).items() if key not in merged})
    return table


def file_values(path) -> dict[str, str]:
    """The values a .env file sets, for resolving the data home only; {} without
    python-dotenv or for anything but a readable regular file."""
    if path is None or not os.path.isfile(path):
        return {}
    try:
        from dotenv import dotenv_values

        text = Path(path).read_text(encoding="utf-8")
    except Exception:
        return {}
    return {key: value for key, value in dotenv_values(stream=io.StringIO(text)).items() if value is not None}


def load_layered_env(repo_env, home_env) -> dict[str, dict]:
    """Load the repo .env, then the data-home .env, into ``os.environ`` (a key already
    set is kept), and record where every key came from. Returns the table.

    ``home_env`` may be a callable, called after the repo layer is loaded. A key a
    previous load in this process attributed to a file keeps that attribution: it is
    in the environment now only because that load put it there."""
    from dotenv.main import DotEnv

    previous = {key: row for key, row in _TABLE.items() if row["layer"] in (REPO_ENV, USER_ENV)}
    table = {key: ({"layer": previous[key]["layer"], "shadowed": list(previous[key]["shadowed"])}
                   if key in previous else {"layer": PROCESS, "shadowed": []})
             for key in os.environ}
    files: dict[str, dict] = {}
    disabled = dotenv_disabled(os.environ)
    repo_path = None
    for layer, source in ((REPO_ENV, repo_env), (USER_ENV, home_env)):
        path = _resolve(source)
        if layer == REPO_ENV:
            repo_path = path
        kind = ("fifo" if is_fifo(path) else "file") if path is not None and is_file_or_fifo(path) else "absent"
        files[layer] = {"path": str(path) if path is not None else None, "kind": kind}
        if kind == "absent" or disabled:
            continue
        if layer == USER_ENV and _same_file(path, repo_path):
            files[layer]["kind"] = "same file as the repo .env"
            continue
        with open(path, encoding="utf-8") as stream:   # once: a pipe cannot be read twice
            text = stream.read()
        dotenv = DotEnv(None, stream=io.StringIO(text), interpolate=True, override=False)
        before = set(os.environ)
        dotenv.set_as_environment_variables()   # load_dotenv's own step: a key already set is kept
        for key in set(os.environ) - before:
            table[key] = {"layer": layer, "shadowed": []}
        _shadow(table, layer, [key for key, value in dotenv.dict().items() if value is not None])
    _TABLE.clear()
    _TABLE.update({key: {"layer": row["layer"], "shadowed": list(row["shadowed"])} for key, row in table.items()})
    _FILES.clear()
    _FILES.update(files)
    return {key: {"layer": row["layer"], "shadowed": list(row["shadowed"])} for key, row in _TABLE.items()}


def note_for(key: str, layer: str) -> str:
    """Why a row's layer is not the whole story, or ""."""
    return BEFORE_LOAD_NOTE if key in READ_BEFORE_LOAD and layer in (REPO_ENV, USER_ENV) else ""


def files() -> dict[str, dict]:
    """The files the last load read, per layer ({} when nothing was loaded)."""
    return {layer: dict(info) for layer, info in _FILES.items()}


def provenance(environ: Mapping[str, str] | None = None) -> dict[str, dict]:
    """The recorded layer of every key now in the environment. A key that appeared
    after the load (or with no load at all, as in tests) is ``runtime``."""
    environ = os.environ if environ is None else environ
    out = {}
    for key in environ:
        row = _TABLE.get(key)
        out[key] = ({"layer": row["layer"], "shadowed": list(row["shadowed"])} if row is not None
                    else {"layer": RUNTIME, "shadowed": []})
    return out


__all__ = [
    "LABELS", "PROCESS", "READ_BEFORE_LOAD", "REPO_ENV", "RUNTIME", "USER_ENV",
    "derive", "dotenv_disabled", "env_file_keys", "files", "is_fifo", "is_file_or_fifo",
    "load_layered_env", "note_for", "provenance", "text_keys",
]

