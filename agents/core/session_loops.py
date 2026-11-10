"""``/loop`` — a repeating prompt inside the conversation you are in (H460, H578).

The state machine is Hermes's own ``hermes_cli/loops.py``, adopted as is (the Adopt lane:
``agents/vendor/hermes/hermes_cli/loops.py`` behind ``hermes_compat.goals`` and
``hermes_compat.loops_config``): the ``/loop [interval] <prompt> [--times N] [--until …]``
grammar, ``status``/``pause``/``resume``/``stop``, a fixed cadence with a 30 s floor, the
self-paced mode that doubles from 60 s to 15 min while the reply's digest (clock and
duration tokens stripped) does not change and snaps back when it does, the stop order
``LOOP_COMPLETE`` → ``--until`` judge (fail-open) → ``--times`` → the ``max_ticks``
backstop (which pauses, not finishes), and per-session state that a restart restores.

What is Nerva's is everything that makes a tick an ordinary governed turn:

* **Owner only.** ``/loop`` is an owner command; a tick runs as the owner on the channel
  and session the loop was set from, and nobody else's turn can start or steer one.
* **Every tick crosses the Action Kernel** (``session.loop_tick``) before it runs: the
  kill switch, plan mode, the approval mode (``off`` makes nothing auto-run, so the loop
  pauses) and the loop's own budget ledger (wall time since it was set, and its tick
  count) can each deny it, and a denial *pauses* the loop with the reason. Inside the
  tick, every tool call goes through the same gates as a typed message.
* **The emergency stop pauses every loop** (``e-stop engaged``) — pause, not kill, as
  Hermes's Ctrl+C; ``/loop resume`` continues after the owner lifts it.
* **The watcher never fires mid-turn.** It scans every 15 s (the heartbeat scheduler's
  seam) and skips — leaving the tick due — while the session has a running turn, while
  an active goal run owns the boundary, or when the loop has no route.
* The ``--until`` judge is a strict-local auxiliary one-shot with no tools, asked before
  ``complete_tick``; its verdict is handed to the adopted code through
  ``hermes_compat.goals.judge_scope``. A judge that cannot answer is "continue"
  (fail-open, as upstream), and the tick cap still bounds the loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("jarvis.session_loops")

TICK_KIND = "session.loop_tick"
SCAN_SECONDS = 15
#: Wall time a loop may run from when it was set before the kernel's budget pauses it.
DEFAULT_MAX_WALL_SECONDS = 24 * 3600
_JUDGE_SYSTEM = (
    "You judge whether a stop condition is met, from a report you are shown. Answer with "
    "one word on the first line — DONE, CONTINUE or BLOCKED — and a short reason on the "
    "second. DONE only when the report shows concrete evidence the condition holds; "
    "BLOCKED only when it shows the condition cannot be met."
)


def _loops():
    """The adopted loop module, with Nerva's per-session store installed behind it."""
    from agents.vendor.hermes.hermes_cli import loops
    from agents.vendor.hermes_compat import goals as compat_goals

    if compat_goals._get_session_db() is None:
        from .session_meta import default_store

        compat_goals.set_session_db(default_store())
    return loops


def _route_of(principal: Any) -> dict[str, str]:
    return {
        "channel": str(getattr(principal, "channel", "") or ""),
        "chat": str(getattr(principal, "chat", "") or ""),
        "sender": str(getattr(principal, "sender", "") or ""),
        "scope": str(getattr(principal, "scope", "") or "dm"),
    }


_BUDGET_PREFIX = "loopbudget:"
_RESUME_WORDS = frozenset({"resume"})


