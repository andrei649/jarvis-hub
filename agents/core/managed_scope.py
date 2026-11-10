"""G1 (H249 / H267 / H629) — operator-pinned ("managed") configuration.

An administrator pins individual settings and environment values in files the owner's
writers cannot change. The managed layer is applied LAST: it beats the settings store,
the selected product posture, the process environment and every ``.env`` file, leaf by
leaf, so the rest of the configuration stays the owner's.

Where it lives (the same shape as Hermes's ``/etc/hermes``)::

    $NERVA_MANAGED_DIR   (or JARVIS_MANAGED_DIR; the process environment only — a .env
                          file cannot set it, env_provenance.FROM_PROCESS_ONLY)
    else /etc/nerva       (POSIX) or %PROGRAMDATA%\\Nerva (Windows), when it exists

    <dir>/config.yaml     settings pins: {category: {key: value}}; a mapping below a
                          json setting's key pins only those leaves
    <dir>/.env            environment pins: KEY=VALUE (either spelling of a hub
                          variable), taken literally, never interpolated
    <dir>/.managed        optional managed-mode marker: every configuration write is
                          refused; its first non-comment line names how to change the
                          configuration instead (e.g. "sudo nixos-rebuild switch")
    NERVA_MANAGED=<name>  managed mode without a directory (Hermes's HERMES_MANAGED): set by
                          the package or service that installs Nerva, e.g. "nix"
    <dir>/profiles/<name>/{config.yaml,.env,.managed}
                          pins for one profile (JARVIS_PROFILE=<name>), applied on top
                          of the shared ones

A ``${NAME}`` or ``${env:NAME}`` reference inside a pinned setting value is expanded
against the process environment and the managed ``.env`` only, never against a value a
``.env`` file supplied, so a reference the owner controls cannot shadow a pinned literal.

Fail closed: a managed file that exists but cannot be read or parsed (and a managed
directory named by ``NERVA_MANAGED_DIR`` that does not exist) makes every configuration
writer refuse, naming the file, instead of silently unpinning. The hub refuses to start
on one (``env_provenance.load_hub_env``). Readers keep the last version of a file that
parsed in this process.

Under pytest the system location is ignored (a real ``/etc/nerva`` on a developer box must
not leak policy into the suite); an explicit ``NERVA_MANAGED_DIR`` still applies.
"""
from __future__ import annotations

import copy
import io
import json
import logging
import os
import re
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("nerva.managed")

#: The variable that names the managed directory (``NERVA_MANAGED_DIR`` preferred).
DIR_ENV = "JARVIS_MANAGED_DIR"
#: Managed mode without a directory (Hermes's ``HERMES_MANAGED``; ``NERVA_MANAGED`` preferred).
MANAGED_ENV = "JARVIS_MANAGED"
CONFIG_FILE, ENV_FILE, MARKER_FILE, PROFILES_DIR = "config.yaml", ".env", ".managed", "profiles"
POSIX_DEFAULT = Path("/etc/nerva")
ADMINISTRATOR = "managed by your administrator"
DEFAULT_INSTRUCTION = "ask your administrator to change it"

_MISSING = object()
#: Any value: the write is refused whatever it holds (``config unset``, the marker).
ANY = object()

_REFERENCE = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")


class ManagedRefused(Exception):
    """A configuration write the managed layer refuses. ``names`` are the settings or
    variables refused, ``source`` the managed file that pins them. Deliberately not an
    ``OSError``/``PermissionError``: a route that answers a storage error with 503 must not
    swallow it; the hub maps it to 409 everywhere (``agents/web.py`` exception handler)."""

    def __init__(self, message: str, *, names=(), source: str | None = None) -> None:
        super().__init__(message)
        self.names = list(names)
        self.source = source

    def payload(self) -> dict[str, Any]:
        return {"error": "managed", "detail": str(self), "managed": self.names, "source": self.source}


class ManagedUnreadable(RuntimeError):
    """A managed file exists and cannot be read or parsed (fail closed)."""


@dataclass(frozen=True)
class Scope:
    """What the managed layer pins right now, for one environment."""

    directory: Path | None = None
    explicit: bool = False
    profile: str | None = None
    files: tuple[dict, ...] = ()
    settings: dict = field(default_factory=dict)           # {category: {key: raw value}}
    setting_sources: dict = field(default_factory=dict)    # (category, key) -> file
    env: dict = field(default_factory=dict)                # canonical name -> value
    env_sources: dict = field(default_factory=dict)        # canonical name -> file
    lock: str | None = None                                # the marker's instruction
    lock_source: str | None = None
    problems: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.settings or self.env or self.lock is not None or self.problems)


