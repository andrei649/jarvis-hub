"""H20.3 — Runtime context compression. All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.context_compressor import ContextCompressor


def _turns(n, size=400):
    return [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"turn {i} " + "x" * size} for i in range(n)]


@pytest.mark.asyncio
async def test_no_compression_under_budget():
    cc = ContextCompressor(max_tokens=100000)
    out = await cc.compress(_turns(3))
    assert out["compressed"] is False and out["evicted"] == 0


@pytest.mark.asyncio
async def test_compresses_when_over_budget():
    cc = ContextCompressor(max_tokens=200, keep_recent=2)
    out = await cc.compress(_turns(10))
    assert out["compressed"] is True
    assert len(out["kept"]) == 2 and out["evicted"] == 8
    assert out["summary"]                       # a digest was produced
    assert out["tokens"] < sum(cc._turn_tokens(t) for t in _turns(10))


@pytest.mark.asyncio
async def test_uses_injected_summarizer():
    async def summ(text):
        return "LLM SUMMARY"

    cc = ContextCompressor(summarizer=summ, max_tokens=100, keep_recent=1)
    out = await cc.compress(_turns(6))
    assert out["summary"] == "LLM SUMMARY"


@pytest.mark.asyncio
async def test_summarizer_failure_falls_back_to_digest():
    async def boom(text):
        raise RuntimeError("llm down")

    cc = ContextCompressor(summarizer=boom, max_tokens=100, keep_recent=1)
    out = await cc.compress(_turns(6))
    assert out["compressed"] is True and "[summary of earlier conversation]" in out["summary"]


def test_token_estimate():
    assert ContextCompressor.estimate_tokens("abcd" * 10) == 10
