"""H395 — Mid-turn user steering for the caller's or owner's own running turn.

Sub-agents already carry a per-spawn ``SteerChannel``; this module brings the same
runtime-owned steering inbox to live interactive conversation turns (``POST /chat``,
``POST /chat/stream``, Telegram/channel turns, and ``nerva chat -i``):

* **Credential isolation on HTTP** — ``POST /chat/steer`` derives ``actor`` from the
  authenticated HTTP request credentials (``http_actor``), never from a payload field,
  and steers only a live turn started by that exact credential matching ``session_id``
  or ``turn_id`` (``X-Nerva-Turn-Id``). Another credential's turn is reported as
  ``no_active_turn`` (404), never revealed or modified.
* **Owner isolation on ``/steer``** — the ``/steer <instruction>`` slash command is
  ``ADMIN``-tier and steers only an active ``owner=True`` turn in the target session.
* **Governance invariant** — every message pushed here constructs a ``SteerMessage``
  with ``origin="user"``, which seals ``can_approve=False``. Mid-turn steering can
  adjust course or focus between tool-loop rounds, and NEVER approves a queued
  ``ActionKernel`` task, clears ``recall_taint``, or widens ``action_origin``.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .steering import steering_available, steering_scope
from .subagents import SteerChannel, SteerMessage
from .turn_interrupts import turn_id_from

MAX_STEER_CHARS = 4_000
MAX_STEER_PENDING = 32
_seq = itertools.count(1)
_lock = threading.Lock()


@dataclass(eq=False)
class LiveSteerTurn:
    actor: str | None
    session_id: str
    turn_id: str | None
    owner: bool
    channel: SteerChannel
    active: bool = True


_live: set[LiveSteerTurn] = set()
_current: ContextVar[LiveSteerTurn | None] = ContextVar("nerva_live_steer_turn", default=None)


def _clean_message(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned or len(cleaned) > MAX_STEER_CHARS:
        return None
    return cleaned


@contextmanager
def track_turn_steer(
    *,
    session_id: str | None,
    actor: str | None = None,
    turn_id: str | None = None,
    owner: bool = False,
) -> Iterator[LiveSteerTurn | None]:
    """Bind a per-turn ``SteerChannel`` for an interactive conversation turn.

    Nested calls inside the same turn (e.g. ``web.py`` wrapping ``Orchestrator``)
    reuse the outer ``LiveSteerTurn`` and update its ``session_id`` once resolved.
    Sub-agent runs that already bound their own ``steering_scope`` are left untouched.
    """
    existing = _current.get()
    if existing is not None and existing.active:
        if session_id:
            with _lock:
                existing.session_id = str(session_id)
        yield existing
        return
    if steering_available(""):
        yield None
        return
    if not actor and not owner:
        yield None
        return
    chan = SteerChannel(f"turn_{next(_seq)}")
    entry = LiveSteerTurn(
        actor=actor or None,
        session_id=str(session_id or ""),
        turn_id=turn_id_from(turn_id),
        owner=bool(owner),
        channel=chan,
    )
    with _lock:
        _live.add(entry)
    token = _current.set(entry)
    try:
        with steering_scope(chan):
            yield entry
    finally:
        entry.active = False
        _current.reset(token)
        with _lock:
            _live.discard(entry)


def update_session_id(session_id: str | None) -> None:
    """Update the resolved session id on the current task's ``LiveSteerTurn``, if any."""
    entry = _current.get()
    if entry is not None and entry.active and session_id:
        with _lock:
            entry.session_id = str(session_id)


def _deliver(entry: LiveSteerTurn, message: str) -> tuple[str, int]:
    pending_now = len(entry.channel._pending)
    if pending_now >= MAX_STEER_PENDING:
        return "queue_full", pending_now
    entry.channel.push(SteerMessage(entry.channel.spawn_id, message, origin="user"))
    return "queued", len(entry.channel._pending)


def steer_http(
    actor: str | None,
    message: str,
    *,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> tuple[str, int]:
    """Deliver mid-turn user guidance to *actor*'s own matching HTTP turn."""
    cleaned = _clean_message(message)
    if cleaned is None:
        return "invalid", 0
    valid_turn = turn_id_from(turn_id) if turn_id is not None else None
    if turn_id is not None and valid_turn is None:
        return "invalid", 0
    if not actor or (session_id is None and valid_turn is None):
        return "no_active_turn", 0
    with _lock:
        candidates = [
            entry for entry in _live
            if entry.active
            and entry.actor == actor
            and (session_id is None or entry.session_id == session_id)
            and (valid_turn is None or entry.turn_id == valid_turn)
        ]
    if not candidates:
        return "no_active_turn", 0
    return _deliver(candidates[-1], cleaned)


def steer_owner_session(session_id: str | None, message: str) -> tuple[str, int]:
    """Deliver mid-turn owner guidance to the owner's active turn in *session_id*."""
    cleaned = _clean_message(message)
    if cleaned is None:
        return "invalid", 0
    sid = str(session_id or "").strip()
    if not sid:
        return "no_active_turn", 0
    with _lock:
        candidates = [
            entry for entry in _live
            if entry.active and entry.owner and entry.session_id == sid
        ]
    if not candidates:
        return "no_active_turn", 0
    return _deliver(candidates[-1], cleaned)


def active_steer_turns() -> int:
    """Count of currently tracked steerable turns (diagnostics/tests)."""
    with _lock:
        return sum(1 for entry in _live if entry.active)
