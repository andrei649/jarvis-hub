"""Run a project's verify recipe — only through Nerva's governed terminal path.

Hermes's ``agent/verify/runner.py`` spawns the phases itself and boots the app in a
process group of its own. That file is not adopted. Here a phase is one or more
``terminal_run`` calls sent through the tool front door (``ToolRPCServer.handle``), the
same door the model's own commands use, so every one of them:

* is refused in **plan mode** before its approval card exists (the front door's
  plan-mode floor: a verification run executes the project's code, so it is not a read);
* becomes an **approval card** (``toolrpc.terminal_run``, ask tier) unless the owner's
  smart approvals or a standing consent approve that exact command — the approval mode
  (``auto | ask | off``) and the sealed-receipt rule apply unchanged;
* crosses the **target policy plane**, the **hardline denylist**, the ``terminal.exec``
  contract and the **Action Kernel** when it runs (``environments/execution.py``);
* is recorded in the **evidence ledger** when it finishes, by the coordinator hook, whether
  it ran now or later from the approval queue.

What this module adds is order and refusals before anything is queued: the e-stop
(nothing is queued while it is engaged), plan mode, a command that needs a shell (the
governed transports run a plain argv only), and the phase order — a phase runs only when
the one before it passed in this call. A phase that waits for an approval stops the run;
once approved it runs from the queue and its result lands in the ledger, and
``/verify run`` again continues.

Not done here, and why: starting the app and polling a readiness URL (Hermes's ``start``
phase). The governed transports run a bounded command to completion; there is no
governed way to keep a server running in the background and tear its process group
down, so the start command is shown, never run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.verify.runner")

PHASES = ("bootstrap", "build", "test")
DEFAULT_PHASES = ("build", "test")
DEFAULT_TARGET = "local-host"
DEFAULT_TIMEOUT = 600


@dataclass(frozen=True)
class Step:
    phase: str
    command: str
    refused: str = ""       # why this command cannot go through the governed path


@dataclass
class RunReport:
    root: str
    status: str             # passed | failed | waiting | refused | nothing
    reason: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"root": self.root, "status": self.status, "reason": self.reason, "steps": list(self.steps)}


def plan(recipe, phases: tuple[str, ...] = DEFAULT_PHASES) -> list[Step]:
    """The steps for *phases* of *recipe*, in phase order; a command that needs a shell
    is marked refused (it would be refused by the transport anyway)."""
    from agents.core.environments.execution import parse_argv

    steps: list[Step] = []
    for phase in PHASES:
        if phase not in phases or recipe is None:
            continue
        for command in getattr(recipe, phase, []) or []:
            _argv, problem = parse_argv(command, windows=False)
            steps.append(Step(phase, command, problem or ""))
    return steps


def preflight(session: str | None) -> str:
    """Why nothing may be queued now ('' when it may)."""
    from agents.core import estop
    from agents.core.kernel import plan_mode

    if estop.is_engaged():
        return "the emergency stop is engaged; nothing is queued until /resume"
    try:
        if session and plan_mode.default_store().is_active(session):
            return "this conversation is in plan mode; a verification run executes the project's code, so it waits for /plan off"
    except Exception:  # noqa: BLE001 — an unreadable plan-mode state holds everything
        return "plan mode cannot be read; nothing is queued"
    return ""


async def run(tool_rpc, *, root: Path, recipe, session: str | None, phases: tuple[str, ...] = DEFAULT_PHASES,
              target: str = DEFAULT_TARGET, timeout: int = DEFAULT_TIMEOUT, actor: str | None = None,
              resume: bool = True) -> RunReport:
    """Send the recipe's *phases* through ``terminal_run`` one command at a time. With
    *resume*, a build or test command the ledger shows passing since the project's last
    edit is not queued again."""
    from agents.core.llm.request_context import session_scope

    from . import evidence

    report = RunReport(root=str(root), status="nothing")
    steps = plan(recipe, phases)
    if not steps:
        report.reason = "the recipe has no command for " + ", ".join(phases)
        return report
    blocked = preflight(session)
    if blocked:
        report.status, report.reason = "refused", blocked
        return report
    if tool_rpc is None or not callable(getattr(tool_rpc, "handle", None)):
        report.status, report.reason = "refused", "the tool server is not running"
        return report
    for step in steps:
        entry: dict[str, Any] = {"phase": step.phase, "command": step.command}
        report.steps.append(entry)
        if step.refused:
            entry["result"] = "refused"
            entry["reason"] = step.refused
            report.status = "refused"
            report.reason = f"{step.command!r} needs a shell ({step.refused}); the governed path runs a plain command only"
            return report
        if resume and step.phase != "bootstrap" and evidence.passed_since_edit(str(root), step.command):
            entry["result"] = "passed"
            entry["reason"] = "already passed since the last edit (ledger)"
            continue
        blocked = preflight(session)     # the e-stop or plan mode may arrive between steps
        if blocked:
            entry["result"] = "refused"
            report.status, report.reason = "refused", blocked
            return report
        args = {"target": target, "command": step.command, "cwd": str(root), "timeout": int(timeout)}
        with session_scope(session or None):
            answer = await tool_rpc.handle({"tool": "terminal_run", "args": args}, actor=actor)
        task_id = answer.get("task_id") if isinstance(answer, dict) else None
        if isinstance(task_id, int):
            evidence.note_task(task_id, session or "")
        reason = answer.get("reason") if isinstance(answer, dict) else "no_answer"
        if isinstance(answer, dict) and answer.get("reason") == "approval_required":
            entry["result"] = "waiting"
            entry["task_id"] = task_id
            report.status = "waiting"
            report.reason = (f"{step.command!r} waits for your approval (task {task_id}); once it has run, "
                             "/verify run continues with the next phase")
            return report
        result = answer.get("result") if isinstance(answer, dict) and isinstance(answer.get("result"), dict) else answer
        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        if not isinstance(exit_code, int) and isinstance(task_id, int):
            # Run inside the call (a smart approval or a standing consent) but answered
            # without the transport's result (a failing command): the ledger has it.
            row = evidence.for_task(task_id)
            exit_code = row["exit_code"] if row is not None else None
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            entry["exit_code"] = exit_code
            entry["result"] = "passed" if exit_code == 0 else "failed"
            if exit_code != 0:
                report.status, report.reason = "failed", f"{step.command!r} exited with {exit_code}"
                return report
            continue
        entry["result"] = "refused"
        entry["reason"] = str(reason or "refused")
        report.status = "refused"
        detail = answer.get("detail") if isinstance(answer, dict) else ""
        report.reason = f"{step.command!r} was refused: {reason}" + (f" ({detail})" if detail else "")
        return report
    report.status = "passed"
    return report


__all__ = ["DEFAULT_PHASES", "DEFAULT_TARGET", "PHASES", "RunReport", "Step", "plan", "preflight", "run"]
