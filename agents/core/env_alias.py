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
sandbox allowlist, a denylist by prefix, ``/api/admin/env`` and the 116 direct
``os.environ`` readers all see the environment they saw when the operator wrote
``JARVIS_<X>``. Nothing new exists for a filter to miss. ``env_config``'s getters also
read both spellings at call time (``resolve_spellings``), so a ``NERVA_<X>`` set while
running reaches them without this module.

**One rule when both spellings are set.** A layer is the process environment or one
``.env`` file. *Across* layers nothing is new: the first layer to set the variable wins,
whichever spelling each used, so a ``.env`` value never overrides a process value.
*Within* one layer:

- equal values: fine, the variable has that value;
- one of them blank: the other is used (blank means "not set" throughout ``env_config``);
- different values: the operator has contradicted themselves, and the hub **refuses to
  start**, naming the variable and never a value — unless the variable is on the short
  reviewed list of ordinary tuning knobs (``env_config.NERVA_WINS_ON_CONFLICT``), where
  the ``NERVA_`` spelling wins and one warning names the variable.

The list is the *exception*, so the rule fails closed: a posture flag, a credential, a
file-location root, an endpoint, an allowlist, and any variable nobody has reviewed —
a new one, a dynamic ``JARVIS_ROLE_*`` name — all refuse. Picking either value silently
for one of those would let a stale line decide the box's protection.

A refused pair is left in the environment exactly as found (both keys, both values), so
the refusal is stateless: ``conflicts`` finds it again from the environment alone, in
every process that inherits it. ``refuse_conflicts`` is the boot guard; it runs from
``env_provenance.load_hub_env`` (every hub entry point loads through it) and again from
``boot_guards``.

**Which spelling was used** is the one thing a move forgets, and the operator is owed it
(``/api/admin/env/sources`` and ``nerva doctor`` flag the deprecated spelling). It is kept
in the environment itself as a list of names — never values — under ``MARKER``, so a hub
that re-executes itself, or a coordinator started by the supervisor, still knows. The
marker starts with ``_``: the admin env routes skip such names, and every child-process
allowlist drops it.

Standard library only; never logs, prints or returns a value.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Container, Mapping, MutableMapping
from typing import NamedTuple

from .env_config import (
    DEPRECATED_PREFIX,
    NERVA_WINS_ON_CONFLICT,
    PREFERRED_PREFIX,
    other_spelling,
    resolve_spellings,
)

logger = logging.getLogger("nerva.env_alias")

#: Names (never values) of the hub variables whose value in effect was supplied under
#: the preferred spelling. See the module docstring.
MARKER = "_NERVA_ENV_PREFERRED"

_WARNED: set[str] = set()


def canonical(name: str) -> str:
    """The name the hub reads: ``JARVIS_X`` for either spelling of a hub variable, and
    *name* itself for everything else."""
    if isinstance(name, str) and name.startswith(PREFERRED_PREFIX):
        return other_spelling(name) or name
    return name


def preferred_name(name: str) -> str | None:
    """``NERVA_X`` for either spelling of a hub variable; None for any other name."""
    other = other_spelling(name)
    if other is None:
        return None
    return name if name.startswith(PREFERRED_PREFIX) else other


def refuses_on_conflict(name: str) -> bool:
    """Whether two different values for this hub variable in one layer stop the boot
    (everything but the reviewed ordinary knobs)."""
    return canonical(name)[len(DEPRECATED_PREFIX):] not in NERVA_WINS_ON_CONFLICT


class Fold(NamedTuple):
    """What one layer's keys come to once both spellings are one variable. Names only
    beside ``values``, which holds what the layer itself supplied."""

    values: dict[str, str]        # what the layer sets, hub variables under their JARVIS_ name
    spelling: dict[str, str]      # hub variable -> the spelling whose value is in effect
    shadowed: tuple[str, ...]     # hub variables a higher layer already set (this layer's value is ignored)
    overridden: tuple[str, ...]   # ordinary knobs set twice, differently: the NERVA_ value won
    refused: tuple[str, ...]      # set twice, differently, and not an ordinary knob


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
    overridden: list[str] = []
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
            if refuses_on_conflict(name):
                refused.append(name)
                values[name], values[new_key] = added[name], added[new_key]
                continue
            overridden.append(name)
        value, used = resolve_spellings(added, name)
        values[name], spelling[name] = value, used
    return Fold(values, spelling, tuple(shadowed), tuple(overridden), tuple(refused))


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


