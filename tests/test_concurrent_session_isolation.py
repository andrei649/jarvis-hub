"""BUG-5 — concurrent conversations must not cross-contaminate.

Orchestrator is a process-wide singleton (web.py builds one `orch`). Before the
fix it held a single shared `self.session_id` that `handle_input` /
`handle_input_stream` read across many `await` points, so two concurrent turns
(two browser tabs, or web + telegram) interleaved and a reply landed in the
WRONG conversation.

These tests fire two `handle_input` (and `handle_input_stream`) calls on the
SAME orchestrator instance with DIFFERENT sessions, forcing them to interleave
mid-call via an asyncio.Event, then assert each turn was recorded to its OWN
session's history. They FAIL against the shared-`self.session_id` code (the
second task's session write clobbers the first's, so the first task's assistant
turn lands in the wrong session) and PASS once the session is async-context
local.
"""

import asyncio
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator


class _Intent:
    """Minimal IntentRouter.classify() result the orchestrator expects."""

    def __init__(self):
        self.target_agents = ["jarvis"]
        self.is_general = True
        self.confidence = 1.0
        self.context = {"keywords_found": [], "scores": {}, "source": "keyword_match"}


@pytest.fixture
def orch():
    return Orchestrator(JarvisConfig())


def _wire_stubs(o, *, both_started: asyncio.Event, started_count: dict):
    """Replace the LLM-touching helpers with offline stubs that yield control
    mid-call so two concurrent handle_input calls provably interleave.

    The stub returns a reply that echoes the session that was active *when it
    started* — but the assertion checks the recorded session, which is what the
    bug corrupts.
    """

    async def _fake_classify(text, agents):
        return _Intent()

    async def _fake_plugin_data(text, intent):
        return {}

    async def _fake_parallel(agent_ids, text, context, plugin_data=None):
        # Mark that this task has reached the mid-call await with its own
        # session pinned, then block until BOTH tasks are here. This guarantees
        # the two turns interleave around the `await` exactly the way two real
        # concurrent requests would.
        started_count["n"] += 1
        if started_count["n"] >= 2:
            both_started.set()
        await both_started.wait()
        # A tiny extra hop so the event loop can ping-pong between the tasks.
        await asyncio.sleep(0)
        return {"jarvis": f"reply for {text}"}

    o.router.classify = _fake_classify
    o._gather_plugin_data = _fake_plugin_data
    o._call_agents_parallel = _fake_parallel
    # Keep the post-turn bookkeeping offline + cheap.
    o.llm_router.select_backend = lambda agent, text: (None, "", "local")
    o._synthesize = _passthrough_synthesize
    o.entities = None
    o.kg_updater = None
    o.run_history = None
    o.tracer = None


async def _passthrough_synthesize(responses, intent):
    return next(iter(responses.values()))


@pytest.mark.asyncio
async def test_two_concurrent_turns_keep_separate_histories(orch):
    o = orch
    # Two distinct in-memory sessions on the SAME orchestrator (explicit ids so
    # the timestamp-based default can't collide within the same second).
    sid_a = await o.memory.new_session("sess_A")
    sid_b = await o.memory.new_session("sess_B")
    assert sid_a != sid_b

    both_started = asyncio.Event()
    started = {"n": 0}
    _wire_stubs(o, both_started=both_started, started_count=started)

    async def turn(session_id, user_text):
        # Each request carries its own session — the realistic per-request entry
        # point (mirrors what /chat threads through). On the old shared-attribute
        # code this raced on `self.session_id`; with the fix the session is
        # async-context local.
        return await o.handle_input(user_text, channel="web", session_id=session_id)

    reply_a, reply_b = await asyncio.gather(
        turn(sid_a, "question A"),
        turn(sid_b, "question B"),
    )

    # Each reply must answer the question it was asked.
    assert reply_a == "reply for question A"
    assert reply_b == "reply for question B"

    hist_a = await o.memory.get_history(sid_a)
    hist_b = await o.memory.get_history(sid_b)

    texts_a = [t["content"] for t in hist_a]
    texts_b = [t["content"] for t in hist_b]

    # Session A holds ONLY A's user turn + A's assistant reply (no B leakage).
    assert "question A" in texts_a
    assert "reply for question A" in texts_a
    assert "question B" not in texts_a
    assert "reply for question B" not in texts_a

    # Session B holds ONLY B's turns.
    assert "question B" in texts_b
    assert "reply for question B" in texts_b
    assert "question A" not in texts_b
    assert "reply for question A" not in texts_b

    # Exactly one user + one assistant turn per session — nothing duplicated or
    # misfiled by the race.
    assert len(hist_a) == 2
    assert len(hist_b) == 2


@pytest.mark.asyncio
async def test_two_concurrent_stream_turns_keep_separate_histories(orch):
    """Same isolation guarantee for the streaming path used by /chat/stream."""
    o = orch
    sid_a = await o.memory.new_session("sess_SA")
    sid_b = await o.memory.new_session("sess_SB")

    both_started = asyncio.Event()
    started = {"n": 0}

    async def _fake_classify(text, agents):
        return _Intent()

    async def _fake_plugin_data(text, intent):
        return {}

    class _FakeBackend:
        async def generate_stream(self, *, model, prompt, system, max_tokens,
                                  temperature, on_token):
            started["n"] += 1
            if started["n"] >= 2:
                both_started.set()
            await both_started.wait()
            await asyncio.sleep(0)
            # The user text is embedded in the prompt; echo a session-stable reply.
            marker = "question A" if "question A" in prompt else "question B"
            return f"stream reply for {marker}"

    class _FakeAgent:
        name = "Jarvis"
        soul = {"content": ""}
        config = {"model": "stub"}

    o.router.classify = _fake_classify
    o._gather_plugin_data = _fake_plugin_data
    o.agents["jarvis"] = _FakeAgent()
    o.llm_router.select_backend = lambda agent, prompt: (_FakeBackend(), "stub", "local")
    o.llm_router.get_model = lambda agent_id: "stub"
    o.checkpoints.load = lambda agent_id, session_id: None
    o.security = None
    o.tracer = None

    async def turn(session_id, user_text):
        return await o.handle_input_stream(
            user_text, channel="web", on_token=lambda t: None, session_id=session_id
        )

    reply_a, reply_b = await asyncio.gather(
        turn(sid_a, "question A"),
        turn(sid_b, "question B"),
    )

    assert reply_a == "stream reply for question A"
    assert reply_b == "stream reply for question B"

    texts_a = [t["content"] for t in await o.memory.get_history(sid_a)]
    texts_b = [t["content"] for t in await o.memory.get_history(sid_b)]

    assert "question A" in texts_a and "stream reply for question A" in texts_a
    assert "question B" not in texts_a and "stream reply for question B" not in texts_a
    assert "question B" in texts_b and "stream reply for question B" in texts_b
    assert "question A" not in texts_b and "stream reply for question A" not in texts_b
