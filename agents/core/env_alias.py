"""env_alias.py — RB-2: ``NERVA_<X>`` is the preferred spelling of every ``JARVIS_<X>``.

The product is Nerva; its variables were all still ``JARVIS_*``. Every hub variable now
has two spellings of ONE variable: ``NERVA_<X>`` (preferred) and ``JARVIS_<X>``
(deprecated, kept working). The code keeps reading the ``JARVIS_`` name; this module is
what makes a ``NERVA_`` spelling arrive there.

**How.** The environment is kept *canonical*: a hub variable lives in it under its
``JARVIS_`` name only. ``normalize`` folds a ``NERVA_<X>`` onto ``JARVIS_<X>`` and takes
the ``NERVA_`` key back out (a move, not a copy), at the two places a value can enter:

- the process environment, when the ``agents`` package is first imported
  (``agents/__init__.py`` and ``agents/core/__init__.py``: before any hub module, so
  before every import-time read in ``agents.web``), and
- each ``.env`` layer, inside ``env_provenance.load_layered_env``, as that layer loads.

Moving is what keeps every downstream rule exactly as it was: a child process, a
sandbox allowlist, a denylist by prefix, ``/api/admin/env`` and the direct
``os.environ`` readers all see the environment they saw when the operator wrote
``JARVIS_<X>``. Nothing new exists for a filter to miss. ``env_config``'s getters also
read both spellings at call time (``resolve_spellings``), so a ``NERVA_<X>`` set while
running reaches them without this module. Wherever an operator *names* a variable
instead of setting it (a ``--token-env`` option, a passthrough list, a ``${NAME}``
reference), the name is brought to the same form with ``canonical``.

**One rule when both spellings are set, for every hub variable.** A layer is the
process environment or one ``.env`` file. *Across* layers nothing is new: the first
layer to set the variable wins, whichever spelling each used, so a ``.env`` value never
overrides a process value. *Within* one layer:

- equal values: fine, the variable has that value;
- one of them blank: the other is used (blank means "not set" throughout ``env_config``);
- different values: the hub **refuses to start**, naming the variable and never a value.

There is no variable for which one spelling "wins" over the other. A refused pair is
left in the environment exactly as found (both keys, both values), so the refusal is
stateless: ``conflicts`` finds it again from the environment alone, in every process
that inherits it, and until the process has stopped both kinds of reader see the
``JARVIS_`` value (``env_config.resolve_spellings``). ``refuse_conflicts`` is the boot
guard; it runs from ``env_provenance.load_hub_env`` (every hub entry point loads through
it), from ``boot_guards`` and from the command-line entries.

In the process environment one of the two lines is often not the operator's: the
container image, the compose file, the service unit and the start scripts pin a few
variables under the ``JARVIS_`` spelling (``docs/FLAGS.md`` lists them). The refusal
says so, and says the remedy: override a pinned variable under the spelling the
launcher uses, or change the launcher's line.

**Paths.** ``PATH_TYPED`` names the variables whose value is a directory or a file.
Nothing here refuses one for what it *is*: a root the operator wrote out
(``JARVIS_FILE_ROOTS=/``) boots, as it always did, with one loud warning naming the
variable (``root_paths``). What is refused is a path that a ``.env`` builds from a
``${...}`` reference to nothing — that is decided where the reference is expanded
(``env_provenance``), from the record of the expansion and never from the final string.

**Which spelling was used** is the one thing a move forgets, and the operator is owed it
(``/api/admin/env/sources`` and ``nerva doctor`` flag the deprecated spelling). It is kept
in the environment itself as a list of names — never values — under ``MARKER``, because
the hub is importable under two module names and both must see it. It is this process's
own note: a value inherited from outside is discarded at the first fold, a ``.env`` file
cannot write it, the admin env routes skip names that start with ``_``, and every
child-process allowlist drops it. The hub's own re-exec and the supervisor's spawn of the
coordinator pass it on explicitly (``hand_over``: the marker plus the pid that vouches for
it), so the note survives a self-restart; it is display-only, names and never values.

Standard library only; never logs, prints or returns a value.
"""

from __future__ import annotations

import os
import posixpath
import re
import sys
from collections.abc import Container, Mapping, MutableMapping
from typing import NamedTuple

