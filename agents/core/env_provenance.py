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
names and layer labels only, never a value.

The settings plane is separate: ``settings_db`` reports each stored value as the
declared ``default`` or ``set``.

Apart from the lazy python-dotenv import in ``load_layered_env``, this module is
stdlib-only, so ``scripts/doctor.py`` can derive the same table offline in a broken
install (``derive``).
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

PROCESS, REPO_ENV, USER_ENV, RUNTIME = "process", "repo_env", "user_env", "runtime"
LABELS = {
    PROCESS: "process environment",
    REPO_ENV: "repo .env",
    USER_ENV: "data-home .env",
    RUNTIME: "set while running",
}

_TABLE: dict[str, dict] = {}

# python-dotenv's grammar (dotenv/parser.py), ported for key names only. A binding is
# optional whitespace and ``export``, a single-quoted or unquoted key, ``=`` and a
# value (quoted values may span lines), then an optional comment and the end of the
# line. Anything else on the line makes the whole binding an error, which dotenv
# skips to the end of that line; a key with no ``=`` is parsed but never set.
_MULTILINE_WS = re.compile(r"\s*")
_WS = re.compile(r"[^\S\r\n]*")
_EXPORT = re.compile(r"(?:export[^\S\r\n]+)?")
_SINGLE_QUOTED_KEY = re.compile(r"'([^']+)'")
_UNQUOTED_KEY = re.compile(r"([^=\#\s]+)")
_EQUAL_SIGN = re.compile(r"(=[^\S\r\n]*)")
_SINGLE_QUOTED_VALUE = re.compile(r"'((?:\\'|[^'])*)'")
_DOUBLE_QUOTED_VALUE = re.compile(r'"((?:\\"|[^"])*)"')
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


def env_file_keys(path) -> list[str]:
    """The keys a ``.env`` file sets, in file order, as python-dotenv parses them,
    without their values. Nothing inside a quoted value is read as a key."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, TypeError):
        return []
    keys: list[str] = []
    pos = 0
    while pos < len(text):
        pos = _MULTILINE_WS.match(text, pos).end()
        if pos >= len(text):
            break
        start = pos
        try:
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
            if key is not None and has_value and key not in keys:
                keys.append(key)
        except _Unparsable:
            pos = _REST_OF_LINE.match(text, pos).end()
        if pos <= start:
            pos = start + 1
    return keys


def _layered(files: list[tuple[str, object]], present: set[str]) -> dict[str, dict]:
    table = {key: {"layer": PROCESS, "shadowed": []} for key in present}
    for layer, path in files:
        for key in env_file_keys(path) if path is not None else []:
            if key in table:
                if layer not in table[key]["shadowed"] and table[key]["layer"] != layer:
                    table[key]["shadowed"].append(layer)
            else:
                table[key] = {"layer": layer, "shadowed": []}
    return table


def derive(repo_env, home_env, environ: Mapping[str, str]) -> dict[str, dict]:
    """The table for an environment, without loading anything (scripts/doctor.py)."""
    return _layered([(REPO_ENV, repo_env), (USER_ENV, home_env)], set(environ))


def load_layered_env(repo_env, home_env) -> dict[str, dict]:
    """Load the repo .env, then the data-home .env, into ``os.environ`` (a key already
    set is kept), and record where every key came from. Returns the table."""
    from dotenv import load_dotenv

    table = {key: {"layer": PROCESS, "shadowed": []} for key in os.environ}
    for layer, path in ((REPO_ENV, repo_env), (USER_ENV, home_env)):
        if path is None or not Path(path).is_file():
            continue
        before = set(os.environ)
        load_dotenv(path)  # override=False: the first layer to define a key wins
        for key in set(os.environ) - before:
            table[key] = {"layer": layer, "shadowed": []}
        for key in env_file_keys(path):
            row = table.get(key)
            if row is not None and row["layer"] != layer and layer not in row["shadowed"]:
                row["shadowed"].append(layer)
    _TABLE.clear()
    _TABLE.update({key: {"layer": row["layer"], "shadowed": list(row["shadowed"])} for key, row in table.items()})
    return {key: {"layer": row["layer"], "shadowed": list(row["shadowed"])} for key, row in _TABLE.items()}


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
