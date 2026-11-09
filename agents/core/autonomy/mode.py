"""The approval dial: ``autonomy.mode`` (auto | ask | off), read and written in one place.

H484 (Hermes ``approvals.mode: manual | smart | off``). Nerva's dial has three positions
and every one of them only *adds* asking:

* ``auto`` — the balanced default: each action is decided by its risk tier.
* ``ask``  — anything with a side effect waits for the owner.
* ``off``  — nothing runs without the owner, and the proactive loop is paused.

There is deliberately no position that silences approvals (Hermes' ``off``; see H066):
the dial is settings, and every action it governs still crosses ``kernel.authorize`` and
the permanent owner-approval floor.

A stored value the dial does not know is never run as ``auto``: it warns and falls back
to ``ask``. A YAML 1.1 boolean spelling (a bare ``off`` read as ``False``) is the dial's
``off``.

Every surface that changes the mode — the admin route, ``/approvals`` in chat, ``nerva
approvals mode`` — writes through :func:`set_global_mode`, which persists the setting,
applies it to the live policy, reloads the runtime settings the coordinator reads on its
next tick, and records the change in the audit log.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("jarvis.autonomy.mode")

MODES: tuple[str, ...] = ("auto", "ask", "off")
DEFAULT_MODE = "auto"
#: What an unknown stored value is read as (Hermes falls back to ``manual``).
FALLBACK_MODE = "ask"
#: Hermes' words for the two positions the dials share, accepted where a person types the
#: mode (chat, CLI). Hermes' ``off`` has no counterpart: here ``off`` is the strictest.
ALIASES: dict[str, str] = {"manual": "ask", "smart": "auto"}
USAGE = "auto|ask|off"

_MEANING = {
    "auto": "each action is decided by its risk tier; the irreversible tier always asks",
    "ask": "anything with a side effect waits for your approval",
    "off": "nothing runs without your approval, and the proactive loop is paused",
}
_warned: set[str] = set()


class ModeNotSaved(RuntimeError):
    """The settings store did not take the write; nothing was applied."""


def normalize_mode(value: Any) -> tuple[str, bool]:
    """``(mode, known)`` for a stored value. Unset is the default; ``False`` (YAML 1.1
    ``off``/``no``) is ``off``; anything else that is not a position is ``ask``, not known."""
    if value is None or value == "":
        return DEFAULT_MODE, True
    if value is False:
        return "off", True
    if isinstance(value, str):
        word = value.strip().lower()
        if not word:
            return DEFAULT_MODE, True
        if word in MODES:
            return word, True
    return FALLBACK_MODE, False


def read_mode(value: Any, *, where: str = "autonomy.mode") -> str:
    """The mode a stored *value* stands for, warning once per unknown value."""
    mode, known = normalize_mode(value)
    if not known:
        shown = repr(value)[:40]
        if shown not in _warned:
            _warned.add(shown)
            logger.warning("%s holds %s, which is not one of %s; reading it as %s",
                           where, shown, USAGE, FALLBACK_MODE)
    return mode


def parse_requested(word: Any) -> str | None:
    """The position a typed *word* asks for (Hermes' ``manual``/``smart`` included), or None."""
    if not isinstance(word, str):
        return None
    word = word.strip().lower()
    word = ALIASES.get(word, word)
    return word if word in MODES else None


def meaning(mode: str) -> str:
    return _MEANING.get(mode, "")


def _policy(orch: Any) -> Any:
    return getattr(getattr(orch, "autonomy", None), "policy", None)


def global_mode(orch: Any) -> str:
    """The live global mode: the policy's, else the stored setting."""
    policy = _policy(orch)
    value = getattr(policy, "mode", None)
    if value is None or value == "":
        get_setting = getattr(orch, "get_setting", None)
        value = get_setting("autonomy.mode", DEFAULT_MODE) if callable(get_setting) else None
    return read_mode(value)


def agent_modes(orch: Any) -> dict[str, str]:
    """The per-agent overrides, each read through :func:`read_mode`."""
    policy = _policy(orch)
    raw = getattr(policy, "agent_modes", None)
    if raw is None:
        get_setting = getattr(orch, "get_setting", None)
        raw = get_setting("autonomy.agent_modes", {}) if callable(get_setting) else {}
    if not isinstance(raw, dict):
        return {}
    return {str(agent): read_mode(value, where=f"autonomy.agent_modes[{str(agent)[:32]}]")
            for agent, value in raw.items() if value not in (None, "")}


def describe(orch: Any, agent: str | None = None) -> dict[str, str]:
    """What an approval card shows: the mode that applies to *agent* right now, whether
    it is the agent's own override or the global dial, and the global dial."""
    overall = global_mode(orch)
    override = agent_modes(orch).get(agent) if agent else None
    return {"effective": override or overall, "source": "agent" if override else "global",
            "global": overall}


def _put_category(category: str, values: dict) -> tuple[int, list[str]]:
    from ..settings_db import put_category

    return put_category(category, values)


def set_global_mode(orch: Any, requested: str, *, actor: str, surface: str) -> dict:
    """Persist, apply and audit the global mode. *requested* must be one of :data:`MODES`
    (``ValueError`` otherwise); the caller has already established the owner. Blocking.

    Returns ``{"mode", "was", "changed", "audited"}``. The write stands when the audit row
    cannot be saved (a tightening must never wait on the log); ``audited`` says so."""
    mode = requested.strip().lower() if isinstance(requested, str) else ""
    if mode not in MODES:
        raise ValueError(f"mode must be {USAGE}")
    was = global_mode(orch)
    _updated, skipped = _put_category("autonomy", {"mode": mode})
    if "mode" in (skipped or []):
        raise ModeNotSaved("the settings store did not take autonomy.mode")
    policy = _policy(orch)
    if policy is not None:
        policy.mode = mode
    reload = getattr(orch, "load_runtime_settings", None)
    if callable(reload):
        try:
            reload()    # the coordinator re-reads the setting each tick: no stale value
        except Exception:  # noqa: BLE001 — the write and the live policy stand
            logger.warning("autonomy.mode: runtime settings reload failed", exc_info=True)
    audited = _audit(orch, f"settings.autonomy.mode: {was} → {mode} (via {surface}, by {actor})")
    return {"mode": mode, "was": was, "changed": was != mode, "audited": audited}


def _audit(orch: Any, preview: str) -> bool:
    audit = getattr(orch, "audit", None)
    if audit is None:
        return False
    try:
        from ..security.types import SecurityEvent, SecurityEventType

        audit.log(SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE,
            timestamp=time.time(),
            content_preview=preview,
            action_taken="settings_update",
        ))
        return True
    except Exception:  # noqa: BLE001 — reported to the caller as audited=False
        logger.warning("autonomy.mode: the change could not be recorded in the audit log", exc_info=True)
        return False


__all__ = [
    "ALIASES", "DEFAULT_MODE", "FALLBACK_MODE", "MODES", "USAGE", "ModeNotSaved",
    "agent_modes", "describe", "global_mode", "meaning", "normalize_mode", "parse_requested",
    "read_mode", "set_global_mode",
]
