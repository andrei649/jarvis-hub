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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "prompt_template": self.prompt_template,
            "depends_on": self.depends_on,
        }


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
