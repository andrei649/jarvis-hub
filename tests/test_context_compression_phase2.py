"""Hermes migration Phase 2 — context compression maturity (B1, handoff 2026-07-07).

Extends H20.3 with hermes-agent's remaining compression mechanics, all opt-in:

* ``keep_first``  — protect the first N turns verbatim (session anchoring: the
  user's original ask survives every eviction), alongside the existing
  ``keep_recent`` tail protection.
* structured summary template — the injected LLM summarizer receives hermes's
  Historical context / Pending asks / Remaining work prompt instead of a raw
  transcript blob.
* iterative summary-merge — a ``prior`` summary from an earlier compression is
  folded in so the summarizer only reads turns it hasn't seen yet.
* strict-local summarizer wiring — ``memory.compression_summarizer`` (default
  OFF) builds the summarizer from ``LLMRouter.local_backend`` ONLY (the H20
  fail-closed seam); no local backend ⇒ deterministic digest, never cloud.

Default path stays byte-identical: with the new settings unset the compressor
behaves exactly as H20.3 shipped it (pinned by test_context_compression_hotpath).
Pure/offline: fake memory + fake router, no orchestrator init.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.context_compressor import ContextCompressor  # noqa: E402
from core.orchestrator import Orchestrator  # noqa: E402


def _turn(role, content, agent_id=None):
    return {"role": role, "content": content, "agent_id": agent_id}


def _long_turns(n, tag, size=1200):
    return [_turn("user", f"{tag} {i}. " + "x" * size) for i in range(n)]


# ── ContextCompressor: keep_first ────────────────────────────────────────────

async def test_keep_first_protects_leading_turns_verbatim():
    first = [_turn("user", "ORIGINAL GOAL: build a rocket. " + "z" * 1200)]
    middle = _long_turns(6, "Middle noise")
    recent = _long_turns(3, "Recent question", size=1200)
    cc = ContextCompressor(max_tokens=200, keep_recent=3, keep_first=1)
    result = await cc.compress(first + middle + recent)
    assert result["compressed"] is True
    assert result["kept_first"] == first          # leading turn survives verbatim
    assert result["kept"] == recent               # tail protection unchanged
    assert result["evicted"] == 6                 # only the middle was evicted
    assert "ORIGINAL GOAL" not in result["summary"]


async def test_keep_first_default_zero_is_h20_3_shape():
    turns = _long_turns(8, "Old")
    cc = ContextCompressor(max_tokens=200, keep_recent=2)
    result = await cc.compress(turns)
    assert result["kept_first"] == []             # new key, empty by default
    assert result["compressed"] is True
    assert result["evicted"] == 6


async def test_under_budget_uncompressed_still_carries_kept_first():
    turns = [_turn("user", "hi"), _turn("assistant", "hello")]
    cc = ContextCompressor(max_tokens=100000, keep_first=1)
    result = await cc.compress(turns)
    assert result["compressed"] is False
    assert result["kept_first"] == []
    assert result["kept"] == turns


# ── ContextCompressor: structured template + prior merge ─────────────────────

async def test_structured_summarizer_receives_template_sections():
    prompts = []

    async def summ(prompt):
        prompts.append(prompt)
        return "Historical context: rockets.\nPending asks: none.\nRemaining work: launch."

    cc = ContextCompressor(summarizer=summ, max_tokens=100, keep_recent=1,
                           structured=True)
    result = await cc.compress(_long_turns(5, "Topic"))
    assert result["compressed"] is True
    assert len(prompts) == 1
    for section in ("Historical context", "Pending asks", "Remaining work"):
        assert section in prompts[0]
    assert "Topic 0" in prompts[0]                # transcript folded into prompt
    assert result["summary"].startswith("Historical context")


async def test_prior_summary_merges_and_only_new_turns_are_summarized():
    prompts = []

    async def summ(prompt):
        prompts.append(prompt)
        return "MERGED SUMMARY"

    turns = _long_turns(8, "Turn")
    cc = ContextCompressor(summarizer=summ, max_tokens=100, keep_recent=2,
                           structured=True)
    prior = {"summary": "EARLIER SUMMARY", "covered": 4}
    result = await cc.compress(turns, prior=prior)
    assert result["summary"] == "MERGED SUMMARY"
    assert result["covered"] == 6                 # all older turns now folded
    assert "EARLIER SUMMARY" in prompts[0]        # prior handed to the merge
    assert "Turn 4" in prompts[0] and "Turn 5" in prompts[0]  # the NEW older turns
    assert "Turn 0" not in prompts[0]             # already-covered turns not re-read


async def test_stale_prior_is_ignored_when_history_shrank():
    async def summ(prompt):
        return "S"

    turns = _long_turns(4, "T")
    cc = ContextCompressor(summarizer=summ, max_tokens=100, keep_recent=2)
    # covered=10 > the 2 older turns that exist → prior must be discarded
    result = await cc.compress(turns, prior={"summary": "OLD", "covered": 10})
    assert result["compressed"] is True
    assert result["covered"] == 2


async def test_summarizer_failure_falls_back_to_full_deterministic_digest():
    async def boom(prompt):
        raise RuntimeError("no local backend")

    turns = _long_turns(6, "Fact")
    cc = ContextCompressor(summarizer=boom, max_tokens=100, keep_recent=2,
                           structured=True)
    result = await cc.compress(turns, prior={"summary": "OLD", "covered": 2})
    # fallback digests ALL older turns (prior may be unusable) — nothing lost
    assert result["summary"].startswith("[summary of earlier conversation]")
    assert result["covered"] == 4


# ── Orchestrator wiring: strict-local summarizer (default OFF) ───────────────

class _FakeMemory:
    def __init__(self, turns):
        self.turns = turns

    async def get_context(self, session_id, last_n=10):
        return "\n".join(
            f"[{t.get('agent_id') or t.get('role', '')}]: {t.get('content', '')}"
            for t in self.turns[-last_n:])

    async def get_history(self, session_id, last_n=None):
        return [dict(t) for t in (self.turns[-last_n:] if last_n else self.turns)]


class _LocalBackend:
    def __init__(self):
        self.calls = []

    async def generate(self, **kw):
        self.calls.append(kw)
        return "Historical context: local summary."


class _FakeRouter:
    """local_backend present; touching .backend (the cloud-preferring accessor)
    is the strict-local violation this suite exists to catch."""

    def __init__(self, local=None):
        self._local = local
        self.active_model = "test-local-model"

    @property
    def local_backend(self):
        if self._local is None:
            raise RuntimeError("No local LLM backend available (strict-local path).")
        return self._local

    @property
    def backend(self):  # pragma: no cover - the assertion IS the coverage
        raise AssertionError("compression summarizer must never touch router.backend")


def _orch(turns, settings, router=None):
    o = Orchestrator.__new__(Orchestrator)
    o.memory = _FakeMemory(turns)
    o.session_id = "s"
    o.llm_router = router
    o.get_setting = lambda key, default=None: settings.get(key, default)
    return o


def _over_budget_turns():
    return _long_turns(6, "Old topic") + _long_turns(4, "Recent question")


async def test_summarizer_flag_off_stays_deterministic():
    backend = _LocalBackend()
    o = _orch(_over_budget_turns(), {"memory.context_compression": True},
              router=_FakeRouter(local=backend))
    out = await o._history_for_prompt(10)
    assert "[summary of earlier conversation]" in out
    assert backend.calls == []                    # flag off → zero LLM calls


async def test_summarizer_flag_on_uses_local_backend_only():
    backend = _LocalBackend()
    o = _orch(_over_budget_turns(),
              {"memory.context_compression": True,
               "memory.compression_summarizer": True},
              router=_FakeRouter(local=backend))
    out = await o._history_for_prompt(10)
    assert len(backend.calls) == 1
    assert backend.calls[0]["model"] == "test-local-model"
    assert "Historical context: local summary." in out
    for i in range(4):
        assert f"Recent question {i}" in out      # tail still verbatim


async def test_summarizer_no_local_backend_degrades_to_digest():
    o = _orch(_over_budget_turns(),
              {"memory.context_compression": True,
               "memory.compression_summarizer": True},
              router=_FakeRouter(local=None))     # local_backend raises
    out = await o._history_for_prompt(10)
    assert "[summary of earlier conversation]" in out   # degraded, never raised


async def test_keep_first_setting_renders_leading_turns_before_summary():
    first = [_turn("user", "ORIGINAL GOAL: build a rocket. " + "z" * 1200)]
    o = _orch(first + _over_budget_turns(),
              {"memory.context_compression": True,
               "memory.compression_keep_first": 1})
    out = await o._history_for_prompt(11)
    assert out.index("ORIGINAL GOAL") < out.index("[summary of earlier conversation]")


async def test_iterative_cache_second_turn_reuses_prior_summary():
    backend = _LocalBackend()
    o = _orch(_over_budget_turns(),
              {"memory.context_compression": True,
               "memory.compression_summarizer": True},
              router=_FakeRouter(local=backend))
    await o._history_for_prompt(10)
    # a new turn arrives; only it should be folded into the next summarizer call
    o.memory.turns = o.memory.turns + [_turn("user", "Newest question? " + "q" * 1200)]
    await o._history_for_prompt(11)
    assert len(backend.calls) == 2
    second_prompt = backend.calls[1]["prompt"]
    assert "Historical context: local summary." in second_prompt   # prior merged
    assert "Old topic 0" not in second_prompt                      # not re-read
