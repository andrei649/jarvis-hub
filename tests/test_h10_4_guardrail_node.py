"""Tests for H10.4 — Guardrails Node in the Visual Builder."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.guardrail_node import apply_guardrail
from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.pipeline import Pipeline, WorkflowStep

SECRET = "key is sk-abcdefghijklmnopqrstuvwxyz123456"
EMAIL = "reach me at bob@example.com please"
CLEAN = "just a normal sentence"


# ── unit: modes ──────────────────────────────────────────────────────────────

def test_clean_input_passes():
    out, info = apply_guardrail({"mode": "block"}, CLEAN)
    assert out == CLEAN and info["clean"] is True and info["action"] == "pass"


def test_warn_passes_through_with_findings():
    out, info = apply_guardrail({"mode": "warn"}, SECRET)
    assert out == SECRET
    assert info["action"] == "warn" and "openai_key" in info["findings"]


def test_redact_masks_value():
    out, info = apply_guardrail({"mode": "redact", "scanners": ["secret"]}, SECRET)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in out
    assert info["action"] == "redact"


def test_block_returns_error():
    out, info = apply_guardrail({"mode": "block"}, SECRET)
    assert out.startswith("[error:guardrail blocked:") and "openai_key" in out
    assert info["action"] == "block"


def test_scanner_selection():
    # only the PII scanner → a secret-only string is clean
    out, info = apply_guardrail({"mode": "block", "scanners": ["pii"]}, SECRET)
    assert info["clean"] is True
    out2, info2 = apply_guardrail({"mode": "redact", "scanners": ["pii"]}, EMAIL)
    assert "bob@example.com" not in out2 and info2["action"] == "redact"


# ── serialization ────────────────────────────────────────────────────────────

def test_step_roundtrip_guardrail():
    s = WorkflowStep("g", "_passthrough", "{prev}", depends_on=["prev"],
                     kind="guardrail", guardrail={"mode": "block", "scanners": ["secret"]})
    s2 = WorkflowStep.from_dict(s.to_dict())
    assert s2.kind == "guardrail" and s2.guardrail["mode"] == "block"


# ── engine integration ───────────────────────────────────────────────────────

class _LeakyOrch:
    async def handle_input(self, text, channel="workflow", agent_override=None):
        return SECRET


@pytest.mark.asyncio
async def test_guardrail_block_marks_error_and_records_info():
    p = Pipeline("p", "P", "", [
        WorkflowStep("gen", "writer", "{_input}"),
        WorkflowStep("gate", "_passthrough", "{gen}", depends_on=["gen"],
                     kind="guardrail", guardrail={"mode": "block"}),
    ])
    ctx = await WorkflowEngine(_LeakyOrch()).run(p, "go")
    assert ctx["gate"].startswith("[error:guardrail blocked:")
    assert "gate" in ctx["_errors"] and ctx["_ok"] is False
    assert ctx["_guardrails"]["gate"]["action"] == "block"


@pytest.mark.asyncio
async def test_guardrail_redact_lets_pipeline_continue():
    p = Pipeline("p", "P", "", [
        WorkflowStep("gen", "writer", "{_input}"),
        WorkflowStep("gate", "_passthrough", "{gen}", depends_on=["gen"],
                     kind="guardrail", guardrail={"mode": "redact"}),
    ])
    ctx = await WorkflowEngine(_LeakyOrch()).run(p, "go")
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in ctx["gate"]
    assert ctx["_ok"] is True
