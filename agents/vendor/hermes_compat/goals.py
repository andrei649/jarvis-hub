"""``hermes_cli.goals`` for the vendored ``hermes_cli/loops.py`` (rule ``hermes-cli-goals``).

``loops.py`` takes four things from Hermes's goal module, and each is Nerva's here:

* ``_get_session_db()`` — the store a loop's state lives in. Hermes keeps it in
  SessionDB ``state_meta`` under ``loop:<session>``; Nerva installs its own store
  (``agents/core/session_meta.py``: the same rows in one small JSON file under the data
  root, written atomically), so a loop survives a restart and ``list_active_loops`` sees
  it. Nothing installed means no store: upstream then drops the write with a warning.
* ``_warn_dropped_write`` — a log line, as upstream.
* ``judge_goal(condition, response)`` — the ``--until`` judge. Upstream calls a model
  synchronously from inside ``complete_tick``. Nerva never blocks the event loop on a
  model: the driver asks the judge first (an auxiliary local one-shot, no tools) and
  puts the verdict in :func:`judge_scope`; this function answers only that verdict for
  exactly that condition and reply. Anything else raises, and ``loops.py`` treats a
  raising judge as "continue" (fail-open, as upstream).
* ``GoalManager`` — whether an active goal owns the session's boundary, so a loop tick
  defers to it. The driver installs the probe (:func:`set_goal_probe`); none installed
  means no goal.

This module imports no network, process or file library; the store is injected.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("jarvis.session_loops")

_store: Any = None
_store_lock = threading.Lock()


def set_session_db(store: Any) -> None:
    """Install the store loop state lives in (Nerva's ``session_meta.SessionMetaStore``:
    ``get_meta`` / ``set_meta`` / ``list_meta_prefix``). ``None`` uninstalls it."""
    global _store
    with _store_lock:
        _store = store


def _get_session_db() -> Any:
    with _store_lock:
        return _store


def _warn_dropped_write(owner: str, kind: str, session_id: str) -> None:
    logger.warning("%s: no session store; the %s for %s was not saved", owner, kind, session_id)


# ── the --until judge: answered by Nerva's driver before complete_tick ────────────────

_verdict: ContextVar[tuple[str, str, str, str] | None] = ContextVar("loop_until_verdict", default=None)


@contextmanager
def judge_scope(condition: str, response: str, verdict: str, reason: str):
    """Make *verdict* (``done`` | ``continue`` | ``blocked``) the judge's answer for this
    exact condition and reply while the block runs."""
    if verdict not in {"done", "continue", "blocked"}:
        verdict = "continue"
    token = _verdict.set((condition, response, verdict, str(reason or "")[:300]))
    try:
        yield
    finally:
        _verdict.reset(token)


def judge_goal(condition: str, response: str, *args: Any, **kwargs: Any):
    held = _verdict.get()
    if held is None or held[0] != condition or held[1] != response:
        raise RuntimeError("no judge verdict for this reply")
    return held[2], held[3], False, False, False


# ── goal ownership of the session boundary ─────────────────────────────────────────────

_goal_probe: Callable[[str], bool] | None = None


def set_goal_probe(probe: Callable[[str], bool] | None) -> None:
    global _goal_probe
    _goal_probe = probe


class GoalManager:
    def __init__(self, session_id: str = "") -> None:
        self.session_id = str(session_id or "")

    def is_active(self) -> bool:
        probe = _goal_probe
        if probe is None:
            return False
        return bool(probe(self.session_id))

    def is_waiting(self) -> bool:
        return False
