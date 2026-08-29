"""
Tests for the grown-transcript salvage guard in ContextCompressor.compress —
the essence of hermes-agent's salvage_grown_transcript (Nous Research, MIT,
v2026.8.27): a "compression" whose output is at least as large as its input
must return the original turns untouched.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.context_compressor import ContextCompressor


def _turns(n, chars=200):
    return [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"turn {i}: " + ("x" * chars)} for i in range(n)]


async def test_grown_summary_salvages_original_turns():
    async def rambling_summarizer(_block):
        return "y" * 100_000  # longer than the whole transcript

    compressor = ContextCompressor(summarizer=rambling_summarizer,
                                   max_tokens=100, keep_recent=2)
    turns = _turns(10)
    result = await compressor.compress(turns)
    assert result["compressed"] is False
    assert result["kept"] == turns
    assert result["evicted"] == 0
    assert result["summary"] == ""
    assert result["tokens"] == sum(
        compressor.estimate_tokens(t["content"]) for t in turns)


async def test_normal_compression_still_shrinks():
    async def terse_summarizer(_block):
        return "short summary"

    compressor = ContextCompressor(summarizer=terse_summarizer,
                                   max_tokens=100, keep_recent=2)
    turns = _turns(10)
    result = await compressor.compress(turns)
    assert result["compressed"] is True
    assert result["kept"] == turns[-2:]
    assert result["tokens"] < sum(
        compressor.estimate_tokens(t["content"]) for t in turns)
