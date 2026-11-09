"""The approval dial: ``autonomy.mode`` (auto | ask | off), read and written in one place.

H484 (Hermes ``approvals.mode: manual | smart | off``). Nerva's dial has three positions
and every one of them only *adds* asking:

* ``auto`` — the balanced default: each action is decided by its risk tier. Reads and
  reversible actions run; a payment inside the owner's per-action and daily money caps
  runs too; any other irreversible action asks.
* ``ask``  — anything with a side effect waits for the owner.
* ``off``  — the policy approves nothing on its own: every new action waits for the
  owner, work the policy approved earlier goes back to waiting instead of running, and
  the proactive loop is paused. ``off`` is a floor: no per-agent override loosens it.

There is deliberately no position that silences approvals (Hermes' ``off``; see H066):
the dial is settings, and every action it governs still crosses ``kernel.authorize`` and
the permanent owner-approval floor.

A stored value the dial does not know is never run as ``auto``: it warns and falls back
to ``ask``. A YAML 1.1 boolean spelling (a bare ``off`` read as ``False``) is the dial's
``off``.

Every surface that changes the mode — the admin routes, ``/approvals`` in chat, ``nerva
approvals mode`` — writes through :func:`set_global_mode` / :func:`set_agent_mode`, which
persist the setting, apply it to the live policy, refresh the runtime settings the
coordinator reads, check what the coordinator will read, and record the change (or the
failed attempt) in the audit log. :func:`sync_policy` is the one place the stored values
are copied onto the live policy (at boot and on every coordinator tick).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("jarvis.autonomy.mode")

MODES: tuple[str, ...] = ("auto", "ask", "off")
DEFAULT_MODE = "auto"
#: What an unknown stored value is read as (Hermes falls back to ``manual``).
FALLBACK_MODE = "ask"
#: Hermes' words for the two positions the dials share, read the same way whether a
#: person types them or a store holds them. Hermes' ``off`` has no counterpart: here
#: ``off`` is the strictest position.
ALIASES: dict[str, str] = {"manual": "ask", "smart": "auto"}
USAGE = "auto|ask|off"
#: How much each position asks; the stricter of two modes is the higher one.
_RANK = {"auto": 0, "ask": 1, "off": 2}

_MEANING = {
    "auto": ("each action is decided by its risk tier: reads and reversible actions run, a payment "
             "inside your per-action and daily money caps runs, any other irreversible action asks"),
    "ask": "anything with a side effect waits for your approval",
    "off": ("nothing the policy would approve on its own runs: every action waits for your approval, "
            "and the proactive loop is paused"),
}
_warned: set[str] = set()
#: One writer at a time reads the old value, persists, applies and audits (two writers
#: must never leave the store, the live policy and the last audit row disagreeing).
_write_lock = threading.RLock()


class ModeNotSaved(RuntimeError):
    """The settings store did not take the write; nothing was applied."""


def normalize_mode(value: Any) -> tuple[str, bool]:
    """``(mode, known)`` for a stored value. Unset (``None`` / ``""``) is the default;
    ``False`` (YAML 1.1 ``off``/``no``) is ``off``; Hermes' ``manual``/``smart`` are
    ``ask``/``auto``; anything else — blank text included — is ``ask``, not known."""
    if value is None or value == "":
        return DEFAULT_MODE, True
    if value is False:
        return "off", True
    if isinstance(value, str):
        word = value.strip().lower()
        word = ALIASES.get(word, word)
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


def is_unset(value: Any) -> bool:
    """A per-agent override that is no override: missing, empty or blank text."""
    return value is None or (isinstance(value, str) and not value.strip())


def parse_requested(word: Any) -> str | None:
    """The position a typed *word* asks for (Hermes' ``manual``/``smart`` included), or None."""
    if not isinstance(word, str) or not word.strip():
        return None
    mode, known = normalize_mode(word)
    return mode if known else None


def stricter(a: str, b: str) -> str:
    return a if _RANK.get(a, 1) >= _RANK.get(b, 1) else b


def resolve(overall: Any, override: Any) -> tuple[str, str]:
    """``(effective mode, source)`` for an agent: its own override, else the global mode —
    except that a global ``off`` is a floor no override loosens. Source is ``"agent"``
    only when the override is what decides."""
    overall = read_mode(overall)
    if overall == "off" or is_unset(override):
        return overall, "global"
    return read_mode(override, where="autonomy.agent_modes"), "agent"


def meaning(mode: str) -> str:
    return _MEANING.get(mode, "")


def _policy(orch: Any) -> Any:
    return getattr(getattr(orch, "autonomy", None), "policy", None)


def _setting(orch: Any, key: str, default: Any) -> Any:
    get_setting = getattr(orch, "get_setting", None)
    return get_setting(key, default) if callable(get_setting) else default


def global_mode(orch: Any) -> str:
    """The live global mode: the policy's, else the stored setting."""
    policy = _policy(orch)
    value = getattr(policy, "mode", None)
    if value is None or value == "":
        value = _setting(orch, "autonomy.mode", DEFAULT_MODE)
    return read_mode(value)


def agent_modes(orch: Any) -> dict[str, str]:
    """The per-agent overrides as stored, each read through :func:`read_mode`. What an
    override *does* is :func:`resolve` — under a global ``off`` it does nothing."""
    policy = _policy(orch)
    raw = getattr(policy, "agent_modes", None)
    if raw is None:
        raw = _setting(orch, "autonomy.agent_modes", {})
    if not isinstance(raw, dict):
        return {}
    return {str(agent): read_mode(value, where=f"autonomy.agent_modes[{str(agent)[:32]}]")
            for agent, value in raw.items() if not is_unset(value)}


def looser_overrides(orch: Any) -> dict[str, str]:
    """The agents whose override lets them ask *less* than the global mode, with that
    override. Empty under a global ``off`` (the floor) and under ``auto`` (nothing is looser)."""
    overall = global_mode(orch)
    if overall == "off":
        return {}
    return {agent: mode for agent, mode in agent_modes(orch).items()
            if _RANK[mode] < _RANK[overall]}


def describe(orch: Any, agent: str | None = None) -> dict[str, str]:
    """The mode that applies to *agent* right now, whether it is the agent's own override
    or the global dial, and the global dial."""
    overall = global_mode(orch)
    policy = _policy(orch)
    raw = getattr(policy, "agent_modes", None)
    if raw is None:
        raw = _setting(orch, "autonomy.agent_modes", {})
    override = raw.get(agent) if agent and isinstance(raw, dict) else None
    effective, source = resolve(overall, override)
    return {"effective": effective, "source": source, "global": overall}


def stored_values(read: Any) -> tuple[str, dict]:
    """``(mode, agent_modes)`` from a ``read(key, default)`` settings reader, normalised:
    what a policy is built with at boot and resynced to on every tick."""
    raw = read("autonomy.agent_modes", {})
    overrides = {str(agent): value for agent, value in raw.items()
                 if not is_unset(value)} if isinstance(raw, dict) else {}
    return read_mode(read("autonomy.mode", DEFAULT_MODE)), overrides


def sync_policy(orch: Any) -> str:
    """Copy the stored mode and per-agent overrides onto the live policy; returns the
    global mode now in force. Runs at boot and at the top of every coordinator tick —
    before the e-stop check, so a stored ``off`` governs while the hub is paused too.

    A write whose settings refresh failed leaves a *pending* value on the policy
    (:func:`set_global_mode`); until the settings the coordinator reads agree with it,
    the stricter of the two stays in force, so a stale cache never loosens the policy."""
    policy = _policy(orch)
    mode, overrides = stored_values(lambda key, default: _setting(orch, key, default))
    if policy is None:
        return mode
    pending = getattr(policy, "_pending_mode", None)
    if pending is not None:
        wanted, stale = pending
        if mode == stale and mode != wanted:
            mode = stricter(mode, wanted)       # the settings still read the old value
        else:
            policy._pending_mode = None         # they caught up, or were changed again
    if policy.mode != mode:
        policy.mode = mode
    policy.agent_modes = overrides
    return mode


def _put_category(category: str, values: dict) -> tuple[int, list[str]]:
    from ..settings_db import put_category

    return put_category(category, values)


def _refresh(orch: Any, key: str, value: Any, *, correct: bool = True) -> bool:
    """Make ``orch.get_setting(key)`` answer *value* (what the coordinator will read on its
    next tick): reload the runtime settings, and — with *correct* — if the reload did not
    bring the value in, correct the cached entry. True when the readback agrees. The
    per-agent overrides are never corrected in place: safe mode serves them absent, and
    a cache write must not put back what it stripped."""
    reload = getattr(orch, "load_runtime_settings", None)
    if callable(reload):
        try:
            reload()
        except Exception:  # noqa: BLE001 — judged by the readback below
            logger.warning("%s: runtime settings reload failed", key, exc_info=True)
    if _setting(orch, key, None) == value:
        return True
    cache = getattr(orch, "_runtime_settings", None)
    if correct and isinstance(cache, dict):
        cache[key] = value
    return _setting(orch, key, None) == value


def set_global_mode(orch: Any, requested: str, *, actor: str, surface: str) -> dict:
    """Persist, apply and audit the global mode. *requested* must be one of :data:`MODES`
    (``ValueError`` otherwise); the caller has already established the owner. Blocking.

    Returns ``{"mode", "was", "changed", "audited", "effective"}``. ``effective`` is False
    when the settings the coordinator reads do not hold the new value after the write:
    the live policy then keeps the *stricter* of the old and the new mode until they do
    (a tightening is in force at once and cannot revert; a loosening waits). A store that
    refuses the write raises :class:`ModeNotSaved` with nothing applied, and the failed
    attempt is audited. The write stands when the audit row cannot be saved (a
    tightening must never wait on the log); ``audited`` says so."""
    mode = requested.strip().lower() if isinstance(requested, str) else ""
    if mode not in MODES:
        raise ValueError(f"mode must be {USAGE}")
    with _write_lock:
        was = global_mode(orch)
        who = f"(via {surface}, by {actor})"
        try:
            _updated, skipped = _put_category("autonomy", {"mode": mode})
        except Exception as exc:
            _audit(orch, f"settings.autonomy.mode: {was} → {mode} NOT SAVED, still {was} {who}",
                   "settings_update_failed")
            raise ModeNotSaved("the settings store refused autonomy.mode") from exc
        if "mode" in (skipped or []):
            _audit(orch, f"settings.autonomy.mode: {was} → {mode} NOT SAVED, still {was} {who}",
                   "settings_update_failed")
            raise ModeNotSaved("the settings store did not take autonomy.mode")
        effective = _refresh(orch, "autonomy.mode", mode)
        policy = _policy(orch)
        if policy is not None:
            if effective:
                policy._pending_mode = None
                policy.mode = mode
            else:
                # The coordinator would copy a stale value back: hold the stricter one.
                stale = read_mode(_setting(orch, "autonomy.mode", DEFAULT_MODE))
                policy._pending_mode = (mode, stale)
                policy.mode = stricter(stricter(was, stale), mode)
        note = "" if effective else " — saved, but the running settings still read the old value"
        audited = _audit(orch, f"settings.autonomy.mode: {was} → {mode}{note} {who}", "settings_update")
        return {"mode": mode, "was": was, "changed": was != mode, "audited": audited,
                "effective": effective, "live": global_mode(orch)}


def set_agent_mode(orch: Any, agent: str, requested: str, *, actor: str, surface: str) -> dict:
    """Persist, apply and audit one agent's override; ``default`` clears it. Same contract
    as :func:`set_global_mode`. Returns ``{"agent", "mode", "was", "agents", "audited",
    "effective"}`` (``mode`` None when cleared)."""
    agent = agent.strip() if isinstance(agent, str) else ""
    mode = requested.strip().lower() if isinstance(requested, str) else ""
    if not agent or mode not in (*MODES, "default"):
        raise ValueError(f"mode must be {USAGE}|default")
    with _write_lock:
        raw = _setting(orch, "autonomy.agent_modes", {})
        agents = {str(k): v for k, v in raw.items() if not is_unset(v)} if isinstance(raw, dict) else {}
        was = agents.get(agent)
        if mode == "default":
            agents.pop(agent, None)
        else:
            agents[agent] = mode
        shown = f"settings.autonomy.agent_modes[{agent[:64]}]: {was or 'default'} → {mode}"
        who = f"(via {surface}, by {actor})"
        try:
            _updated, skipped = _put_category("autonomy", {"agent_modes": agents})
        except Exception as exc:
            _audit(orch, f"{shown} NOT SAVED {who}", "settings_update_failed")
            raise ModeNotSaved("the settings store refused autonomy.agent_modes") from exc
        if "agent_modes" in (skipped or []):
            _audit(orch, f"{shown} NOT SAVED {who}", "settings_update_failed")
            raise ModeNotSaved("the settings store did not take autonomy.agent_modes")
        effective = _refresh(orch, "autonomy.agent_modes", agents, correct=False)
        policy = _policy(orch)
        if policy is not None and effective:
            policy.agent_modes = dict(agents)
        audited = _audit(orch, f"{shown} {who}", "settings_update")
        return {"agent": agent, "mode": None if mode == "default" else mode, "was": was,
                "agents": agents, "audited": audited, "effective": effective}


def _audit(orch: Any, preview: str, action: str) -> bool:
    audit = getattr(orch, "audit", None)
    if audit is None:
        return False
    try:
        from ..security.types import SecurityEvent, SecurityEventType

        audit.log(SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE,
            timestamp=time.time(),
            content_preview=preview,
            action_taken=action,
        ))
        return True
    except Exception:  # noqa: BLE001 — reported to the caller as audited=False
        logger.warning("autonomy.mode: the change could not be recorded in the audit log", exc_info=True)
        return False


__all__ = [
    "ALIASES", "DEFAULT_MODE", "FALLBACK_MODE", "MODES", "USAGE", "ModeNotSaved",
    "agent_modes", "describe", "global_mode", "is_unset", "looser_overrides", "meaning",
    "normalize_mode", "parse_requested", "read_mode", "resolve", "set_agent_mode",
    "set_global_mode", "stored_values", "stricter", "sync_policy",
]
