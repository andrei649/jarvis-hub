"""Bounded, literal project-relative path selection for read-only diffs."""

from __future__ import annotations

import unicodedata

_MAX_PATHS = 8
_MAX_PATH_BYTES = 256
_MAX_TOTAL_BYTES = 1024
_FORBIDDEN = frozenset("\\*?[]:")


def validate_paths(paths: object) -> tuple[str, ...] | None:
    """Return unchanged literal paths, or None for an invalid selection.

    This performs no filesystem access or path normalization. An empty selection
    is valid; callers decide whether it means no rows or an omitted filter.
    """
    if type(paths) not in (tuple, list) or len(paths) > _MAX_PATHS:
        return None
    validated: list[str] = []
    seen: set[str] = set()
    total = 0
    for path in paths:
        if type(path) is not str or not path or path in seen:
            return None
        try:
            size = len(path.encode("utf-8"))
        except UnicodeEncodeError:
            return None
        total += size
        if size > _MAX_PATH_BYTES or total > _MAX_TOTAL_BYTES:
            return None
        if any(part in ("", ".", "..") for part in path.split("/")):
            return None
        if any(ch in _FORBIDDEN or unicodedata.category(ch)[0] == "C"
               or unicodedata.category(ch) in ("Zl", "Zp") for ch in path):
            return None
        seen.add(path)
        validated.append(path)
    return tuple(validated)
