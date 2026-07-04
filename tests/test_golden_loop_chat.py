"""Golden loop #1 — chat → memory (ORIZONT 26 · O26-P0.1).

One faked turn runs through the REAL pipeline: `handle_input` with the LLM
faked at the `generate()` seam only (see tests/golden_harness.py). Nothing
above that seam is stubbed — intent routing, agent dispatch, guardrails,
conversation memory, learning/bench/run-history records and entity/KG ingest
are all the production objects. This is the behavioral loop the deep dive
found missing: no prior test asserted that memory actually grows after a chat.

Loop #1 asserts a web-chat turn:
  1. answers with the (faked) LLM's reply, routed to the local slot,
  2. persists user + assistant turns to the session history,
  3. grows learning + bench + run-history via `_record_interactions`,
  4. ingests entities and KG triples from the user's turn,
  5. threads turn 1's history into turn 2's prompt at the LLM seam.

The stream path (`handle_input_stream`, the /chat/stream surface the HUD
uses) used to skip `_record_interactions` entirely — finding F1, fixed by
O26-P0.2 (#494). Its loop is asserted green here so the regression cannot
return: a stream turn must feed learning/run-history/entity ingest exactly
like the non-stream path.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))
sys.path.insert(0, str(repo_root / "tests"))  # golden_harness lives beside the tests

from golden_harness import (  # noqa: E402
    DEFAULT_REPLY,
    FAKE_MODEL,
    make_golden_orchestrator,
)

# Chosen to classify as general chat (→ jarvis, single agent, no synthesis)
# and to carry a deterministic KG triple: (Andrei Popescu, lives_in, Bucharest).
# Avoid howard-routed phrasings ("tell", "write", …): howard's RAG path embeds
# via Ollama and would burn seconds in offline retries.
TURN_1 = "Andrei Popescu lives in Bucharest and works at Innoveo."
TURN_2 = "Can you repeat that back to me?"


@pytest.fixture
async def golden(monkeypatch, tmp_path):
    return await make_golden_orchestrator(monkeypatch, tmp_path)


async def test_faked_web_turn_runs_the_whole_loop(golden):
    """Loop #1, non-stream: chat → reply + memory + learning + KG, one turn."""
    orch, fake = golden
    sid = await orch.memory.new_session("golden_loop1")

    learn0 = len(orch.learning.interactions)
    # Count raw bench samples, not get_results(): the aggregate view drops
    # zero-latency samples, and Windows' coarse monotonic tick measures a
    # faked instant generate as exactly 0.0.
    bench0 = sum(1 for s in orch.bench.samples if s.agent_id == "jarvis")
    # Run-history shares the suite-wide store (its module binds DEFAULT_PATH at
    # import — see the harness docstring) and list() caps at 50, so a length
    # delta stops growing once the shared ring passes the cap. Mark the newest
    # pre-turn entry and assert a NEWER one appears instead.
    _pre = orch.run_history.list("jarvis", limit=1)
    run_ts0 = _pre[0]["ts"] if _pre else 0.0

    reply = await orch.handle_input(TURN_1, channel="web", session_id=sid)

    # 1 — the reply is the fake backend's, reached through real routing (local slot).
    assert reply == DEFAULT_REPLY
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == FAKE_MODEL

    # 2 — both turns landed in THIS session's conversation history.
    history = await orch.memory.get_history(sid)
    roles = [(h.get("role"), h.get("content")) for h in history]
    assert (("user", TURN_1) in roles), roles
    assert any(r == "assistant" and DEFAULT_REPLY in (c or "") for r, c in roles), roles

    # 3 — the turn was recorded: learning, bench and run-history all grew.
    assert len(orch.learning.interactions) == learn0 + 1
    rec = orch.learning.interactions[-1]
    assert rec.agent_id == "jarvis"
    assert rec.metadata.get("channel") == "web"
    assert sum(1 for s in orch.bench.samples if s.agent_id == "jarvis") == bench0 + 1
    newest = orch.run_history.list("jarvis", limit=1)[0]
    assert newest["ts"] > run_ts0 and TURN_1[:40] in newest.get("input_preview", "")

    # 4 — the user's turn fed the knowledge layer: entity store + KG triple.
    assert orch.entities.get("Andrei Popescu") is not None
    assert orch.memory.graph.get_entity("Andrei Popescu") is not None
    rels = orch.memory.graph.get_relations("Andrei Popescu")
    assert any(r.get("relation") == "lives_in" and r.get("target") == "Bucharest"
               for r in rels), rels

    # 5 — turn 2's prompt (at the LLM seam) carries turn 1's history.
    reply2 = await orch.handle_input(TURN_2, channel="web", session_id=sid)
    assert reply2 == DEFAULT_REPLY
    assert TURN_1 in fake.calls[-1]["prompt"]


async def test_stream_turn_delivers_tokens_and_memory(golden):
    """The stream path's working half: tokens flow, the reply is remembered."""
    orch, fake = golden
    sid = await orch.memory.new_session("golden_loop1_stream")

    tokens: list[str] = []
    reply = await orch.handle_input_stream(
        TURN_1, channel="web", on_token=tokens.append, session_id=sid)

    assert reply == DEFAULT_REPLY
    assert "".join(tokens) == DEFAULT_REPLY
    assert fake.calls and fake.calls[0]["model"] == FAKE_MODEL

    history = await orch.memory.get_history(sid)
    roles = [(h.get("role"), h.get("content")) for h in history]
    assert (("user", TURN_1) in roles), roles
    assert any(r == "assistant" and DEFAULT_REPLY in (c or "") for r, c in roles), roles


async def test_stream_turn_feeds_learning_and_knowledge(golden):
    """Loop #1 via the stream path — the F1 regression guard (O26-P0.2, #494)."""
    orch, _fake = golden
    sid = await orch.memory.new_session("golden_loop1_stream_f1")

    learn0 = len(orch.learning.interactions)
    _pre = orch.run_history.list("jarvis", limit=1)
    run_ts0 = _pre[0]["ts"] if _pre else 0.0

    await orch.handle_input_stream(TURN_1, channel="web",
                                   on_token=lambda _t: None, session_id=sid)

    assert len(orch.learning.interactions) > learn0
    newest = orch.run_history.list("jarvis", limit=1)[0]
    assert newest["ts"] > run_ts0 and TURN_1[:40] in newest.get("input_preview", "")
    assert orch.entities.get("Andrei Popescu") is not None
