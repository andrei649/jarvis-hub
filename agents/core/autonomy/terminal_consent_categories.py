"""Closed H487 category catalog for pinned Hermes terminal warnings.

Classification is evidence for a future consent producer, not approval. The
terminal hardline, taint, target and kernel gates remain independent.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping
from types import MappingProxyType

from . import hermes_command_detection as detector
from .consent_ledger import ConsentCategory

_PREFIX = "terminal.warning."
_SESSION_ONLY = frozenset(
    {
        detector._PARSER_LIMIT_DESCRIPTION,
        detector._MALFORMED_EXEC_DESCRIPTION,
    }
)
_EXTRA_DESCRIPTIONS = frozenset(
    {
        detector._PARSER_LIMIT_DESCRIPTION,
        detector._MALFORMED_EXEC_DESCRIPTION,
        detector._GATEWAY_LIFECYCLE_SPLICE_DESCRIPTION,
        "script execution via -e/-c flag",
        "script execution via heredoc",
        "shell command via -c/-lc flag",
    }
)


def _category_key(description: str) -> str:
    slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", description.lower())).strip("_")
    return _PREFIX + slug


_DESCRIPTIONS = (
    frozenset(description for _, description in detector.DANGEROUS_PATTERNS)
    | _EXTRA_DESCRIPTIONS
    | frozenset(
        f"arbitrary program execution via {tool} {flag}"
        for tool, flags in detector._READ_TOOL_EXEC_FLAGS.items()
        for flag in flags
    )
)
_CATEGORY_BY_DESCRIPTION = {
    description: ConsentCategory(_category_key(description), description not in _SESSION_ONLY)
    for description in _DESCRIPTIONS
}
_UNCLASSIFIED = ConsentCategory("terminal.warning.unclassified", permanent=False)
_CATALOG = tuple(
    sorted((*_CATEGORY_BY_DESCRIPTION.values(), _UNCLASSIFIED), key=lambda category: category.key)
)
if len(_CATALOG) != len({category.key for category in _CATALOG}):
    raise RuntimeError("pinned Hermes warning descriptions have colliding category keys")
if any(len(category.key) > 128 for category in _CATALOG):
    raise RuntimeError("pinned Hermes warning category exceeds ledger key limit")

_DESCRIPTION_BY_KEY: Mapping[str, str] = MappingProxyType(
    {category.key: description for description, category in _CATEGORY_BY_DESCRIPTION.items()}
    | {_UNCLASSIFIED.key: "unknown dangerous command finding"}
)


def terminal_consent_catalog() -> tuple[ConsentCategory, ...]:
    """Return all reviewed warnings; unknown findings have a session-only key."""
    return _CATALOG


def terminal_consent_descriptions() -> Mapping[str, str]:
    """Expose the pinned warning descriptions for future owner-facing review."""
    return _DESCRIPTION_BY_KEY


def terminal_consent_categories(
    command: str,
    *,
    resolved_user_home: str | None = None,
    resolved_hermes_home: str | None = None,
    trusted_gateway_lifecycle: Callable[[str], bool] | None = None,
) -> tuple[ConsentCategory, ...] | None:
    """Return the first pinned warning category, empty for benign, None if malformed.

    Home paths and lifecycle detection are supplied explicitly by a trusted
    caller. Without a lifecycle predicate, that Hermes-specific fallback is
    unavailable. A returned category never grants or executes anything.
    """
    if not isinstance(command, str) or not command.strip():
        return None
    if any(
        path is not None and (not isinstance(path, str) or "\x00" in path)
        for path in (resolved_user_home, resolved_hermes_home)
    ) or (trusted_gateway_lifecycle is not None and not callable(trusted_gateway_lifecycle)):
        return None
    try:
        if detector._command_parser_limit_exceeded(command):
            return (_CATEGORY_BY_DESCRIPTION[detector._PARSER_LIMIT_DESCRIPTION],)
        # shlex only checks malformed quoting; detector still owns risk and
        # priority. Do this before a benign verdict can become reusable consent.
        shlex.split(command, posix=True)
        with detector.classification_context(
            resolved_user_home=resolved_user_home,
            resolved_hermes_home=resolved_hermes_home,
            trusted_gateway_lifecycle=trusted_gateway_lifecycle,
        ):
            dangerous, description, _ = detector.detect_dangerous_command(command)
    except Exception:
        # A failed trusted predicate or parser can never become a benign
        # classification that a later consent consumer might reuse.
        return None
    if not dangerous:
        return ()
    if not isinstance(description, str):
        return (_UNCLASSIFIED,)
    return (_CATEGORY_BY_DESCRIPTION.get(description, _UNCLASSIFIED),)


__all__ = [
    "ConsentCategory",
    "terminal_consent_catalog",
    "terminal_consent_categories",
    "terminal_consent_descriptions",
]
