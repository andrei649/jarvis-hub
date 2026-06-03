"""Workflow pipeline data structures (H5.6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WorkflowStep:
    """One step in a Pipeline."""
    id: str
    agent_id: str          # target agent, or "" / "_passthrough" for pass-through
    prompt_template: str   # may reference {_input} or {<step_id>} from prior steps
    depends_on: list[str] = field(default_factory=list)
    # H10.12: optional early-termination guard evaluated against this step's output.
    # e.g. {"type": "contains", "value": "APPROVED"} → halt the pipeline if matched.
    terminate_when: Optional[dict] = None
    # H10.10: optional structured-output schema; engine validates the step's reply
    # and exposes typed fields as {step_id.field} to downstream steps.
    output_schema: Optional[dict] = None
    # H10.15: step kind — "agent" (default) or "critic". A critic evaluates a
    # target step's output (score + feedback) and can request re-runs.
    kind: str = "agent"
    # Critic config: {"target": <step_id>, "pass_threshold": 0.7, "max_retries": 1}.
    critic: Optional[dict] = None
    # H10.13: router config for kind=="router" — an agent picks a route label,
    # and the engine dispatches to the mapped agent.
    # {"routes": {"billing": "gecko", ...}, "default": "jarvis", "dispatch_template": "{_input}"}
    router: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "agent_id": self.agent_id,
            "prompt_template": self.prompt_template,
            "depends_on": self.depends_on,
        }
        if self.terminate_when:
            d["terminate_when"] = self.terminate_when
        if self.output_schema:
            d["output_schema"] = self.output_schema
        if self.kind and self.kind != "agent":
            d["kind"] = self.kind
        if self.critic:
            d["critic"] = self.critic
        if self.router:
            d["router"] = self.router
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowStep":
        return cls(
            id=d["id"],
            agent_id=d["agent_id"],
            prompt_template=d["prompt_template"],
            depends_on=list(d.get("depends_on") or []),
            terminate_when=d.get("terminate_when"),
            output_schema=d.get("output_schema"),
            kind=d.get("kind", "agent"),
            critic=d.get("critic"),
            router=d.get("router"),
        )


@dataclass
class Pipeline:
    """Directed acyclic graph of WorkflowSteps."""
    id: str
    name: str
    description: str
    steps: list[WorkflowStep]

    def execution_batches(self) -> list[list[WorkflowStep]]:
        """Topological sort → serial batches; steps within a batch run in parallel."""
        resolved: set[str] = set()
        batches: list[list[WorkflowStep]] = []
        remaining = list(self.steps)
        while remaining:
            ready = [s for s in remaining if all(d in resolved for d in s.depends_on)]
            if not ready:
                raise ValueError(
                    f"Cycle or unresolved dependency in pipeline '{self.id}': "
                    f"stuck on {[s.id for s in remaining]}"
                )
            batch_ids = {s.id for s in ready}
            batches.append(ready)
            resolved |= batch_ids
            remaining = [s for s in remaining if s.id not in batch_ids]
        return batches

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Pipeline":
        steps = [WorkflowStep.from_dict(s) for s in d.get("steps", [])]
        pipeline = cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            description=d.get("description", ""),
            steps=steps,
        )
        # Validate DAG — raises ValueError on cycles or unresolved deps.
        pipeline.execution_batches()
        return pipeline
