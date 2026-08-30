"""Workflow-engine limits — WFL-062 / WFL-063 / WFL-112.

Each of these defects manifests as a HANG or an unbounded call count rather than
a plain wrong answer, so the assertions here pin call counts and wall-clock, not
just return values. Hermetic: scripted orchestrators, no network, no LLM.
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.workflows.engine import (
    _MAX_CONDITION_PATTERN,
    _MAX_CONDITION_TEXT,
    _MAX_LOOP_DEPTH,
    WorkflowEngine,
    evaluate_condition,
)
from agents.core.workflows.hierarchical import MAX_RETRIES_CAP, HierarchicalManager
from agents.core.workflows.pipeline import Pipeline

# A pattern whose group body repeats and which is itself repeated: on an
# unmatched subject this backtracks exponentially. On unpatched HEAD a single
# `re.search` of it never returned within 60s.
REDOS = r"(a+)+$"
REDOS_SUBJECT = "a" * 200 + "!"


class _CountingOrch:
    """Counts agent calls; always fails validation so retries run to exhaustion."""

    def __init__(self, reply="[error:always]"):
        self.calls = 0
        self.reply = reply

    async def handle_input(self, text, channel="workflow", agent_override=None):
        self.calls += 1
        return self.reply


# ── WFL-062: bounded max_retries ─────────────────────────────────────────────

def _post(client, **body):
    payload = {"goal": "g", "crew": [{"id": "s", "agent": "jarvis"}]}
    payload.update(body)
    return client.post("/api/workflows/hierarchical", json=payload)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from agents import web
    with TestClient(web.app) as c:
        yield c


def test_over_cap_max_retries_refused(client):
    r = _post(client, max_retries=1_000_000)
    assert r.status_code == 400
    assert str(MAX_RETRIES_CAP) in r.json()["error"]


def test_infinite_max_retries_is_400_not_500(client):
    # `1e400` decodes to float("inf"); int(inf) raises OverflowError, which used
    # to escape the handler as a 500. Sent raw — the client's encoder won't emit inf.
    r = client.post(
        "/api/workflows/hierarchical",
        content='{"goal": "g", "crew": [{"id": "s", "agent": "jarvis"}], "max_retries": 1e400}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400


def test_negative_max_retries_refused(client):
    assert _post(client, max_retries=-1).status_code == 400


def test_max_retries_at_cap_accepted(client):
    r = _post(client, max_retries=MAX_RETRIES_CAP)
    assert r.status_code == 200
    assert "members" in r.json()


def test_string_max_retries_still_accepted(client):
    assert _post(client, max_retries="3").status_code == 200


@pytest.mark.asyncio
async def test_manager_clamps_retries_so_work_is_bounded():
    """The real DoS assertion: the run cannot exceed the cap in agent calls."""
    orch = _CountingOrch()
    mgr = HierarchicalManager(orch, max_retries=10**6)
    assert mgr.max_retries == MAX_RETRIES_CAP
    await mgr.run("g", [{"id": "t", "agent": "w"}])
    # (cap + 1) attempts for the crew member, plus one synthesis call.
    assert orch.calls <= MAX_RETRIES_CAP + 2


# ── WFL-063: bounded loop nesting ────────────────────────────────────────────

def _nested_loop_pipeline(levels: int, iterations: int) -> Pipeline:
    """A pipeline of *levels* loops nested one inside the next, innermost body a leaf."""
    body = [{"id": "leaf", "agent_id": "leaf", "prompt_template": "x"}]
    for depth in reversed(range(levels)):
        body = [{
            "id": f"loop{depth}", "agent_id": "_passthrough", "prompt_template": "",
            "kind": "loop", "loop": {"max_iterations": iterations, "steps": body},
        }]
    return Pipeline.from_dict({"id": "p", "name": "p", "steps": body})


@pytest.mark.asyncio
async def test_too_deep_loop_nesting_refused():
    orch = _CountingOrch(reply="x")
    levels = _MAX_LOOP_DEPTH + 1
    ctx = await WorkflowEngine(orch).run(_nested_loop_pipeline(levels, 3), "go")
    assert ctx["loop0"] == f"[error:loop: max nesting depth {_MAX_LOOP_DEPTH} exceeded]"
    # Unguarded this would be 3**4 = 81 leaf calls; the refused level runs none.
    assert orch.calls == 0
    assert ctx["_ok"] is False


@pytest.mark.asyncio
async def test_nesting_within_cap_still_runs():
    """Over-refusal guard: a legal 2-level nest keeps its full iteration product."""
    orch = _CountingOrch(reply="x")
    p = Pipeline.from_dict({"id": "p", "name": "p", "steps": [{
        "id": "outer", "agent_id": "_passthrough", "prompt_template": "",
        "kind": "loop", "loop": {"max_iterations": 4, "steps": [{
            "id": "inner", "agent_id": "_passthrough", "prompt_template": "",
            "kind": "loop", "loop": {"max_iterations": 3, "steps": [
                {"id": "leaf", "agent_id": "leaf", "prompt_template": "x"},
            ]},
        }]},
    }]})
    await WorkflowEngine(orch).run(p, "go")
    assert orch.calls == 12


@pytest.mark.asyncio
async def test_nested_loops_sharing_an_id_do_not_clobber_the_counter():
    orch = _CountingOrch(reply="x")
    p = Pipeline.from_dict({"id": "p", "name": "p", "steps": [{
        "id": "lp", "agent_id": "_passthrough", "prompt_template": "",
        "kind": "loop", "loop": {"max_iterations": 2, "steps": [{
            "id": "lp", "agent_id": "_passthrough", "prompt_template": "",
            "kind": "loop", "loop": {"max_iterations": 5, "steps": [
                {"id": "leaf", "agent_id": "leaf", "prompt_template": "x"},
            ]},
        }]},
    }]})
    ctx = await WorkflowEngine(orch).run(p, "go")
    assert ctx["lp._iter"] == "2"  # the OUTER counter, not the inner loop's 5


# ── WFL-112: bounded termination-condition regex ─────────────────────────────

def test_catastrophic_regex_refused_fast():
    t0 = time.monotonic()
    assert evaluate_condition({"type": "regex", "value": REDOS}, REDOS_SUBJECT) is False
    assert time.monotonic() - t0 < 1.0


def test_benign_regex_conditions_still_evaluate():
    assert evaluate_condition({"type": "regex", "value": r"score=\d+"}, "score=42")
    assert evaluate_condition({"type": "regex", "value": "^(foo|bar)$"}, "bar")
    assert evaluate_condition({"type": "regex", "value": "(?:ab)+"}, "abab")
    assert not evaluate_condition({"type": "regex", "value": r"score=\d+"}, "score=x")


def test_over_long_pattern_refused():
    long_pattern = "a" * (_MAX_CONDITION_PATTERN + 1)
    assert evaluate_condition({"type": "regex", "value": long_pattern}, "a" * 2000) is False


def test_subject_text_is_truncated():
    text = "b" * _MAX_CONDITION_TEXT + "needle"
    assert evaluate_condition({"type": "regex", "value": "needle"}, text) is False
    assert evaluate_condition({"type": "regex", "value": "needle"}, "needle") is True


@pytest.mark.asyncio
async def test_engine_terminate_when_redos_does_not_hang():
    """Covers the `terminate_when` call site inside the async run loop."""
    p = Pipeline.from_dict({"id": "p", "name": "p", "steps": [{
        "id": "s", "agent_id": "_passthrough", "prompt_template": REDOS_SUBJECT,
        "terminate_when": {"type": "regex", "value": REDOS},
    }]})
    ctx = await asyncio.wait_for(WorkflowEngine(_CountingOrch()).run(p, "go"), timeout=10)
    assert ctx["_terminated"] is False  # refused guard fails open: don't terminate
    assert ctx["_elapsed"] < 2.0


@pytest.mark.asyncio
async def test_loop_until_redos_does_not_hang():
    """Covers the loop `until` call site."""
    p = Pipeline.from_dict({"id": "p", "name": "p", "steps": [{
        "id": "lp", "agent_id": "_passthrough", "prompt_template": "",
        "kind": "loop", "loop": {
            "max_iterations": 3,
            "until": {"type": "regex", "value": REDOS},
            "steps": [{"id": "b", "agent_id": "_passthrough",
                       "prompt_template": REDOS_SUBJECT}],
        },
    }]})
    ctx = await asyncio.wait_for(WorkflowEngine(_CountingOrch()).run(p, "go"), timeout=10)
    assert ctx["_loops"]["lp"]["exited_by"] == "max_iterations"
    assert ctx["_elapsed"] < 2.0