def _budget_since(session_id: str) -> float | None:
    """When this loop's current allotment started: when it was set, or last resumed."""
    from agents.vendor.hermes_compat import goals as compat_goals

    store = compat_goals._get_session_db()
    raw = store.get_meta(_BUDGET_PREFIX + session_id) if store is not None else None
    try:
        return float(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _set_budget_since(session_id: str, when: float) -> None:
    from agents.vendor.hermes_compat import goals as compat_goals

    store = compat_goals._get_session_db()
    if store is not None:
        store.set_meta(_BUDGET_PREFIX + session_id, repr(float(when)))


async def loop_command(ctx: Any) -> str:
    """``/loop`` and ``/proactive`` (owner).

    Refused in a group: a wakeup runs with the owner's authority and its answer goes
    back to the chat it was set from, and a group is not the owner's own chat."""
    if not ctx.principal.admin:
        return "Only the owner can set or change a loop; nothing changed."
    if str(getattr(ctx.principal, "scope", "dm") or "dm") != "dm":
        return ("A loop runs as you and answers in the chat it was set from, so it is set only "
                "in a direct conversation with you, never in a group. Nothing changed.")
    session = getattr(ctx.orch, "session_id", None)
    if not session:
        return "A loop belongs to a conversation, and there is no conversation here."
    loops = _loops()
    word = (ctx.args or "").strip().lower()

    def run() -> dict:
        manager = loops.LoopManager(str(session))
        if word in _RESUME_WORDS:
            return _resume(loops, manager, str(session))
        result = loops.dispatch_loop_command(manager, ctx.args or "", route=_route_of(ctx.principal))
        if result.get("created") and manager.state is not None:
            state = manager.state
            # An explicit --times above the backstop is the owner's own cap: it wins.
            if state.times and state.max_ticks and state.times > state.max_ticks:
                state.max_ticks = int(state.times)
                manager._save()
            _set_budget_since(str(session), float(state.created_at or time.time()))
        return result

    try:
        result = await asyncio.to_thread(run)
    except Exception:
        logger.warning("/loop failed", exc_info=True)
        return "The loop could not be saved; nothing changed."
    output = str(result.get("output") or "")
    if result.get("created"):
        _audit(ctx.orch, "loop.set", f"session {session}")
        output += ("\nEach wakeup runs as an ordinary turn through the Action Kernel; the "
                   "emergency stop, plan mode or approval mode off pauses it.")
    elif word in _RESUME_WORDS and result.get("resumed"):
        _audit(ctx.orch, "loop.resumed", f"session {session}")
    return output


def _resume(loops, manager, session_id: str) -> dict:
    """``/loop resume``: the adopted resume, plus a fresh allotment — the wall-time budget
    counts from now, and a loop paused by its tick cap gets another full cap."""
    state = manager.state
    if state is not None and state.status == "paused" and state.max_ticks \
            and state.ticks_fired >= state.max_ticks:
        state.max_ticks = int(state.ticks_fired) + loops.max_ticks_default()
    resumed = manager.resume()
    if resumed is None:
        return {"output": "No loop to resume.", "resumed": False}
    _set_budget_since(session_id, time.time())
    return {"output": f"▶ Loop resumed ({resumed.cadence_label()}): {resumed.prompt}", "resumed": True}


def _audit(orch: Any, action: str, why: str) -> None:
    log = getattr(orch, "intent_log", None)
    if log is None:
        return
    try:
        log.record(actor="loop", action=action, why=why, metadata={})
    except Exception:  # noqa: BLE001
        logger.debug("loop audit failed", exc_info=True)


# ── the watcher ──────────────────────────────────────────────────────────────────────


def _session_busy(orch: Any, session_id: str, route: dict | None = None, *,
                  include_session: bool = True) -> bool:
    """A turn holds this conversation: its session, or (for a chat channel) the chat's
    route, whose lease a channel turn takes before it picks the live session."""
    rows = getattr(orch, "turn_holders", None)
    try:
        holders = rows() if callable(rows) else []
    except Exception:  # noqa: BLE001 — cannot tell: treat as busy (leave the tick due)
        return True
    keys = {session_id} if include_session else set()
    base = _route_base(route)
    if base:
        keys.add(base)
    return any(str(row.get("session_id")) in keys for row in holders)


def _route_base(route: dict | None) -> str | None:
    """The channel route key (``build_session_key``) a chat's turns lease first."""
    if not route or not route.get("channel") or route.get("channel") in _LOCAL_OWNER_SURFACES:
        return None
    try:
        from .channels.session import SessionSource, build_session_key

        return build_session_key(SessionSource(channel=route["channel"], sender=route.get("sender") or None,
                                               thread_id=route.get("chat") or None))
    except Exception:  # noqa: BLE001
        return None


def _goal_probe(orch: Any):
    """Whether a goal owns this conversation's turn boundary. Hermes's /goal injects its own
    turns into the session, so a loop tick waits for it. Nerva's goal runs (company mode)
    are worked in their own steps and never take a turn in a conversation, so no goal owns
    a session's boundary and a loop never waits for one. The probe stays the seam: a
    session-bound goal would answer here."""
    def probe(_session_id: str) -> bool:
        return False

    return probe


def tick_decision(orch: Any, session_id: str, state: Any, *, now: float | None = None, kernel=None):
    """May this tick run? ``(allowed, reason)``.

    With the Action Kernel on (``JARVIS_ACTION_KERNEL``), the tick is a
    ``session.loop_tick`` action through ``kernel.authorize`` (bound to the live kill
    switch, policy and audit, plus this loop's own budget ledger). With it off (the
    default) the same floors are read directly, so a loop is never less bounded than a
    turn: the kill switch, plan mode, the loop's budget and approval mode ``off``."""
    from .kernel import Action, Verdict, kernel_enabled
    from .kernel.binding import make_action_kernel
    from .kernel.budget import BudgetLedger, BudgetLimits
    from .llm.request_context import session_scope

    ledger = BudgetLedger(limits=BudgetLimits(max_wall_seconds=float(DEFAULT_MAX_WALL_SECONDS)))
    since = _budget_since(session_id) if session_id else None
    ledger.start(float(since or getattr(state, "created_at", 0.0) or time.time()))
    max_ticks = int(getattr(state, "max_ticks", 0) or 0)
    if max_ticks:
        # The tick about to fire counts: ticks_fired + 1 may not exceed the backstop.
        ledger.register_dimension("loop_ticks", limit=max_ticks,
                                  used=int(getattr(state, "ticks_fired", 0) or 0) + 1, unit="ticks")
    action = Action(kind=TICK_KIND, agent="jarvis", title="Loop wakeup",
                    payload={"session_id": session_id,
                             "tick": int(getattr(state, "ticks_fired", 0) or 0) + 1, "risk_tier": 0},
                    origin="generated")
    if kernel_enabled():
        if kernel is None:
            kernel = make_action_kernel(orch, budget_ledger=ledger)
            if kernel is None:
                return False, "no autonomy policy to authorize the tick"
            call = lambda: kernel(action, now=now)  # noqa: E731
        else:
            call = lambda: kernel(action)  # noqa: E731 — an injected hook takes the action alone
        with session_scope(session_id):           # plan mode is judged for the loop's session
            decision = call()
        if decision.verdict is Verdict.GRANT:
            return True, ""
        if decision.verdict is Verdict.QUEUE:
            return False, f"the approval mode does not let it run by itself ({decision.reason})"
        return False, decision.reason or "denied by the Action Kernel"
    # Kernel off: the same floors, read directly.
    switch = getattr(orch, "kill_switch", None)
    try:
        if switch is not None and switch.is_halted(action.scope):
            return False, f"kill-switch engaged for scope '{action.scope}'"
    except Exception:  # noqa: BLE001 — a switch that cannot be read is a halt
        return False, "the kill switch cannot be read"
    from .kernel.plan_mode import action_denial

    planned = action_denial(TICK_KIND, action.payload, session_id=session_id)
    if planned:
        return False, planned
    over = ledger.exceeded(now)
    if over:
        return False, f"budget: {over}"
    policy = getattr(getattr(orch, "autonomy", None), "policy", None) or getattr(orch, "autonomy_policy", None)
    if policy is not None:
        try:
            mode = policy.effective_mode("jarvis")
        except Exception:  # noqa: BLE001
            mode = "off"
        if mode == "off":
            return False, "the approval mode is off, so nothing runs by itself"
    return True, ""


async def _judge(orch: Any, until: str, reply: str) -> tuple[str, str]:
    """``(verdict, reason)`` from a strict-local one-shot; ``continue`` when it cannot say."""
    router = getattr(orch, "llm_router", None)
    if router is None or not until or not (reply or "").strip():
        return "continue", "judge unavailable"
    from .llm.auxiliary_text import run_oneshot

    prompt = f"Stop condition: {until[:500]}\n\nReport:\n{reply[-6000:]}"
    try:
        answer = await run_oneshot(router, prompt, system=_JUDGE_SYSTEM, purpose="loop_judge",
                                   max_tokens=60, temperature=0.0)
    except Exception:  # noqa: BLE001 — fail-open, as upstream
        return "continue", "judge unavailable"
    lines = [line.strip() for line in str(answer or "").strip().splitlines() if line.strip()]
    if not lines:
        return "continue", "judge gave no verdict"
    word = lines[0].split()[0].strip(".:!").upper() if lines[0].split() else ""
    verdict = {"DONE": "done", "BLOCKED": "blocked"}.get(word, "continue")
    return verdict, (lines[1] if len(lines) > 1 else lines[0])[:200]


#: Channels whose replies the HUD or the CLI read from the session itself.
_SESSION_SURFACES = frozenset({"", "web", "cli", "loop", "voice"})
#: Channels whose replies go through the governed workspace reply path (``channel.reply``);
#: a loop does not push to them on its own.
_GOVERNED_REPLY_CHANNELS = frozenset({"slack", "discord", "email"})


async def _deliver(orch: Any, route: dict, text: str) -> bool:
    """Push *text* to the chat the loop was set from (Telegram, ntfy, …) through the
    channel manager's own send contract. The HUD and the CLI read the session instead;
    Slack, Discord and email replies stay on their governed path and are not pushed."""
    channel = str((route or {}).get("channel") or "")
    if not text or channel in _SESSION_SURFACES or channel in _GOVERNED_REPLY_CHANNELS:
        return False
    manager = getattr(orch, "channel_manager", None)
    send = getattr(manager, "send", None)
    if not callable(send):
        return False
    delivery = {"chat_id": route["chat"]} if route.get("chat") else {}
    try:
        return bool(await send(channel, text, **delivery, voice=False, plain=True))
    except Exception:  # noqa: BLE001 — a failed push never stops the loop
        logger.warning("loop reply could not be delivered on %s", channel, exc_info=True)
        return False


async def _notify(orch: Any, session_id: str, message: str, route: dict | None = None) -> None:
    memory = getattr(orch, "memory", None)
    if not message:
        return
    if memory is not None:
        try:
            await memory.add_turn(session_id, "assistant", message, agent_id="commands")
        except Exception:  # noqa: BLE001
            logger.debug("loop notice not stored", exc_info=True)
    await _deliver(orch, route or {}, message)


async def _pause(orch: Any, session_id: str, manager: Any, reason: str, *, to_chat: bool = True) -> None:
    """Pause with the reason: noted in the session (the HUD and /recap show it), audited, and
    sent to the chat unless *to_chat* is False — a chat whose owner is no longer confirmed
    is told nothing."""
    route = dict(getattr(manager.state, "route", {}) or {}) if to_chat else {}
    state = await asyncio.to_thread(manager.pause, reason)
    if state is not None:
        _audit(orch, "loop.paused", f"session {session_id}: {reason}")
        await _notify(orch, session_id, f"⏸ Loop paused — {reason}. /loop resume continues it, /loop stop ends it.",
                      route)


async def run_tick(orch: Any, session_id: str, *, now: float | None = None) -> dict:
    """One watcher pass for one session's loop. Returns what happened (for tests and logs).

    The whole tick — the wakeup turn, the push to the chat, the --until judge and the
    bookkeeping — holds the session's turn lease, so a conversation change (/undo, /new,
    /reset, a rollover) waits for it or skips the session, and never moves a loop whose
    wakeup is still in flight."""
    if _session_busy(orch, session_id, None):
        return {"ran": False, "why": "busy"}
    lease = getattr(orch, "turn_lease", None)
    if not callable(lease):
        return await _run_tick_held(orch, session_id, now=now)
    async with lease(session_id) as held:
        if not held:
            return {"ran": False, "why": "busy"}
        return await _run_tick_held(orch, session_id, now=now)


async def _run_tick_held(orch: Any, session_id: str, *, now: float | None = None) -> dict:
    from agents.core import estop
    from agents.vendor.hermes_compat import goals as compat_goals

    loops = _loops()
    manager = await asyncio.to_thread(loops.LoopManager, session_id)
    if not manager.is_due():
        return {"ran": False, "why": "not_due"}
    state = manager.state
    if estop.get_state() is not None:
        await _pause(orch, session_id, manager, "e-stop engaged")
        return {"ran": False, "why": "estop"}
    route = dict(getattr(state, "route", {}) or {})
    if not route.get("channel"):
        return {"ran": False, "why": "no_route"}
    if _session_busy(orch, session_id, route, include_session=False):    # we hold the session
        return {"ran": False, "why": "busy"}
    compat_goals.set_goal_probe(_goal_probe(orch))
    if await asyncio.to_thread(loops.goal_blocks_loop_tick, session_id):
        return {"ran": False, "why": "goal"}
    allowed, reason = tick_decision(orch, session_id, state, now=now)
    if not allowed:
        await _pause(orch, session_id, manager, reason)
        return {"ran": False, "why": "kernel", "reason": reason}
    principal, refused = _tick_principal(orch, route)
    if principal is None:
        await _pause(orch, session_id, manager, refused, to_chat=False)
        return {"ran": False, "why": "owner", "reason": refused}
    message = await asyncio.to_thread(manager.fire_tick)
    if not message:
        return {"ran": False, "why": "not_due"}
    from .orchestrator import bind_turn_principal, reset_turn_principal

    token = bind_turn_principal(principal)
    try:
        reply = await orch.handle_input(message, channel=principal.channel, session_id=session_id)
    except asyncio.CancelledError:
        # Cancelled mid-turn: the tick may have acted, so it counts; the loop is not left
        # waiting for a reply that will never come.
        _release_tick(manager)
        raise
    except Exception:
        logger.warning("loop tick for %s failed; it counts, and the loop goes on", session_id, exc_info=True)
        await asyncio.to_thread(_release_tick, manager)
        return {"ran": False, "why": "turn_failed"}
    finally:
        reset_turn_principal(token)
    reply = str(reply or "")
    from .orchestrator import is_failed_turn_reply

    failed = is_failed_turn_reply(None, reply)
    delivered = await _deliver(orch, route, reply) if not failed else False
    _touch_route(orch, route)
    until = str(getattr(manager.state, "until", "") or "")
    # As Hermes: a loop whose prompt is a slash command is not judged on the command's
    # output (no LOOP_COMPLETE, no --until verdict, no digest); the caps still apply.
    command_loop = message.lstrip().startswith("/")
    # A failed turn's text (a backend-failure reply) is not judged either.
    evaluated = "" if command_loop or failed else reply
    if until and evaluated:
        verdict, why = await _judge(orch, until, evaluated)
    else:
        verdict, why = "continue", ""
    # Re-read the row before completing: if the loop was stopped or moved meanwhile, this
    # tick's state is not written back over it.
    fresh = await asyncio.to_thread(loops.load_loop, session_id)
    if fresh is None or fresh.status != "active" or not fresh.awaiting_response:
        return {"ran": True, "status": getattr(fresh, "status", None), "stopped": False,
                "reason": "the loop changed during the wakeup; nothing written back",
                "message": "", "delivered": delivered}
    manager._state = fresh
    with compat_goals.judge_scope(until, evaluated, verdict, why):
        result = await asyncio.to_thread(manager.complete_tick, evaluated)
    if result.get("message"):
        await _notify(orch, session_id, str(result["message"]), route)
    if result.get("stopped"):
        _audit(orch, f"loop.{result.get('status')}", f"session {session_id}: {result.get('reason')}")
    return {"ran": True, "status": result.get("status"), "stopped": bool(result.get("stopped")),
            "reason": result.get("reason"), "message": result.get("message", ""), "delivered": delivered}


def _touch_route(orch: Any, route: dict) -> None:
    """A wakeup is activity on its chat: the chat's route does not idle-roll under a loop
    that is still talking in it. Only an existing, active route is touched."""
    base = _route_base(route)
    if not base:
        return
    try:
        from .channels.session_lifecycle import lifecycle

        service = lifecycle(orch)
        state = service.store.state(base)
        if state.active:
            service.store.touch(base, service.now(), state.channel, state.kind)
    except Exception:  # noqa: BLE001 — bookkeeping only
        logger.debug("loop route activity not recorded", exc_info=True)


def _release_tick(manager: Any) -> None:
    """A fired tick whose turn raised: it counts toward the caps (it may have acted), and
    the loop stops waiting for it, so the next tick comes at its provisional due time."""
    state = manager.state
    if state is not None and state.awaiting_response:
        state.awaiting_response = False
        manager._save()


#: The surfaces whose owner is whoever holds the hub's admin credential (the HUD, the CLI):
#: a loop set there keeps running as the owner in that session, and its answers are read
#: from the session. Any chat channel is re-judged on every tick.
_LOCAL_OWNER_SURFACES = frozenset({"web", "cli", "voice", "loop"})


def _tick_principal(orch: Any, route: dict):
    """``(principal, None)`` for this tick, or ``(None, reason)`` when the chat the loop was
    set from is no longer the owner's. A chat channel's owner is decided again, now, by
    the check a typed message gets (``Orchestrator._channel_principal``: the owner ids,
    the pairing, a running adapter); the saved route grants nothing by itself."""
    from .commands import Principal

    channel = str(route.get("channel") or "")
    scope = str(route.get("scope") or "dm")
    if scope != "dm":
        return None, "a loop runs only in a direct conversation with the owner"
    if channel in _LOCAL_OWNER_SURFACES:
        return Principal(channel=channel, sender=route.get("sender") or None, admin=True,
                         chat=route.get("chat") or None, scope="dm"), None
    judge = getattr(orch, "_channel_principal", None)
    if not callable(judge):
        return None, f"the owner on {channel} could not be confirmed"
    try:
        principal = judge(channel, route.get("sender") or None, route.get("chat") or None, "private")
    except Exception:  # noqa: BLE001 — cannot confirm the owner: fail closed
        logger.warning("loop owner check failed on %s", channel, exc_info=True)
        principal = None
    if principal is None or getattr(principal, "admin", False) is not True:
        return None, f"the sender on {channel} is no longer confirmed as the owner"
    return principal, None


async def scan(orch: Any, *, now: float | None = None) -> list[dict]:
    """The watcher: one pass over every active loop. Never raises."""
    loops = _loops()
    try:
        active = await asyncio.to_thread(loops.list_active_loops)
    except Exception:  # noqa: BLE001
        logger.warning("loop scan could not read the loop store", exc_info=True)
        return []
    out = []
    for session_id, _state in active:
        try:
            out.append({"session_id": session_id, **await run_tick(orch, session_id, now=now)})
        except Exception:  # noqa: BLE001
            logger.warning("loop scan failed for %s", session_id, exc_info=True)
    return out


async def pause_all(reason: str) -> int:
    """Pause every active loop (the e-stop path calls this through the watcher)."""
    loops = _loops()
    count = 0
    for session_id, _state in await asyncio.to_thread(loops.list_active_loops):
        manager = await asyncio.to_thread(loops.LoopManager, session_id)
        if await asyncio.to_thread(manager.pause, reason) is not None:
            count += 1
    return count


def migrate_session(old_session: str, new_session: str, *, channel: str | None = None) -> dict:
    """A conversation moved to a new session id (/undo, /new, /reset, a chat's idle or daily
    rollover): its loop and its plan mode move with it, as Hermes's
    ``migrate_loop_to_session`` carries a loop across a rotation. With *channel*, a loop
    moves only when it was set from that channel (a chat's rollover never takes the HUD's
    loop). A wakeup still in flight is never moved; its run_tick holds the session lease,
    and a row moved anyway arrives with no wakeup pending. Never raises."""
    out = {"loop": False, "plan_mode": False}
    if not old_session or not new_session or old_session == new_session:
        return out
    try:
        from .kernel import plan_mode

        out["plan_mode"] = plan_mode.migrate(str(old_session), str(new_session))
    except Exception:  # noqa: BLE001
        logger.warning("plan mode could not follow %s -> %s", old_session, new_session, exc_info=True)
    try:
        loops = _loops()
        state = loops.load_loop(str(old_session))
        if state is None or (channel is not None
                             and str((state.route or {}).get("channel") or "") != str(channel)):
            return out
        moved = loops.migrate_loop_to_session(str(old_session), str(new_session), reason="session change")
        if moved:
            carried = loops.LoopManager(str(new_session))
            if carried.state is not None and carried.state.awaiting_response:
                carried.state.awaiting_response = False
                carried._save()
            since = _budget_since(str(old_session))
            if since is not None:
                _set_budget_since(str(new_session), since)
        out["loop"] = bool(moved)
    except Exception:  # noqa: BLE001
        logger.warning("loop could not follow %s -> %s", old_session, new_session, exc_info=True)
    return out
