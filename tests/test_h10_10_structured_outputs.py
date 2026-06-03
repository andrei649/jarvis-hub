"""Tests for H10.10 — Structured Agent Outputs (Pydantic)."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.pipeline import Pipeline, WorkflowStep
from agents.core.workflows.structured import extract_json, validate_output

SCHEMA = {"fields": {
    "sentiment": {"type": "str", "required": True},
    "score": {"type": "float", "required": False, "default": 0.0},
}}


# ── json extraction ──────────────────────────────────────────────────────────

def test_extract_json_fenced_and_bare():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('here: {"a": 2} trailing') == {"a": 2}
    assert extract_json("no json here") is None
    assert extract_json("") is None


# ── validation / coercion ────────────────────────────────────────────────────

def test_validate_ok_and_coerces():
    r = validate_output('{"sentiment": "positive", "score": "0.9"}', SCHEMA)
    assert r["ok"] is True
    assert r["data"]["sentiment"] == "positive"
    assert r["data"]["score"] == 0.9            # coerced str→float


def test_validate_optional_default_applied():
    r = validate_output('{"sentiment": "neutral"}', SCHEMA)
    assert r["ok"] is True and r["data"]["score"] == 0.0


def test_validate_missing_required_fails():
    r = validate_output('{"score": 1.0}', SCHEMA)
    assert r["ok"] is False and "sentiment" in r["error"]


def test_validate_no_json_fails():
    r = validate_output("just prose, no object", SCHEMA)
    assert r["ok"] is False and "no JSON" in r["error"]


def test_bad_schema_reported():
    r = validate_output('{"a": 1}', {"fields": {}})
    assert r["ok"] is False and "schema" in r["error"]


# ── engine integration ───────────────────────────────────────────────────────

class _JSONOrch:
    """Returns a JSON object so the schema validates."""
    async def handle_input(self, text, channel="workflow", agent_override=None):
        return '{"sentiment": "positive", "score": 0.8}'


class _ProseOrch:
    async def handle_input(self, text, channel="workflow", agent_override=None):
        return "I think it's good, no JSON though."


@pytest.mark.asyncio
async def test_engine_exposes_structured_fields_downstream():
    p = Pipeline("p", "P", "", [
        WorkflowStep("classify", "ag", "{_input}", output_schema=SCHEMA),
        WorkflowStep("use", "_passthrough", "verdict={classify.sentiment} ({classify.score})",
                     depends_on=["classify"]),
    ])
    ctx = await WorkflowEngine(_JSONOrch()).run(p, "rate this")
    assert ctx["_structured"]["classify"]["ok"] is True
    assert ctx["classify.sentiment"] == "positive"
    # downstream template saw the typed field
    assert ctx["use"] == "verdict=positive (0.8)"
    assert ctx["_ok"] is True


@pytest.mark.asyncio
async def test_engine_marks_error_on_invalid_structured():
    p = Pipeline("p", "P", "", [
        WorkflowStep("classify", "ag", "{_input}", output_schema=SCHEMA),
    ])
    ctx = await WorkflowEngine(_ProseOrch()).run(p, "rate this")
    assert ctx["_structured"]["classify"]["ok"] is False
    assert "classify" in ctx["_errors"]
    assert ctx["_ok"] is False
