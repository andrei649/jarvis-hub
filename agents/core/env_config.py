"""
env_config.py — O26-P2.1 (AUD-14): ONE home for reading environment variables.

Before this module the tree had 163 env-read sites with EIGHT divergent
boolean conventions — ``.lower() in ("1","true","yes")`` (no "on"),
``("1","true","yes","on")``, case-sensitive ``("1","true","True")`` where
"TRUE" silently meant off, negated-falsy ``not in ("0","false","False")``
where "off" silently meant on, exact ``== "1"``, inverted disable-flags,
presence checks, and one helper (`_env_int`) written twice. The same var
could parse differently in two files (JARVIS_WORKFLOW_PERSIST=0 *enabled*
the coordinator drain while the engine read it as off).

The rules here:

- **Leaf module.** Standard library only (``os``). No imports from
  ``agents.core`` — anything (web.py, orchestrator, kernel, security,
  routers) may import this at module top without a cycle. The module is
  stateless, so the dual import identity (``core.env_config`` and
  ``agents.core.env_config`` are distinct module objects) is harmless.
- **Read at call time, never cache.** ~210 ``monkeypatch.setenv`` sites in
  the test suite assert that flag functions re-read the environment on every
  call. Env reads are cheap; correctness beats micro-optimization.
- **Never raise, never log values.** Getters degrade to their default on
  garbage input; many vars are credentials, so nothing here prints, logs,
  or enumerates values.
- **No side effects.** This module must NOT load ``.env`` — dotenv loads
  late (plugin build, inside the app lifespan, ``override=False``) and
  moving it earlier would silently activate ``.env`` keys for import-time
  posture reads (DEV_MODE, admin tokens). That is a posture change, not a
  refactor.
- **Unknown spellings resolve to the flag's DEFAULT, in both directions.**
  Historically, default-off opt-ins parsed with truthy-membership (junk →
  off) while default-on strict flags parsed with falsy-membership (junk →
  on). Both meant the same thing: *unrecognized input falls back to the
  declared default*. ``truthy(value, default)`` says it once, so a typo in
  JARVIS_ALLOW_INSECURE_BIND can never open the bind, and a typo in
  JARVIS_STRICT_EGRESS can never relax egress.

What does NOT belong here: the settings-DB plane (``settings_db.get_value``
is live-updatable /admin state with its own precedence at each call site),
composition/override logic (JARVIS_HARDENED forcing strict egress or
blocking mutating MCP stays with its owners), and the BUG-14 LOCAL_ONLY
floor (``hybrid_router.LOCAL_ONLY_AGENTS`` stays a code-enforced constant
that no env var — through this module or otherwise — can weaken).
"""

from __future__ import annotations

import json
import os

TRUTHY_SPELLINGS = frozenset({"1", "true", "yes", "on"})
FALSY_SPELLINGS = frozenset({"0", "false", "no", "off", "disable", "disabled"})


def truthy(value: object, default: bool = False) -> bool:
    """THE boolean parse: case-insensitive spellings, unknown → *default*.

    ``truthy`` on 1/true/yes/on; falsy on 0/false/no/off/disable/disabled;
    ``None``, empty/whitespace, and unrecognized strings resolve to
    *default* so a mis-spelled value can never flip a flag away from its
    declared posture. Non-strings are stringified first (settings values
    arrive as bool/int sometimes) — ``True``/``1`` stringify into the
    truthy set, ``False``/``0`` into the falsy set.
    """
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    if text in TRUTHY_SPELLINGS:
        return True
    if text in FALSY_SPELLINGS:
        return False
    return default


def env_flag(name: str, default: bool = False) -> bool:
    """Boolean env flag with an explicit default direction.

    ``env_flag("JARVIS_HARDENED")`` — opt-in, off unless explicitly on.
    ``env_flag("JARVIS_LLM_WARMUP", True)`` — default-on, off only when
    explicitly disabled. Unset, empty, or unrecognized → *default*.
    """
    return truthy(os.environ.get(name), default)


def env_str(name: str, default: str = "") -> str:
    """Raw string env read (no strip — callers that trim, trim themselves)."""
    value = os.environ.get(name)
    return default if value is None else value


def env_list(name: str, default: list[str] | None = None, sep: str = ",") -> list[str]:
    """Best-effort separated string list: trims entries and skips blanks."""
    fallback = list(default or [])
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    return [entry for entry in (part.strip() for part in raw.split(sep)) if entry]


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    """Best-effort int: unset, blank, or non-numeric → *default* (never raises).

    With *minimum*, an out-of-range value also falls back to *default*
    (e.g. a negative VRAM budget) — fall back, not clamp: a nonsense value
    means the operator's intent is unknown, so the shipped default wins.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def env_float(name: str, default: float, minimum: float | None = None) -> float:
    """Best-effort float: unset, blank, non-numeric, or out-of-range → *default*."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def env_json_object(name: str, default: dict | None = None) -> dict:
    """Best-effort JSON object: unset, invalid, or non-object → *default*.

    This is for structured env knobs such as provider config maps. It never
    raises and returns a fresh dict so callers cannot mutate a shared fallback.
    """
    fallback = dict(default or {})
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
    except ValueError:
        return fallback
    if not isinstance(value, dict):
        return fallback
    return dict(value)


def env_int_map(name: str, default: dict[str, int] | None = None) -> dict[str, int]:
    """Best-effort ``key:int`` map: bad entries are skipped, never raised.

    Format is a comma-separated list such as ``"whatsapp:10,teams:30"``.
    Whitespace is ignored around keys and values; blank keys, missing separators,
    and non-integer values are omitted. A fresh dict is returned every time.
    """
    fallback = dict(default or {})
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    out: dict[str, int] = {}
    for pair in raw.split(","):
        key, sep, value = pair.strip().partition(":")
        key = key.strip()
        if not sep or not key:
            continue
        try:
            out[key] = int(value)
        except ValueError:
            continue
    return out
