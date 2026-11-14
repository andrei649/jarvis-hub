"""delegate_tool.py — H400: the model hands work to isolated sub-agents (``delegate_task``).

Hermes ``delegate_task``, rebuilt on the spawn machinery Nerva already had
(:class:`agents.core.subagents.SubAgentManager`): the tool validates the request, asks
who is calling, and then calls ``spawn_batch`` — the same gate, caps, timeout and
registry the owner's ``/api/subagents`` routes use. It adds no second path to a child.

What a child is, stated once:

* **Never more than its parent.** Its tools are the tools this turn was offered minus
  the blocked ones (no further delegation, no long-term memory write, no skill
  proposal, no question to the user, no spoken or sent message, no scheduled job, no
  board). It runs as the *same agent* as its parent (the model cannot pick another, so
  it cannot pick one with a looser approval override or a wider ``tools:`` list), in a
  task that carries the parent's principal, action origin — so a turn that read
  untrusted content hands the taint down — job toolset bound and model pin. Its gated
  calls queue for the owner's approval exactly as the parent's do.
* **Fresh.** It gets a session of its own and a focused brief (the goal, the context
  the parent wrote for it, the output contract); it does not see the parent's history.
* **Data.** What it answers comes back as a tool result declared untrusted: the loop
  fences it and raises the parent turn's taint. With ``output_schema`` the answer must
  be JSON that validates, checked here on the parent's side.

Who may call it: an owner at an operator surface (the web HUD, the local voice loop),
inside a model turn. A guest, an inbound channel turn, a job, a script run by
``execute_code``, a direct ToolRPC call and a sub-agent itself are refused. It is
refused while the agent's approval mode is ``off`` (nothing a machine decided runs),
and — through the spawn gate — while the emergency stop is engaged or spawning is
paused. Off unless ``llm.delegate_task`` is on: off means not registered.

The model's arguments carry goals, context and schemas. Depth, concurrency, the
timeout, the model, the agent and the tools are host state.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from .action_origin import current_action_origin
from .capability_manifests import RollbackContract
from .subagents import (
    BATCH_MAX,
    CHILD_TIMEOUT_MAX_SECONDS,
    CONTEXT_MAX_CHARS,
    DEFAULT_CHILD_TIMEOUT_SECONDS,
    current_spawn_id,
    schema_problem,
)
from .tool_profiles import PRINCIPAL_OWNER, SURFACE_OPERATOR, classify_turn
from .tool_rpc import ToolRPCValidationError, current_tool_actor, current_tool_turn

logger = logging.getLogger("jarvis.delegate_tool")

TOOL = "delegate_task"
SETTING = "llm.delegate_task"
TIMEOUT_SETTING = "autonomy.subagent_timeout_seconds"
GOAL_MAX_CHARS = 4000
SPAWN_ID_MAX_CHARS = 120
STEER_MAX_CHARS = 2000
ACTIONS = ("spawn", "collect", "list", "steer", "stop")
#: What of one child's answer the parent's transcript is given (Hermes: 24 000).
OUTPUT_MAX_CHARS = 24_000
#: Added to the child timeout for the tool loop's own deadline on this tool, so the
#: manager's timeout (which cancels the child and reports it) fires first.
LOOP_GRACE_SECONDS = 15.0

DESCRIPTION = (
    "Hand one or more self-contained tasks to sub-agents and wait for their answers. Each "
    "sub-agent starts fresh: it sees none of this conversation, only the goal and context "
    "you write for it, and it works with the tools you have minus delegation, memory "
    "writes, skill proposals, questions to the user, messages, scheduling and the board. "
    "Tasks in one call run in parallel, up to the free sub-agent slots; each has a time "
    "limit. Use it for independent sub-tasks whose intermediate steps you do not need to "
    "see. With background true the call returns at once and each result is delivered once, "
    "later, to delegate_task with collect true. What a sub-agent reports is its own account, "
    "returned as data: verify what matters. "
    "Unavailable while the Action Kernel is on (it has no approval card to wait on)."
)
#: H400 (M3): why a spawn is refused while the Action Kernel is on. The kernel classifies
#: a ``tool.rpc`` effect at the irreversible tier and answers "ask the owner", and a
#: delegation has no approval card to wait on, so it is refused — as a session-kernel
#: cell of ``execute_code`` is. The kernel's classification is not changed for this.
KERNEL_REFUSAL = "kernel_requires_approval"
KERNEL_REFUSAL_DETAIL = ("with the Action Kernel on (JARVIS_ACTION_KERNEL), delegate_task needs a "
                         "kernel grant; the kernel asks the owner for a tool.rpc effect and a "
                         "delegation has no approval card to wait on, so delegation is off while "
                         "the kernel is on")
#: H400 (NIT): the most of one child's parsed answer the parent's transcript is given.
STRUCTURED_MAX_CHARS = OUTPUT_MAX_CHARS
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": BATCH_MAX,
            "description": "The tasks. Each entry starts one sub-agent; one task is a one-entry list.",
            "items": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string", "minLength": 1, "maxLength": GOAL_MAX_CHARS,
                        "description": ("What this sub-agent should accomplish. Specific and "
                                        "self-contained: it knows nothing about this conversation."),
                    },
                    "context": {
                        "type": "string", "maxLength": CONTEXT_MAX_CHARS,
                        "description": ("Background this sub-agent needs: paths, error messages, "
                                        "constraints. Each sub-agent sees only its own context."),
                    },
                    "output_schema": {
                        "type": "object",
                        "description": ("Optional schema (type, required, enum, properties, items) "
                                        "the sub-agent's final answer must satisfy as JSON. It is "
                                        "told the schema; an answer that does not validate fails."),
                    },
                },
                "required": ["goal"],
                "additionalProperties": False,
            },
        },
        "background": {
            "type": "boolean",
            "description": ("Run the tasks in the background and return at once with their ids. "
                            "Each result is delivered exactly once, later: call delegate_task with "
                            "{\"collect\": true} to receive the finished ones."),
        },
        "collect": {
            "type": "boolean",
            "description": ("Alone (no tasks): receive the results of this conversation's background "
                            "sub-agents that have finished since the last collect. Each result is "
                            "handed out once."),
        },
        "action": {
            "type": "string",
            "enum": list(ACTIONS),
            "description": ("Operation to run: 'spawn' (default when tasks are supplied), 'collect' "
                            "(receive finished background results), 'list' (inspect this conversation's "
                            "sub-agents and concurrency slots), 'steer' (send guidance to a running "
                            "child of this conversation), or 'stop' (cancel a running child of this "
                            "conversation)."),
        },
        "spawn_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": SPAWN_ID_MAX_CHARS,
            "description": ("Running sub-agent id of this conversation to target when action is "
                            "'steer' or 'stop'."),
        },
        "message": {
            "type": "string",
            "minLength": 1,
            "maxLength": STEER_MAX_CHARS,
            "description": "Guidance message delivered to the running child when action is 'steer'.",
        },
    },
    "additionalProperties": False,
}
ROLLBACK = RollbackContract(
    mode="implementation_specific",
    description=("Starting a sub-agent changes nothing by itself: each tool a sub-agent calls has "
                 "that tool's own effect and rollback, and a gated one still queues for the owner's "
                 "approval. A running sub-agent is stopped with POST /api/subagents/{id}/stop, and "
                 "POST /api/subagents/pause stops new ones."),
    limitations=("The model time a sub-agent spent is spent; what a tool it called wrote is undone "
                 "only as that tool allows."),
)


def child_timeout_seconds(settings: Callable[[str, Any], Any]) -> Any:
    """``autonomy.subagent_timeout_seconds`` as stored (the manager sanitizes it)."""
    try:
        return settings(TIMEOUT_SETTING, DEFAULT_CHILD_TIMEOUT_SECONDS)
    except Exception:
        return DEFAULT_CHILD_TIMEOUT_SECONDS


def loop_timeout_seconds(manager: Any) -> float:
    """How long the tool loop waits for one ``delegate_task`` call: the manager's own
    child timeout plus a grace, so a slow child is cancelled and reported by the manager
    before the loop gives up on the call. With no manager the loop's default stands."""
    read = getattr(manager, "child_timeout", None)
    try:
        seconds = float(read()) if callable(read) else DEFAULT_CHILD_TIMEOUT_SECONDS
    except Exception:
        seconds = DEFAULT_CHILD_TIMEOUT_SECONDS
    return min(seconds, CHILD_TIMEOUT_MAX_SECONDS) + LOOP_GRACE_SECONDS


