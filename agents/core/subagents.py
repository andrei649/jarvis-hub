"""
subagents.py — H20.6 Dynamic sub-agent delegation (+ steerable workers).

Extends the author-defined parallelism of the WorkflowEngine (H5.6) to
**agent-initiated** spawning: at runtime an agent can delegate a piece of work to
an **isolated** sub-agent (its own session), **concurrently**, under a
configurable **cap** (the gate — an agent can't fork unbounded work). Each
sub-agent runs through an INJECTABLE runner (the orchestrator's dispatch in
prod; a stub offline), so the governance/isolation layer is offline-testable.

Company-mode additions (co-subagent-steer):

* **steer / stop** — a running child has a per-spawn :class:`SteerChannel`
  inbox. Runners that accept a ``steer`` kwarg receive it (additive contract,
  like ``blocked``); ``stop()`` cancels the child task. Steer messages carry a
  declared *origin* (``user`` from the guarded HTTP surface, ``agent`` for
  inter-agent messages) and are **never** an approval — see :meth:`decide`.
* **typed output** — ``spawn(..., output_schema=...)`` validates the runner's
  result with :func:`validate_output` (type / required / enum only, no new
  dependency); a violation surfaces as a ``failed`` spawn, not a silent pass.
* **cost per delegation** — tokens/cost are attributed per spawn from the
  runner's ``usage`` (exact) or, failing that, from the cost-tracker delta
  around the run (best-effort; concurrent spawns can share a delta).
* **spawn persistence (observability only)** — finished spawn records are
  appended to ``data_path("subagents", "spawns.jsonl")`` when the
  ``JARVIS_SUBAGENT_SPAWN_LOG`` flag is on (default off). Nothing is replayed
  from it: sub-agents remain NOT the company unit — child queue rows are.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .env_config import env_flag
from .iteration_budget import IterationBudget

logger = logging.getLogger("jarvis.subagents")

# Capabilities a sub-agent must NOT exercise, regardless of what the runner can
# do. Adapted from hermes-agent `DELEGATE_BLOCKED_TOOLS` (Nous Research, MIT):
# no recursive delegation, no writes to shared memory cores, no outbound
# channel sends, no skill authoring, no user clarification round-trips. The
# list is recorded on every spawn and handed to runners that accept a
# `blocked` kwarg; runners that don't are unchanged (additive contract).
DELEGATE_BLOCKED_CAPABILITIES = frozenset({
    "delegate", "memory_write", "channel_send", "skill_manage", "clarify",
})

# Declared provenance of a steer message. `user` = the guarded HTTP surface
# (an operator typing at a running worker); `agent` = another agent / the
# parent talking to its child. Neither is an approval — approvals only ever
# come from a human decision on a queue row (worker.apply_decision).
STEER_ORIGINS = frozenset({"user", "agent"})
STEER_MAX_CHARS = 4000

# Default-off persistence flag (observability only).
SPAWN_LOG_ENV = "JARVIS_SUBAGENT_SPAWN_LOG"

# Spawn lifecycle. `stopping` is the window between stop() and the child task
# unwinding; every other move is a terminal write.
SPAWN_TRANSITIONS: dict[str, frozenset] = {
    "running": frozenset({"done", "failed", "stopping", "stopped"}),
    "stopping": frozenset({"stopped", "failed", "done"}),
    "done": frozenset(),
    "failed": frozenset(),
    "stopped": frozenset(),
}
TERMINAL_STATUSES = frozenset({"done", "failed", "stopped"})

# JSON-schema-ish type names the validator understands (no external dependency).
_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class NullRunner:
    """Offline default — echoes the task without a real agent."""

    async def __call__(self, task: str, session_id: str, agent: str) -> dict:
        return {"output": f"[stub:{agent or 'sub'}] {task}", "session_id": session_id}


def _runner_accepts(runner, name: str) -> bool:
    """Whether the injected runner declares kwarg *name* (additive opt-in)."""
    try:
        if inspect.isfunction(runner) or inspect.ismethod(runner):
            target = runner
        elif callable(runner):
            target = runner.__call__
        else:
            target = runner
        params = inspect.signature(target).parameters
        return name in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        return False


def _runner_accepts_blocked(runner) -> bool:
    """Whether the injected runner declares a `blocked` kwarg (additive opt-in)."""
    return _runner_accepts(runner, "blocked")


@dataclass(frozen=True)
class SteerMessage:
    """One steer delivered to a running child. Immutable, origin-validated."""

    spawn_id: str
    text: str
    origin: str = "user"
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.spawn_id, str) or not self.spawn_id:
            raise ValueError("steer requires a spawn_id")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("steer text must be a non-empty string")
        if len(self.text) > STEER_MAX_CHARS:
            raise ValueError(f"steer text exceeds {STEER_MAX_CHARS} chars")
        if self.origin not in STEER_ORIGINS:
            raise ValueError(f"steer origin must be one of {sorted(STEER_ORIGINS)}")

    def to_dict(self) -> dict:
        # `can_approve` is a hard-coded False on purpose: a runner reading its
        # inbox can never mistake a steer for a human decision.
        return {"spawn_id": self.spawn_id, "text": self.text, "origin": self.origin,
                "ts": self.ts, "can_approve": False}


class SteerChannel:
    """Per-spawn inbox handed to runners that accept a ``steer`` kwarg.

    A runner drains it with :meth:`poll` (non-blocking) between its own steps,
    or awaits :meth:`get` when it wants to block for guidance. ``stop_requested``
    flips when the manager begins cancelling the child, so a cooperative runner
    can wind down before the CancelledError lands."""

    def __init__(self, spawn_id: str) -> None:
        self.spawn_id = spawn_id
        self._q: asyncio.Queue = asyncio.Queue()
        self.stop_requested = False
        self.delivered: list[dict] = []

    def push(self, msg: SteerMessage) -> None:
        self._q.put_nowait(msg.to_dict())

    def poll(self) -> list[dict]:
        out: list[dict] = []
        while True:
            try:
                item = self._q.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.delivered.append(item)
            out.append(item)
        return out

    async def get(self, timeout: Optional[float] = None) -> Optional[dict]:
        try:
            if timeout is None:
                item = await self._q.get()
            else:
                item = await asyncio.wait_for(self._q.get(), timeout)
        except TimeoutError:
            return None
        self.delivered.append(item)
        return item

    @property
    def pending(self) -> int:
        return self._q.qsize()


def validate_output(value: Any, schema: Any, path: str = "$") -> list[str]:
    """Validate *value* against a minimal schema: ``type`` / ``required`` / ``enum``
    (plus nested ``properties`` and ``items``). Returns a list of violations —
    empty means valid. Unknown keywords are ignored; a non-dict schema is a
    single violation rather than an exception."""
    if not isinstance(schema, dict):
        return [f"{path}: schema must be an object"]
    out: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        checks = [_TYPE_CHECKS.get(str(t)) for t in types]
        if any(c is None for c in checks):
            out.append(f"{path}: unknown type {expected!r}")
        elif not any(c(value) for c in checks if c is not None):
            out.append(f"{path}: expected type {expected!r}, got {type(value).__name__}")
            return out
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        out.append(f"{path}: value {value!r} not in enum {enum!r}")
    required = schema.get("required")
    if isinstance(required, list):
        if isinstance(value, dict):
            for key in required:
                if key not in value:
                    out.append(f"{path}: missing required property {key!r}")
        else:
            out.append(f"{path}: required properties on non-object")
    props = schema.get("properties")
    if isinstance(props, dict) and isinstance(value, dict):
        for key, sub in props.items():
            if key in value:
                out.extend(validate_output(value[key], sub, f"{path}.{key}"))
    items = schema.get("items")
    if isinstance(items, dict) and isinstance(value, list):
        for i, item in enumerate(value):
            out.extend(validate_output(item, items, f"{path}[{i}]"))
    return out


def _default_cost_probe() -> dict:
    """Read the live cost tracker (best-effort; empty when unavailable)."""
    try:
        from . import cost_tracker
        return cost_tracker.get_summary()
    except Exception:
        logger.debug("cost probe unavailable", exc_info=True)
        return {}


def _cost_totals(summary: Any) -> Optional[dict]:
    agents = summary.get("agents") if isinstance(summary, dict) else None
    if not isinstance(agents, dict):
        return None
    tot = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for data in agents.values():
        if not isinstance(data, dict):
            continue
        for k in ("input_tokens", "output_tokens"):
            try:
                tot[k] += int(data.get(k, 0) or 0)
            except (TypeError, ValueError):
                continue
        try:
            tot["cost_usd"] += float(data.get("cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    return tot


def _usage_from_result(result: Any) -> Optional[dict]:
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        return None
    try:
        return {"input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
                "cost_usd": round(float(usage.get("cost_usd", 0.0) or 0.0), 6),
                "source": "runner_usage"}
    except (TypeError, ValueError):
        return None


def _compact_for_log(rec: dict, limit: int = 2000) -> dict:
    """Bound the persisted line: long outputs are previewed, not stored whole."""
    out = {k: v for k, v in rec.items() if k != "result"}
    result = rec.get("result")
    if isinstance(result, dict):
        preview = dict(result)
        for k, v in list(preview.items()):
            if isinstance(v, str) and len(v) > limit:
                preview[k] = v[:limit] + "…"
        out["result"] = preview
    elif isinstance(result, str):
        out["result"] = result[:limit]
    else:
        out["result"] = result
    return out


class SubAgentManager:
    """Gated, isolated, concurrent, steerable sub-agent spawning."""

    def __init__(self, runner: Optional[Callable[..., Awaitable[dict]]] = None,
                 max_concurrent: int = 3, parent_agent: str = "jarvis",
                 max_depth: Optional[int] = 8,
                 budget: Optional["IterationBudget"] = None,
                 blocked: Optional[frozenset] = None,
                 cost_probe: Optional[Callable[[], dict]] = None,
                 spawn_log: Optional[Path] = None,
                 persist: Optional[bool] = None,
                 decision_hook: Optional[Callable[..., Awaitable[Any]]] = None) -> None:
        self._runner = runner or NullRunner()
        self.max_concurrent = max(1, int(max_concurrent))
        self.parent_agent = parent_agent
        # H20.6 hardening: total-spawn budget (refundable IterationBudget) on top
        # of the concurrency cap — None keeps today's unbounded-total behavior.
        self.budget = budget
        # Capability scoping for children (hermes DELEGATE_BLOCKED_TOOLS analog).
        self.blocked = frozenset(blocked) if blocked is not None else DELEGATE_BLOCKED_CAPABILITIES
        self._runner_takes_blocked = _runner_accepts_blocked(self._runner)
        self._runner_takes_steer = _runner_accepts(self._runner, "steer")
        # K3 (OWASP unbounded-consumption): cap the recursion DEPTH of agent-initiated
        # delegation — an agent spawning sub-agents that spawn sub-agents can't tower up
        # forever. None = unbounded. Depth is inferred from the recorded parent-chain, so
        # it needs no runner cooperation (the spawning sub-agent just passes its own id as
        # `parent`, which it already does to attribute the spawn).
        self.max_depth = max_depth if (max_depth is None or max_depth > 0) else None
        # Per-delegation cost: tracker snapshot around the run (injectable for tests).
        self._cost_probe = cost_probe or _default_cost_probe
        # Observability-only persistence (default off; env flag or explicit `persist`).
        self.persist = env_flag(SPAWN_LOG_ENV) if persist is None else bool(persist)
        self._spawn_log = Path(spawn_log) if spawn_log is not None else None
        self._log_lock = threading.Lock()
        # The only path from a spawn context to an approval decision. In prod the
        # integrator wires worker.apply_decision; `decide()` refuses agent-origin
        # requests before this hook is ever consulted.
        self._decision_hook = decision_hook
        self._spawns: dict[str, dict] = {}
        self._channels: dict[str, SteerChannel] = {}
        self._tasks: dict[str, asyncio.Future] = {}
        self._active = 0
        self._counter = 0

    # ── introspection ────────────────────────────────────────────
    def _active_count(self) -> int:
        return self._active

    def _depth_of(self, parent: str) -> int:
        """How deep a spawn under *parent* would sit (0 = top-level, i.e. parent is the
        root agent, not a recorded sub-agent). Walks the recorded parent links; the `seen`
        guard makes a malformed cycle terminate instead of spinning."""
        depth, cur, seen = 0, parent, set()
        while cur in self._spawns and cur not in seen:
            seen.add(cur)
            depth += 1
            cur = self._spawns[cur].get("parent", "")
        return depth

    def _set_status(self, rec: dict, new: str) -> None:
        cur = rec["status"]
        if new not in SPAWN_TRANSITIONS.get(cur, frozenset()):
            raise ValueError(f"illegal spawn transition {cur} -> {new}")
        rec["status"] = new

    # ── spawn ────────────────────────────────────────────────────
    async def spawn(self, task: str, agent: str = "", parent: str = "",
                    output_schema: Optional[dict] = None) -> dict:
        """Spawn an isolated sub-agent for `task`. Rejected if the concurrency cap is
        reached, the total-spawn budget is spent, or the parent-chain is already
        `max_depth` deep (recursion guard). With `output_schema`, the runner's result
        must validate or the spawn is recorded as failed."""
        parent = parent or self.parent_agent
        depth = self._depth_of(parent)
        if self.max_depth is not None and depth >= self.max_depth:
            return {"ok": False, "reason": "recursion_depth_cap",
                    "depth": depth, "max_depth": self.max_depth}
        if self._active >= self.max_concurrent:
            return {"ok": False, "reason": "concurrency_cap",
                    "active": self._active, "cap": self.max_concurrent}
        if output_schema is not None and not isinstance(output_schema, dict):
            return {"ok": False, "reason": "invalid_output_schema"}
        if self.budget is not None and not self.budget.consume():
            return {"ok": False, "reason": "spawn_budget_exhausted",
                    "used": self.budget.used, "max_total": self.budget.max_total}
        self._counter += 1
        spawn_id = f"sub-{parent}-{self._counter}"
        session_id = f"session::{spawn_id}"   # isolated session
        rec = {"id": spawn_id, "parent": parent, "agent": agent or "sub",
               "task": task, "session_id": session_id, "status": "running",
               "created_at": time.time(), "finished_at": None, "result": None,
               "blocked": sorted(self.blocked), "output_schema": output_schema,
               "steers": [], "steerable": self._runner_takes_steer,
               "stop_reason": None, "cost": None}
        self._spawns[spawn_id] = rec
        chan = SteerChannel(spawn_id)
        self._channels[spawn_id] = chan
        self._active += 1
        before = _cost_totals(self._safe_probe())
        child = asyncio.ensure_future(self._run(task, session_id, agent or "sub", chan))
        self._tasks[spawn_id] = child
        result: Any = None
        try:
            result = await child
        except asyncio.CancelledError:
            if rec["status"] == "stopping":
                self._set_status(rec, "stopped")
                rec["result"] = {"error": "stopped", "reason": rec.get("stop_reason")}
            else:
                # The *parent* was cancelled (the awaiting task went away): record it
                # honestly and let the cancellation keep propagating upward.
                rec["stop_reason"] = rec.get("stop_reason") or "parent_cancelled"
                self._set_status(rec, "stopped")
                rec["result"] = {"error": "stopped", "reason": rec["stop_reason"]}
                self._finish(rec, before, result)
                raise
        except Exception:
            logger.warning("sub-agent run failed", exc_info=True)
            self._set_status(rec, "failed")
            rec["result"] = {"error": "run failed"}
        else:
            violations = (validate_output(result, output_schema)
                          if output_schema is not None else [])
            if violations:
                self._set_status(rec, "failed")
                rec["result"] = {"error": "output_schema_violation",
                                 "violations": violations, "output": result}
            else:
                self._set_status(rec, "done")
                rec["result"] = result
        self._finish(rec, before, result)
        await self._persist(rec)
        return {"ok": rec["status"] == "done", "id": spawn_id,
                "session_id": session_id, "status": rec["status"],
                "result": rec["result"], "cost": rec["cost"]}

    async def _run(self, task: str, session_id: str, agent: str, chan: SteerChannel):
        kwargs: dict[str, Any] = {}
        if self._runner_takes_blocked:
            kwargs["blocked"] = self.blocked
        if self._runner_takes_steer:
            kwargs["steer"] = chan
        return await self._runner(task, session_id, agent, **kwargs)

    def _safe_probe(self) -> dict:
        try:
            return self._cost_probe() or {}
        except Exception:
            logger.debug("cost probe failed", exc_info=True)
            return {}

    def _finish(self, rec: dict, before: Optional[dict], result: Any) -> None:
        """Release the slot, close the channel, attribute cost — exactly once."""
        if rec.get("finished_at") is not None:
            return
        rec["finished_at"] = time.time()
        self._active -= 1
        self._channels.pop(rec["id"], None)
        self._tasks.pop(rec["id"], None)
        cost = _usage_from_result(result)
        if cost is None and before is not None:
            after = _cost_totals(self._safe_probe())
            if after is not None:
                cost = {"input_tokens": max(0, after["input_tokens"] - before["input_tokens"]),
                        "output_tokens": max(0, after["output_tokens"] - before["output_tokens"]),
                        "cost_usd": round(max(0.0, after["cost_usd"] - before["cost_usd"]), 6),
                        "source": "tracker_delta"}
        rec["cost"] = cost

    # ── persistence (observability only) ─────────────────────────
    def spawn_log_path(self) -> Path:
        if self._spawn_log is None:
            from .paths import data_path
            self._spawn_log = data_path("subagents", "spawns.jsonl")
        return self._spawn_log

    def _append_log(self, line: str) -> None:
        path = self.spawn_log_path()
        with self._log_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    async def _persist(self, rec: dict) -> None:
        if not self.persist:
            return
        try:
            line = json.dumps(_compact_for_log(rec), ensure_ascii=False, sort_keys=True,
                              default=str)
            await asyncio.to_thread(self._append_log, line)
        except Exception:
            logger.debug("spawn record not persisted", exc_info=True)

    # ── steer / stop ─────────────────────────────────────────────
    def steer(self, spawn_id: str, message: str, origin: str = "user") -> dict:
        """Deliver a steer message to a running child. Returns `delivered=False`
        (still ok) when the runner never opted into the `steer` kwarg — the
        message is recorded on the spawn either way."""
        rec = self._spawns.get(spawn_id)
        if rec is None:
            return {"ok": False, "reason": "unknown_spawn", "id": spawn_id}
        if rec["status"] != "running":
            return {"ok": False, "reason": "not_running", "id": spawn_id,
                    "status": rec["status"]}
        try:
            msg = SteerMessage(spawn_id=spawn_id, text=message, origin=origin)
        except ValueError as e:
            return {"ok": False, "reason": "invalid_steer", "detail": str(e), "id": spawn_id}
        rec["steers"].append(msg.to_dict())
        chan = self._channels.get(spawn_id)
        delivered = chan is not None and self._runner_takes_steer
        if chan is not None:
            chan.push(msg)
        return {"ok": True, "id": spawn_id, "delivered": delivered,
                "origin": origin, "pending": chan.pending if chan else 0}

    def stop(self, spawn_id: str, reason: str = "operator") -> dict:
        """Cancel a running child. The status is `stopping` until the child task
        unwinds (its awaiting `spawn()` records `stopped`)."""
        rec = self._spawns.get(spawn_id)
        if rec is None:
            return {"ok": False, "reason": "unknown_spawn", "id": spawn_id}
        if rec["status"] != "running":
            return {"ok": False, "reason": "not_running", "id": spawn_id,
                    "status": rec["status"]}
        rec["stop_reason"] = str(reason or "operator")[:80]
        self._set_status(rec, "stopping")
        chan = self._channels.get(spawn_id)
        if chan is not None:
            chan.stop_requested = True
        fut = self._tasks.get(spawn_id)
        if fut is not None and not fut.done():
            fut.cancel()
        return {"ok": True, "id": spawn_id, "status": rec["status"]}

    # ── approval seam ────────────────────────────────────────────
    async def decide(self, spawn_id: str, task_id: int, action: str,
                     origin: str = "agent") -> dict:
        """The ONLY route from a spawn context to a queue decision. Agent-origin
        requests (inter-agent steers, a child's own output) are refused before the
        injected `decision_hook` is consulted: a sub-agent can never approve, and a
        message from another agent can never stand in for the human. `user`-origin
        requests are forwarded to the hook, which in prod is the worker's
        `apply_decision` — the same human-decision path the inbox uses."""
        if origin != "user":
            return {"ok": False, "reason": "agent_origin_cannot_approve",
                    "origin": origin, "task_id": task_id, "action": action}
        if self._decision_hook is None:
            return {"ok": False, "reason": "decision_hook_unavailable",
                    "task_id": task_id, "action": action}
        if spawn_id not in self._spawns:
            return {"ok": False, "reason": "unknown_spawn", "id": spawn_id}
        try:
            out = await self._decision_hook(task_id, action,
                                            decided_by=f"user:via-subagent:{spawn_id}")
        except Exception as e:
            logger.warning("decision hook failed", exc_info=True)
            return {"ok": False, "reason": "decision_failed", "detail": str(e)[:200]}
        return {"ok": True, "task_id": task_id, "action": action,
                "status": getattr(out, "status", None)}

    # ── read model ───────────────────────────────────────────────
    def list(self) -> "list[dict]":
        return [{k: v for k, v in r.items() if k != "result"} for r in self._spawns.values()]

    def get(self, spawn_id: str) -> Optional[dict]:
        r = self._spawns.get(spawn_id)
        return dict(r) if r else None

    def stats(self) -> dict:
        by_status: dict[str, int] = {}
        cost_usd = 0.0
        for r in self._spawns.values():
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            if isinstance(r.get("cost"), dict):
                cost_usd += float(r["cost"].get("cost_usd", 0.0) or 0.0)
        out = {"total": len(self._spawns), "active": self._active,
               "cap": self.max_concurrent, "max_depth": self.max_depth,
               "blocked": sorted(self.blocked), "by_status": by_status,
               "steerable": self._runner_takes_steer, "persist": self.persist,
               "cost_usd": round(cost_usd, 6)}
        if self.budget is not None:
            out["budget"] = self.budget.status()
        return out


__all__ = [
    "DELEGATE_BLOCKED_CAPABILITIES", "NullRunner", "STEER_ORIGINS", "SPAWN_LOG_ENV",
    "SPAWN_TRANSITIONS", "SteerChannel", "SteerMessage", "SubAgentManager",
    "validate_output",
]
