"""Plan mode (H668) — a per-session floor that lets only reads run.

``/plan <task>`` puts the conversation in plan mode and hands the model Hermes's plan
prompt (``agents/vendor/hermes/agent/plan_prompt.py``, adopted byte-identical). The
prompt asks the model not to implement anything; this module is what makes that true
whatever the model does. While a session is in plan mode:

* the Action Kernel (``kernel.authorize``) denies every action kind that is not a read,
  before the policy, the approval queue or a sealed receipt is consulted — so a plan turn
  cannot even queue an approval card for a write;
* the tool front door (``ToolRPCServer.handle``) refuses every gated tool and every
  ungated tool that has not declared itself ``read_only`` (H325), with the kernel on or
  off (it is off by default), before preflight or intake run.

Rules that keep it a *restriction only*:

* Nothing here ever grants. Every check returns a denial reason or ``None``; ``None``
  means "plan mode has nothing to say" and the ordinary gates decide as before.
* A read is judged from the action **kind** alone (the policy's own verb table), never
  from the payload, which a caller or a model's arguments can fill: a payload
  ``risk_tier`` of 0 does not make a write a read here. The one exception is
  ``plugin.egress``, whose method the kernel's own egress hook sets: ``GET``/``HEAD``
  is a read, anything else is not.
* The state is persisted (``<data>/sessions/plan_mode.json``), so a restart keeps a
  session in plan mode until the owner leaves it. A state file that exists but cannot be
  read fails closed: every session counts as being in plan mode until the owner rewrites
  it with ``/plan off``.
* Entering and leaving are owner actions: :meth:`PlanModeStore.enter` and
  :meth:`PlanModeStore.exit` refuse a principal that is not the owner, whatever command
  or route called them, and each change is written to the audit sink when one is given.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.kernel.plan_mode")

#: The reason every plan-mode denial starts with (cards, tool results and tests read it).
DENIAL_PREFIX = "plan mode"
#: The kinds that are reads although their verb is not in the policy's read table.
_EGRESS_KIND = "plugin.egress"
_READ_METHODS = frozenset({"GET", "HEAD"})
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,199}\Z")
_MAX_TASK = 500


class PlanModeUnreadable(RuntimeError):
    """The plan-mode state file exists and cannot be read; callers fail closed."""


class PlanModeRefused(PermissionError):
    """Entering or leaving plan mode was asked for by someone who is not the owner."""


def valid_session(session_id: Any) -> bool:
    return isinstance(session_id, str) and _SESSION.fullmatch(session_id) is not None


class PlanModeStore:
    """The sessions in plan mode, persisted as one small JSON object."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        if self._path is None:
            from agents.core.paths import data_path

            self._path = data_path("sessions", "plan_mode.json")
        return self._path

    def _read(self) -> dict[str, dict]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise PlanModeUnreadable(str(exc)) from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise PlanModeUnreadable("plan mode state is not JSON") from exc
        sessions = data.get("sessions") if isinstance(data, dict) else None
        if not isinstance(sessions, dict):
            raise PlanModeUnreadable("plan mode state has no sessions object")
        return {str(k): v for k, v in sessions.items() if isinstance(v, dict)}

    def _write(self, sessions: dict[str, dict]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".plan_mode.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "sessions": sessions}, fh, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # ── reads ────────────────────────────────────────────────────────────────

    def state(self, session_id: str) -> dict | None:
        """The session's plan-mode row, or None. Raises :class:`PlanModeUnreadable`."""
        if not valid_session(session_id):
            return None
        with self._lock:
            return self._read().get(session_id)

    def is_active(self, session_id: str | None) -> bool:
        """Whether *session_id* is in plan mode. An unreadable store answers True (fail
        closed) for any session; no session at all answers False."""
        if not session_id:
            return False
        try:
            return self.state(str(session_id)) is not None
        except PlanModeUnreadable:
            logger.warning("plan mode state unreadable; treating the session as in plan mode")
            return True

    def active_sessions(self) -> list[str]:
        with self._lock:
            return sorted(self._read())

    # ── owner actions ────────────────────────────────────────────────────────

    def enter(self, session_id: str, *, owner: bool, by: str, task: str = "", audit=None) -> dict:
        """Put *session_id* in plan mode. Only the owner may; returns the row."""
        if owner is not True:
            raise PlanModeRefused("only the owner can turn plan mode on")
        if not valid_session(session_id):
            raise ValueError("plan mode needs a conversation")
        row = {"since": time.time(), "by": str(by or "owner")[:120],
               "task": " ".join(str(task or "").split())[:_MAX_TASK], "plans": []}
        with self._lock:
            try:
                sessions = self._read()
            except PlanModeUnreadable:
                sessions = {}               # the owner's write replaces an unreadable file
            previous = sessions.get(session_id)
            if previous is not None:
                row["since"] = previous.get("since", row["since"])
                row["plans"] = list(previous.get("plans") or [])[-20:]
            sessions[session_id] = row
            self._write(sessions)
        _audit(audit, "plan_mode.enter", by, session_id)
        return dict(row)

    def exit(self, session_id: str, *, owner: bool, by: str, audit=None) -> bool:
        """Take *session_id* out of plan mode. Only the owner may; True when it was on."""
        if owner is not True:
            raise PlanModeRefused("only the owner can turn plan mode off")
        with self._lock:
            try:
                sessions = self._read()
            except PlanModeUnreadable:
                sessions = None
            if sessions is None:
                # An unreadable file held every session in plan mode; the owner's exit
                # rewrites it empty (the only way out of the fail-closed state).
                self._write({})
                _audit(audit, "plan_mode.exit", by, session_id, note="state file was unreadable; reset")
                return True
            was = sessions.pop(session_id, None) is not None
            if was:
                self._write(sessions)
        if was:
            _audit(audit, "plan_mode.exit", by, session_id)
        return was

    def carry(self, old_session: str, new_session: str) -> bool:
        """Copy *old_session*'s row to *new_session* (see :func:`migrate`). The old row
        stays: the old id may still be addressed, and it stays restricted."""
        with self._lock:
            try:
                sessions = self._read()
            except PlanModeUnreadable:
                return False          # every session is held already (fail closed)
            row = sessions.get(old_session)
            if row is None or new_session in sessions:
                return False
            sessions[new_session] = dict(row, carried_from=old_session)
            self._write(sessions)
        return True

    def note_plan(self, session_id: str, path: str) -> None:
        """Remember a saved plan file on the session's row (hub-owned, not a model write)."""
        with self._lock:
            try:
                sessions = self._read()
            except PlanModeUnreadable:
                return
            row = sessions.get(session_id)
            if row is None:
                return
            row["plans"] = [*(row.get("plans") or []), str(path)][-20:]
            self._write(sessions)


def _audit(audit, action: str, by: str, session_id: str, note: str = "") -> None:
    if audit is None:
        return
    try:
        audit.record(actor=str(by or "owner")[:120], action=action,
                     why=note or f"session {session_id}", metadata={"session_id": session_id})
    except Exception:  # noqa: BLE001 — the audit sink never blocks the owner's change
        logger.debug("plan mode audit record failed", exc_info=True)


_DEFAULT = PlanModeStore()


def default_store() -> PlanModeStore:
    return _DEFAULT


def set_default_store(store: PlanModeStore) -> PlanModeStore:
    """Swap the process store (tests). Returns the previous one."""
    global _DEFAULT
    previous, _DEFAULT = _DEFAULT, store
    return previous


def current_session() -> str | None:
    """The conversation the running turn belongs to (bound around every generation)."""
    try:
        from agents.core.llm.request_context import current_session as _current

        return _current()
    except Exception:  # noqa: BLE001
        return None


#: The kernel kinds the Action Kernel registry knows that only read. A registered kind is
#: a read only if it is listed here: its name is never trusted to say so
#: (``checkpoint.restore`` starts with "check", and it restores files). ``plugin.egress``
#: is judged by its method below.
READ_KINDS = frozenset({"research"})
def kind_is_read(kind: str, payload: Any = None) -> bool:
    """Whether *kind* only reads, judged from the kind alone, never the payload's claims.

    Only :data:`READ_KINDS` and a ``plugin.egress`` GET or HEAD (the kernel's own egress
    hook sets the method) are reads. Every other kind — registered or not — is not: a
    name is never trusted to say what an action does (``checkpoint.restore`` starts with
    "check", ``get.purge`` with "get")."""
    kind = str(kind or "").strip().lower()
    if not kind:
        return False
    if kind == _EGRESS_KIND:
        method = payload.get("method") if isinstance(payload, dict) else None
        return isinstance(method, str) and method.upper() in _READ_METHODS
    return kind in READ_KINDS


def migrate(old_session: str, new_session: str, *, store: PlanModeStore | None = None) -> bool:
    """Carry plan mode to a conversation's new session id (/undo, /new, a channel's idle or
    daily rollover). Hub-internal and restrict-only: it never takes a session out of plan
    mode. True when the new session is now in plan mode because the old one was."""
    store = store or _DEFAULT
    if not old_session or not new_session or old_session == new_session:
        return False
    if not valid_session(old_session) or not valid_session(new_session):
        return False
    return store.carry(old_session, new_session)


# G18 (H404) — the same floor for one context rather than one session: the /review
# reviewer sub-agent runs inside ``read_only_floor``, so every action it plans and every
# tool it calls is judged as plan mode judges them, whatever session it is in. It is a
# context variable: it reaches the reviewer's own tasks and tool threads (each copies the
# context it was started from) and nothing else. Restriction only, like plan mode.
READ_ONLY_PREFIX = "read-only reviewer"
_READ_ONLY_FLOOR: ContextVar[str | None] = ContextVar("nerva_read_only_floor", default=None)


@contextlib.contextmanager
def read_only_floor(label: str = "review"):
    """Let only reads run in this context (the reviewer's run)."""
    token = _READ_ONLY_FLOOR.set(str(label or "review")[:40])
    try:
        yield
    finally:
        _READ_ONLY_FLOOR.reset(token)


def read_only_floor_active() -> str | None:
    """The floor's label when the code in flight is inside :func:`read_only_floor`."""
    return _READ_ONLY_FLOOR.get()


def action_denial(kind: str, payload: Any = None, *, session_id: str | None = None,
                  store: PlanModeStore | None = None) -> str | None:
    """The kernel's plan-mode floor: a denial reason for a non-read *kind* while the
    session is in plan mode (or the code runs under :func:`read_only_floor`), else None.
    Never a grant."""
    if _READ_ONLY_FLOOR.get() is not None and not kind_is_read(kind, payload):
        return f"{READ_ONLY_PREFIX}: only reads run in a review ({kind})"
    session = session_id if session_id is not None else current_session()
    if not session or not (store or _DEFAULT).is_active(session):
        return None
    if kind_is_read(kind, payload):
        return None
    return f"{DENIAL_PREFIX}: only reads run until the owner leaves plan mode ({kind})"


def tool_denial(name: str, *, gated: bool, risk: str | None, session_id: str | None = None,
                store: PlanModeStore | None = None) -> str | None:
    """The tool front door's plan-mode floor: a gated tool, or one that did not declare
    itself ``read_only``, is refused while the session is in plan mode (or the code runs
    under :func:`read_only_floor`)."""
    if _READ_ONLY_FLOOR.get() is not None and (gated or risk != "read_only"):
        return f"{READ_ONLY_PREFIX}: only read-only tools run in a review ({name})"
    session = session_id if session_id is not None else current_session()
    if not session or not (store or _DEFAULT).is_active(session):
        return None
    if not gated and risk == "read_only":
        return None
    return f"{DENIAL_PREFIX}: only read-only tools run until the owner leaves plan mode ({name})"