# ── locating the directory ───────────────────────────────────────────────────

def _under_pytest(environ: Mapping[str, str]) -> bool:
    return "PYTEST_CURRENT_TEST" in environ


def _system_default(environ: Mapping[str, str]) -> Path:
    if os.name == "nt":
        return Path(environ.get("PROGRAMDATA") or r"C:\ProgramData") / "Nerva"
    return POSIX_DEFAULT


#: What the hub's load saw in the process environment (``capture``): the managed folder,
#: managed mode and the process environment a pinned ``${NAME}`` may expand from. Once
#: captured, a later in-process write to ``os.environ`` moves none of them.
_CAPTURED: dict[str, Any] | None = None


#: The names that locate the managed layer, read from the process environment before any
#: ``.env`` file (env_provenance.READ_BEFORE_LOAD lists the hub's own).
_HUB_LOCATION = ("JARVIS_MANAGED_DIR", "JARVIS_MANAGED", "JARVIS_PROFILE")
LOCATION_NAMES = (*_HUB_LOCATION, *("NERVA" + name[len("JARVIS"):] for name in _HUB_LOCATION), "PROGRAMDATA")


def capture(environ: Mapping[str, str] | None = None, *, force: bool = False) -> None:
    """Record where the managed layer is, and whether managed mode is on, as the process
    environment says before any ``.env`` file is read (``load_hub_env`` calls this first).
    Under pytest only with *force*: a load in one test must not fix the managed folder for
    every later test in the process. The process environment a pinned ``${NAME}`` may
    expand from is recorded after the load (:func:`capture_process_env`)."""
    global _CAPTURED
    # "under pytest" from the loaded modules, not the environment: the hub's start reads no
    # variable of its own before the .env files are loaded (H273 review)
    if "_pytest" in sys.modules and not force:
        return
    env = os.environ if environ is None else environ
    location = {}
    for name in LOCATION_NAMES:
        value = env.get(name)
        if value is not None:
            location[name] = value
    _CAPTURED = {"location": location, "env": None}


def capture_process_env(environ: Mapping[str, str] | None = None, *, force: bool = False) -> None:
    """After the hub's load: the values the process environment itself supplied (no ``.env``
    layer, nothing placed later by the Integrations panel), what a pinned ``${NAME}`` may
    expand from. *environ* (tests) is taken whole."""
    if _CAPTURED is None:
        if not force:
            return
        capture(force=True)
    if environ is not None:
        _CAPTURED["env"] = dict(environ)
        return
    from . import env_provenance as ep

    table = ep.provenance()
    _CAPTURED["env"] = {key: value for key, value in os.environ.items()
                        if table.get(key, {}).get("layer") == ep.PROCESS}


def reset_capture() -> None:
    """Forget the captured environment (tests)."""
    global _CAPTURED
    _CAPTURED = None


def _source_env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    """The environment the managed layer is located from: *environ* when given, else what
    the hub's load captured, else (no load in this process, as in the CLI) ``os.environ``."""
    if environ is not None:
        return environ
    if _CAPTURED is not None:
        return _CAPTURED["location"]
    return os.environ


_WARNED: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _WARNED:
        _WARNED.add(message)
        logger.warning("%s", message)


def _windows_admin_owned(path: Path) -> bool:
    """True when *path* is owned by Administrators or SYSTEM (pywin32), False when it is
    not or when that cannot be established."""
    try:
        import win32security  # type: ignore[import-not-found]

        sd = win32security.GetFileSecurity(str(path), win32security.OWNER_SECURITY_INFORMATION)
        owner = win32security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())
    except Exception:  # noqa: BLE001 — unknown owner: not trusted
        return False
    return owner in ("S-1-5-32-544", "S-1-5-18")


