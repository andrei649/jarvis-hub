"""RB-2 — the ``nerva`` command's entry: one variable, two spellings, never a guess.

``NERVA_<X>`` is the preferred spelling of every ``JARVIS_<X>`` variable (``JARVIS_<X>``
is deprecated and still honoured). Importing the ``agents`` package has already folded
this shell's environment onto the ``JARVIS_`` names the command tree reads
(``agents.core.env_alias``), so ``NERVA_ADMIN_TOKEN``, ``NERVA_HOME`` and the rest simply
work. What is left for the entry point is the one case the fold will not decide: a
credential, a posture flag or a data root set under both spellings with different
values. The hub refuses to start on that, by name; the command refuses too, rather than
send one of two tokens or open one of two data roots. The verbs that diagnose or repair
a configuration (``REPAIR_VERBS``: ``nerva doctor``, ``nerva config …``, ``support``,
``logs``, ``uninstall``, ``completion``) are never refused: they print the conflict as a
warning and run (``doctor``'s ``config_sources`` is red).

Both ways in (``python scripts/nerva.py`` and ``python -m agents.cli``) call ``main``
here, which hands everything else to ``agents.cli.nerva.main`` unchanged.
"""

from __future__ import annotations

import os
import sys

#: The verbs that diagnose or repair a configuration (``nerva doctor``, ``nerva config
#: env-path`` …): they are never refused — they report the conflict and run.
REPAIR_VERBS = frozenset({"doctor", "config", "support", "logs", "uninstall", "completion"})


def main(argv: list[str] | None = None) -> int:
    from agents.core import env_alias

    from . import nerva

    raw = list(sys.argv[1:] if argv is None else argv)
    disagreeing = env_alias.conflicts(os.environ)
    if disagreeing:
        at = nerva._verb_index(raw)
        message = env_alias.conflict_message(disagreeing, "this shell's environment")
        if (raw[at] if at < len(raw) else "") not in REPAIR_VERBS:
            sys.stderr.write(message + "\n")
            return nerva.EXIT_USAGE
        # a verb whose job is to look at, or repair, a broken configuration: say it, and run
        sys.stderr.write("warning: the hub will not start on this configuration.\n" + message + "\n")
    return nerva.main(raw)
