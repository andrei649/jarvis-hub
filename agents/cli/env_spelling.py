"""RB-2 — the ``nerva`` command's entry: one variable, two spellings, never a guess.

``NERVA_<X>`` is the preferred spelling of every ``JARVIS_<X>`` variable (``JARVIS_<X>``
is deprecated and still honoured). Importing the ``agents`` package has already folded
this shell's environment onto the ``JARVIS_`` names the command tree reads
(``agents.core.env_alias``), so ``NERVA_ADMIN_TOKEN``, ``NERVA_HOME`` and the rest simply
work. What is left for the entry point is the one case the fold will not decide: a
credential, a posture flag or a data root set under both spellings with different
values. The hub refuses to start on that, by name; the command refuses too, rather than
send one of two tokens or open one of two data roots. Only the read-only diagnostics
(``nerva doctor``, ``completion``, ``logs``, ``config path``, ``config env-path``) are
never refused: they write nothing and send nothing, print the conflict as a warning
and run (``doctor``'s ``config_sources`` is red). Every verb that writes a setting,
deletes, uploads or talks to a hub with a token refuses, naming the variable.

Both ways in (``python scripts/nerva.py`` and ``python -m agents.cli``) call ``main``
here, which hands everything else to ``agents.cli.nerva.main`` unchanged.
"""

from __future__ import annotations

import os
import sys

#: The read-only diagnostics: they look at the configuration, write nothing and send
#: nothing, so they are never refused — they report the conflict and run. ``logs`` reads
#: the hub's log file on this machine. Of ``config`` only the two verbs that print where
#: things are; ``config set`` and the rest write, and refuse like everything else.
READ_ONLY_VERBS = frozenset({"doctor", "completion", "logs"})
READ_ONLY_CONFIG_VERBS = frozenset({"path", "env-path"})


def _read_only(raw: list[str], at: int) -> bool:
    verb = raw[at] if at < len(raw) else ""
    if verb == "config":
        rest = [word for word in raw[at + 1:] if not word.startswith("-")]
        return bool(rest) and rest[0] in READ_ONLY_CONFIG_VERBS
    return verb in READ_ONLY_VERBS


def main(argv: list[str] | None = None) -> int:
    from agents.core import env_alias

    from . import nerva

    raw = list(sys.argv[1:] if argv is None else argv)
    disagreeing = env_alias.conflicts(os.environ)
    if disagreeing:
        at = nerva._verb_index(raw)
        message = env_alias.conflict_message(disagreeing, "this shell's environment")
        if not _read_only(raw, at):
            sys.stderr.write(message + "\n")
            return nerva.EXIT_USAGE
        # a verb that only looks at the configuration: say it, and run
        sys.stderr.write("warning: the hub will not start on this configuration.\n" + message + "\n")
    return nerva.main(raw)