def managed_dir(environ: Mapping[str, str] | None = None) -> tuple[Path | None, bool]:
    """``(directory, named explicitly)``. An explicit ``NERVA_MANAGED_DIR`` is returned
    whether or not it exists (a missing one fails closed in :func:`scope`); the system
    location only when it is a directory, and never under pytest. On Windows the default
    ``%PROGRAMDATA%\\Nerva`` (``PROGRAMDATA`` from the process environment) counts only
    when Administrators or SYSTEM own it: any local user may create that folder, so one
    they own is ignored with a warning (name the folder with ``NERVA_MANAGED_DIR``)."""
    from .env_config import resolve_spellings

    env = _source_env(environ)
    raw = (resolve_spellings(env, DIR_ENV)[0] or "").strip()
    if raw:
        return Path(raw).expanduser(), True
    if _under_pytest(env):
        return None, False
    default = _system_default(env)
    try:
        present = default.is_dir()
    except OSError:
        return default, False          # there, but not even stat-able: read it and fail closed
    if present and os.name == "nt" and not _windows_admin_owned(default):
        _warn_once(f"managed configuration: {default} is not owned by Administrators or SYSTEM and is "
                   "ignored; set NERVA_MANAGED_DIR to a folder only administrators can write")
        return None, False
    return (default, False) if present else (None, False)


def _ownership_problem(path: Path) -> str | None:
    """POSIX: a managed folder or file the owner could rewrite is no pin at all. Refused
    unless root owns it and neither its group nor others may write it."""
    if os.name == "nt":
        return None
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{path}: {type(exc).__name__}: {exc.strerror or exc}"
    if st.st_uid != 0:
        return f"{path}: not owned by root (uid {st.st_uid}); an administrator's pins must be root-owned"
    if st.st_mode & 0o022:
        return f"{path}: writable by its group or by others (mode {st.st_mode & 0o777:o})"
    return None


def _profile(environ: Mapping[str, str]) -> str | None:
    from .paths import profile_name

    try:
        return profile_name(environ)
    except Exception:  # noqa: BLE001 — a refused profile name: its hub does not start
        return None


# ── reading the files (stat-keyed, last good kept for readers) ───────────────

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple, Any]] = {}
_LAST_GOOD: dict[str, Any] = {}


def invalidate() -> None:
    """Forget every parsed file (tests; an administrator's edit is picked up by its stat
    signature anyway)."""
    with _LOCK:
        _CACHE.clear()
        _LAST_GOOD.clear()


def _signature(st: os.stat_result) -> tuple:
    return (st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns)


def _read(path: Path, parse) -> tuple[str, Any, str | None]:
    """``(state, parsed, error)``: state is ``absent``, ``read`` or ``unreadable``. An
    unreadable file answers its last good parse (or None) with the reason."""
    key = str(path)
    try:
        st = path.stat()
    except FileNotFoundError:
        return "absent", None, None
    except OSError as exc:
        return "unreadable", copy.deepcopy(_LAST_GOOD.get(key)), f"{type(exc).__name__}: {exc.strerror or exc}"
    sig = _signature(st)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == sig:
            return "read", copy.deepcopy(hit[1]), None
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")         # strict: an administrator's file must fail loud
        parsed = parse(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.error("managed configuration %s cannot be read: %s — configuration writes are refused "
                     "until it is fixed", path, exc)
        return "unreadable", copy.deepcopy(_LAST_GOOD.get(key)), f"{type(exc).__name__}: {exc}"
    with _LOCK:
        _CACHE[key] = (sig, copy.deepcopy(parsed))
        _LAST_GOOD[key] = copy.deepcopy(parsed)
    return "read", parsed, None


def _parse_config(text: str) -> dict:
    import yaml

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"not YAML: {exc}") from exc
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise ValueError("the top level must be a mapping of category: {key: value}")
    out: dict[str, dict] = {}
    for category, values in doc.items():
        if not isinstance(category, str) or not isinstance(values, dict):
            raise ValueError(f"{category!r} must be a category name holding a mapping of key: value")
        for key in values:
            if not isinstance(key, str):
                raise ValueError(f"{category}: every key must be a string, got {key!r}")
        try:
            json.dumps(values)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{category}: a value is not plain data ({exc})") from exc
        out[category] = dict(values)
    return out


def _parse_env(text: str) -> dict[str, str]:
    """KEY=VALUE lines, python-dotenv's grammar, taken literally (never interpolated). A
    line python-dotenv would skip with a warning refuses the file here: an administrator's
    pin must not vanish silently."""
    from dotenv.parser import parse_stream

    out: dict[str, str] = {}
    for binding in parse_stream(io.StringIO(text)):
        if binding.error:
            raise ValueError(f"line {binding.original.line} is not KEY=VALUE")
        if binding.key is None:
            continue
        if binding.value is None:
            raise ValueError(f"{binding.key} has no '=': write {binding.key}=VALUE (or {binding.key}= for empty)")
        canonical = canonical_env(binding.key)
        if canonical in out and out[canonical] != binding.value:
            raise ValueError(f"{canonical} is set twice, differently")
        out[canonical] = binding.value
    return out