from .env_config import (
    DEPRECATED_PREFIX,
    PREFERRED_PREFIX,
    env_str,
    other_spelling,
    resolve_spellings,
)

#: Names (never values) of the hub variables whose value in effect was supplied under
#: the preferred spelling. See the module docstring.
MARKER = "_NERVA_ENV_PREFERRED"

#: Set beside the marker by a parent that passes it on: that parent's pid (``hand_over``).
HANDOFF = "_NERVA_ENV_PREFERRED_PID"
#: The hub's own notes in the environment: no ``.env`` file may set them.
PRIVATE_NAMES = frozenset({MARKER, HANDOFF})

#: Exit status of a process that stopped because its configuration is refused (sysexits'
#: EX_CONFIG): retrying cannot help, so a supervisor must not respawn on it.
CONFIG_REFUSED_EXIT = 78


class ConfigurationRefused(SystemExit):
    """The configuration contradicts itself (or names the filesystem root): the process
    must not start. A ``SystemExit`` whose text is the refusal, as every boot guard
    raises; a launcher that supervises the process turns it into ``CONFIG_REFUSED_EXIT``."""


def canonical(name: str) -> str:
    """The name the hub reads: ``JARVIS_X`` for either spelling of a hub variable, and
    *name* itself for everything else. THE function for a variable an operator names
    rather than sets."""
    if isinstance(name, str) and name.startswith(PREFERRED_PREFIX):
        return other_spelling(name) or name
    return name


def preferred_name(name: str) -> str | None:
    """``NERVA_X`` for either spelling of a hub variable; None for any other name."""
    other = other_spelling(name)
    if other is None:
        return None
    return name if name.startswith(PREFERRED_PREFIX) else other


def lookup(environ: Mapping[str, str], name: str) -> str | None:
    """*name*'s value in *environ* under either spelling (the one pair rule), or None."""
    return resolve_spellings(environ, name)[0]


class Fold(NamedTuple):
    """What one layer's keys come to once both spellings are one variable. Names only
    beside ``values``, which holds what the layer itself supplied."""

    values: dict[str, str]        # what the layer sets, hub variables under their JARVIS_ name
    spelling: dict[str, str]      # hub variable -> the spelling whose value is in effect
    shadowed: tuple[str, ...]     # hub variables a higher layer already set (this layer's value is ignored)
    refused: tuple[str, ...]      # set under both spellings, differently


def _differ(new: object, old: object) -> bool:
    return new != old and bool(str(new).strip()) and bool(str(old).strip())


def fold(added: Mapping[str, str], before: Container[str] = ()) -> Fold:
    """Fold one layer. *added* is what the layer sets, as spelled; *before* is what the
    higher layers already set (canonical names). Pure: nothing is read but the arguments.

    A refused pair stays in ``values`` under both names, untouched, so whoever applies
    the fold leaves the contradiction where ``conflicts`` can see it."""
    values: dict[str, str] = {}
    spelling: dict[str, str] = {}
    shadowed: list[str] = []
    refused: list[str] = []
    for key in added:
        other = other_spelling(key)
        if other is None:
            values[key] = added[key]
            continue
        name = canonical(key)
        if name in spelling or name in shadowed or name in refused:
            continue                      # the pair was handled at its first key
        if name in before:
            shadowed.append(name)
            continue
        new_key = preferred_name(key)
        if new_key in added and name in added and _differ(added[new_key], added[name]):
            refused.append(name)
            values[name], values[new_key] = added[name], added[new_key]
            continue
        value, used = resolve_spellings(added, name)
        values[name], spelling[name] = value, used
    return Fold(values, spelling, tuple(shadowed), tuple(refused))


