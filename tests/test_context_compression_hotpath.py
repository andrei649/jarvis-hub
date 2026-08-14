"""H20.3 wiring — ContextCompressor on the prompt hot path (default-off).

Covers Orchestrator._history_for_prompt: with ``memory.context_compression``
off (the default) it is byte-identical to ``memory.get_context``; on and under
budget it yields the same string via ``get_history``; over budget the older
turns collapse into the deterministic ``[summary of earlier conversation]``
digest while the recent turns stay verbatim. The compressor's ``summarizer``
must stay ``None`` on this path (zero LLM/egress — safe for LOCAL_ONLY agents).
Pure/offline: fake memory, no orchestrator init.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import context_compressor as cc_mod  # noqa: E402
from agents.core.orchestrator import Orchestrator  # noqa: E402


class _FakeMemory:
    def __init__(self, turns):
        self.turns = turns
        self.get_context_calls = 0
        self.get_history_calls = 0

    def _slice(self, last_n):
        return self.turns[-last_n:] if last_n else list(self.turns)

    async def get_context(self, session_id, last_n=10):
        self.get_context_calls += 1
        return "\n".join(
            f"[{t.get('agent_id') or t.get('role', '')}]: {t.get('content', '')}"
            for t in self._slice(last_n)
        )

    async def get_history(self, session_id, last_n=None):
        self.get_history_calls += 1
        return [dict(t) for t in self._slice(last_n)]


def _turn(role, content, agent_id=None):
    return {"role": role, "content": content, "agent_id": agent_id}


def _orch(turns, settings):
    o = Orchestrator.__new__(Orchestrator)
    o.memory = _FakeMemory(turns)
    o.session_id = "s"
    o.get_setting = lambda key, default=None: settings.get(key, default)
    return o


async def test_off_by_default_is_get_context_and_never_reads_history():
    turns = [_turn("user", "Hello?"), _turn("assistant", "Hi.", agent_id="jarvis")]
    o = _orch(turns, {})   # flag unset → default False
    out = await o._history_for_prompt(6)
    assert out == "[user]: Hello?\n[jarvis]: Hi."
    assert o.memory.get_context_calls == 1
    assert o.memory.get_history_calls == 0


async def test_on_under_budget_matches_get_context_shape():
    turns = [_turn("user", "One?"), _turn("assistant", "Two."), _turn("user", "Three.")]
    o = _orch(turns, {"memory.context_compression": True})
    out = await o._history_for_prompt(6)
    # compress is a no-op under budget → same string get_context would produce
    assert out == await o.memory.get_context("s", 6)


async def test_on_over_budget_digests_older_keeps_recent_verbatim():
    # 10 turns × ~1200 chars ≈ 3000 estimated tokens > the 2000 default budget.
    old = [_turn("user", f"Old topic {i}. " + "x" * 1200) for i in range(6)]
    recent = [_turn("user", f"Recent question {i}? " + "y" * 1200) for i in range(4)]
    o = _orch(old + recent, {"memory.context_compression": True})
    out = await o._history_for_prompt(10)
    assert out.startswith("[summary of earlier conversation]")
    for i in range(4):
        assert f"Recent question {i}?" in out          # kept verbatim
    assert "x" * 1200 not in out                       # older bodies evicted
    assert len(out) < sum(len(t["content"]) for t in old + recent)


async def test_on_summarizer_stays_none(monkeypatch):
    captured = {}
    real = cc_mod.ContextCompressor

    class Spy(real):
        def __init__(self, *a, **kw):
            captured.update(kw)
            super().__init__(*a, **kw)

    monkeypatch.setattr(cc_mod, "ContextCompressor", Spy)
    o = _orch([_turn("user", "hi")], {"memory.context_compression": True})
    await o._history_for_prompt(6)
    # The local-only rail: the hot path must never inject an LLM summarizer.
    assert "summarizer" in captured and captured["summarizer"] is None


async def test_on_empty_history_is_empty_string():
    o = _orch([], {"memory.context_compression": True})
    assert await o._history_for_prompt(6) == ""