def _parse_marker(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:200]
    return DEFAULT_INSTRUCTION


def _merge(base: Any, top: Any) -> Any:
    """*top* deep-merged onto *base*, leaf by leaf (a mapping merges, anything else replaces)."""
    if isinstance(base, dict) and isinstance(top, dict) and top:
        out = dict(base)
        for key, value in top.items():
            out[key] = _merge(base.get(key, _MISSING), value) if key in base else copy.deepcopy(value)
        return out
    return copy.deepcopy(top)


def _env_lock(environ: Mapping[str, str]) -> tuple[str | None, str | None]:
    """Hermes's coarse ``HERMES_MANAGED``: ``NERVA_MANAGED=<what manages it>`` (e.g. ``nix``,
    ``ansible``) set by the package or service that installs Nerva turns managed mode on
    without a managed directory. ``(instruction, source)`` or ``(None, None)``."""
    from .env_config import PREFERRED_PREFIX, is_recognized_bool, resolve_spellings, truthy

    value = (resolve_spellings(environ, MANAGED_ENV)[0] or "").strip()
    source = PREFERRED_PREFIX + MANAGED_ENV.split("_", 1)[1]
    if not value or (is_recognized_bool(value) and not truthy(value)):
        return None, None
    if is_recognized_bool(value):
        return DEFAULT_INSTRUCTION, source
    return f"this installation is managed by {value[:80]}: change the configuration through it", source


def scope(environ: Mapping[str, str] | None = None) -> Scope:
    """The managed layer for *environ* (default: this process), read now."""
    env = _source_env(environ)
    directory, explicit = managed_dir(env)
    if directory is None:
        lock, lock_source = _env_lock(env)
        return Scope(lock=lock, lock_source=lock_source)
    profile = _profile(env)
    problems: list[str] = []
    files: list[dict] = []
    try:
        present = directory.is_dir()
    except OSError as exc:
        present = False
        problems.append(f"{directory}: {exc}")
    if not present and not problems:
        problems.append(f"{directory}: named by NERVA_MANAGED_DIR but not a directory")
    if present:
        owned = _ownership_problem(directory)
        if owned:
            problems.append(owned)
    places = [("shared", directory)]
    if profile:
        places.append((f"profile {profile}", directory / PROFILES_DIR / profile))
    settings: dict = {}
    setting_sources: dict = {}
    pinned_env: dict = {}
    env_sources: dict = {}
    lock = lock_source = None
    for where, folder in places:
        for name, parse in ((CONFIG_FILE, _parse_config), (ENV_FILE, _parse_env), (MARKER_FILE, _parse_marker)):
            path = folder / name
            state, parsed, error = _read(path, parse) if present else ("absent", None, None)
            if state == "read" and not error:
                error = _ownership_problem(path)
                if error:
                    state = "untrusted"
            files.append({"path": str(path), "kind": name, "scope": where, "state": state,
                          **({"error": error} if error else {})})
            if error:
                problems.append(f"{path}: {error}")
            if parsed is None:
                continue
            if name == CONFIG_FILE:
                for category, values in parsed.items():
                    for key, value in values.items():
                        here = settings.setdefault(category, {})
                        here[key] = _merge(here.get(key), value) if key in here else copy.deepcopy(value)
                        setting_sources[(category, key)] = str(path)
            elif name == ENV_FILE:
                for var, value in parsed.items():
                    pinned_env[var] = value
                    env_sources[var] = str(path)
            else:
                lock, lock_source = parsed, str(path)
    if lock is None:
        lock, lock_source = _env_lock(env)
    problems.extend(_schema_problems(settings, setting_sources, pinned_env))
    return Scope(directory=directory, explicit=explicit, profile=profile, files=tuple(files),
                 settings=settings, setting_sources=setting_sources, env=pinned_env, env_sources=env_sources,
                 lock=lock, lock_source=lock_source, problems=tuple(problems))


_SCHEMA_MEMO: dict[str, list[str]] = {}


