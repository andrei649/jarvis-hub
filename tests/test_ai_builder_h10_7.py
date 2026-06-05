"""H10.7: AI-assisted workflow step builder.

A plain-language description becomes a validated step config (kind/agent
allowlisted, no stray fields). The LLM is injectable and there's a deterministic
keyword fallback, so it works offline and never returns junk.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.workflows.ai_builder import generate_step, KNOWN_KINDS  # noqa: E402
import agents.web as web  # noqa: E402

AGENTS = ["jarvis", "vision", "stark"]


def _fake_llm(reply):
    async def llm(_prompt):
        return reply
    return llm


# ── heuristic (no LLM) ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("desc,kind,extra", [
    ("redact any secrets before sending", "guardrail", {}),
    ("extract the JSON fields from the reply", "transform", {"transform": "json_extract"}),
    ("summarize the research findings", "transform", {"transform": "summarize"}),
    ("choose which agent should handle it", "router", {}),
    ("score the answer and retry until good", "critic", {}),
    ("loop until the list is complete", "loop", {}),
    ("ask vision to research the topic", "agent", {"agent": "vision"}),
])
async def test_heuristic_maps_keywords(desc, kind, extra):
    cfg = await generate_step(desc, AGENTS, llm=None)
    assert cfg["kind"] == kind
    assert cfg["source"] == "heuristic"
    for k, v in extra.items():
        assert cfg[k] == v


@pytest.mark.asyncio
async def test_empty_description_defaults_to_agent():
    cfg = await generate_step("", AGENTS)
    assert cfg["kind"] == "agent" and cfg["agent"] == "jarvis" and cfg["prompt"] == "{_input}"


# ── with an LLM ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_valid_json_is_used_and_validated():
    reply = 'Sure! ' + json.dumps({"kind": "agent", "agent": "vision", "prompt": "research {_input}"})
    cfg = await generate_step("do research", AGENTS, llm=_fake_llm(reply))
    assert cfg == {"kind": "agent", "agent": "vision", "prompt": "research {_input}", "source": "ai"}


@pytest.mark.asyncio
async def test_llm_unknown_agent_is_defaulted_to_a_real_one():
    reply = json.dumps({"kind": "agent", "agent": "ghostagent", "prompt": "x"})
    cfg = await generate_step("do thing", AGENTS, llm=_fake_llm(reply))
    assert cfg["agent"] == "jarvis"            # fell back to a valid agent


@pytest.mark.asyncio
async def test_llm_bad_transform_op_is_normalised():
    reply = json.dumps({"kind": "transform", "transform": "nonsense", "prompt": "x"})
    cfg = await generate_step("transform it", AGENTS, llm=_fake_llm(reply))
    assert cfg["kind"] == "transform" and cfg["transform"] == "summarize"


@pytest.mark.asyncio
async def test_llm_junk_falls_back_to_heuristic():
    cfg = await generate_step("redact secrets", AGENTS, llm=_fake_llm("I cannot help with that."))
    assert cfg["kind"] == "guardrail" and cfg["source"] == "heuristic"


@pytest.mark.asyncio
async def test_llm_invalid_kind_falls_back():
    reply = json.dumps({"kind": "wizardry", "prompt": "x"})
    cfg = await generate_step("summarize this", AGENTS, llm=_fake_llm(reply))
    assert cfg["kind"] in KNOWN_KINDS and cfg["source"] == "heuristic"


@pytest.mark.asyncio
async def test_llm_exception_falls_back():
    async def boom(_p):
        raise RuntimeError("llm down")
    cfg = await generate_step("route this", AGENTS, llm=boom)
    assert cfg["kind"] == "router" and cfg["source"] == "heuristic"


# ── endpoint ──────────────────────────────────────────────────────

def test_generate_endpoint_returns_step(monkeypatch):
    monkeypatch.setattr(web, "orch", None)        # no LLM → heuristic
    client = TestClient(web.app)
    resp = client.post("/api/workflows/step/generate", json={"description": "redact secrets"})
    assert resp.status_code == 200
    step = resp.json()["step"]
    assert step["kind"] == "guardrail"
