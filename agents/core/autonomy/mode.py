"""The approval dial: ``autonomy.mode`` (auto | ask | off), read and written in one place.

H484 (Hermes ``approvals.mode: manual | smart | off``). Nerva's dial has three positions
and every one of them only *adds* asking:

* ``auto`` — the balanced default: each action is decided by its risk tier. Reads and
  reversible actions run; a payment inside the owner's per-action and daily money caps
  runs too; any other irreversible action asks.
* ``ask``  — anything with a side effect waits for the owner.
* ``off``  — nothing a machine approved runs: every new action waits for the owner,
  work approved earlier by anything but a human (the policy, the smart reviewer, a
  standing consent, an unknown decider) goes back to waiting instead of running, and the
  proactive loop is paused. ``off`` is a floor: no per-agent override loosens it.

There is deliberately no position that silences approvals (Hermes' ``off``; see H066):
the dial is settings, and every action it governs still crosses ``kernel.authorize`` and
the permanent owner-approval floor.

A stored value the dial does not know is never run as ``auto``: it warns and falls back
to ``ask``. A YAML 1.1 boolean spelling (a bare ``off`` read as ``False``) is the dial's
``off``.

The settings store is the truth. Every writer — :func:`set_global_mode` and
:func:`set_agent_mode` (the admin routes, ``/approvals`` in chat, ``nerva approvals
mode``) and :func:`locked_settings_write` (the generic settings PUT, import, reset,
reseed, undo) — holds one lock around persist + :func:`sync_policy`, and
:func:`sync_policy`, which also runs at the top of every coordinator tick, reads the
store under that lock and makes the live policy hold exactly that. So after any
interleaving the live policy is what the store holds; a read that fails leaves the
policy as it is. Changes, refused writes and no-ops are recorded in the audit log.
"""

from __future__ import annotations

import logging
import re
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

#: Kinds whose approval the kernel honours only while the mode is ``auto`` (it checks a
#: sealed approval receipt): terminal commands, checkpoint operations, browser steps,
#: provider and endpoint changes. Under ``ask`` or ``off`` an owner's approval of one
#: does not run it — the task fails with that reason. (An owner decision; not changed here.)
RECEIPT_NOTE = ("an approval of a terminal command, a checkpoint operation, a browser step or a "
                "provider change takes effect only in auto")
_MEANING = {
    "auto": ("each action is decided by its risk tier: reads and reversible actions run, a payment "
             "inside your per-action and daily money caps runs, any other irreversible action asks"),
    "ask": f"anything with a side effect waits for your approval; {RECEIPT_NOTE}",
    "off": ("nothing a machine approved runs: every action waits for your approval and the proactive "
            f"loop is paused; {RECEIPT_NOTE}"),
}
_warned: set[str] = set()
#: One writer at a time reads the old value, persists, applies and audits (two writers
#: must never leave the store, the live policy and the last audit row disagreeing).
_write_lock = threading.RLock()


class ModeNotSaved(RuntimeError):
    """The settings store did not take the write; nothing was applied."""


def normalize_mode(value: Any) -> tuple[str, bool]:
    """``(mode, known)`` for a stored value. Unset (``None``: no row) is the default;
    ``False`` (YAML 1.1 ``off``/``no``) is ``off``; Hermes' ``manual``/``smart`` are
    ``ask``/``auto``; anything else — an explicitly stored empty or blank text included —
    is ``ask``, not known."""
    if value is None:
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
    if value is None:
        value = _setting(orch, "autonomy.mode", DEFAULT_MODE)
    return read_mode(value)


def _live_overrides(orch: Any) -> dict:
    policy = _policy(orch)
    raw = getattr(policy, "agent_modes", None)
    if raw is None:
        raw = _setting(orch, "autonomy.agent_modes", {})
    return raw if isinstance(raw, dict) else {}


def agent_modes(orch: Any) -> dict[str, str]:
    """The per-agent overrides the live policy holds, each read through :func:`read_mode`.
    What an override *does* is :func:`resolve` — under a global ``off`` it does nothing."""
    return {str(agent): read_mode(value, where=f"autonomy.agent_modes[{str(agent)[:32]}]")
            for agent, value in _live_overrides(orch).items() if not is_unset(value)}


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
    effective, source = resolve(overall, _live_overrides(orch).get(agent) if agent else None)
    return {"effective": effective, "source": source, "global": overall}