def _schema_problems(settings: dict, sources: dict, pinned_env: dict) -> list[str]:
    """A pin its declaration refuses (or a name no setting declares) is a problem, not a
    silent fallback to the owner's value: writes are refused and the hub does not start."""
    if not settings:
        return []
    try:
        memo_key = json.dumps(settings, sort_keys=True, default=str)
    except (TypeError, ValueError):
        memo_key = repr(settings)
    hit = _SCHEMA_MEMO.get(memo_key)
    if hit is not None:
        return list(hit)
    from . import settings_db

    base = dict(_CAPTURED["env"] if _CAPTURED is not None and _CAPTURED["env"] is not None else os.environ)
    base.update(pinned_env)
    out: list[str] = []
    for category, values in settings.items():
        for key, value in values.items():
            source = sources.get((category, key), "")
            spec = settings_db._SPEC.get((category, key))
            if spec is None:
                out.append(f"{source}: {category}.{key} is not a declared setting")
                continue
            whole = _merge(copy.deepcopy(spec.get("value")), expand(value, base))
            errors = settings_db.validate_category(category, {key: whole}, references=False)
            if errors:
                out.append(f"{source}: {category}.{key} is refused by its declaration: {'; '.join(errors)}")
    _SCHEMA_MEMO.clear()
    _SCHEMA_MEMO[memo_key] = out
    return list(out)


# ── reading a pinned value ───────────────────────────────────────────────────

def process_environ() -> dict[str, str]:
    """What a managed ``${NAME}`` may expand to: the process environment the hub's load
    captured before any ``.env`` file was read (``capture``), so neither a ``.env`` value
    nor one placed in ``os.environ`` later (the Integrations panel's keys) can supply it;
    then the managed ``.env`` on top. With no load in this process: ``os.environ`` without
    the ``.env`` layers env_provenance recorded."""
    if _CAPTURED is not None and _CAPTURED["env"] is not None:
        env = dict(_CAPTURED["env"])
    else:
        from . import env_provenance as ep

        env = dict(os.environ)
        if ep.files():                               # a load ran in this process
            for key, row in ep.provenance().items():
                if row["layer"] in (ep.REPO_ENV, ep.USER_ENV):
                    env.pop(key, None)
    env.update(scope().env)
    return env


def expand(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    """*value* with every ``${NAME}`` / ``${env:NAME}`` expanded from *environ* (default
    :func:`process_environ`); a reference to nothing is left as written."""
    from .env_config import resolve_spellings

    if environ is None:
        if not _has_reference(value):
            return copy.deepcopy(value)
        environ = process_environ()

    def one(match: re.Match) -> str:
        found = resolve_spellings(environ, match.group(1))[0]
        return match.group(0) if found is None else found

    if isinstance(value, str):
        return _REFERENCE.sub(one, value)
    if isinstance(value, dict):
        return {key: expand(item, environ) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item, environ) for item in value]
    return value


def _has_reference(value: Any) -> bool:
    if isinstance(value, str):
        return _REFERENCE.search(value) is not None
    if isinstance(value, dict):
        return any(_has_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_reference(item) for item in value)
    return False


def leaves(value: Any, prefix: tuple = ()) -> list[tuple]:
    """The pinned leaf paths of a pin: ``[()]`` for a whole value, one path per leaf of
    a non-empty mapping (an empty mapping is itself a leaf)."""
    if isinstance(value, dict) and value:
        out: list[tuple] = []
        for key, item in value.items():
            out.extend(leaves(item, (*prefix, key)))
        return out
    return [prefix]


def setting_pin(category: str, key: str, current: Scope | None = None) -> tuple[Any, str] | None:
    """``(the pinned value, expanded; the file that pins it)`` or None."""
    current = scope() if current is None else current
    values = current.settings.get(category)
    if not isinstance(values, dict) or key not in values:
        return None
    return expand(values[key]), current.setting_sources.get((category, key), str(current.directory))


def overlay(stored: Any, pinned: Any) -> Any:
    """The value a reader sees: *pinned* merged onto *stored* leaf by leaf."""
    return _merge(stored, pinned)


