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
from typing import TYPE_CHECKING

from .pipeline import Pipeline, WorkflowStep
from .structured import validate_output

if TYPE_CHECKING:
    from agents.core.orchestrator import Orchestrator

logger = logging.getLogger("jarvis.workflows")

_TIMEOUT = 120.0  # seconds per step


class WorkflowEngine:
    """Run a Pipeline against the live orchestrator, sharing results between steps."""

    def __init__(self, orchestrator: Orchestrator):
        self._orch = orchestrator

    async def run(self, pipeline: Pipeline, initial_input: str) -> dict:
        """Execute *pipeline* and return {step_id: response, ..., _elapsed, _ok}."""
        t0 = time.monotonic()
        ctx: dict[str, str] = {"_input": initial_input}
        ctx["_structured"] = {}
        errors: list[str] = []

        terminated_by: str = ""

        for batch in pipeline.execution_batches():
            if len(batch) == 1:
                step = batch[0]
                out = await self._run_step(step, ctx)
                ctx[step.id] = out
                if out.startswith("[error:"):
                    errors.append(step.id)
            else:
                coros = [self._run_step(s, ctx) for s in batch]
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
        return ctx

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
