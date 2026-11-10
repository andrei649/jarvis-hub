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
    "see. What a sub-agent reports is its own account, returned as data: verify what matters. "
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
    },
    "required": ["tasks"],
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
        if not isinstance(args, Mapping) or set(args) != {"tasks"}:
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
        return {"tasks": cleaned}

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
        tasks = list(args.get("tasks") or [])
        refusal = self._kernel_refusal(agent, len(tasks))
        if refusal is not None:
            return refusal
        batch = [{"task": item["goal"], "agent": agent,
                  **({"context": item["context"]} if item.get("context") else {}),
                  **({"answer_schema": item["output_schema"]} if item.get("output_schema") is not None else {})}
                 for item in tasks]
        started = time.monotonic()
        outcome = await manager.spawn_batch(batch, parent=agent, tools=frozenset(offer),
                                            model_authored=True, queue=False)
        return project(outcome, tasks, time.monotonic() - started)


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
    if child.get("ok") is True:
        text = result.get("output")
        if isinstance(text, str):
            view["output"] = text[:OUTPUT_MAX_CHARS]
            if len(text) > OUTPUT_MAX_CHARS:
                view["output_truncated"] = True
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