def same(a: Any, b: Any) -> bool:
    """JSON equality: ``1 == 1.0``, but ``True`` is not ``1``."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and a == b


def _conflicts(pinned: Any, value: Any, prefix: tuple = ()) -> list[tuple]:
    if isinstance(pinned, dict) and pinned:
        if not isinstance(value, dict):
            return [prefix]
        out: list[tuple] = []
        for key, item in pinned.items():
            out.extend(_conflicts(item, value.get(key, _MISSING), (*prefix, key)))
        return out
    return [] if value is not _MISSING and same(value, pinned) else [prefix]


def _dotted(category: str, key: str, path: tuple = ()) -> str:
    return ".".join([category, key, *[str(part) for part in path]])


# ── the writers' gate ────────────────────────────────────────────────────────

def _unreadable_message(current: Scope) -> str:
    return ("configuration is " + ADMINISTRATOR + ", and the managed configuration cannot be read ("
            + "; ".join(current.problems) + "): nothing is changed until the administrator fixes it")


def _lock_message(current: Scope) -> str:
    return (f"configuration is {ADMINISTRATOR} ({current.lock_source}) and cannot be changed here: "
            f"{current.lock}")


def check_writable(current: Scope | None = None) -> Scope:
    """Raise :class:`ManagedRefused` when no configuration write may happen at all: a
    managed file that cannot be read (fail closed) or the managed-mode marker. Returns
    the scope it judged."""
    current = scope() if current is None else current
    if current.problems:
        raise ManagedRefused(_unreadable_message(current), names=["*"],
                             source=str(current.directory) if current.directory else None)
    if current.lock is not None:
        raise ManagedRefused(_lock_message(current), names=["*"], source=current.lock_source)
    return current


def setting_refusal(category: str, key: str, path: tuple = (), source: str = "") -> str:
    return (f"cannot set {_dotted(category, key, path)}: it is {ADMINISTRATOR} ({source}) "
            "and cannot be changed")


def check_setting_write(category: str, key: str, value: Any = ANY, *, current: Scope | None = None) -> None:
    """Refuse a single-setting write that would change a pinned value. *value* ``ANY``
    (an unset, a write whose value is not known yet) is refused whenever the key is
    pinned; a value that keeps every pinned leaf as pinned passes."""
    current = check_writable(current)
    pin = setting_pin(category, key, current)
    if pin is None:
        return
    pinned, source = pin
    bad = [()] if value is ANY else _conflicts(pinned, value)
    if bad:
        raise ManagedRefused(setting_refusal(category, key, bad[0], source),
                             names=[_dotted(category, key, path) for path in bad], source=source)


def split_setting_write(category: str, data: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A category write: ``(what may be written, the pinned keys left out)``. A pinned key
    whose value keeps every pinned leaf is left out (writing it would only copy the
    administrator's value into the owner's store); one that would change a pinned leaf
    refuses the whole write."""
    current = scope()
    if not current.active:
        return dict(data), []
    current = check_writable(current)
    kept: dict[str, Any] = {}
    stripped: list[str] = []
    for key, value in data.items():
        pin = setting_pin(category, key, current)
        if pin is None:
            kept[key] = value
            continue
        check_setting_write(category, key, value, current=current)
        if leaves(pin[0]) == [()]:
            stripped.append(key)            # the whole value is the administrator's
        else:
            kept[key] = value               # the owner's leaves of a leaf-pinned json setting
    return kept, stripped


