"""Stop-generating — an aborted stream must persist NO partial reply.

The HUD Stop button aborts the /chat/stream fetch; the server's disconnect path
(web.py `_chat_event_stream` finally-block) cancels the runner task while it is
blocked inside ``backend.generate_stream``. This proves the safety claim the
client-only Stop design rests on: cancellation mid-generation keeps the USER
turn (persisted before generation, orchestrator.py:852) but never writes an
assistant turn (the persist at :1029 sits after generate_stream returns) — a
half-generated reply can't poison conversation memory or later recall.

Fixture mirrors tests/test_concurrent_session_isolation.py (real Orchestrator,
offline stubs down to a fake backend).
"""

import asyncio
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator


class _Intent:
    def __init__(self):
        self.target_agents = ["jarvis"]
        self.is_general = True
        self.confidence = 1.0
        self.context = {"keywords_found": [], "scores": {}, "source": "keyword_match"}


class _FakeAgent:
    name = "Jarvis"
    soul = {"content": ""}
    config = {"model": "stub"}
    tool_runtime = None
    generate_response = Agent.generate_response


@pytest.fixture
def orch():
    return Orchestrator(JarvisConfig())


async def test_cancel_mid_generation_persists_user_turn_only(orch):
    o = orch
    sid = await o.memory.new_session("sess_stop")
    started = asyncio.Event()
    streamed = []

    class _BlockingBackend:
        async def generate_stream(self, *, model, prompt, system, max_tokens,
                                  temperature, on_token):
            # Some tokens already reached the client — exactly the Stop-button
            # moment — then the generation hangs until it is cancelled.
            on_token("Partial ")
            started.set()
            await asyncio.Event().wait()   # blocks forever; only cancel ends it

    async def _fake_classify(text, agents):
        return _Intent()

    async def _fake_plugin_data(text, intent):
        return {}

    o.router.classify = _fake_classify
    o._gather_plugin_data = _fake_plugin_data
    o.agents["jarvis"] = _FakeAgent()
    o.llm_router.select_backend = lambda agent, prompt: (_BlockingBackend(), "stub", "local")
    o.llm_router.get_model = lambda agent_id: "stub"
    o.checkpoints.load = lambda agent_id, session_id: None
    o.security = None
    o.tracer = None

    task = asyncio.create_task(o.handle_input_stream(
        "stoppable question", channel="web",
        on_token=lambda t: streamed.append(t), session_id=sid,
    ))
    await asyncio.wait_for(started.wait(), 2)   # generation is provably mid-flight
    task.cancel()                                # what the SSE disconnect path does
    with pytest.raises(asyncio.CancelledError):
        await task

    turns = await o.memory.get_history(sid)
    roles = [t["role"] for t in turns]
    texts = [t["content"] for t in turns]
    assert "stoppable question" in texts         # the user turn was kept (:852)
    assert "assistant" not in roles              # the partial was NOT persisted (:1029 unreached)
    assert streamed                              # ...even though tokens had streamed to the client