# ── the per-agent override map: its shape, wherever it is written ────────────

_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
#: Agent ids that take an override without being in the roster: the owner's own tasks
#: (checkpoint operations) and the hub's (scheduler, system proposals).
SPECIAL_AGENTS = frozenset({"owner", "system"})
MAX_OVERRIDES = 64


def agent_id_problem(agent: Any) -> str | None:
    """Why *agent* cannot name an override, or None: 1–64 characters, starting with a
    letter or digit, of letters, digits, ``_ . : -`` (no control character, no
    ``__proto__``)."""
    if not isinstance(agent, str) or _AGENT_ID.fullmatch(agent) is None:
        return "an agent id is 1-64 characters: a letter or digit, then letters, digits, _ . : -"
    return None


def overrides_problem(value: Any) -> str | None:
    """Why *value* cannot be stored as ``autonomy.agent_modes``, or None. A JSON object of
    at most :data:`MAX_OVERRIDES` well-formed agent ids, each ``auto``, ``ask`` or ``off``."""
    if not isinstance(value, dict):
        return "must be a JSON object of agent id → auto|ask|off"
    if len(value) > MAX_OVERRIDES:
        return f"at most {MAX_OVERRIDES} per-agent overrides"
    for agent, mode in value.items():
        if agent_id_problem(agent):
            return f"agent id {_plain(agent)!r} is not valid: {agent_id_problem(agent)}"
        if not isinstance(mode, str) or mode not in MODES:
            return f"override for {agent} must be {USAGE}"
    return None


def _plain(text: Any, limit: int = 64) -> str:
    """*text* for an audit row or a reply: printable ASCII only, bounded."""
    shown = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text)[:limit])
    return shown + ("…" if len(str(text)) > limit else "")


def _map_text(overrides: Any) -> str:
    if not isinstance(overrides, dict) or not overrides:
        return "{}"
    items = [f"{_plain(agent, 32)}: {_plain(mode, 8)}" for agent, mode in sorted(overrides.items(), key=str)]
    return "{" + ", ".join(items[:MAX_OVERRIDES]) + ("" if len(items) <= MAX_OVERRIDES else ", …") + "}"


def roster_problem(orch: Any, agent: str) -> str | None:
    """Why *agent* cannot be given an override on this hub, or None: it must be one of
    the hub's agents or a :data:`SPECIAL_AGENTS` id. A hub with no roster to ask (not
    booted) accepts any well-formed id."""
    roster = getattr(orch, "agents", None)
    if not isinstance(roster, dict) or not roster:
        return None
    if agent in roster or agent in SPECIAL_AGENTS:
        return None
    return f"no agent named {_plain(agent)!r} on this hub"


# ── the store is the truth; the live policy follows it under one lock ────────


def _put_category(category: str, values: dict) -> tuple[int, list[str]]:
    from ..settings_db import put_category

    return put_category(category, values)


def _read_raw(key: str, default: Any) -> Any:
    """What the settings store holds for ``autonomy.<key>``, as stored."""
    from ..settings_db import get_value

    return get_value("autonomy", key, default)


def _read_store(key: str, default: Any) -> Any:
    """What the settings store holds for ``autonomy.<key>``, as the hub may use it: in
    safe mode the per-agent overrides keep only the entries that ask more."""
    from ..safe_mode import get_value

    return get_value("autonomy", key, default)


def stored_values(read: Any = None) -> tuple[str, dict]:
    """``(mode, agent_modes)`` as stored, normalised — what a policy is built with at
    boot and follows afterwards. *read* is a ``read(key, default)`` reader of
    ``autonomy.<key>`` (default: the settings store, through safe mode)."""
    if read is None:
        def read(key, default):
            return _read_store(key.split(".", 1)[1], default)
    raw = read("autonomy.agent_modes", {})
    overrides = {str(agent): value for agent, value in raw.items()
                 if not is_unset(value)} if isinstance(raw, dict) else {}
    return read_mode(read("autonomy.mode", DEFAULT_MODE)), overrides