def strip_settings(changes: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """A bulk write (an import, a reset, an undo): ``(changes without any pinned key,
    the pinned ``category.key`` names it left out)``. Refuses outright only when nothing
    may be written (unreadable managed file, marker)."""
    current = scope()
    if not current.active:
        return {cat: dict(values) for cat, values in changes.items()}, []
    current = check_writable(current)
    out: dict[str, dict[str, Any]] = {}
    stripped: list[str] = []
    for cat, values in changes.items():
        for key, value in values.items():
            pin = setting_pin(cat, key, current)
            if pin is None:
                out.setdefault(cat, {})[key] = value
            elif leaves(pin[0]) != [()] and isinstance(value, dict):
                # a leaf-pinned json setting: the owner's leaves are written, the pinned
                # ones are put back to the administrator's value (and named if they differed)
                if _conflicts(pin[0], value):
                    stripped.append(f"{cat}.{key}")
                out.setdefault(cat, {})[key] = overlay(value, pin[0])
            else:
                stripped.append(f"{cat}.{key}")
    return out, sorted(stripped)


def pinned_setting_names(current: Scope | None = None) -> list[str]:
    current = scope() if current is None else current
    return sorted(f"{cat}.{key}" for cat, values in current.settings.items() for key in values)


# ── the environment ──────────────────────────────────────────────────────────

def canonical_env(name: str) -> str:
    from .env_config import other_spelling

    return (other_spelling(name) or name) if isinstance(name, str) and name.startswith("NERVA_") else name


def env_pins(environ: Mapping[str, str] | None = None, *, strict: bool = True) -> dict[str, str]:
    """The pinned environment (canonical names). *strict*: raise :class:`ManagedUnreadable`
    when a managed file cannot be read, instead of answering what parsed last."""
    current = scope(environ)
    if strict and current.problems:
        raise ManagedUnreadable(_unreadable_message(current))
    return dict(current.env)


def is_env_managed(name: str, current: Scope | None = None) -> bool:
    current = scope() if current is None else current
    return canonical_env(name) in current.env


def check_env_write(name: str) -> None:
    """Refuse a write of an environment value the managed ``.env`` pins (or any, while the
    managed configuration cannot be read or the marker is present). For every writer of a
    ``.env`` value or of a key that lands where one does."""
    current = check_writable()
    canonical = canonical_env(name)
    if canonical in current.env:
        source = current.env_sources.get(canonical, str(current.directory))
        raise ManagedRefused(f"cannot set {name}: it is {ADMINISTRATOR} ({source}) and cannot be changed",
                             names=[canonical], source=source)


# ── what the CLI and the HUD show ────────────────────────────────────────────

def describe(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The managed layer for a view: where, which files, the pinned names (an environment
    value never, a setting value only through the settings readers), the marker and why
    writes are refused, if they are."""
    current = scope(environ)
    return {
        "directory": str(current.directory) if current.directory else None,
        "explicit": current.explicit,
        "profile": current.profile,
        "active": current.active,
        "files": [dict(row) for row in current.files],
        "settings": [{"name": f"{cat}.{key}", "source": current.setting_sources.get((cat, key)),
                      "leaves": [".".join(str(p) for p in path) for path in leaves(values[key]) if path]}
                     for cat, values in sorted(current.settings.items()) for key in sorted(values)],
        "env": [{"name": name, "source": current.env_sources.get(name)} for name in sorted(current.env)],
        "lock": ({"instruction": current.lock, "source": current.lock_source}
                 if current.lock is not None else None),
        "problems": list(current.problems),
        "writes": ("refused: the managed configuration cannot be read" if current.problems
                   else "refused: managed mode" if current.lock is not None
                   else "pinned values refused" if current.active else "allowed"),
    }


__all__ = [
    "ADMINISTRATOR", "ANY", "CONFIG_FILE", "DIR_ENV", "ENV_FILE", "MARKER_FILE", "ManagedRefused",
    "ManagedUnreadable", "PROFILES_DIR", "Scope", "canonical_env", "check_env_write", "check_setting_write",
    "check_writable", "describe", "env_pins", "expand", "invalidate", "is_env_managed", "leaves",
    "managed_dir", "overlay", "pinned_setting_names", "process_environ", "same", "scope", "setting_pin",
    "split_setting_write", "strip_settings",
]


def audit_refusal(exc: ManagedRefused, where: str) -> bool:
    """Write the ``settings_managed_refused`` audit row for a refusal (names and the
    managed file, never a value). True when written."""
    try:
        import time

        from .app_state import get_orch
        from .security.types import SecurityEvent, SecurityEventType

        orch = get_orch()
        audit = getattr(orch, "audit", None) if orch else None
        if audit is None:
            return False
        audit.log(SecurityEvent(event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                                content_preview=f"{where}: write refused: {exc.names} {exc}"[:500],
                                action_taken="settings_managed_refused"))
        return True
    except Exception:  # noqa: BLE001 — the refusal stands either way
        logger.warning("managed configuration: a refusal could not be audited")
        return False


#: The model choice the provider-selection and custom-endpoint routes move.
SELECTION_SETTINGS = (("llm", "compatible_provider"), ("llm", "compatible_model"))


def check_llm_write(*, selection: bool) -> None:
    """For the routes that change the model setup outside the settings store (custom
    endpoints, signed provider selection, provider credentials): refused in managed mode
    or while the managed configuration cannot be read; a route that moves the model
    choice (*selection*) also when the administrator pinned it."""
    current = check_writable()
    if selection:
        for category, key in SELECTION_SETTINGS:
            check_setting_write(category, key, ANY, current=current)
