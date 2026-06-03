"""WorkflowEngine — executes Pipeline instances (H5.6).

Coordinates multi-agent pipelines: parallel branches, sequential steps,
shared intermediate results.  Injects results via template substitution
so downstream steps can reference upstream outputs.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from typing import TYPE_CHECKING

from .pipeline import Pipeline, WorkflowStep
from .structured import extract_json, validate_output

if TYPE_CHECKING:
    from agents.core.orchestrator import Orchestrator

logger = logging.getLogger("jarvis.workflows")

_TIMEOUT = 120.0  # seconds per step
_MAX_RECENT_RUNS = 50  # H10.2 — recent-run trace ring for the HUD overlay


class WorkflowEngine:
    """Run a Pipeline against the live orchestrator, sharing results between steps."""

    def __init__(self, orchestrator: Orchestrator):
        self._orch = orchestrator
        # H10.2: ring of recent run traces for the visual overlay.
        self.recent_runs: deque = deque(maxlen=_MAX_RECENT_RUNS)

    async def run(self, pipeline: Pipeline, initial_input: str) -> dict:
        """Execute *pipeline* and return {step_id: response, ..., _elapsed, _ok}."""
        t0 = time.monotonic()
        ctx: dict[str, str] = {"_input": initial_input}
        ctx["_structured"] = {}
        errors: list[str] = []

        terminated_by: str = ""
        step_map = {s.id: s for s in pipeline.steps}
        ctx["_trace"] = []

        for batch in pipeline.execution_batches():
            if len(batch) == 1:
                step = batch[0]
                out = await self._traced_execute(step, ctx, step_map)
                ctx[step.id] = out
                if out.startswith("[error:"):
                    errors.append(step.id)
            else:
                coros = [self._traced_execute(s, ctx, step_map) for s in batch]
                outputs = await asyncio.gather(*coros, return_exceptions=True)
                for step, out in zip(batch, outputs):
                    if isinstance(out, Exception):
                        ctx[step.id] = f"[error:{out}]"
                        errors.append(step.id)
                    else:
                        ctx[step.id] = out

            # H10.10: validate + expose structured fields for any schema'd step.
            for step in batch:
                if step.output_schema:
                    self._apply_structured(step, ctx, errors)

            # H10.12: stop early if any step in this batch tripped its guard.
            for step in batch:
                if step.terminate_when and evaluate_condition(step.terminate_when, ctx.get(step.id, "")):
                    terminated_by = step.id
                    break
            if terminated_by:
                break

        ctx["_elapsed"] = round(time.monotonic() - t0, 2)
        ctx["_ok"] = len(errors) == 0
        ctx["_errors"] = errors
        ctx["_terminated"] = bool(terminated_by)
        ctx["_terminated_by"] = terminated_by
        # H10.2: stash the run so the HUD can render an overlay of recent runs.
        self.recent_runs.append({
            "pipeline_id": pipeline.id,
            "pipeline_name": pipeline.name,
            "ts": time.time(),
            "elapsed": ctx["_elapsed"],
            "ok": ctx["_ok"],
            "terminated_by": terminated_by,
            "steps": list(ctx["_trace"]),
        })
        return ctx

    async def _traced_execute(self, step: WorkflowStep, ctx: dict, step_map: dict) -> str:
        """H10.2 — time a step and append a trace entry (input/output/status)."""
        t = time.monotonic()
        input_preview = _render(step.prompt_template, ctx)[:160]
        out = await self._execute_step(step, ctx, step_map)
        entry = {
            "step": step.id,
            "kind": step.kind,
            "agent": step.agent_id,
            "input_preview": input_preview,
            "output_preview": (out or "")[:160],
            "elapsed_ms": round((time.monotonic() - t) * 1000, 1),
            "ok": not (out or "").startswith("[error:"),
        }
        ctx.setdefault("_trace", []).append(entry)
        return out

    def recent(self, limit: int = 20) -> list[dict]:
        """Return up to *limit* recent run traces, most recent first."""
        runs = list(self.recent_runs)
        runs.reverse()
        return runs[:max(1, limit)]

    async def _execute_step(self, step: WorkflowStep, ctx: dict, step_map: dict) -> str:
        """Dispatch a step by kind: critic loop (H10.15) or normal agent run."""
        if step.kind == "critic":
            return await self._run_critic(step, ctx, step_map)
        if step.kind == "router":
            return await self._run_router(step, ctx)
        if step.kind == "transform":
            return self._run_transform(step, ctx)
        if step.kind == "guardrail":
            return self._run_guardrail(step, ctx)
        if step.kind == "loop":
            return await self._run_loop(step, ctx, step_map)
        return await self._run_step(step, ctx)

    async def _run_loop(self, step: WorkflowStep, ctx: dict, step_map: dict) -> str:
        """H10.6 — re-run an inline body of steps until an exit condition or cap.

        A loop-back edge with an iteration counter: the body (``loop.steps``) runs
        in listed order, sharing ``ctx``; after each pass the ``until`` condition is
        checked against the last body step's output. Useful for retry loops and
        iterative refinement. ``max_iterations`` is clamped to [1, 100].
        """
        cfg = step.loop or {}
        max_iter = max(1, min(100, int(cfg.get("max_iterations", 3) or 3)))
        until = cfg.get("until")
        body = [b if isinstance(b, WorkflowStep) else WorkflowStep.from_dict(b)
                for b in (cfg.get("steps") or [])]
        if not body:
            return ctx.get(step.id, "")

        iterations, exited_by, last = 0, "max_iterations", ctx.get(step.id, "")
        for i in range(max_iter):
            iterations += 1
            ctx[f"{step.id}._iter"] = str(i + 1)
            for b in body:
                ctx[b.id] = await self._execute_step(b, ctx, step_map)
            last = ctx.get(body[-1].id, "")
            if until and evaluate_condition(until, last):
                exited_by = "condition"
                break
        ctx.setdefault("_loops", {})[step.id] = {"iterations": iterations, "exited_by": exited_by}
        return last

    def _run_transform(self, step: WorkflowStep, ctx: dict) -> str:
        """H10.3 — deterministic, no-LLM transform of the rendered input."""
        from .transforms import apply_transform
        return apply_transform(step.transform or {}, _render(step.prompt_template, ctx))

    def _run_guardrail(self, step: WorkflowStep, ctx: dict) -> str:
        """H10.4 — per-workflow secret/PII guardrail (warn/redact/block)."""
        from .guardrail_node import apply_guardrail
        out, info = apply_guardrail(step.guardrail or {}, _render(step.prompt_template, ctx))
        ctx.setdefault("_guardrails", {})[step.id] = info
        return out

    async def _run_router(self, step: WorkflowStep, ctx: dict) -> str:
        """H10.13 — an agent picks a route label; dispatch to the mapped agent.

        The router agent (step.agent_id) replies with a label — either bare text
        containing a route name or JSON {"route": "<label>"}. The engine maps the
        label to an agent and runs it; falls back to ``default``. With no match
        and no default, the router's own reply is returned (no dispatch).
        """
        cfg = step.router or {}
        routes = cfg.get("routes", {}) or {}
        default = cfg.get("default", "")

        decision = await self._run_step(step, ctx)
        label = _match_route(decision, routes) or (default and "_default")
        chosen_agent = routes.get(label) if label and label != "_default" else default
        chosen_label = label if (label and label != "_default") else ("default" if default else "")

        ctx[f"{step.id}.route"] = chosen_label
        ctx[f"{step.id}.agent"] = chosen_agent or ""
        ctx.setdefault("_routes", {})[step.id] = {
            "route": chosen_label, "agent": chosen_agent or "", "decision": decision,
        }

        if not chosen_agent:
            return decision
        routed = WorkflowStep(
            id=f"{step.id}__routed",
            agent_id=chosen_agent,
            prompt_template=cfg.get("dispatch_template", "{_input}"),
        )
        return await self._run_step(routed, ctx)

    async def _run_critic(self, step: WorkflowStep, ctx: dict, step_map: dict) -> str:
        """H10.15 — evaluate a target step's output; re-run it on low scores.

        The critic agent is asked to reply with JSON {"score": 0-1, "pass": bool,
        "feedback": "..."}. While the critique fails and retries remain, the target
        step is re-run with the feedback available as {_critic_feedback}.
        """
        cfg = step.critic or {}
        target_id = cfg.get("target", "")
        threshold = float(cfg.get("pass_threshold", 0.7))
        max_retries = int(cfg.get("max_retries", 1))
        target_step = step_map.get(target_id)

        attempts = 0
        score = None
        passed = False
        feedback = ""
        critique = ""
        while True:
            attempts += 1
            critique = await self._run_step(step, ctx)
            parsed = extract_json(critique) or {}
            raw_score = parsed.get("score")
            try:
                score = float(raw_score) if raw_score is not None else None
            except (TypeError, ValueError):
                score = None
            feedback = str(parsed.get("feedback", ""))
            if "pass" in parsed:
                passed = bool(parsed["pass"])
            else:
                passed = score is not None and score >= threshold

            if passed or attempts > max_retries or target_step is None:
                break
            # Re-run the target with the critic's feedback in scope.
            ctx["_critic_feedback"] = feedback
            ctx[target_id] = await self._run_step(target_step, ctx)

        ctx[f"{step.id}.score"] = "" if score is None else str(score)
        ctx[f"{step.id}.passed"] = str(passed)
        ctx.setdefault("_critics", {})[step.id] = {
            "target": target_id, "score": score, "passed": passed,
            "feedback": feedback, "attempts": attempts,
        }
        return critique

    def _apply_structured(self, step: WorkflowStep, ctx: dict, errors: list) -> None:
        """H10.10 — validate a step's output against its schema and expose fields.

        Stores the result under ctx["_structured"][step.id] and, on success,
        flattens each field to ctx["{step.id}.{field}"] for template references.
        A validation failure marks the step as an error but does not raise.
        """
        result = validate_output(ctx.get(step.id, ""), step.output_schema)
        ctx["_structured"][step.id] = result
        if result["ok"]:
            for field, value in result["data"].items():
                ctx[f"{step.id}.{field}"] = "" if value is None else str(value)
        else:
            if step.id not in errors:
                errors.append(step.id)
            logger.warning("Step %r structured-output invalid: %s", step.id, result["error"])

    async def _run_step(self, step: WorkflowStep, ctx: dict) -> str:
        prompt = _render(step.prompt_template, ctx)
        if not step.agent_id or step.agent_id == "_passthrough":
            return prompt
        try:
            return await asyncio.wait_for(
                self._orch.handle_input(prompt, channel="workflow", agent_override=step.agent_id),
                timeout=_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Step %r timed out after %ss", step.id, _TIMEOUT)
            return f"[error:timeout after {_TIMEOUT}s]"
        except Exception as e:
            logger.warning("Step %r failed: %s", step.id, e)
            return f"[error:{e}]"


def _match_route(decision: str, routes: dict) -> str:
    """Resolve a route label from a router agent's reply (JSON or bare text)."""
    if not decision or not routes:
        return ""
    parsed = extract_json(decision)
    if isinstance(parsed, dict) and parsed.get("route") in routes:
        return str(parsed["route"])
    low = decision.lower()
    # Prefer an exact token-ish match; longest label first to avoid substrings.
    for label in sorted(routes, key=len, reverse=True):
        if label.lower() in low:
            return label
    return ""


def evaluate_condition(cond: dict, text: str) -> bool:
    """H10.12 — evaluate a termination guard against a step's output text.

    Supported ``type`` values: ``contains`` / ``not_contains`` (case-insensitive),
    ``equals`` (exact, trimmed), ``regex`` (search), ``not_empty``. Unknown or
    malformed conditions evaluate to False (fail-open: don't terminate).
    """
    if not isinstance(cond, dict):
        return False
    ctype = cond.get("type", "")
    value = cond.get("value", "")
    text = text or ""
    try:
        if ctype == "contains":
            return str(value).lower() in text.lower()
        if ctype == "not_contains":
            return str(value).lower() not in text.lower()
        if ctype == "equals":
            return text.strip() == str(value).strip()
        if ctype == "regex":
            return re.search(str(value), text) is not None
        if ctype == "not_empty":
            return bool(text.strip())
    except re.error:
        return False
    return False


def _render(template: str, ctx: dict) -> str:
    """Replace {key} tokens with ctx values; unknown keys → empty string."""
    def replace(m: re.Match) -> str:
        return str(ctx.get(m.group(1), ""))
    return re.sub(r"\{([^}]+)\}", replace, template)
