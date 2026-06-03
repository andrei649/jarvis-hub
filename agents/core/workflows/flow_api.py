"""
flow_api.py — H10.9 Python Flow Decorator API.

Define workflows in Python code (complement to the YAML/JSON Visual Builder),
CrewAI-style, then compile to the existing Pipeline so the WorkflowEngine runs
them unchanged::

    @jarvis_flow(name="Research")
    class ResearchFlow:
        @step
        def gather(self):
            return {"agent": "researcher", "prompt": "research: {_input}"}

        @listen("gather")
        def summarize(self):
            return {"agent": "writer", "prompt": "summarize: {gather}"}

        @router("summarize")
        def route(self):
            return {"router": {"routes": {"deep": "analyst"}, "default": "jarvis"}}

    pipeline = build_flow(ResearchFlow)

Each decorated method returns a *step spec* dict: ``agent``/``agent_id``,
``prompt``/``prompt_template``, and optional ``transform``/``guardrail``/
``router``/``loop``/``output_schema``/``terminate_when``/``critic``. The step id
is the method name; ``@listen`` sets dependencies; method definition order is
preserved.
"""

from __future__ import annotations

import re
from typing import Union

from .pipeline import Pipeline, WorkflowStep


def jarvis_flow(name: str = "", description: str = ""):
    """Class decorator marking a flow definition."""
    def deco(cls):
        cls._is_flow = True
        cls._flow_name = name or cls.__name__
        cls._flow_description = description
        return cls
    return deco


def _mark(fn, *, depends_on=None, kind="agent"):
    fn._step = {"id": fn.__name__, "depends_on": list(depends_on or []), "kind": kind}
    return fn


def step(fn=None, *, depends_on=None, kind="agent"):
    """Mark a method as a workflow step (a root step by default)."""
    if fn is not None:
        return _mark(fn, depends_on=depends_on, kind=kind)
    return lambda f: _mark(f, depends_on=depends_on, kind=kind)


def listen(*step_ids):
    """Mark a step that runs after (depends on) the given step ids."""
    return lambda f: _mark(f, depends_on=list(step_ids), kind="agent")


def router(*step_ids):
    """Mark a router step depending on the given step ids."""
    return lambda f: _mark(f, depends_on=list(step_ids), kind="router")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "flow"


def build_flow(flow: Union[type, object]) -> Pipeline:
    """Compile a ``@jarvis_flow`` class (or instance) into a validated Pipeline."""
    cls = flow if isinstance(flow, type) else type(flow)
    if not getattr(cls, "_is_flow", False):
        raise ValueError("build_flow expects a @jarvis_flow-decorated class")
    inst = cls() if isinstance(flow, type) else flow

    steps: list[WorkflowStep] = []
    for name, attr in vars(cls).items():               # definition order (py3.7+)
        meta = getattr(attr, "_step", None)
        if not meta:
            continue
        spec = getattr(inst, name)() or {}
        steps.append(WorkflowStep(
            id=meta["id"],
            agent_id=spec.get("agent_id", spec.get("agent", "")),
            prompt_template=spec.get("prompt_template", spec.get("prompt", "")),
            depends_on=meta["depends_on"],
            kind=spec.get("kind", meta["kind"]),
            terminate_when=spec.get("terminate_when"),
            output_schema=spec.get("output_schema"),
            critic=spec.get("critic"),
            router=spec.get("router"),
            transform=spec.get("transform"),
            guardrail=spec.get("guardrail"),
            loop=spec.get("loop"),
        ))
    if not steps:
        raise ValueError(f"flow '{cls._flow_name}' defines no steps")

    pipeline = Pipeline(
        id=_slug(cls._flow_name),
        name=cls._flow_name,
        description=cls._flow_description,
        steps=steps,
    )
    pipeline.execution_batches()   # validate DAG (raises on cycle/unresolved dep)
    return pipeline
