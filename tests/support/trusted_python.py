"""A Python interpreter that the hook validator itself accepts as a hook program.

``sys.executable`` is not always one: GitHub's ``ubuntu-latest`` runner installs Python
under ``/opt/hostedtoolcache``, which every user can write, and the G17 hook validator
(``agents.core.hooks.store.inspect_argv`` through ``local_providers.trusted_program``)
rightly refuses a program there. Tests that need a hook to run Python pick the first
candidate the validator's own check accepts and skip, with the reason, when none does.
"""

from __future__ import annotations

import functools
import os
import shutil
import sys
from pathlib import Path

#: Why a test is skipped when no interpreter on this host passes the validator.
NO_TRUSTED_PYTHON = ("no Python interpreter on this host passes the hook validator's ownership "
                     "checks (the running one sits under a directory every user can write)")


def _candidates() -> list[str]:
    raw = [sys.executable, os.path.realpath(sys.executable) if sys.executable else "",
           shutil.which("python3") or "", "/usr/bin/python3", "/usr/local/bin/python3"]
    seen: list[str] = []
    for item in raw:
        if item and os.path.isabs(item) and item not in seen:
            seen.append(item)
    return seen


def _accepted(candidate: str) -> bool:
    """Whether the hook validator takes *candidate* as an interpreter program (argv[0]) —
    asked of the validator itself, with only the script slot left empty."""
    from agents.core.hooks import store

    problems, _ = store.inspect_argv([candidate])
    # An accepted interpreter is refused only because it names no script after it.
    return bool(problems) and all(p.startswith("argv[1]:") for p in problems)


@functools.lru_cache(maxsize=1)
def trusted_python() -> str | None:
    """The first candidate interpreter the hook validator accepts, or None."""
    for candidate in _candidates():
        if _accepted(candidate):
            return candidate
    return None


def trusted_dir(path: Path) -> Path:
    """Create *path* (and make it and its scripts' modes explicit) so the validator's
    "not writable by everyone, nor its directory" rule holds whatever the umask."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o755)
    return path
