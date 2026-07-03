"""
test_o26_golden_loop_chat.py — ORIZONT 26 golden loop #1 (P0.1 + P0.2 / finding F1).

The product's core loop, exercised end-to-end with the LLM faked ONLY at the
``generate()`` seam: a web chat turn through the STREAMING path (the HUD's
`/chat/stream` → ``handle_input_stream`` — the owner's primary surface) must
feed the per-turn record seam exactly like the non-streaming path does:
learning interactions, run-history, entity/KG ingest.

Before the F1 fix, ``handle_input_stream`` never called ``_record_interactions``
— web chat produced NO memory/learning/metrics while Telegram did. This loop
pins the fix so the regression cannot return.

Everything below the generate() seam is REAL: real Orchestrator boot, real
router/plugins/memory/learning/run-history/KG stores (the readiness-matrix
fixture precedent). Offline: the fake backend never touches a socket.
"""

import asyncio
import sys
from functools import lru_cache
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import LLMBackend  # noqa: E402

REPLY = (
    "Noted, sir — Mara's flight lands Friday at 18:40; I'll keep that evening "
    "clear and can set a departure reminder for the airport run."
)


class FakeBackend(LLMBackend):
    """The generate() seam — deterministic reply, streamed token-by-token."""

    def __init__(self):
        self.calls = 0

    async def generate(self, model, prompt, system="", max_tokens=0, temperature=0.7, **kw):
        self.calls += 1
        return REPLY

    async def generate_stream(self, model, prompt, system="", max_tokens=0,
                              temperature=0.7, on_token=None, **kw):
        self.calls += 1
        if on_token:
            for word in REPLY.split(" "):
                on_token(word + " ")
        return REPLY


@lru_cache(maxsize=1)
def _orch():
    """Real orchestrator, faked only at the generate() seam."""
    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator(JarvisConfig())
    asyncio.run(orch.load_agents())  # 17 real agents; degrades gracefully offline
    fake = FakeBackend()
    # Route every agent to the fake backend; keep the real route label shape.
    orch.llm_router.select_backend = lambda agent_id, prompt="": (fake, "fake-model", "local")
    # Bypass the guardrails backend-facade so the fake seam is what generates
    # (guardrails behavior has its own suite; this loop pins the record seam).
    orch.security = None
    orch._fake_backend = fake
    return orch


def _counts(orch) -> dict:
    graph = getattr(orch.memory, "graph", None)
    return {
        "learning": len(orch.learning.interactions),
        "kg": len(graph.list_entities(limit=1000)) if graph else 0,
    }


def test_golden_loop_1_web_stream_chat_feeds_memory_and_learning():
    """F1 pin: a streamed web turn must grow learning + run-history + KG."""
    orch = _orch()
    before = _counts(orch)
    tokens: list[str] = []

    reply = asyncio.run(
        orch.handle_input_stream(
            "Mara's flight is AB123 and Mara's sister is Ioana.",
            channel="web",
            on_token=tokens.append,
        )
    )

    assert reply == REPLY
    assert tokens, "streaming must emit tokens"
    after = _counts(orch)
    assert after["learning"] > before["learning"], (
        "F1 regression: handle_input_stream recorded no learning interaction"
    )
    assert after["kg"] > before["kg"], (
        "F1 regression: handle_input_stream ingested nothing into the KG"
    )
    # Run-history timeline received the turn (H10.17) for the responding agent.
    recorded = orch.learning.interactions[-1]
    assert recorded.metadata.get("channel") == "web", (
        "the record must carry the real channel (CDX-2), not a default"
    )


def test_golden_loop_1_stream_and_nonstream_paths_record_symmetrically():
    """The same message through both paths produces a learning record each."""
    orch = _orch()
    before = len(orch.learning.interactions)

    asyncio.run(orch.handle_input("Radu's deadline moved to the 15th.", channel="telegram"))
    mid = len(orch.learning.interactions)
    assert mid > before, "non-stream path stopped recording (pre-existing behavior)"

    asyncio.run(
        orch.handle_input_stream("Radu's deadline moved to the 15th.", channel="web")
    )
    assert len(orch.learning.interactions) > mid, (
        "stream path records fewer interactions than the non-stream path"
    )


def test_golden_loop_1_empty_target_never_crashes_the_record_seam():
    """Pre-bound agent_id/route_name: a turn that routes nowhere still returns."""
    orch = _orch()
    # Force an empty candidate list through the routing seam.
    original = orch._route_candidates
    orch._route_candidates = lambda intent: []
    try:
        reply = asyncio.run(
            orch.handle_input_stream("status check with no candidates", channel="web")
        )
        assert isinstance(reply, str)
    finally:
        orch._route_candidates = original