def _warn_overridden(names, where: str) -> None:
    for name in names:
        if name not in _WARNED:
            _WARNED.add(name)
            logger.warning("%s and %s are both set in %s with different values: %s is used "
                           "(%s is the deprecated spelling; remove one)",
                           preferred_name(name), name, where, preferred_name(name), name)


def normalize(environ: MutableMapping[str, str], *, where: str = "the process environment",
              quiet: bool = False) -> Fold:
    """Make *environ* canonical in place: every hub variable under its ``JARVIS_`` name,
    its ``NERVA_`` spelling folded in and removed. Idempotent — a second call finds
    nothing to do. A refused pair is left exactly as found. Never raises."""
    pairs = {key: environ[key] for key in list(environ)
             if isinstance(key, str) and key.startswith(PREFERRED_PREFIX) and other_spelling(key)}
    if not pairs:
        return Fold({}, {}, (), (), ())
    for key in list(pairs):
        name = canonical(key)
        if name in environ:
            pairs[name] = environ[name]
    folded = fold(pairs)
    for name in folded.spelling:
        environ[name] = folded.values[name]
        environ.pop(preferred_name(name), None)
    _record(environ, folded.spelling)
    if not quiet:
        _warn_overridden(folded.overridden, where)
    return folded


def normalize_process_env() -> Fold:
    """``normalize(os.environ)`` — the process-start step (see the module docstring)."""
    return normalize(os.environ)


def normalized(environ: Mapping[str, str]) -> dict[str, str]:
    """A canonical copy of *environ*, for code that predicts what the hub would read from
    an environment it was handed (the doctor, ``env_provenance.derive``). Silent."""
    copy = dict(environ)
    normalize(copy, quiet=True)
    return copy


def conflicts(environ: Mapping[str, str] | None = None) -> list[str]:
    """The hub variables set under both spellings with different values that stop a boot
    (``JARVIS_`` names, sorted). Read from *environ* alone."""
    environ = os.environ if environ is None else environ
    found = set()
    for key in list(environ):
        if not (isinstance(key, str) and key.startswith(PREFERRED_PREFIX)):
            continue
        name = other_spelling(key)
        if (name is not None and name in environ and _differ(environ[key], environ[name])
                and refuses_on_conflict(name)):
            found.add(name)
    return sorted(found)


def conflict_message(names, where: str) -> str:
    """The refusal: the variables and the remedy, never a value."""
    pairs = ", ".join(f"{preferred_name(name)} / {name}" for name in names)
    return (f"Refusing to start: {pairs} — set under both spellings in {where}, with different values.\n"
            "NERVA_<X> and JARVIS_<X> are one variable (NERVA_ is the preferred spelling, JARVIS_ the "
            "deprecated one). Which value was meant cannot be guessed for a setting that decides the "
            "box's protection, its credentials or where its data lives — keep one of the two lines.")


def refuse_conflicts(environ: Mapping[str, str] | None = None, *,
                     where: str = "the process environment") -> None:
    """The boot guard: stop when a hub variable is set twice, differently (and is not an
    ordinary knob). Names the variable, never a value."""
    names = conflicts(environ)
    if names:
        raise SystemExit(conflict_message(names, where))


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
    "DEPRECATED_PREFIX", "Fold", "MARKER", "PREFERRED_PREFIX", "canonical", "conflict_message", "conflicts",
    "fold", "normalize", "normalize_process_env", "normalized", "preferred_name", "preferred_supplied",
    "refuse_conflicts", "refuses_on_conflict", "spelling_info", "supplied_name",
]
