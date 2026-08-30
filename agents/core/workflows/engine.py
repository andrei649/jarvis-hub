"""WorkflowEngine — executes Pipeline instances (H5.6).

Coordinates multi-agent pipelines: parallel branches, sequential steps,
shared intermediate results.  Injects results via template substitution
so downstream steps can reference upstream outputs.
"""
from __future__ import annotations

import asyncio
import contextlib
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
_MAX_DEPTH = 5  # H10.14 — max nested sub-workflow recursion depth
# H22.6 — cap concurrent steps within a parallel batch so a wide pipeline can't
# fan out into dozens of simultaneous LLM calls (one per agent) and starve the
# interactive path. Each step already has a per-step timeout (_TIMEOUT).
_MAX_PARALLEL_STEPS = 8
# WFL-063 — max nested loop depth. Mirrors the subflow guard above in shape, with
# a lower number on purpose: a subflow level adds one pipeline, while each loop
# level MULTIPLIES the work below it by up to _MAX_ITERATIONS.
_MAX_LOOP_DEPTH = 3
_MAX_ITERATIONS = 100  # per-level iteration clamp (H10.6)
# WFL-112 — bounds for a caller-supplied `regex` condition. The pattern is refused
# structurally (see _has_nested_quantifier) rather than run under a timeout:
# CPython's `re` holds the GIL for the whole match, so neither asyncio.to_thread
# nor a worker thread can interrupt a catastrophic backtrack — offloading would
# only move the stall off this coroutine while still wedging a shared executor
# slot. A pattern that cannot start cannot hang the loop.
_MAX_CONDITION_PATTERN = 512
_MAX_CONDITION_TEXT = 8192


def persist_enabled() -> bool:
    """``JARVIS_WORKFLOW_PERSIST`` — ONE parse for engine and coordinator (O26-P2.1).

    Pre-P2.1 the autonomy coordinator presence-checked this var (so ``=0``
    *enabled* the pending-queue drain) while this module truthy-checked it;
    the same deployment could have the store off and the drain on.
    """
    from agents.core.env_config import env_flag
    return env_flag("JARVIS_WORKFLOW_PERSIST")