def sync_policy(orch: Any) -> str:
    """Make the live policy hold what the settings store holds — the mode and the
    per-agent overrides — and return the global mode now in force. Under the write lock,
    so it never interleaves with a writer; reads the store itself, not the runtime
    settings cache, so a stale cache can neither loosen nor revert the policy (the two
    cached entries are corrected from the store on the way). Runs at the top of every
    coordinator tick, before the e-stop check, and after every settings write. Raises
    when the store cannot be read: the policy is then left exactly as it is."""
    with _write_lock:
        mode, overrides = stored_values()
        policy = _policy(orch)
        if policy is not None:
            if policy.mode != mode:
                policy.mode = mode
            policy.agent_modes = overrides
        cache = getattr(orch, "_runtime_settings", None)
        if isinstance(cache, dict):
            if cache.get("autonomy.mode") != mode:
                cache["autonomy.mode"] = mode
            if cache.get("autonomy.agent_modes") != overrides:
                cache["autonomy.agent_modes"] = dict(overrides)
        return mode


def locked_settings_write(orch: Any, write: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a settings write that may change the mode or the overrides — a category PUT,
    an import, a reset, a reseed, an undo — under the same lock as the dedicated
    writers, and bring the live policy to what the store then holds before the lock is
    released. Returns what *write* returns; a failed sync is logged, never raised (the
    write stands, and the coordinator's next tick syncs)."""
    with _write_lock:
        result = write(*args, **kwargs)
        if orch is not None:
            try:
                sync_policy(orch)
            except Exception:  # noqa: BLE001
                logger.warning("approval mode: the live policy was not synced after a settings write",
                               exc_info=True)
        return result


def _apply_after_write(orch: Any, requested: str) -> str:
    """After a persisted mode write: the live mode. If the store cannot be read back the
    policy keeps the stricter of what it runs and what was asked — never a looser one."""
    try:
        return sync_policy(orch)
    except Exception:  # noqa: BLE001
        logger.warning("autonomy.mode: saved, but the store could not be read back", exc_info=True)
        policy = _policy(orch)
        if policy is not None:
            policy.mode = stricter(read_mode(policy.mode), requested)
        return global_mode(orch)


def set_global_mode(orch: Any, requested: str, *, actor: str, surface: str) -> dict:
    """Persist, apply and audit the global mode. *requested* must be one of :data:`MODES`
    (``ValueError`` otherwise); the caller has already established the owner. Blocking.

    Returns ``{"mode", "was", "changed", "audited", "effective", "live"}``. ``live`` is
    the mode the policy runs after the write — read back from the store under the lock,
    so it is what the store holds even if another writer got there. ``effective`` is
    whether that is the requested mode. A store that refuses the write raises
    :class:`ModeNotSaved` with nothing applied, and the failed attempt is audited. A write
    of the mode already stored and running is audited as a no-op. The write stands when
    the audit row cannot be saved (a tightening must never wait on the log);
    ``audited`` says so."""
    mode = requested.strip().lower() if isinstance(requested, str) else ""
    if mode not in MODES:
        raise ValueError(f"mode must be {USAGE}")
    who = f"(via {_plain(surface, 24)}, by {_plain(actor, 64)})"
    with _write_lock:
        was = global_mode(orch)
        try:
            stored_before = read_mode(_read_raw("mode", DEFAULT_MODE))
        except Exception:  # noqa: BLE001 — unknown: not a no-op
            stored_before = None
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
        live = _apply_after_write(orch, mode)
        effective = live == mode
        if was == mode == stored_before and effective:
            audited = _audit(orch, f"settings.autonomy.mode: {mode} written again, unchanged {who}",
                             "settings_noop")
        else:
            note = "" if effective else f" — saved, but the mode in force is {live}"
            audited = _audit(orch, f"settings.autonomy.mode: {was} → {mode}{note} {who}", "settings_update")
        return {"mode": mode, "was": was, "changed": was != live, "audited": audited,
                "effective": effective, "live": live}


def set_agent_mode(orch: Any, agent: str, requested: str, *, actor: str, surface: str) -> dict:
    """Persist, apply and audit one agent's override; ``default`` clears it. The map is
    read from the store inside the lock (never from the runtime cache, which safe mode
    filters and another process can outdate), so no other agent's override is lost; the
    audit row carries the whole map before and after.

    Returns ``{"agent", "mode", "was", "agents", "audited", "effective", "live"}``:
    ``agents`` is the stored map, ``live`` the override the policy now holds for the
    agent (None for none), ``effective`` whether that is what was asked — it is not when
    safe mode drops a looser override, or the store could not be read back."""
    agent = agent.strip() if isinstance(agent, str) else ""
    mode = requested.strip().lower() if isinstance(requested, str) else ""
    if agent_id_problem(agent) or mode not in (*MODES, "default"):
        raise ValueError(f"mode must be {USAGE}|default, for a well-formed agent id")
    who = f"(via {_plain(surface, 24)}, by {_plain(actor, 64)})"
    with _write_lock:
        try:
            raw = _read_raw("agent_modes", {})
        except Exception as exc:
            _audit(orch, f"settings.autonomy.agent_modes[{agent}] → {mode} NOT SAVED: "
                         f"the stored map could not be read {who}", "settings_update_failed")
            raise ModeNotSaved("the stored overrides could not be read") from exc
        before = {str(k): v for k, v in raw.items() if not is_unset(v)} if isinstance(raw, dict) else {}
        after = dict(before)
        if mode == "default":
            after.pop(agent, None)
        else:
            after[agent] = mode
        change = f"settings.autonomy.agent_modes: {_map_text(before)} → {_map_text(after)}"
        try:
            _updated, skipped = _put_category("autonomy", {"agent_modes": after})
        except Exception as exc:
            _audit(orch, f"{change} NOT SAVED {who}", "settings_update_failed")
            raise ModeNotSaved("the settings store refused autonomy.agent_modes") from exc
        if "agent_modes" in (skipped or []):
            _audit(orch, f"{change} NOT SAVED {who}", "settings_update_failed")
            raise ModeNotSaved("the settings store did not take autonomy.agent_modes")
        try:
            sync_policy(orch)
        except Exception:  # noqa: BLE001 — judged by what the policy holds, below
            logger.warning("autonomy.agent_modes: saved, but the store could not be read back", exc_info=True)
        held = _live_overrides(orch).get(agent)
        live = None if is_unset(held) else read_mode(held, where="autonomy.agent_modes")
        effective = live == (None if mode == "default" else mode)
        if before == after and effective:
            audited = _audit(orch, f"settings.autonomy.agent_modes: {_map_text(after)} written again, "
                                   f"unchanged {who}", "settings_noop")
        else:
            note = "" if effective else f" — saved, but {agent} runs {live or 'the global mode'}"
            audited = _audit(orch, f"{change}{note} {who}", "settings_update")
        return {"agent": agent, "mode": None if mode == "default" else mode,
                "was": before.get(agent), "agents": after, "audited": audited,
                "effective": effective, "live": live}


def audit_offline_write(audit: Any, key: str, before: Any, after: Any, *, actor: str, surface: str) -> bool:
    """The audit row for a write of ``autonomy.mode`` / ``autonomy.agent_modes`` made
    straight to the store by a process that is not the hub (``nerva config set``)."""
    if key == "agent_modes":
        change = f"settings.autonomy.agent_modes: {_map_text(before)} → {_map_text(after)}"
    else:
        change = f"settings.autonomy.mode: {_plain(read_mode(before), 8)} → {_plain(read_mode(after), 8)}"
    return _audit(SimpleAudit(audit), f"{change} (via {_plain(surface, 24)}, by {_plain(actor, 64)})",
                  "settings_update")


class SimpleAudit:
    """An orchestrator-shaped holder for a bare audit log (:func:`audit_offline_write`)."""

    def __init__(self, audit: Any) -> None:
        self.audit = audit


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
    "ALIASES", "DEFAULT_MODE", "FALLBACK_MODE", "MAX_OVERRIDES", "MODES", "SPECIAL_AGENTS", "USAGE",
    "ModeNotSaved", "agent_id_problem", "agent_modes", "audit_offline_write", "describe",
    "global_mode", "is_unset", "locked_settings_write", "looser_overrides", "meaning",
    "normalize_mode", "overrides_problem", "parse_requested", "read_mode", "resolve",
    "roster_problem", "set_agent_mode", "set_global_mode", "stored_values", "stricter", "sync_policy",
]
