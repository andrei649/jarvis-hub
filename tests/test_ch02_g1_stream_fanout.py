"""ch02-G1 — /chat/stream fans out and synthesizes (the cockpit's only chat path).

`_handle_input_stream` ran the FIRST routed agent and broke, so multi-agent
synthesis was unreachable from the HUD, and the per-agent route map was only
ever written by the non-stream path (a stream turn could inherit a STALE map
from a previous turn — the locality mislabel half of G1). Wire design: the
primary streams live; secondaries run in parallel afterwards; the merged
synthesis arrives as the final text (the SSE `end` event replaces the bubble,
so the HUD needs no changes).
"""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from tests.golden_harness import FakeBackend, make_golden_orchestrator


class ScriptedBackend(FakeBackend):
    """Distinct deterministic reply per call, so synthesis is distinguishable."""

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        await super().generate(model, prompt, system, max_tokens, temperature)
        return f"reply-{len(self.calls)}"


async def _stream_orch(monkeypatch, tmp_path, targets):
    orch, fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    scripted = ScriptedBackend()
    orch.llm_router._backend = scripted
    monkeypatch.setattr(orch, "_route_candidates", lambda intent: list(targets))
    return orch, scripted


async def test_stream_fans_out_and_synthesizes(monkeypatch, tmp_path):
    orch, fake = await _stream_orch(monkeypatch, tmp_path, ["pepper", "stark"])
    tokens: list[str] = []

    final = await orch.handle_input_stream(
        "compare our launch options", on_token=tokens.append
    )

    # primary + secondary + synthesis all reached the LLM seam
    assert len(fake.calls) >= 3
    synthesis_prompt = fake.calls[-1]["prompt"]
    assert "reply-1" in synthesis_prompt and "reply-2" in synthesis_prompt
    # the merged synthesis is the final text; the live-streamed tokens are the
    # primary's only (the SSE `end` event replaces the bubble with `final`)
    assert final == f"reply-{len(fake.calls)}"
    assert "".join(tokens).startswith("reply-1")
    assert final not in ("reply-1", "reply-2")


async def test_stream_single_agent_path_unchanged(monkeypatch, tmp_path):
    orch, fake = await _stream_orch(monkeypatch, tmp_path, ["pepper"])

    async def _never(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("synthesize must not run for a single-agent stream")

    monkeypatch.setattr(orch, "_synthesize", _never)
    tokens: list[str] = []

    final = await orch.handle_input_stream("just pepper please", on_token=tokens.append)

    assert len(fake.calls) == 1
    assert final == "reply-1" and "".join(tokens) == "reply-1"


async def test_stream_route_map_is_per_turn_never_stale(monkeypatch, tmp_path):
    """The map a turn records must hold only that turn's agents.

    The observation moved INSIDE the turn, and the guarantee got stronger rather than
    weaker. These maps are context-local now (a concurrent turn on the same orchestrator
    was overwriting them, and the cost meter reads them), so a previous turn's entries
    cannot reach this one at all — there is no longer a shared map for the turn's reset
    to clean up, and reading `orch._last_routes` after the turn has ended no longer
    reports what the turn did. The last assertion is the new half: what the earlier turn
    left behind is still exactly where it was, untouched.
    """
    orch, fake = await _stream_orch(monkeypatch, tmp_path, ["pepper"])
    # A previous (non-stream) turn left a stale per-agent route map behind.
    orch._last_routes = {"frigga": "local-deep", "ultron": "local"}
    orch._last_latencies = {"frigga": 12.0}

    seen: dict[str, dict] = {}
    real_record = orch._record_interactions

    def _spy(*args, **kwargs):
        seen["routes"] = dict(orch._last_routes)
        seen["latencies"] = dict(orch._last_latencies)
        return real_record(*args, **kwargs)

    monkeypatch.setattr(orch, "_record_interactions", _spy)

    await orch.handle_input_stream("fresh stream turn", on_token=lambda t: None)

    assert set(seen["routes"]) == {"pepper"}
    assert seen["routes"]["pepper"]  # the primary's real route, recorded
    assert set(seen["latencies"]) == {"pepper"}
    assert set(orch._last_routes) == {"frigga", "ultron"}


async def test_stream_synthesis_holds_the_strict_local_floor(monkeypatch, tmp_path):
    """SEC-B1: a strict-local contributor pins the stream merge to the local
    backend — select_backend is never consulted for the synthesis call."""
    orch, fake = await _stream_orch(monkeypatch, tmp_path, ["pepper", "frigga"])
    select_calls: list[str] = []
    real_select = orch.llm_router.select_backend

    def _spy(agent_id, prompt):
        select_calls.append(agent_id)
        return real_select(agent_id, prompt)

    monkeypatch.setattr(orch.llm_router, "select_backend", _spy)

    final = await orch.handle_input_stream("family question", on_token=lambda t: None)

    assert final  # a merge was produced
    # every select_backend call belongs to a routed agent; none to the merge
    assert set(select_calls) <= {"pepper", "frigga"}
