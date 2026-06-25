"""Tests for Orchestrator.process() (FIX 1) and the _record_interactions
success/error heuristic (FIX 2).

These are unit tests: they construct a bare Orchestrator and stub the LLM /
learning collaborators so no real backend, network or model is needed.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator


class _StubAgent:
    """Minimal stand-in for an Agent (only the bits the orchestrator touches)."""

    def __init__(self, agent_id="jarvis"):
        self.id = agent_id
        self.config = {"model": "stub-model"}
        self._failures = 0

    @property
    def should_demote(self):
        return False

    def get_demotion_target(self):
        return None


@pytest.fixture
def orch():
    return Orchestrator(JarvisConfig())


# ── FIX 1: Orchestrator.process ───────────────────────────────────────────────


def test_process_method_exists(orch):
    assert hasattr(orch, "process")


@pytest.mark.asyncio
async def test_process_returns_stubbed_completion(orch):
    orch.agents["jarvis"] = _StubAgent("jarvis")

    async def _fake_parallel(ids, prompt, context, plugin_data):
        return {ids[0]: "Hello from the stub LLM."}

    orch._call_agents_parallel = _fake_parallel
    out = await orch.process("hi", agent="jarvis", channel="reflection")
    assert isinstance(out, str)
    assert out == "Hello from the stub LLM."


@pytest.mark.asyncio
async def test_process_default_agent_is_jarvis(orch):
    # The autonomy _llm executor calls process(prompt, channel="autonomy") with
    # no agent kwarg → must default to jarvis.
    orch.agents["jarvis"] = _StubAgent("jarvis")
    seen = {}

    async def _fake_parallel(ids, prompt, context, plugin_data):
        seen["ids"] = ids
        return {ids[0]: "ok"}

    orch._call_agents_parallel = _fake_parallel
    out = await orch.process("summarize this", channel="autonomy")
    assert seen["ids"] == ["jarvis"]
    assert out == "ok"


@pytest.mark.asyncio
async def test_process_empty_prompt_returns_empty(orch):
    orch.agents["jarvis"] = _StubAgent("jarvis")
    assert await orch.process("", agent="jarvis") == ""


@pytest.mark.asyncio
async def test_process_no_agent_returns_empty(orch):
    # No agents loaded → fail safe, never raise.
    assert await orch.process("hi", agent="jarvis") == ""


@pytest.mark.asyncio
async def test_process_swallows_no_backend(orch):
    orch.agents["jarvis"] = _StubAgent("jarvis")

    async def _raise(ids, prompt, context, plugin_data):
        raise RuntimeError("No LLM backend available")

    orch._call_agents_parallel = _raise
    out = await orch.process("hi", agent="jarvis")
    assert out == ""


@pytest.mark.asyncio
async def test_process_returns_empty_on_error_marker(orch):
    # _call_agents_parallel returns structured error markers instead of raising.
    orch.agents["jarvis"] = _StubAgent("jarvis")

    async def _fake_parallel(ids, prompt, context, plugin_data):
        return {ids[0]: "[jarvis error: boom]"}

    orch._call_agents_parallel = _fake_parallel
    assert await orch.process("hi", agent="jarvis") == ""


@pytest.mark.asyncio
async def test_process_keeps_answer_mentioning_error(orch):
    # A normal answer that merely contains "error:" must pass through unchanged
    # (only the leading structured marker counts).
    orch.agents["jarvis"] = _StubAgent("jarvis")
    answer = "The log line was: error: disk full — here is the fix."

    async def _fake_parallel(ids, prompt, context, plugin_data):
        return {ids[0]: answer}

    orch._call_agents_parallel = _fake_parallel
    assert await orch.process("hi", agent="jarvis") == answer


# ── FIX 2: _record_interactions success/error heuristic ───────────────────────


def _record_and_capture(orch, agent_id, resp):
    """Run _record_interactions for a single response and return the `success`
    value that was passed to learning.record."""
    orch.agents[agent_id] = _StubAgent(agent_id)
    captured = {}

    def _fake_record(**kwargs):
        captured["success"] = kwargs.get("success")

    orch.learning.record = _fake_record
    # Disable the optional collaborators so the path stays minimal/offline.
    orch.entities = None
    orch.kg_updater = None
    orch.run_history = None
    orch._record_interactions("a user question", {agent_id: resp}, resp, "local")
    return captured.get("success")


def test_record_real_error_marked_failure(orch):
    # The exact marker _call_agents_parallel emits: f"[{agent_id} error: {e}]".
    assert _record_and_capture(orch, "friday", "[friday error: timed out]") is False


def test_record_real_timeout_marked_failure(orch):
    assert _record_and_capture(orch, "friday", "[friday timeout]") is False


def test_record_normal_answer_mentioning_error_is_success(orch):
    # The old heuristic ("error:" in resp) false-positived this normal answer.
    resp = "Here is how to fix the build error: run make clean first."
    assert _record_and_capture(orch, "steve", resp) is True


def test_record_marker_for_other_agent_is_success(orch):
    # An error marker naming a *different* agent must not flag this agent.
    resp = "Per gecko's note: [gecko error: api down], but markets are open."
    assert _record_and_capture(orch, "friday", resp) is True


def test_record_plain_answer_is_success(orch):
    assert _record_and_capture(orch, "jarvis", "All good, sir.") is True


# ── CDX-2: the real channel is recorded, not a hard-coded "web" ───────────────


def _record_and_capture_meta(orch, channel=None):
    """Run _record_interactions and return the metadata dict passed to
    learning.record. Passes `channel` only when given, so the default is tested."""
    orch.agents["friday"] = _StubAgent("friday")
    captured = {}
    orch.learning.record = lambda **kw: captured.update(kw)
    orch.entities = None
    orch.kg_updater = None
    orch.run_history = None
    args = ("a user question", {"friday": "an answer"}, "an answer", "local")
    if channel is None:
        orch._record_interactions(*args)
    else:
        orch._record_interactions(*args, channel=channel)
    return captured.get("metadata", {})


def test_record_threads_real_channel(orch):
    # A telegram-origin turn must be recorded as telegram (was always "web").
    assert _record_and_capture_meta(orch, channel="telegram")["channel"] == "telegram"


def test_record_channel_defaults_to_web(orch):
    # Back-compat: callers that don't pass a channel still get the prior default.
    assert _record_and_capture_meta(orch)["channel"] == "web"
