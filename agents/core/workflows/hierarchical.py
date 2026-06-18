"""
hierarchical.py — H10.11 Hierarchical Workflow Manager.

A `hierarchical` workflow mode where a **manager** agent coordinates a crew:
it runs each crew member toward the goal, validates the result, and
**redistributes** (retries — optionally to a fallback agent, with feedback) when
a step fails. Finally the manager synthesizes the crew's outputs into one answer.

Complements the flat-DAG WorkflowEngine; here control is centralized in the
manager rather than encoded as edges.
"""

from __future__ import annotations

import re
from typing import Optional


def _render(template: str, ctx: dict) -> str:
    # Possessive `[^}]++` keeps the match linear (no O(n²) backtracking on input
    # with unmatched `{`) — same capture/behavior. CodeQL #302.
    return re.sub(r"\{([^}]++)\}", lambda m: str(ctx.get(m.group(1), "")), template)


def _ok(text: str) -> bool:
    return bool((text or "").strip()) and not (text or "").startswith("[error:")


class HierarchicalManager:
    def __init__(self, orchestrator, manager_agent: str = "jarvis", max_retries: int = 1) -> None:
        self._orch = orchestrator
        self.manager_agent = manager_agent
        self.max_retries = max(0, int(max_retries))

    async def _run(self, agent: str, prompt: str) -> str:
        try:
            return await self._orch.handle_input(prompt, channel="workflow", agent_override=agent)
        except Exception as e:
            return f"[error:{e}]"

    async def _run_member(self, member: dict, goal: str, ctx: dict) -> dict:
        agent = member.get("agent", self.manager_agent)
        fallback = member.get("fallback")
        prompt_tmpl = member.get("prompt", "{_goal}")
        used_agent, feedback, attempts, out = agent, "", 0, ""
        while attempts <= self.max_retries:
            attempts += 1
            prompt = _render(prompt_tmpl, {**ctx, "_goal": goal})
            if feedback:
                prompt = f"{prompt}\n\n[Manager feedback]: {feedback}"
            out = await self._run(used_agent, prompt)
            if _ok(out):
                break
            # redistribute: prefer a fallback agent, carry corrective feedback
            feedback = "Previous attempt failed validation; correct and retry."
            if fallback and used_agent != fallback:
                used_agent = fallback
        return {
            "id": member.get("id", agent),
            "agent": used_agent,
            "output": out,
            "attempts": attempts,
            "redistributed": used_agent != agent,
            "ok": _ok(out),
        }

    async def _synthesize(self, goal: str, results: list[dict]) -> str:
        parts = "\n".join(f"- {r['id']}: {r['output']}" for r in results)
        prompt = (f"Goal: {goal}\n\nCrew results:\n{parts}\n\n"
                  f"Synthesize these into a single final answer for the goal.")
        return await self._run(self.manager_agent, prompt)

    async def run(self, goal: str, crew: list[dict]) -> dict:
        """Coordinate *crew* toward *goal*: run → validate → redistribute → synthesize."""
        ctx: dict = {"_goal": goal}
        results: list[dict] = []
        for member in crew or []:
            r = await self._run_member(member, goal, ctx)
            ctx[r["id"]] = r["output"]
            results.append(r)
        final = await self._synthesize(goal, results) if results else ""
        return {
            "goal": goal,
            "manager": self.manager_agent,
            "members": results,
            "final": final,
            "ok": all(r["ok"] for r in results) if results else True,
            "redistributed": [r["id"] for r in results if r["redistributed"]],
        }
