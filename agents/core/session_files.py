"""One rule for "is this file in the data root a conversation session?".

The data root is shared: conversation transcripts (``<sid>.json`` snapshot +
``<sid>.jsonl`` append-log) sit beside knowledge-graph state, decay state, the
autonomy journal and other runtime JSON. Three call sites needed to tell them
apart and had drifted into two partial copies of the rule —
``retention._NON_SESSION_JSONL`` and ``data_purge._NON_SESSION_JSONL`` (jsonl
denylist only), while ``memory.persistence.list_sessions`` had none at all and
treated *every* ``*.json`` in the root as a session. That is how ``entities.json``
— rewritten on any turn mentioning a proper noun, therefore usually the newest
``*.json`` — became "the most recent session" and broke restore on a default
install.

The rule, in one place:

* a stem on :data:`NON_SESSION_STEMS` is never a session;
* a stem that is not a valid session id is never a session;
* a payload is only a session snapshot if it declares ``session_id`` + ``turns``.

Content confirmation matters more than any denylist: it is the only check that
also holds for a data file nobody has thought of yet.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.core.validation import is_valid_session_id

# Known non-session files that live in the data root. The ``*.jsonl`` names come
# from the retention/purge denylists; the ``*.json`` names are the memory-state
# files ``data_purge.PURGE_MEMORY_FILES`` removes by exact name (kept as literals
# here so this module stays import-cycle-free and usable from either side).
NON_SESSION_STEMS: frozenset[str] = frozenset({
    # append-logs that are not transcripts
    "autonomy_journal",
    "problems",
    # memory/runtime state written into the same root
    "entities",
    "bitemporal_kg",
    "decay",
    "config",
    "settings",
})


def is_session_stem(stem: str) -> bool:
    """True when *stem* could name a conversation session (name check only)."""
    return stem not in NON_SESSION_STEMS and is_valid_session_id(stem)


def looks_like_session_snapshot(path: Path) -> bool:
    """True when *path* is a ``<sid>.json`` snapshot written by ``save_memory``.

    Confirms the payload shape rather than trusting the filename. Unreadable or
    malformed files are not sessions — restoring from one would fail anyway.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    return (
        isinstance(data, dict)
        and bool(data.get("session_id"))
        and isinstance(data.get("turns"), list)
    )
