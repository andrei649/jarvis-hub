"""template_vars.py — the variables a skill body may name, rendered as it reaches the model (H340).

Hermes substitutes ``${HERMES_SKILL_DIR}`` and ``${HERMES_SESSION_ID}`` into a skill body
at load time, plus the owner's ``skills.template_vars``, so a skill can say "run
``${HERMES_SKILL_DIR}/scripts/report.sh``" without knowing where it was installed.

Nerva renders the same variables, under its own names and Hermes' (an imported skill uses
the second), at the one point a body reaches the model: ``skill_view``. The rules:

* the fixed set is :data:`FIXED` — the skill's directory and the turn's session id;
* the owner's ``skills.template_vars`` add literal text only. A key is an identifier and
  cannot shadow a fixed name; a value is one printable line of at most
  :data:`MAX_VALUE` characters that does not point anywhere else (no ``$``, no
  ``env:`` or ``secret:``). A bad entry is dropped and its ``${...}`` stays literal;
* nothing reads the process environment, so a body cannot name its way to a secret;
* one pass: a value is never expanded again, and an unknown ``${...}`` stays as written.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("jarvis.skills.template_vars")

SETTING = "skills.template_vars"
MAX_VARS = 32
MAX_KEY = 64
MAX_VALUE = 256
SKILL_DIR_NAMES = ("NERVA_SKILL_DIR", "HERMES_SKILL_DIR")
SESSION_ID_NAMES = ("NERVA_SESSION_ID", "HERMES_SESSION_ID")
FIXED = frozenset(SKILL_DIR_NAMES + SESSION_ID_NAMES)

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_POINTERS = ("env:", "secret:")


def _plain_value(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > MAX_VALUE:
        return False
    if "$" in value or value.strip().lower().startswith(_POINTERS):
        return False
    return value.isprintable()


def clean_template_vars(raw: Any) -> dict[str, str]:
    """The owner's variables that may be rendered; every other entry is dropped (logged)."""
    if not isinstance(raw, Mapping):
        if raw not in (None, "", {}):
            logger.warning("%s is not a map of names to text; ignored", SETTING)
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if len(out) >= MAX_VARS:
            logger.warning("%s holds more than %d variables; the rest are ignored", SETTING, MAX_VARS)
            break
        if (not isinstance(key, str) or len(key) > MAX_KEY or not _KEY.fullmatch(key)
                or key in FIXED or not _plain_value(value)):
            logger.warning("%s entry %r is not a plain literal variable; ignored", SETTING, str(key)[:MAX_KEY])
            continue
        out[key] = value
    return out


def render_skill_body(body: str, *, skill_dir: str, session_id: str,
                      template_vars: Any = None) -> str:
    """``body`` with every known ``${NAME}`` replaced, in one pass."""
    values = clean_template_vars(template_vars)
    values.update(dict.fromkeys(SKILL_DIR_NAMES, str(skill_dir)))
    values.update(dict.fromkeys(SESSION_ID_NAMES, str(session_id or "")))

    def _sub(match: re.Match) -> str:
        return values.get(match.group(1), match.group(0))

    return _TOKEN.sub(_sub, body)


__all__ = ["FIXED", "MAX_VALUE", "MAX_VARS", "SETTING", "clean_template_vars", "render_skill_body"]