class WorkflowEngine:
    """Run a Pipeline against the live orchestrator, sharing results between steps."""

    def __init__(self, orchestrator: Orchestrator, run_store=None):
        self._orch = orchestrator
        # H10.2: ring of recent run traces for the visual overlay.
        self.recent_runs: deque = deque(maxlen=_MAX_RECENT_RUNS)
        # 0.34: optional run-history persistence so the overlay survives a restart.
        # Opt-in: a store is attached only when one is passed (tests) or
        # JARVIS_WORKFLOW_PERSIST is set — default None keeps behavior unchanged.
        if run_store is None and persist_enabled():
            try:
                from .run_store import WorkflowRunStore
                run_store = WorkflowRunStore()
            except Exception:
                logger.warning("workflow run-store init failed — persistence off", exc_info=True)
        self._run_store = run_store
        if self._run_store is not None:
            try:
                self.recent_runs.extend(self._run_store.all())   # seed from disk (deque caps to last N)
            except Exception:
                logger.warning("workflow run-store seed failed", exc_info=True)

    async def run(self, pipeline: Pipeline, initial_input: str, _depth: int = 0) -> dict:
        """Execute *pipeline* and return {step_id: response, ..., _elapsed, _ok}."""
        t0 = time.monotonic()
        ctx: dict[str, str] = {"_input": initial_input}
        ctx["_structured"] = {}
        ctx["_depth"] = _depth
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
                # H22.6 — bound the parallel fan-out with a semaphore so a wide
                # batch interleaves at most _MAX_PARALLEL_STEPS at a time instead
                # of launching every step's LLM call at once.
                sem = asyncio.Semaphore(_MAX_PARALLEL_STEPS)

                async def _bounded(s, _sem=sem):
                    async with _sem:
                        return await self._traced_execute(s, ctx, step_map)

                coros = [_bounded(s) for s in batch]
                outputs = await asyncio.gather(*coros, return_exceptions=True)
                for step, out in zip(batch, outputs):
                    if isinstance(out, Exception):
                        ctx[step.id] = f"[error:{out}]"
                        errors.append(step.id)
                    else:
                        ctx[step.id] = out
                        # WFL-032: a RETURNED "[error:…]" (timeout, validator,
                        # guardrail, subflow) must fail the run exactly like the
                        # serial branch — not only raised exceptions.
                        if isinstance(out, str) and out.startswith("[error:"):
                            errors.append(step.id)

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
        self._stash_run({
            "pipeline_id": pipeline.id,
            "pipeline_name": pipeline.name,
            "ts": time.time(),
            "elapsed": ctx["_elapsed"],
            "ok": ctx["_ok"],
            "terminated_by": terminated_by,
            "steps": list(ctx["_trace"]),
        })
        return ctx

    async def drain_pending(self, queue, resolve, *, now: float | None = None,
                            max_runs: int = 25) -> dict:
        """0.34 (opt-in): execute due runs from a :class:`WorkflowPendingQueue`, completing
        or retrying each. ``resolve(pipeline_id) -> Pipeline | None`` keeps the engine
        decoupled from the registry/store. Returns a summary; **nothing calls this on the
        default path** — a caller (e.g. the autonomy coordinator, a deliberate later wave)
        opts in by passing a queue. A run that raises or returns ``_ok=False`` is retried
        with backoff until its attempt cap, then parked ``dead`` (never silently dropped)."""
        now = float(now if now is not None else time.time())
        summary = {"ran": 0, "done": 0, "retried": 0, "dead": 0, "skipped": 0}
        for item in queue.due(now)[:max(1, int(max_runs))]:
            pipeline = None
            with contextlib.suppress(Exception):
                pipeline = resolve(item.get("pipeline_id"))
            if pipeline is None:
                res = queue.fail(item["id"], "pipeline not found", now=now)
                summary["dead" if (res or {}).get("status") == "dead" else "retried"] += 1
                continue
            summary["ran"] += 1
            try:
                result = await self.run(pipeline, item.get("input", ""))
                ok = bool(result.get("_ok"))
                err = "" if ok else "; ".join(result.get("_errors", []) or []) or "workflow reported failure"
            except Exception as e:  # a crashing run must retry, not vanish
                ok, err = False, f"{type(e).__name__}: {e}"
            if ok:
                queue.complete(item["id"])
                summary["done"] += 1
            else:
                res = queue.fail(item["id"], err, now=now)
                summary["dead" if (res or {}).get("status") == "dead" else "retried"] += 1
        return summary

    def _stash_run(self, record: dict) -> None:
        """Append a run record to the in-memory ring and (0.34, opt-in) persist it."""
        self.recent_runs.append(record)
        # getattr: some tests build the engine via __new__ (bypassing __init__).
        store = getattr(self, "_run_store", None)
        if store is not None:
            try:
                store.record(record)
            except Exception:
                logger.warning("workflow run-store record failed", exc_info=True)

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
        if step.kind == "subflow":
            return await self._run_subflow(step, ctx)
        return await self._run_step(step, ctx)

    async def _run_subflow(self, step: WorkflowStep, ctx: dict) -> str:
        """H10.14 — run a nested sub-pipeline as a single step (recursive decomposition).

        The step's rendered prompt_template is the sub-pipeline's input; the sub
        steps' outputs are exposed as ``{step.id}.{sub_step_id}`` and the final sub
        step's output becomes this step's output. Recursion is capped at depth 5.
        """
        from .pipeline import Pipeline
        depth = int(ctx.get("_depth", 0))
        if depth >= _MAX_DEPTH:
            return f"[error:subflow: max nesting depth {_MAX_DEPTH} exceeded]"
        cfg = step.subflow or {}
        try:
            sub = Pipeline.from_dict({
                "id": cfg.get("id", f"{step.id}_sub"),
                "name": cfg.get("name", step.id),
                "description": cfg.get("description", ""),
                "steps": cfg.get("steps", []),
            })
        except (ValueError, KeyError) as e:
            return f"[error:subflow: {e}]"
        if not sub.steps:
            return ctx.get(step.id, "")

        sub_input = _render(step.prompt_template, ctx)
        sub_ctx = await self.run(sub, sub_input, _depth=depth + 1)
        for k, v in sub_ctx.items():
            if not k.startswith("_"):
                ctx[f"{step.id}.{k}"] = v
        ctx.setdefault("_subflows", {})[step.id] = {
            "ok": sub_ctx.get("_ok", True),
            "steps": sub_ctx.get("_trace", []),
        }
        output_key = cfg.get("output") or sub.steps[-1].id
        return sub_ctx.get(output_key, "")

    async def _run_loop(self, step: WorkflowStep, ctx: dict, step_map: dict) -> str:
        """H10.6 — re-run an inline body of steps until an exit condition or cap.

        A loop-back edge with an iteration counter: the body (``loop.steps``) runs
        in listed order, sharing ``ctx``; after each pass the ``until`` condition is
        checked against the last body step's output. Useful for retry loops and
        iterative refinement. ``max_iterations`` is clamped to [1, 100], and
        nesting to ``_MAX_LOOP_DEPTH`` levels (WFL-063) — the per-level clamp
        bounds breadth only, so without a depth guard N levels cost 100**N runs.
        """
        cfg = step.loop or {}
        # Loops nest inside one `run()`, so they need their own counter: `_depth`
        # tracks subflow recursion across runs and is not incremented here.
        depth = int(ctx.get("_loop_depth", 0))
        if depth >= _MAX_LOOP_DEPTH:
            return f"[error:loop: max nesting depth {_MAX_LOOP_DEPTH} exceeded]"
        max_iter = max(1, min(_MAX_ITERATIONS, int(cfg.get("max_iterations", 3) or 3)))
        until = cfg.get("until")
        body = [b if isinstance(b, WorkflowStep) else WorkflowStep.from_dict(b)
                for b in (cfg.get("steps") or [])]
        if not body:
            return ctx.get(step.id, "")

        iter_key = f"{step.id}._iter"
        outer_iter = ctx.get(iter_key)
        iterations, exited_by, last = 0, "max_iterations", ctx.get(step.id, "")
        ctx["_loop_depth"] = depth + 1
        try:
            for i in range(max_iter):
                iterations += 1
                ctx[iter_key] = str(i + 1)
                for b in body:
                    ctx[b.id] = await self._execute_step(b, ctx, step_map)
                last = ctx.get(body[-1].id, "")
                if until and evaluate_condition(until, last):
                    exited_by = "condition"
                    break
        finally:
            ctx["_loop_depth"] = depth
            # A nested loop sharing an outer loop's step id would otherwise
            # clobber its counter. Only restore when nested: at depth 0 the
            # final value stays visible, as templates downstream expect.
            if depth > 0 and outer_iter is not None:
                ctx[iter_key] = outer_iter
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


