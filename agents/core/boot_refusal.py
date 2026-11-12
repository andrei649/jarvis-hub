"""H089 — the exit status of a start the configuration refused.

Hermes' gateway leaves with 78 (sysexits EX_CONFIG) on a permanent configuration failure,
and its service units do not respawn on 78. Nerva's units say the same
(``RestartPreventExitStatus=78`` in ``deploy/systemd`` and the user unit ``nerva service
install`` writes; ``AppExit 78 Exit`` under NSSM). This module decides which status a
refused start leaves with:

* a refusal the configuration itself proves permanent — a boot guard (an open bind with no
  token, an unguarded bot, a mistyped posture flag, a hardened profile without its key), a
  variable under both spellings in the process environment, a refused profile name —
  leaves with :data:`CONFIG_REFUSED_EXIT` at once;
* a refusal that comes from a ``.env`` file is retried **once**: the file may have been
  caught mid-save. The same refusal (by digest; the text is never stored) at the next start
  within :data:`REPEAT_WINDOW_S` is permanent and leaves with 78. A start that gets past the
  configuration clears the record (:func:`clear`).

launchd has no "do not restart on this status". Under the agent ``nerva service install``
writes (``NERVA_SERVICE_WRAPPER=launchd``, ``KeepAlive`` = ``SuccessfulExit: false``), a
permanent refusal therefore leaves with 0, so launchd does not respawn it; the refusal is in
the agent's error log either way.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

CONFIG_REFUSED_EXIT = 78
MARKER_NAME = "boot-refusal.json"
REPEAT_WINDOW_S = 900.0
MAX_MARKER_BYTES = 4096
WRAPPER_ENV = "NERVA_SERVICE_WRAPPER"


def _marker(path: Path | None) -> Path | None:
    if path is not None:
        return path
    try:
        from .paths import data_path

        return data_path(MARKER_NAME)
    except Exception:   # a refused profile name: there is no data root to keep it in
        return None


def _read(path: Path) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return {}
    try:
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(MAX_MARKER_BYTES + 1)
    except OSError:
        return {}
    if len(raw) > MAX_MARKER_BYTES:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".boot-refusal-", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def _digest(refused: BaseException) -> str:
    return hashlib.sha256(str(refused).encode("utf-8", "replace")).hexdigest()


def exit_status(refused: BaseException, *, path: Path | None = None, now: float | None = None,
                wrapper: str | None = None) -> int:
    """The status a start refused with *refused* leaves with (see the module docstring)."""
    status = getattr(refused, "exit_status", 1)
    status = status if isinstance(status, int) else 1
    if status != CONFIG_REFUSED_EXIT:
        marker = _marker(path)
        if marker is not None:
            clock = time.time() if now is None else now
            digest = _digest(refused)
            prior = _read(marker)
            at = prior.get("at")
            if (prior.get("digest") == digest and isinstance(at, (int, float))
                    and 0 <= clock - at <= REPEAT_WINDOW_S):
                status = CONFIG_REFUSED_EXIT
            else:
                _write(marker, {"digest": digest, "at": clock})
    if status == CONFIG_REFUSED_EXIT:
        if wrapper is None:
            from .env_config import env_str

            wrapper = env_str(WRAPPER_ENV)
        if str(wrapper or "").strip().lower() == "launchd":
            return 0
    return status


def clear(path: Path | None = None) -> None:
    """The configuration was accepted: forget an earlier refusal."""
    marker = _marker(path)
    if marker is None:
        return
    with contextlib.suppress(OSError):
        marker.unlink()


__all__ = ["CONFIG_REFUSED_EXIT", "MARKER_NAME", "REPEAT_WINDOW_S", "clear", "exit_status"]
