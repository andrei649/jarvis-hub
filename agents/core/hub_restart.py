"""hub_restart.py — the hub asking itself to restart (H010).

An in-place restore cannot overwrite the state DBs while the hub's stores hold them
open, so an approved restore is *staged* and the hub restarts to apply it before any
store opens (``serve.apply_staged_restore``). This module is the seam between the
code that wants the restart and the process that can do it:

* ``serve.py`` installs a stopper for the uvicorn server it runs (``install``) and,
  once the server has drained and returned, re-execs itself when a restart was
  requested (``serve.run_server``).
* Anything else asks with ``request(reason)``. Without an installed stopper — the hub
  started some other way (``python -m uvicorn agents.web:app``, a test client) — the
  answer is ``False`` and the caller tells the owner to restart the hub themselves;
  nothing pretends a restart is coming.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger("jarvis.hub_restart")

_lock = threading.Lock()
_stopper: Callable[[], None] | None = None
_requested: str | None = None


def install(stopper: Callable[[], None]) -> None:
    """Register the callable that makes the running server stop (serve.py only)."""
    global _stopper
    with _lock:
        _stopper = stopper


def request(reason: str) -> bool:
    """Ask the running hub to stop and start again; False when nothing can restart it."""
    global _requested
    with _lock:
        stopper = _stopper
        if stopper is None:
            return False
        _requested = str(reason or "restart")
    logger.warning("hub restart requested: %s", _requested)
    stopper()
    return True


def requested() -> str | None:
    """The reason a restart was requested in this process, or None."""
    return _requested


def reset() -> None:
    """Forget the stopper and any request (tests, and serve.py before it re-execs)."""
    global _stopper, _requested
    with _lock:
        _stopper = None
        _requested = None


__all__ = ["install", "request", "requested", "reset"]