def _has_nested_quantifier(pattern: str) -> bool:
    """True if *pattern* quantifies a group whose body itself repeats or alternates.

    That shape — ``(a+)+``, ``(a|aa)+``, ``(([a-z])+.)+`` — is what turns a match
    into exponential backtracking. Scanned character by character rather than with
    a regex, because a regex that parses regexes is its own ReDoS. Conservative by
    design: a false positive costs one refused guard, a false negative costs the
    worker.
    """
    stack: list[bool] = []  # one flag per open group: "body repeats or alternates"
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":  # character class — quantifier chars are literal inside
            i += 1
            if i < n and pattern[i] == "^":
                i += 1
            if i < n and pattern[i] == "]":
                i += 1
            while i < n and pattern[i] != "]":
                i += 2 if pattern[i] == "\\" else 1
            i += 1
            continue
        if ch == "(":
            stack.append(False)
            i += 1
            if i < n and pattern[i] == "?":  # (?:…) (?=…) (?<…) (?P<…>…) (?i)
                i += 1
                if i < n and pattern[i] == "P":
                    i += 1
                if i < n and pattern[i] == "<":
                    i += 1
                    if i < n and pattern[i] in "=!":
                        i += 1
                    else:
                        while i < n and pattern[i] != ">":
                            i += 1
                        i += 1
                elif i < n and pattern[i] in ":=!":
                    i += 1
                elif i < n and pattern[i] == "#":
                    while i < n and pattern[i] != ")":
                        i += 1
                else:
                    while i < n and pattern[i] in "aiLmsux-":
                        i += 1
                    if i < n and pattern[i] == ":":
                        i += 1
            continue
        if ch == ")":
            flagged = stack.pop() if stack else False
            quantified = i + 1 < n and pattern[i + 1] in "*+{"
            if flagged and quantified:
                return True
            if stack and (flagged or quantified):
                stack[-1] = True  # the enclosing body repeats too
            i += 1
            continue
        if ch in "*+?{|" and stack:
            stack[-1] = True
        i += 1
    return False


def _safe_regex_search(pattern: str, text: str) -> bool:
    """WFL-112 — run a caller-supplied condition pattern only if it is safe to run.

    Refuses (fail-open, matching the evaluator's contract for a malformed
    condition) an over-long or exponentially-backtracking pattern, and truncates
    the subject text. Refusal, not a timeout, is the mechanism: see the note on
    ``_MAX_CONDITION_PATTERN`` for why a match cannot be interrupted once started.
    """
    if len(pattern) > _MAX_CONDITION_PATTERN:
        logger.warning("Workflow condition regex refused: pattern over %d chars",
                       _MAX_CONDITION_PATTERN)
        return False
    if _has_nested_quantifier(pattern):
        logger.warning("Workflow condition regex refused: nested quantifier (ReDoS risk)")
        return False
    return re.search(pattern, text[:_MAX_CONDITION_TEXT]) is not None


def evaluate_condition(cond: dict, text: str) -> bool:
    """H10.12 — evaluate a termination guard against a step's output text.

    Supported ``type`` values: ``contains`` / ``not_contains`` (case-insensitive),
    ``equals`` (exact, trimmed), ``regex`` (search), ``not_empty``. Unknown or
    malformed conditions evaluate to False (fail-open: don't terminate) — as does
    a ``regex`` refused by the WFL-112 bounds.
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
            return _safe_regex_search(str(value), text)
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