def _refusal(reason: str, **extra: Any) -> dict:
    return {"ok": False, "reason": reason, **extra}


class DelegateTool:
    """The ``delegate_task`` handler. Every collaborator is a host-side reader."""

    def __init__(
        self,
        *,
        manager: Callable[[], Any],
        principal: Callable[[], Any],
        offer: Callable[[], Any],
        mode: Callable[[str], str],
        agents: Callable[[], Any],
        authorizer: Callable[..., Any] | None = None,
        settings: Callable[[str, Any], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._manager = manager
        self._principal = principal
        self._offer = offer
        self._mode = mode
        self._agents = agents
        self._authorizer = authorizer

    # ── the arguments ────────────────────────────────────────────────────────

    def preflight(self, args: Mapping[str, object]) -> dict:
        """Enforce the advertised schema; the server only advertises it."""
        if not isinstance(args, Mapping):
            raise ToolRPCValidationError("invalid_args")
        keys = set(args)
        action = args.get("action")
        if action is not None and (not isinstance(action, str) or action not in ACTIONS):
            raise ToolRPCValidationError("invalid_action")

        # Collect finished background children (`{"collect": true}` or `{"action": "collect"}`).
        if action == "collect" or (action is None and keys == {"collect"}):
            if keys - {"action", "collect"}:
                raise ToolRPCValidationError("invalid_args")
            if "collect" in keys and args["collect"] is not True:
                raise ToolRPCValidationError("invalid_args")
            return {"action": "collect", "collect": True}

        # List this conversation's children and live slot usage (`{"action": "list"}`).
        if action == "list":
            if keys != {"action"}:
                raise ToolRPCValidationError("invalid_args")
            return {"action": "list"}

        # Steer a running child of this conversation (`{"action": "steer", "spawn_id", "message"}`).
        if action == "steer":
            if keys != {"action", "spawn_id", "message"}:
                raise ToolRPCValidationError("invalid_args")
            spawn_id = args.get("spawn_id")
            message = args.get("message")
            if (
                not isinstance(spawn_id, str)
                or not spawn_id.strip()
                or len(spawn_id) > SPAWN_ID_MAX_CHARS
            ):
                raise ToolRPCValidationError("invalid_spawn_id")
            if (
                not isinstance(message, str)
                or not message.strip()
                or len(message) > STEER_MAX_CHARS
            ):
                raise ToolRPCValidationError("invalid_message")
            return {"action": "steer", "spawn_id": spawn_id.strip(), "message": message.strip()}

        # Stop a running child of this conversation (`{"action": "stop", "spawn_id"}`).
        if action == "stop":
            if keys != {"action", "spawn_id"}:
                raise ToolRPCValidationError("invalid_args")
            spawn_id = args.get("spawn_id")
            if (
                not isinstance(spawn_id, str)
                or not spawn_id.strip()
                or len(spawn_id) > SPAWN_ID_MAX_CHARS
            ):
                raise ToolRPCValidationError("invalid_spawn_id")
            return {"action": "stop", "spawn_id": spawn_id.strip()}

        # Spawn (`{"tasks": [...]}` or `{"action": "spawn", "tasks": [...]}`).
        if "tasks" not in keys or keys - {"action", "tasks", "background"}:
            raise ToolRPCValidationError("invalid_args")
        background = args.get("background", False)
        if not isinstance(background, bool):
            raise ToolRPCValidationError("invalid_args")
        tasks = args["tasks"]
        if not isinstance(tasks, list) or not tasks:
            raise ToolRPCValidationError("tasks_required")
        if len(tasks) > BATCH_MAX:
            raise ToolRPCValidationError("too_many_tasks")
        cleaned = []
        for item in tasks:
            if not isinstance(item, Mapping) or set(item) - {"goal", "context", "output_schema"}:
                raise ToolRPCValidationError("invalid_task")
            goal = item.get("goal")
            if not isinstance(goal, str) or not goal.strip() or len(goal) > GOAL_MAX_CHARS:
                raise ToolRPCValidationError("invalid_goal")
            entry: dict[str, Any] = {"goal": goal.strip()}
            context = item.get("context")
            if context is not None:
                if not isinstance(context, str) or len(context) > CONTEXT_MAX_CHARS:
                    raise ToolRPCValidationError("invalid_context")
                if context.strip():
                    entry["context"] = context
            schema = item.get("output_schema")
            if isinstance(schema, str):              # a model may double-encode it
                try:
                    schema = json.loads(schema)
                except ValueError:
                    raise ToolRPCValidationError("invalid_output_schema") from None
            if schema is not None:
                if schema_problem(schema):
                    raise ToolRPCValidationError("invalid_output_schema")
                entry["output_schema"] = schema
            cleaned.append(entry)
        return {"tasks": cleaned, **({"background": True} if background else {})}

    def schema_overrides(self) -> dict[str, Any] | None:
        """H320 — advertise the live concurrency cap, active/free slots, turn cap and timeout."""
        try:
            manager = self._manager()
            stats = manager.stats() if manager is not None else None
        except Exception:
            stats = None
        if not isinstance(stats, Mapping):
            return None
        cap = int(stats.get("cap") or 1)
        active = int(stats.get("active") or 0)
        free = max(0, cap - active)
        turn_cap = int((stats.get("turn_cap") or {}).get("cap") or BATCH_MAX)
        max_depth = stats.get("max_depth", 1)
        timeout_s = int(stats.get("timeout_seconds") or DEFAULT_CHILD_TIMEOUT_SECONDS)
        live_desc = (
            f"{DESCRIPTION} Live host limits: concurrency cap {cap} "
            f"({active} active, {free} free slot(s)), per-turn cap {turn_cap}, "
            f"max depth {max_depth}, child timeout {timeout_s}s."
        )
        return {"description": live_desc}

    # ── authority ────────────────────────────────────────────────────────────

    def switched_on(self) -> bool:
        """``llm.delegate_task`` as stored now (M1): the switch is re-read at every call, so
        turning it off stops delegation at once, not at the next restart. An unreadable
        setting is off."""
        if self._settings is None:
            return True
        try:
            return self._settings(SETTING, False) is True
        except Exception:
            return False

    def _caller_refusal(self, agent: str) -> dict | None:
        """Why this call may not delegate, from host state only; None when it may."""
        if not self.switched_on():
            return _refusal("delegate_task_disabled",
                            detail="llm.delegate_task is off: the owner switched delegation off")
        if current_spawn_id() is not None:
            return _refusal("delegation_blocked_for_subagents",
                            detail="a sub-agent cannot delegate further")
        if current_tool_turn() is None:
            # A script (execute_code), a direct ToolRPC call, an approved task: no model
            # turn is bound, so there is no turn to cap, to bound the tools by, or to taint.
            return _refusal("delegate_requires_model_turn",
                            detail="delegate_task is callable from a model turn only")
        try:
            posture = classify_turn(self._principal(), current_action_origin())
        except Exception:
            logger.warning("delegate_task: the turn's principal is unreadable; refusing")
            return _refusal("delegate_owner_only")
        if (posture.surface, posture.principal) != (SURFACE_OPERATOR, PRINCIPAL_OWNER):
            return _refusal("delegate_owner_only",
                            detail="only the owner's own operator turn may delegate")
        try:
            roster = self._agents()
            known = agent in roster
        except Exception:
            known = False
        if not known:
            return _refusal("unknown_agent", detail="the calling agent is not on this hub's roster")
        try:
            effective = self._mode(agent)
        except Exception:
            logger.warning("delegate_task: the approval mode is unreadable; refusing")
            return _refusal("approval_mode_unknown")
        if effective == "off":
            return _refusal("approval_mode_off",
                            detail="the approval mode is off: nothing a machine decided runs")
        if effective not in ("auto", "ask"):
            return _refusal("approval_mode_unknown")
        return None

    def _kernel_refusal(self, agent: str, count: int) -> dict | None:
        """Cross the Action Kernel when it is on (no new kind: a spawn is a ``tool.rpc``
        effect, like a code cell). Anything but a GRANT refuses — a halted kill switch,
        a tripped budget, and a tainted turn, whose escalation to "ask the owner" has
        no card to wait on here."""
        if self._authorizer is None:
            return None
        from .kernel import Action, Verdict, kernel_enabled

        if not kernel_enabled():
            return None
        try:
            decision = self._authorizer(Action(
                kind="tool.rpc", agent=agent, title=f"Delegate {count} task(s) to sub-agents",
                payload={"tool": TOOL, "target": TOOL, "count": count},
                origin=current_action_origin(),
            ))
        except Exception:
            logger.warning("delegate_task: kernel authorization failed", exc_info=True)
            return _refusal("kernel_denied")
        verdict = getattr(decision, "verdict", None)
        if verdict is Verdict.QUEUE:
            return _refusal(KERNEL_REFUSAL, detail=KERNEL_REFUSAL_DETAIL)
        if verdict is not Verdict.GRANT:
            return _refusal("kernel_denied", detail=str(getattr(decision, "reason", ""))[:200])
        return None

    # ── the call ─────────────────────────────────────────────────────────────

    async def execute(self, args: Mapping[str, object]) -> dict:
        agent = current_tool_actor()
        refusal = self._caller_refusal(agent)
        if refusal is not None:
            return refusal
        try:
            manager = self._manager()
        except Exception:
            manager = None
        if manager is None:
            return _refusal("subagents_unavailable")
        try:
            offer = self._offer()
        except Exception:
            offer = None
        if not isinstance(offer, (frozenset, set)) or TOOL not in offer:
            # No note of what this turn was offered: there is nothing to bound a child by.
            return _refusal("delegate_offer_unknown")
        action = args.get("action")
        if action == "collect" or args.get("collect") is True:
            return await self._collect(manager, agent)
        if action == "list":
            return self._list_children(manager, agent)
        if action == "steer":
            return self._steer_child(manager, agent, str(args.get("spawn_id") or ""),
                                     str(args.get("message") or ""))
        if action == "stop":
            return self._stop_child(manager, agent, str(args.get("spawn_id") or ""))
        tasks = list(args.get("tasks") or [])
        refusal = self._kernel_refusal(agent, len(tasks))
        if refusal is not None:
            return refusal
        batch = [{"task": item["goal"], "agent": agent,
                  **({"context": item["context"]} if item.get("context") else {}),
                  **({"answer_schema": item["output_schema"]} if item.get("output_schema") is not None else {})}
                 for item in tasks]
        started = time.monotonic()
        background = args.get("background") is True
        outcome = await manager.spawn_batch(batch, parent=agent, tools=frozenset(offer),
                                            model_authored=True, queue=False,
                                            **({"background": True} if background else {}))
        return project(outcome, tasks, time.monotonic() - started)

    @staticmethod
    def _owned_by_caller(rec: Any, agent: str, session_id: str | None) -> bool:
        return (
            isinstance(rec, Mapping)
            and rec.get("parent") == agent
            and rec.get("parent_session") == session_id
        )

    def _list_children(self, manager: Any, agent: str) -> dict:
        from .kernel.plan_mode import current_session

        refusal = self._kernel_refusal(agent, 0)
        if refusal is not None:
            return refusal
        list_fn = getattr(manager, "list", None)
        stats_fn = getattr(manager, "stats", None)
        if not callable(list_fn) or not callable(stats_fn):
            return _refusal("subagents_unavailable")
        session_id = current_session()
        rows = [
            {
                "id": row.get("id"),
                "delegation_id": row.get("delegation_id"),
                "status": row.get("status"),
                "goal": str(row.get("task") or "")[:200],
                "background": bool(row.get("background")),
                "steerable": bool(row.get("steerable")),
                "stalled": bool(row.get("stalled")),
                "created_at": row.get("created_at"),
                "finished_at": row.get("finished_at"),
                **({"failure": row["failure"]} if "failure" in row else {}),
            }
            for row in list_fn()
            if self._owned_by_caller(row, agent, session_id)
        ]
        stats = stats_fn()
        cap = int(stats.get("cap") or 1)
        active = int(stats.get("active") or 0)
        return {
            "ok": True,
            "action": "list",
            "count": len(rows),
            "active": active,
            "cap": cap,
            "free_slots": max(0, cap - active),
            "children": rows,
        }

    def _steer_child(self, manager: Any, agent: str, spawn_id: str, message: str) -> dict:
        from .kernel.plan_mode import current_session

        refusal = self._kernel_refusal(agent, 1)
        if refusal is not None:
            return refusal
        get_fn = getattr(manager, "get", None)
        steer_fn = getattr(manager, "steer", None)
        if not callable(get_fn) or not callable(steer_fn):
            return _refusal("subagents_unavailable")
        rec = get_fn(spawn_id)
        if not self._owned_by_caller(rec, agent, current_session()):
            return _refusal(
                "unknown_or_foreign_child",
                id=spawn_id,
                detail="no sub-agent with that id belongs to this conversation and agent",
            )
        # Agent-origin steer: cannot approve inbox queue cards (SubAgentManager.decide enforces user-only).
        result = steer_fn(spawn_id, message, origin="agent")
        return {"action": "steer", **result}

    def _stop_child(self, manager: Any, agent: str, spawn_id: str) -> dict:
        from .kernel.plan_mode import current_session

        refusal = self._kernel_refusal(agent, 1)
        if refusal is not None:
            return refusal
        get_fn = getattr(manager, "get", None)
        stop_fn = getattr(manager, "stop", None)
        if not callable(get_fn) or not callable(stop_fn):
            return _refusal("subagents_unavailable")
        rec = get_fn(spawn_id)
        if not self._owned_by_caller(rec, agent, current_session()):
            return _refusal(
                "unknown_or_foreign_child",
                id=spawn_id,
                detail="no sub-agent with that id belongs to this conversation and agent",
            )
        result = stop_fn(spawn_id, reason=f"parent:{agent}"[:80])
        return {"action": "stop", **result}

    async def _collect(self, manager: Any, agent: str) -> dict:
        """G18 (H401): this conversation's finished background results, each handed out
        once (the claim is durable: a restart, another consumer or a second collect never
        receives the same result again)."""
        from .kernel.plan_mode import current_session

        claim = getattr(manager, "claim_completions", None)
        if not callable(claim):
            return _refusal("subagents_unavailable")
        rows = await claim(f"model:{agent}"[:80], parent_session=current_session())
        children = [_row_view(row) for row in rows]
        answer: dict[str, Any] = {"ok": True, "collected": len(children), "children": children}
        if not children:
            answer["detail"] = "no background sub-agent of this conversation has finished since the last collect"
        if any("output" in child or "structured" in child for child in children):
            answer["tainted"] = True
        return answer


def _row_view(row: Mapping[str, Any]) -> dict:
    """One durable delegation row as the parent model reads it (same shape as a child)."""
    status = str(row.get("status") or "failed")
    child = {"id": row.get("spawn_id"), "status": status, "ok": status == "done",
             "result": row.get("result"), "delegation_id": row.get("delegation_id")}
    view = _child_view(child, str(row.get("goal") or ""))
    view["delegation_id"] = row.get("delegation_id")
    return view


def _child_view(child: Mapping[str, Any], goal: str) -> dict:
    """One child's outcome as the parent model reads it."""
    view: dict[str, Any] = {"goal": goal[:200], "status": child.get("status") or "refused",
                            "ok": child.get("ok") is True}
    if child.get("id"):
        view["id"] = child["id"]
    result = child.get("result")
    if "status" not in child:                        # refused at the gate: nothing ran
        view["reason"] = child.get("reason")
        for key in ("detail", "active", "cap", "spawned", "depth", "max_depth"):
            if key in child:
                view[key] = child[key]
        return view
    if not isinstance(result, Mapping):
        return view
    if isinstance(result.get("worktree"), Mapping):
        # G18 (H402): the child's own branch, whether it was kept, and the files it
        # changed — with the stale-file reminder when there are any.
        view["worktree"] = dict(result["worktree"])
    if child.get("ok") is True:
        text = result.get("output")
        if isinstance(text, str):
            view["output"] = text[:OUTPUT_MAX_CHARS]
            if len(text) > OUTPUT_MAX_CHARS:
                view["output_truncated"] = True
                # H401 (summary spill): the whole answer is kept on the durable row.
                ref = child.get("delegation_id") or child.get("id")
                if ref:
                    view["full_output"] = f"GET /api/subagents/{ref}/result"
        if "structured" in result:
            view["schema_valid"] = True
            try:
                size = len(json.dumps(result["structured"], ensure_ascii=False))
            except (TypeError, ValueError, RecursionError):
                size = STRUCTURED_MAX_CHARS + 1
            if size <= STRUCTURED_MAX_CHARS:
                view["structured"] = result["structured"]
            else:
                # Validated, but too large for the transcript: the (truncated) text stays.
                view["structured_omitted"] = True
        return view
    view["error"] = result.get("error") or "failed"
    for key in ("detail", "reason", "timeout_seconds", "unwound"):
        if key in result:
            view[key] = result[key]
    if result.get("error") == "output_schema_violation":
        view["schema_valid"] = False
        view["violations"] = list(result.get("violations") or [])[:10]
        rejected = result.get("output")
        text = rejected.get("output") if isinstance(rejected, Mapping) else None
        if isinstance(text, str):
            view["output"] = text[:OUTPUT_MAX_CHARS]
    return view


def project(outcome: Any, tasks: list, seconds: float) -> dict:
    """The tool's answer. ``tainted`` is set whenever a child's words are in it, so the
    loop fences the result and marks the turn even when the batch as a whole failed."""
    if not isinstance(outcome, Mapping):
        return _refusal("subagents_unavailable")
    if outcome.get("background") is True and "children" in outcome:
        children = []
        for i, child in enumerate(outcome.get("children") or []):
            view = {"goal": (tasks[i]["goal"] if i < len(tasks) else "")[:200],
                    "status": child.get("status") or "refused", "ok": child.get("status") == "running"}
            for key in ("id", "delegation_id", "reason", "detail"):
                if child.get(key):
                    view[key] = child[key]
            children.append(view)
        return {"ok": outcome.get("ok") is True, "background": True, "children": children,
                "summary": dict(outcome.get("summary") or {}),
                "duration_seconds": round(max(0.0, seconds), 3),
                "notice": ("These sub-agents run in the background. Their results are delivered "
                           "once: call delegate_task with {\"collect\": true} to receive the "
                           "finished ones.")}
    if "children" not in outcome:                    # the whole batch was refused
        return {key: value for key, value in outcome.items()
                if key in {"ok", "reason", "detail", "index", "max", "active", "cap",
                           "requested", "pause"}}
    children = [_child_view(child, tasks[i]["goal"] if i < len(tasks) else "")
                for i, child in enumerate(outcome.get("children") or [])]
    answer: dict[str, Any] = {
        "ok": outcome.get("ok") is True,
        "children": children,
        "summary": dict(outcome.get("summary") or {}),
        "duration_seconds": round(max(0.0, seconds), 3),
    }
    notice = outcome.get("notice")
    if isinstance(notice, Mapping) and isinstance(notice.get("message"), str):
        answer["notice"] = notice["message"]
    if any("output" in child or "structured" in child or "violations" in child for child in children):
        answer["tainted"] = True
    return answer


def register_delegate_tool(
    server,
    *,
    settings: Callable[[str, Any], Any],
    manager: Callable[[], Any],
    principal: Callable[[], Any],
    offer: Callable[[], Any],
    mode: Callable[[str], str],
    agents: Callable[[], Any],
    authorizer: Callable[..., Any] | None = None,
) -> list[str]:
    """Register ``delegate_task`` when the owner has switched it on, else nothing.

    As with ``execute_code``, off means never registered: the tool profile can only
    narrow what exists."""
    try:
        enabled = settings(SETTING, False) is True
    except Exception:
        logger.warning("delegate_task setting unreadable; leaving it off", exc_info=True)
        enabled = False
    if not enabled:
        return []
    tool = DelegateTool(manager=manager, principal=principal, offer=offer, mode=mode,
                        agents=agents, authorizer=authorizer, settings=settings)
    server.register_tool(
        TOOL,
        tool.execute,
        description=DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        capability_id="tool:delegate_task",
        preflight=tool.preflight,
        schema_overrides=tool.schema_overrides,
        # A child's answer is whatever it read and concluded: third-party text to the
        # parent. The fence follows the tool, so it is declared once here.
        untrusted_output=True,
        # A call takes sub-agent slots and runs children that call tools themselves: it
        # runs alone in its model step, after everything the model asked first.
        parallel_safe=False,
        # Ungated is a claim about starting a child, not about what a child can reach:
        # the ungated tools it is offered write, and its gated calls still queue.
        risk="sensitive",
        rollback=ROLLBACK,
    )
    return [TOOL]


__all__ = [
    "DESCRIPTION", "DelegateTool", "INPUT_SCHEMA", "KERNEL_REFUSAL", "LOOP_GRACE_SECONDS",
    "OUTPUT_MAX_CHARS", "STRUCTURED_MAX_CHARS",
    "ROLLBACK", "SETTING", "TIMEOUT_SETTING", "TOOL", "child_timeout_seconds",
    "loop_timeout_seconds", "project", "register_delegate_tool",
]
