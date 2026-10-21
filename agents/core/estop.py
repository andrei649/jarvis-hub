"""
estop.py — global emergency stop: a resumable pause for NEW autonomous work.

While the sentinel file (``<install root>/ESTOP``) exists:

* the heartbeat scheduler skips dispatching due agent heartbeats
  (``heartbeat.py:_run_heartbeat``),
* the autonomy coordinator skips its self-tasking tick
  (``autonomy_coordinator.py:loop``).

Owner conversation is deliberately NOT paused — the owner must always be able
to talk to the hub (including to ask it to resume). In-flight work is NEVER
killed — this is pause-new-work, not panic/exit. The check is a single
``os.stat`` so callers may run it every tick; no caching beyond the OS is
performed, so engaging/disengaging takes effect on the very next check
(when the switch is off, the check also lists the profiles directory — see below).

H694 — one canonical kill switch: the sentinel lives at ``paths.install_root()``,
the root every ``$JARVIS_PROFILE`` hub sits beside, so engaging it from any profile
(or the default hub) pauses them all. A sentinel inside any profile's own data root
(``<install root>-profiles/<name>/ESTOP``, the pre-H694 location) is the same switch:
every scope sees it, the first check folds it into the canonical sentinel (reason and
``engaged_at`` kept), and a resume from any scope removes it.

The sentinel body is optional JSON ``{"reason": ..., "engaged_at": ...}``.
A corrupt or empty file still counts as engaged (fail safe): the pause must
hold even if the file was created by ``touch``.

Ported from hermes-agent ``agent/estop.py`` (Nous Research, MIT, v2026.8.27)
— see LICENSES/hermes-agent-MIT.txt — rescoped from "all new gateway turns"
to autonomous work only (Nerva's graduated-autonomy posture: pausing the
owner's own chat would remove the very channel used to resume).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from agents.core.paths import install_root, profiles_root

SENTINEL_NAME = "ESTOP"

# Per-component "logged already for this engagement" flags so a paused
# dispatch loop logs once per engagement instead of once per tick.
_log_lock = threading.Lock()
_logged_components: set[str] = set()


def sentinel_path() -> Path:
    """Path of the canonical ESTOP sentinel, shared by every profile of the install."""
    return install_root() / SENTINEL_NAME


def _legacy_sentinels() -> list[Path]:
    """Pre-H694 sentinels inside any profile's own data root (usually none)."""
    found: list[Path] = []
    try:
        with os.scandir(profiles_root(install_root())) as entries:
            dirs = [Path(e.path) for e in entries if e.is_dir(follow_symlinks=False)]
    except FileNotFoundError:   # no profile was ever created on this install
        return found
    for directory in sorted(dirs):
        candidate = directory / SENTINEL_NAME
        if candidate.exists():
            found.append(candidate)
    return found


def _fold_legacy() -> list[Path]:
    """Move legacy sentinels onto the canonical one; return those still left behind.

    The first legacy body becomes the canonical sentinel when none is engaged yet (so
    its reason and engaged_at survive); the rest are redundant and removed. Best effort:
    a sentinel that cannot be moved stays where it is and still counts as engaged."""
    canonical = sentinel_path()
    left: list[Path] = []
    for legacy in _legacy_sentinels():
        try:
            if canonical.exists():
                legacy.unlink()
            else:
                canonical.parent.mkdir(parents=True, exist_ok=True)
                os.replace(legacy, canonical)
        except FileNotFoundError:   # another hub folded or resumed it first
            continue
        except OSError:
            left.append(legacy)
    return left


def is_engaged() -> bool:
    """Cheap check: is the global emergency stop engaged?

    One stat when engaged; otherwise also a listing of the profiles directory, so a
    legacy profile-local sentinel binds every scope too (and is folded on sight).

    Fail SAFE on stat errors: if we cannot determine whether the sentinel
    exists (permission error, transient I/O failure on the data root), report
    engaged. The module contract is that the pause must hold even when the
    sentinel is unreadable — a fail-open here would silently lift an
    operator's emergency stop exactly when the filesystem is misbehaving.
    """
    try:
        if sentinel_path().exists():
            return True
        if not _legacy_sentinels():
            return False
        _fold_legacy()
        return True
    except OSError:
        return True


def engage(reason: str | None = None) -> Path:
    """Create the ESTOP sentinel. Idempotent; re-engaging updates the file."""
    path = sentinel_path()
    payload = {
        "engaged_at": datetime.now(UTC).isoformat(),
        "reason": reason or None,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        # Best effort: an empty/partial sentinel still pauses (fail safe).
        with contextlib.suppress(OSError):
            path.touch(exist_ok=True)
    return path


def disengage() -> bool:
    """Remove the ESTOP sentinel and any legacy profile-local one, from any scope.

    Returns True if a pause was lifted."""
    lifted = False
    try:
        legacy = _legacy_sentinels()
    except OSError:
        legacy = []
    for path in [sentinel_path(), *legacy]:
        try:
            path.unlink()
            lifted = True
        except OSError:
            pass
    return lifted


def get_state() -> dict | None:
    """Return ``{"reason": ..., "engaged_at": ...}`` or None when not engaged.

    A sentinel with an unreadable/corrupt body still reports engaged, with
    both fields None — the pause is authoritative, the metadata is not.
    """
    try:
        left = _fold_legacy()
        canonical = sentinel_path()
        path = canonical if canonical.exists() else next(iter(left), None)
    except OSError:
        return {"reason": None, "engaged_at": None}
    if path is None:
        return None
    reason = None
    engaged_at = None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            reason = raw.get("reason") or None
            engaged_at = raw.get("engaged_at") or None
    except (OSError, ValueError):
        pass
    return {"reason": reason, "engaged_at": engaged_at}


def check_paused(component: str, logger: logging.Logger) -> bool:
    """Return True when engaged, logging once per engagement per component.

    Dispatch loops call this every tick; the log fires on the disengaged→
    engaged transition for that component and re-arms after a resume, so a
    long pause doesn't spam one line per tick.
    """
    if not is_engaged():
        with _log_lock:
            _logged_components.discard(component)
        return False
    with _log_lock:
        first = component not in _logged_components
        if first:
            _logged_components.add(component)
    if first:
        state = get_state() or {}
        reason = state.get("reason")
        suffix = f" (reason: {reason})" if reason else ""
        logger.info(
            "%s dispatch paused by global emergency stop%s — resume via "
            "POST /api/ops/estop/resume (%s)",
            component,
            suffix,
            sentinel_path(),
        )
    return True


def _reset_log_state_for_tests() -> None:
    """Clear the log-once bookkeeping (test isolation helper)."""
    with _log_lock:
        _logged_components.clear()


__all__ = [
    "SENTINEL_NAME",
    "sentinel_path",
    "is_engaged",
    "engage",
    "disengage",
    "get_state",
    "check_paused",
]
