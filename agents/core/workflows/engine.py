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
        errors: list[str] = []

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

        ctx["_elapsed"] = round(time.monotonic() - t0, 2)
        ctx["_ok"] = len(errors) == 0
        ctx["_errors"] = errors
        return ctx

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


def _render(template: str, ctx: dict) -> str:
    """Replace {key} tokens with ctx values; unknown keys → empty string."""
    def replace(m: re.Match) -> str:
        return str(ctx.get(m.group(1), ""))
    return re.sub(r"\{([^}]+)\}", replace, template)