def preferred_supplied(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """The hub variables (``JARVIS_`` names) whose value in effect came in under the
    ``NERVA_`` spelling, as the marker records them."""
    environ = os.environ if environ is None else environ
    raw = str(environ.get(MARKER) or "")
    return frozenset(name for name in (part.strip() for part in raw.split(","))
                     if name and other_spelling(name) is not None)


def _record(environ: MutableMapping[str, str], spelling: Mapping[str, str]) -> None:
    if not spelling:
        return
    names = set(preferred_supplied(environ))
    for name, used in spelling.items():
        (names.add if used.startswith(PREFERRED_PREFIX) else names.discard)(name)
    if names:
        environ[MARKER] = ",".join(sorted(names))
    else:
        environ.pop(MARKER, None)


def normalize(environ: MutableMapping[str, str]) -> Fold:
    """Make *environ* canonical in place: every hub variable under its ``JARVIS_`` name,
    its ``NERVA_`` spelling folded in and removed. Idempotent — a second call finds
    nothing to do. A refused pair is left exactly as found. Never raises, never logs."""
    pairs = {key: environ[key] for key in list(environ)
             if isinstance(key, str) and key.startswith(PREFERRED_PREFIX) and other_spelling(key)}
    if not pairs:
        return Fold({}, {}, (), ())
    for key in list(pairs):
        name = canonical(key)
        if name in environ:
            pairs[name] = environ[name]
    folded = fold(pairs)
    for name in folded.spelling:
        environ[name] = folded.values[name]
        environ.pop(preferred_name(name), None)
    _record(environ, folded.spelling)
    return folded


#: Set on ``sys`` (one object whichever name this module was imported under) once this
#: process has folded its environment: the marker in it from then on is this process's.
_FOLDED_FLAG = "_nerva_env_alias_folded"


def normalize_process_env() -> Fold:
    """``normalize(os.environ)`` — the process-start step (see the module docstring). The
    first call in a process also discards a spelling marker it inherited, unless the
    process that started this one handed it over (``hand_over``): the note is never
    trusted from anywhere else (a forked child keeps its parent's, being the same image)."""
    if not getattr(sys, _FOLDED_FLAG, False):
        vouched = os.environ.pop(HANDOFF, None)
        # the hub re-executing itself keeps its pid; a spawned coordinator or successor
        # names its parent (the successor may outlive it: serve.py records the same pid)
        if not vouched or not (vouched in (str(os.getpid()), str(os.getppid()))
                               or vouched == env_str("NERVA_RESTART_PREDECESSOR", None)):
            os.environ.pop(MARKER, None)
        setattr(sys, _FOLDED_FLAG, True)
    return normalize(os.environ)


def hand_over(environ: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """For the hub's own exec or spawn of the next hub process: vouch, with this
    process's pid, for the spelling marker *environ* carries. Display-only; returns
    *environ*."""
    if environ.get(MARKER):
        environ[HANDOFF] = str(os.getpid())
    return environ


def normalized(environ: Mapping[str, str]) -> dict[str, str]:
    """A canonical copy of *environ*, for code that predicts what the hub would read from
    an environment it was handed (the doctor, ``env_provenance.derive``)."""
    copy = dict(environ)
    normalize(copy)
    return copy


def conflicts(environ: Mapping[str, str] | None = None) -> list[str]:
    """The hub variables set under both spellings with different values (``JARVIS_``
    names, sorted). Read from *environ* alone."""
    environ = os.environ if environ is None else environ
    found = set()
    for key in list(environ):
        if not (isinstance(key, str) and key.startswith(PREFERRED_PREFIX)):
            continue
        name = other_spelling(key)
        if name is not None and name in environ and _differ(environ[key], environ[name]):
            found.add(name)
    return sorted(found)


PROCESS_ENVIRONMENT = "the process environment"


def conflict_message(names, where: str = PROCESS_ENVIRONMENT) -> str:
    """The refusal: the variables and the remedy, never a value."""
    pairs = ", ".join(f"{preferred_name(name)} / {name}" for name in names)
    text = (f"Refusing to start: {pairs} — set under both spellings in {where}, with different values.\n"
            "NERVA_<X> and JARVIS_<X> are one variable (NERVA_ is the preferred spelling, JARVIS_ the "
            "deprecated one), and which value was meant is never guessed.")
    if where == PROCESS_ENVIRONMENT or "shell" in where:
        return text + (
            "\nOne of the two may not be yours: the container image, the compose file, the service unit "
            "and the start scripts set a few variables under the JARVIS_ spelling (docs/FLAGS.md lists "
            "them). To override one of those, set it under the SAME spelling the launcher uses "
            "(JARVIS_<X>), or change the launcher's own line; otherwise keep one of your two lines.")
    return text + "\nKeep one of the two lines in that file."


def refuse_conflicts(environ: Mapping[str, str] | None = None, *,
                     where: str = PROCESS_ENVIRONMENT) -> None:
    """The boot guard: stop when a hub variable is set under both spellings, differently.
    Names the variable, never a value."""
    names = conflicts(environ)
    if names:
        raise ConfigurationRefused(conflict_message(names, where))


#: ``<X>`` of the hub variables whose value names a directory or a file (one path, or a
#: list of them). Measured from the readers in ``agents/`` and ``scripts/``; the test
#: ``tests/test_rb2_review_fixes.py`` fails when a name that looks like one is missing.
#: A variable is path-typed by being listed here, by name.
PATH_TYPED = frozenset({
    "HOME", "USER_HOME", "MEMORY_DIR", "APP_ROOT",                      # where the hub's own files live
    "FILE_ROOTS", "TERMINAL_LOCAL_ROOTS", "MEDIA_ROOTS",                # what the tools may reach
    "KEY_DIR", "EXEC_TEMP_DIR", "FORGET_ARCHIVE_DIR", "PLAYWRIGHT_DOWNLOAD_DIR", "DRIVE_AI_DEST",
    "EVAL_STORE", "LOG_FILE", "RUNTIME_LOG", "RUNTIME_STATE", "SUBAGENT_SPAWN_LOG",
    "CA_BUNDLE", "WASM_PYTHON", "TERMINAL_SSH_KNOWN_HOSTS",
})
_DRIVE_ROOT = re.compile(r"[A-Za-z]:[\\/]*\Z")


def path_typed(name: str) -> bool:
    """Whether the hub variable *name* (either spelling) names a directory or a file:
    exactly the names in ``PATH_TYPED``, never a guess from a substring."""
    key = canonical(name)
    return key.startswith(DEPRECATED_PREFIX) and key[len(DEPRECATED_PREFIX):] in PATH_TYPED


def root_paths(environ: Mapping[str, str] | None = None) -> list[str]:
    """The path-typed hub variables whose whole value is literally a filesystem root
    (``/``, ``//``, ``/.``, ``/tmp/..``, ``C:\\``), as spelled in *environ* (sorted names). For a warning: a
    root an operator wrote out is theirs to choose, and the value is not parsed as a
    list (each variable has its own syntax; none is reinterpreted here)."""
    environ = os.environ if environ is None else environ
    found = []
    for key, value in list(environ.items()):
        if not (isinstance(key, str) and path_typed(key)):
            continue
        text = str(value).strip()
        # "/", "//", "/.", "/tmp/.." — what the string says, nothing looked up on disk
        if text and (not posixpath.normpath(text.replace("\\", "/")).strip("/")
                     or _DRIVE_ROOT.match(text) is not None):
            found.append(key)
    return sorted(found)


def root_path_warning(names, where: str = PROCESS_ENVIRONMENT) -> str:
    """The loud line for a literal root: the variables, never a value."""
    return (", ".join(names) + f" {'is' if len(names) == 1 else 'are'} set to the filesystem root in "
            f"{where}: everything on this machine is inside what {'it names' if len(names) == 1 else 'they name'}. "
            "If that is not what you meant, name the directory itself.")


def spelling_info(key: str, environ: Mapping[str, str] | None = None) -> dict:
    """For a hub variable: the spelling its value came in under, the preferred one, and
    whether the deprecated one was used. ``{}`` for any other name."""
    name = canonical(key)
    new_key = preferred_name(name)
    if new_key is None:
        return {}
    used = new_key if name in preferred_supplied(environ) else name
    return {"spelling": used, "preferred": new_key, "deprecated": used != new_key}


def supplied_name(name: str, environ: Mapping[str, str] | None = None) -> str:
    """How the operator spelled *name* (for a message that tells them what to fix)."""
    return spelling_info(name, environ).get("spelling", name)


__all__ = [
    "CONFIG_REFUSED_EXIT", "ConfigurationRefused", "DEPRECATED_PREFIX", "Fold", "HANDOFF", "MARKER",
    "PATH_TYPED", "PREFERRED_PREFIX", "PRIVATE_NAMES", "PROCESS_ENVIRONMENT", "canonical", "conflict_message",
    "conflicts", "fold", "hand_over", "lookup", "normalize", "normalize_process_env", "normalized", "path_typed",
    "preferred_name", "preferred_supplied", "refuse_conflicts", "root_path_warning", "root_paths",
    "spelling_info", "supplied_name",
]
