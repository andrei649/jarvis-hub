"""Conservative, whole-value checks for obvious chat credential placeholders."""

from __future__ import annotations

import re

_TEMPLATE_ENV = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}\Z")
_YOUR_TOKEN = re.compile(r"your_[a-z0-9_]*token[a-z0-9_]*\Z", re.IGNORECASE)
_ANGLE_TOKEN = re.compile(r"<[a-z0-9_ -]*token[a-z0-9_ -]*>\Z", re.IGNORECASE)
_LITERALS = frozenset({"replace_me", "changeme", "token_here"})


def credential_is_configured(value: object) -> bool:
    """Reject only blank and unmistakably templated whole credential values.

    Accepted strings are never normalized or returned. Provider token formats and
    lengths are deliberately outside this local startup check.
    """
    if type(value) is not str:
        return False
    text = value.strip()
    return bool(text) and not (
        text.casefold() in _LITERALS
        or _TEMPLATE_ENV.fullmatch(text)
        or _YOUR_TOKEN.fullmatch(text)
        or _ANGLE_TOKEN.fullmatch(text)
    )
