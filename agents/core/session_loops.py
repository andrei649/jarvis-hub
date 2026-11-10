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


async def loop_command(ctx: Any) -> str:
    """``/loop`` and ``/proactive`` (owner)."""
    if not ctx.principal.admin:
        return "Only the owner can set or change a loop; nothing changed."
    session = getattr(ctx.orch, "session_id", None)
    if not session:
        return "A loop belongs to a conversation, and there is no conversation here."
    loops = _loops()

    def run() -> dict:
        manager = loops.LoopManager(str(session))
        return loops.dispatch_loop_command(manager, ctx.args or "", route=_route_of(ctx.principal))

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
    return output


def _audit(orch: Any, action: str, why: str) -> None:
    log = getattr(orch, "intent_log", None)
    if log is None:
        return
    try:
        log.record(actor="loop", action=action, why=why, metadata={})
    except Exception:  # noqa: BLE001
        logger.debug("loop audit failed", exc_info=True)


# ── the watcher ──────────────────────────────────────────────────────────────────────


def _session_busy(orch: Any, session_id: str) -> bool:
    rows = getattr(orch, "turn_holders", None)
    try:
        holders = rows() if callable(rows) else []
    except Exception:  # noqa: BLE001 — cannot tell: treat as busy (leave the tick due)
        return True
    return any(str(row.get("session_id")) == session_id for row in holders)


def _goal_probe(orch: Any):
    def probe(_session_id: str) -> bool:
        ledger = getattr(orch, "work_runs", None)
        if ledger is None:
            return False
        from .goal_commands import _paused, _running

        return any(not _paused(run) for run in _running(ledger))

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
    ledger.start(float(getattr(state, "created_at", 0.0) or time.time()))
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


async def _pause(orch: Any, session_id: str, manager: Any, reason: str) -> None:
    route = dict(getattr(manager.state, "route", {}) or {})
    state = await asyncio.to_thread(manager.pause, reason)
    if state is not None:
        _audit(orch, "loop.paused", f"session {session_id}: {reason}")
        await _notify(orch, session_id, f"⏸ Loop paused — {reason}. /loop resume continues it, /loop stop ends it.",
                      route)


async def run_tick(orch: Any, session_id: str, *, now: float | None = None) -> dict:
    """One watcher pass for one session's loop. Returns what happened (for tests and logs)."""
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
    if _session_busy(orch, session_id):
        return {"ran": False, "why": "busy"}
    compat_goals.set_goal_probe(_goal_probe(orch))
    if await asyncio.to_thread(loops.goal_blocks_loop_tick, session_id):
        return {"ran": False, "why": "goal"}
    allowed, reason = tick_decision(orch, session_id, state, now=now)
    if not allowed:
        await _pause(orch, session_id, manager, reason)
        return {"ran": False, "why": "kernel", "reason": reason}
    message = await asyncio.to_thread(manager.fire_tick)
    if not message:
        return {"ran": False, "why": "not_due"}
    from .commands import Principal
    from .orchestrator import bind_turn_principal, reset_turn_principal

    principal = Principal(channel=route.get("channel") or "loop", sender=route.get("sender") or None,
                          admin=True, chat=route.get("chat") or None, scope=route.get("scope") or "dm")
    token = bind_turn_principal(principal)
    try:
        reply = await orch.handle_input(message, channel=principal.channel, session_id=session_id)
    except Exception:
        logger.warning("loop tick for %s failed; it is retried on the next pass", session_id, exc_info=True)
        await asyncio.to_thread(manager.abandon_tick)
        return {"ran": False, "why": "turn_failed"}
    finally:
        reset_turn_principal(token)
    reply = str(reply or "")
    delivered = await _deliver(orch, route, reply)
    until = str(getattr(manager.state, "until", "") or "")
    verdict, why = await _judge(orch, until, reply) if until else ("continue", "")
    with compat_goals.judge_scope(until, reply, verdict, why):
        result = await asyncio.to_thread(manager.complete_tick, reply)
    if result.get("message"):
        await _notify(orch, session_id, str(result["message"]), route)
    if result.get("stopped"):
        _audit(orch, f"loop.{result.get('status')}", f"session {session_id}: {result.get('reason')}")
    return {"ran": True, "status": result.get("status"), "stopped": bool(result.get("stopped")),
            "reason": result.get("reason"), "message": result.get("message", ""), "delivered": delivered}


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
