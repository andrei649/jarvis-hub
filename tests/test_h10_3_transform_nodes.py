"""Tests for H10.3 — Workflow Transform Nodes."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.transforms import apply_transform
from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.pipeline import Pipeline, WorkflowStep


# ── unit: each op ────────────────────────────────────────────────────────────

def test_formatter_modes():
    assert apply_transform({"op": "formatter", "mode": "upper"}, "hi") == "HI"
    assert apply_transform({"op": "formatter", "mode": "strip"}, "  x  ") == "x"
    pretty = apply_transform({"op": "formatter", "mode": "json_pretty"}, '{"a":1}')
    assert '"a": 1' in pretty
    assert "[error:" in apply_transform({"op": "formatter", "mode": "json_pretty"}, "nope")


def test_validator_pass_and_fail():
    assert apply_transform({"op": "validator", "check": "non_empty"}, "ok") == "ok"
    assert apply_transform({"op": "validator", "check": "non_empty"}, "  ").startswith("[error:validation")
    assert apply_transform({"op": "validator", "check": "json"}, '{"a":1}') == '{"a":1}'
    assert apply_transform({"op": "validator", "check": "json"}, "x").startswith("[error:")
    assert apply_transform({"op": "validator", "check": "min_length", "value": 5}, "abc").startswith("[error:")
    assert apply_transform({"op": "validator", "check": "contains", "value": "ok"}, "all ok") == "all ok"


def test_json_extract_dotpath_and_default():
    blob = '{"user": {"name": "Bob"}, "items": [10, 20]}'
    assert apply_transform({"op": "json_extract", "field": "user.name"}, blob) == "Bob"
    assert apply_transform({"op": "json_extract", "field": "items.1"}, blob) == "20"
    assert apply_transform({"op": "json_extract", "field": "missing", "default": "—"}, blob) == "—"
    assert apply_transform({"op": "json_extract", "field": "x"}, "notjson").startswith("[error:")


def test_summarize_truncates():
    text = "First sentence. Second one. Third here. Fourth ignored."
    out = apply_transform({"op": "summarize", "max_sentences": 2}, text)
    assert out == "First sentence. Second one."


def test_unknown_op():
    assert apply_transform({"op": "frobnicate"}, "x").startswith("[error:transform: unknown op")


# ── serialization ────────────────────────────────────────────────────────────

def test_step_roundtrip_transform():
    s = WorkflowStep("t", "_passthrough", "{prev}", depends_on=["prev"],
                     kind="transform", transform={"op": "formatter", "mode": "upper"})
    s2 = WorkflowStep.from_dict(s.to_dict())
    assert s2.kind == "transform" and s2.transform["mode"] == "upper"


# ── integration via engine ───────────────────────────────────────────────────

class _MockOrch:
    async def handle_input(self, text, channel="workflow", agent_override=None):
        return '{"name": "Ada", "age": 36}'


@pytest.mark.asyncio
async def test_transform_step_in_pipeline():
    p = Pipeline("p", "P", "", [
        WorkflowStep("gen", "writer", "{_input}"),
        WorkflowStep("name", "_passthrough", "{gen}", depends_on=["gen"],
                     kind="transform", transform={"op": "json_extract", "field": "name"}),
        WorkflowStep("shout", "_passthrough", "{name}", depends_on=["name"],
                     kind="transform", transform={"op": "formatter", "mode": "upper"}),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "go")
    assert ctx["name"] == "Ada"
    assert ctx["shout"] == "ADA"
    assert ctx["_ok"] is True


@pytest.mark.asyncio
async def test_transform_validator_failure_marks_error():
    p = Pipeline("p", "P", "", [
        WorkflowStep("gen", "writer", "{_input}"),
        WorkflowStep("check", "_passthrough", "{gen}", depends_on=["gen"],
                     kind="transform", transform={"op": "validator", "check": "min_length", "value": 9999}),
    ])
    ctx = await WorkflowEngine(_MockOrch()).run(p, "go")
    assert "check" in ctx["_errors"] and ctx["_ok"] is False
