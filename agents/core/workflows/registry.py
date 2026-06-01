"""Built-in workflow templates (H5.6).

Each Pipeline is a reusable recipe.  Add custom pipelines at runtime via
WorkflowRegistry.register().
"""
from __future__ import annotations

from .pipeline import Pipeline, WorkflowStep

_BUILTIN: list[Pipeline] = [
    Pipeline(
        id="finance_report",
        name="Finance Report",
        description="Fetch balances + health data, draft a summary, send via Telegram.",
        steps=[
            WorkflowStep(
                id="balance",
                agent_id="gecko",
                prompt_template="Ce sold am în conturi? Răspunde scurt.",
            ),
            WorkflowStep(
                id="health",
                agent_id="hercules",
                prompt_template="Care e statusul meu de sănătate azi? Răspunde scurt.",
            ),
            WorkflowStep(
                id="summary",
                agent_id="veronica",
                prompt_template=(
                    "Scrie un rezumat de 3 bullet-uri pe baza acestor date:\n"
                    "Financiar: {balance}\nSănătate: {health}"
                ),
                depends_on=["balance", "health"],
            ),
        ],
    ),
    Pipeline(
        id="research_and_brief",
        name="Research & Brief",
        description="Research a topic and produce a structured briefing.",
        steps=[
            WorkflowStep(
                id="research",
                agent_id="vision",
                prompt_template="Cercetează: {_input}. Returnează 5 puncte cheie.",
            ),
            WorkflowStep(
                id="brief",
                agent_id="veronica",
                prompt_template=(
                    "Pe baza cercetării de mai jos, scrie un briefing structurat "
                    "(intro, 3 secțiuni, concluzie):\n{research}"
                ),
                depends_on=["research"],
            ),
        ],
    ),
    Pipeline(
        id="security_digest",
        name="Security Digest",
        description="Run a security scan and system check in parallel, then summarize.",
        steps=[
            WorkflowStep(
                id="security",
                agent_id="ultron",
                prompt_template="Status securitate sistem acum. Scurt.",
            ),
            WorkflowStep(
                id="system",
                agent_id="steve",
                prompt_template="Status hardware și procese critice acum. Scurt.",
            ),
            WorkflowStep(
                id="digest",
                agent_id="jarvis",
                prompt_template=(
                    "Sintetizează în max 5 rânduri:\n"
                    "Securitate: {security}\nSistem: {system}"
                ),
                depends_on=["security", "system"],
            ),
        ],
    ),
]


class WorkflowRegistry:
    """In-memory registry of named pipelines."""

    def __init__(self) -> None:
        self._pipelines: dict[str, Pipeline] = {p.id: p for p in _BUILTIN}

    def register(self, pipeline: Pipeline) -> None:
        self._pipelines[pipeline.id] = pipeline

    def get(self, pipeline_id: str) -> Pipeline | None:
        return self._pipelines.get(pipeline_id)

    def list(self) -> list[dict]:
        return [p.to_dict() for p in self._pipelines.values()]

    def ids(self) -> list[str]:
        return list(self._pipelines.keys())
