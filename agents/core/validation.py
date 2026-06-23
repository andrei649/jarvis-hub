"""Shared input validators (AUD-5).

Small, dependency-free guards for values that cross a trust boundary into a
filesystem path or other sink. Kept in one place so every call site validates
identically.
"""

from __future__ import annotations

import re

# A session id becomes a filename via ``MEMORY_DIR / f"{session_id}.json"`` in
# memory/persistence.py. Restrict it to an inert identifier alphabet so it can
# never carry a path separator, ``..`` traversal, NUL, or whitespace out of the
# memory dir (AUD-5). 128 chars is well above any id the system generates.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_SESSION_ID_LEN = 128


def is_valid_session_id(session_id: object) -> bool:
    """Return ``True`` iff *session_id* is a safe, filesystem-inert identifier.

    Accepts only ``[A-Za-z0-9_-]`` (1..128 chars). Rejects the empty string,
    path separators, ``..``, NUL and whitespace — so a hostile id can never
    escape the memory directory.
    """
    return (
        isinstance(session_id, str)
        and 0 < len(session_id) <= _MAX_SESSION_ID_LEN
        and _SESSION_ID_RE.match(session_id) is not None
    )
