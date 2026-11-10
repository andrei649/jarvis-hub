"""The owner's two verify switches, kept in ``<data>/verify/config.json``.

* ``verify_on_stop`` — ``off`` (default, as in Hermes) or ``on``: the turn-end nudge of
  :mod:`.stop`.
* ``coding_context`` — ``auto`` (default), ``on`` or ``off``: the coding posture of
  :mod:`.coding`. ``auto``: the turn's working folder is a project and the turn can edit
  or run code; ``on``: whenever the working folder is a project; ``off``: never.

Changed only by the owner (``/verify on-stop``, ``/verify coding``), audited. They are owner
configuration: in managed mode (an administrator's ``.managed`` marker, or a managed
configuration that cannot be read) a change is refused like every other configuration
write (``managed_scope.check_writable``). They are not settings-store keys, so an
administrator cannot pin them one by one. An unreadable file reads as the defaults, so a
damaged file can only switch the nudge off.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("jarvis.verify.config")

VERIFY_ON_STOP = ("off", "on")
CODING_CONTEXT = ("auto", "on", "off")
DEFAULTS = {"verify_on_stop": "off", "coding_context": "auto"}
_ALIASES = {"true": "on", "yes": "on", "1": "on", "false": "off", "no": "off", "0": "off"}
_lock = threading.Lock()


def path() -> Path:
    from agents.core.paths import data_path

    return data_path("verify", "config.json")


def load() -> dict[str, str]:
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        if raw.get("verify_on_stop") in VERIFY_ON_STOP:
            out["verify_on_stop"] = raw["verify_on_stop"]
        if raw.get("coding_context") in CODING_CONTEXT:
            out["coding_context"] = raw["coding_context"]
    return out


def normalize(key: str, value: str) -> str | None:
    word = _ALIASES.get(str(value or "").strip().lower(), str(value or "").strip().lower())
    allowed = VERIFY_ON_STOP if key == "verify_on_stop" else CODING_CONTEXT if key == "coding_context" else ()
    return word if word in allowed else None


def save(key: str, value: str, *, by: str = "owner", audit=None) -> dict[str, str]:
    """Set one switch (already normalized); returns the new settings."""
    if key not in DEFAULTS or normalize(key, value) != value:
        raise ValueError(f"{key}={value!r} is not a verify setting")
    from agents.core import managed_scope

    managed_scope.check_writable()      # raises ManagedRefused in managed mode
    with _lock:
        current = load()
        before = current.get(key)
        current[key] = value
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    if audit is not None:
        try:
            audit.record(actor=str(by)[:120], action="verify.setting",
                         why=f"{key}: {before} -> {value}", metadata={"key": key, "value": value})
        except Exception:  # noqa: BLE001 — the audit sink never blocks the owner's change
            logger.debug("verify setting audit failed", exc_info=True)
    return current


def verify_on_stop() -> bool:
    return load()["verify_on_stop"] == "on"


def coding_mode() -> str:
    return load()["coding_context"]


__all__ = ["CODING_CONTEXT", "DEFAULTS", "VERIFY_ON_STOP", "coding_mode", "load", "normalize", "path", "save",
           "verify_on_stop"]
