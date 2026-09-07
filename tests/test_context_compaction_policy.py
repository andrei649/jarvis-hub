"""Compaction policy — what a 24/7 run gives up, and in what order.

The compressor had a budget but no policy, so a long run on a local 32–128k
window died after about twenty screenshots. A policy is what decides *when* to
act and *what to give up first*, and every test here is one way of losing
something that mattered:

  · below the soft threshold the transcript comes back BYTE-IDENTICAL — a
    compressor that rewrites what it did not need to touch is one nobody can
    debug, and "usually a no-op" is a different promise;
  · images go before any text, because a screenshot is worth thousands of tokens
    and almost nothing after the turn it was taken in;
  · the head is never summarised — it is the original ask, and losing it is how
    a run drifts into doing something adjacent to what was requested;
  · the tail is never summarised — it is what is happening now;
  · an unknown model gets the SMALLEST plausible window, because guessing high
    means the provider truncates instead of us, and a provider truncates the tail;
  · every compaction emits a lineage row, because a summary with no provenance is
    a claim about a conversation nobody can check;
  · a failing summariser degrades to a digest and a failing sink never fails the
    compaction: losing the record is bad, losing the conversation is worse.

Hermetic: no model, no network, an injected summariser and sink.
"""

from __future__ import annotations

import hashlib

import pytest

from agents.core.context_compressor import (
    DEFAULT_WINDOW,
    IMAGE_TOKEN_COST,
    MODEL_WINDOWS,
    CompactionPolicy,
    ContextCompressor,
    lineage_row,
    window_for,
)

pytestmark = pytest.mark.asyncio


def _turn(role="user", content="hello", image=False):
    row = {"role": role, "content": content}
    if image:
        row["image_base64"] = "iVBORw0KGgo="
    return row


def _long(n: int, *, chars: int = 400, images: int = 0):
    """A transcript of ``n`` turns, the first ``images`` of them carrying one."""
    return [
        _turn(content="x" * chars, image=(i < images))
        for i in range(n)
    ]


# ── below soft: nothing at all ───────────────────────────────────────────────

async def test_below_the_soft_threshold_the_turns_come_back_byte_identical():
    """Not "a cheap pass that usually no-ops" — identical, because a compressor
    that rewrote a transcript it did not need to touch is undebuggable."""
    turns = _long(4, chars=100)
    original = [dict(t) for t in turns]
    result = await ContextCompressor().compact(turns, model="llama3.1")
    assert result["compressed"] is False
    assert result["tier"] == "none"
    assert result["kept"] == original
    assert result["lineage"] is None


async def test_an_empty_transcript_is_not_a_compaction():
    result = await ContextCompressor().compact([], model="llama3")
    assert result["tier"] == "none"
    assert result["kept"] == []


# ── tier one: images first ───────────────────────────────────────────────────

async def test_images_are_dropped_before_any_text_is_touched():
    """A screenshot is worth thousands of tokens and almost nothing after the
    turn it was taken in; the text that described what was seen survives it."""
    turns = _long(20, chars=80, images=10)
    result = await ContextCompressor().compact(
        turns, model="llama3", policy=CompactionPolicy(protect_last_n=2)
    )
    assert result["tier"] == "images"
    assert result["images_dropped"] > 0
    assert result["summary"] == ""            # no text was summarised
    assert len(result["kept"]) == len(turns)  # and no turn was evicted


async def test_a_dropped_image_leaves_a_visible_hole():
    """A turn with no image and no note cannot be told apart from one that never
    had an image, and those are different conversations."""
    turns = _long(20, chars=80, images=10)
    result = await ContextCompressor().compact(
        turns, model="llama3", policy=CompactionPolicy(protect_last_n=2)
    )
    dropped = [t for t in result["kept"] if t.get("image_dropped")]
    assert dropped
    assert all("image dropped" in t["content"] for t in dropped)
    assert all("image_base64" not in t for t in dropped)


async def test_the_most_recent_images_are_kept():
    """They are what the next step is about; the older ones have already been
    described in text."""
    turns = [_turn(content="x" * 80, image=True) for _ in range(20)]
    result = await ContextCompressor().compact(
        turns, model="llama3", policy=CompactionPolicy(protect_last_n=3)
    )
    assert all("image_base64" in t for t in result["kept"][-3:])
    assert all(t.get("image_dropped") for t in result["kept"][:-3])


async def test_dropping_images_can_be_enough_on_its_own():
    """The cheap move first: if it brings the transcript back under the soft
    threshold, nothing is summarised at all."""
    turns = [_turn(content="hi", image=True) for _ in range(6)]
    result = await ContextCompressor().compact(
        turns, model="llama3", policy=CompactionPolicy(protect_last_n=1)
    )
    assert result["tier"] == "images"
    assert result["summary"] == ""


async def test_an_image_is_counted_in_the_budget():
    """Counting only the text is how the accounting says a transcript fits when
    it does not."""
    compressor = ContextCompressor()
    assert compressor._cost(_turn(content="hi", image=True)) >= IMAGE_TOKEN_COST
    assert compressor._cost(_turn(content="hi")) < IMAGE_TOKEN_COST


# ── tier two: the protected head and tail ────────────────────────────────────

async def test_the_head_is_never_summarised():
    """It is the session's original ask, and losing it is how a run drifts into
    doing something adjacent to what was requested."""
    turns = [_turn(content="ORIGINAL ASK", role="user")] + _long(60, chars=600)
    result = await ContextCompressor(summarizer=_summarizer("s")).compact(
        turns, model="llama3", policy=CompactionPolicy(protect_head=1, protect_last_n=3)
    )
    assert result["tier"] == "summarize"
    assert result["kept_first"][0]["content"] == "ORIGINAL ASK"


async def test_the_tail_is_never_summarised():
    turns = _long(60, chars=600) + [_turn(content="WHAT IS HAPPENING NOW")]
    result = await ContextCompressor(summarizer=_summarizer("s")).compact(
        turns, model="llama3", policy=CompactionPolicy(protect_head=1, protect_last_n=3)
    )
    assert result["kept"][-1]["content"] == "WHAT IS HAPPENING NOW"


async def test_the_middle_really_is_evicted():
    turns = _long(60, chars=600)
    result = await ContextCompressor(summarizer=_summarizer("a summary")).compact(
        turns, model="llama3", policy=CompactionPolicy(protect_head=2, protect_last_n=6)
    )
    assert result["compressed"] is True
    assert result["evicted"] > 0
    assert result["summary"] == "a summary"
    assert len(result["kept"]) + len(result["kept_first"]) < len(turns)


def _summarizer(text: str):
    async def _s(_prompt: str) -> str:
        return text
    return _s


# ── per-model windows ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("model", "window"),
    [("llama3.1:8b", 128_000), ("llama3:latest", 8_192), ("qwen3", 32_768)],
)
async def test_the_window_is_matched_on_the_model_family(model, window):
    assert window_for(model) == window


async def test_the_longest_prefix_wins():
    """"llama3.1" must not be matched by "llama3" — they are 128k and 8k."""
    assert window_for("llama3.1") == MODEL_WINDOWS["llama3.1"]
    assert window_for("llama3") == MODEL_WINDOWS["llama3"]
    assert window_for("llama3.1") != window_for("llama3")


@pytest.mark.parametrize("model", ["", None, "some-model-nobody-has-heard-of"])
async def test_an_unknown_model_falls_back_to_the_default(model):
    assert window_for(model) == DEFAULT_WINDOW


async def test_the_default_window_is_a_conservative_guess_not_an_average():
    """Guessing high means the provider truncates instead of us — and a provider
    truncates the TAIL, which is the half that says what is happening now. So the
    default must sit at or below the middle of what we know about, never near the
    top. Asserting it equals its own constant would prove nothing."""
    known = sorted(MODEL_WINDOWS.values())
    median = known[len(known) // 2]
    assert median >= DEFAULT_WINDOW
    assert max(known) > DEFAULT_WINDOW


async def test_an_unknown_model_actually_compacts_where_a_large_one_would_not():
    """The consequence, not the constant: a transcript that fits comfortably in
    128k must still be compacted for a model nobody recognises."""
    turns = _long(200, chars=800)   # ~40k tokens: over 32k, comfortably under 128k
    # max_tokens far above the transcript: the owner's budget is not what is
    # under test here, the model's window is.
    def _c():
        return ContextCompressor(summarizer=_summarizer("s"), max_tokens=10_000_000)

    unknown = await _c().compact(turns, model="some-model-nobody-has-heard-of")
    roomy = await _c().compact(turns, model="llama3.1")
    assert unknown["tier"] == "summarize"
    assert unknown["compressed"] is True
    assert roomy["tier"] == "none"
    assert roomy["kept"] == turns          # untouched for a model with room


async def test_a_policy_can_override_a_window_for_a_model():
    policy = CompactionPolicy(per_model={"my-local": 4_096})
    assert policy.window("my-local:7b") == 4_096
    assert policy.window("llama3.1") == MODEL_WINDOWS["llama3.1"]


# ── the tiers themselves ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("used", "tier"),
    [(0, "none"), (4_000, "none"), (4_916, "images"), (6_000, "images"),
     (6_964, "summarize"), (100_000, "summarize")],
)
async def test_the_tier_is_a_fraction_of_the_window(used, tier):
    assert CompactionPolicy().tier(used, "llama3") == tier


async def test_a_soft_tier_above_the_hard_one_is_refused():
    """It would summarise before dropping images — the expensive move before the
    cheap one, every single time."""
    with pytest.raises(ValueError, match="soft must not exceed hard"):
        CompactionPolicy(soft=0.9, hard=0.5)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
async def test_a_threshold_outside_zero_to_one_is_refused(bad):
    with pytest.raises(ValueError):
        CompactionPolicy(soft=bad)


@pytest.mark.parametrize(("head", "tail"), [(-1, 6), (2, -1)])
async def test_a_negative_protection_is_refused(head, tail):
    with pytest.raises(ValueError):
        CompactionPolicy(protect_head=head, protect_last_n=tail)


# ── lineage ──────────────────────────────────────────────────────────────────

async def test_a_compaction_emits_a_lineage_row():
    """A summary with no provenance is a claim about a conversation nobody can
    check."""
    rows: list[dict] = []
    turns = _long(60, chars=600)
    result = await ContextCompressor(summarizer=_summarizer("s")).compact(
        turns, model="llama3", session_id="sess-1", sink=rows.append
    )
    assert rows == [result["lineage"]]
    row = rows[0]
    assert row["parent_session_id"] == "sess-1"
    assert row["tier"] == "summarize"
    assert row["evicted_turns"] > 0


async def test_the_lineage_hash_matches_the_summary_it_recorded():
    """It is what lets a stored summary be matched back to its row after the
    session is gone."""
    rows: list[dict] = []
    await ContextCompressor(summarizer=_summarizer("the summary")).compact(
        _long(60, chars=600), model="llama3", session_id="s", sink=rows.append
    )
    assert rows[0]["summary_sha256"] == hashlib.sha256(b"the summary").hexdigest()


async def test_dropping_only_images_still_leaves_a_row():
    rows: list[dict] = []
    turns = [_turn(content="hi", image=True) for _ in range(6)]
    await ContextCompressor().compact(
        turns, model="llama3", policy=CompactionPolicy(protect_last_n=1),
        session_id="s", sink=rows.append,
    )
    assert rows[0]["tier"] == "images"
    assert rows[0]["images_dropped"] > 0


async def test_a_no_op_emits_nothing():
    rows: list[dict] = []
    await ContextCompressor().compact(_long(2, chars=10), model="llama3.1", sink=rows.append)
    assert rows == []


async def test_a_failing_sink_never_fails_the_compaction():
    """Losing the record of what happened is bad. Losing the conversation is
    worse."""
    def _boom(_row):
        raise RuntimeError("the ledger is gone")

    result = await ContextCompressor(summarizer=_summarizer("s")).compact(
        _long(60, chars=600), model="llama3", sink=_boom
    )
    assert result["compressed"] is True


async def test_the_lineage_row_carries_its_schema():
    row = lineage_row(session_id="s", summary="x", evicted=1, images_dropped=0, tier="summarize")
    assert row["schema"] == "nerva.context-compaction.v1"


# ── failures degrade rather than lose the conversation ───────────────────────

async def test_a_failing_summariser_falls_back_to_a_digest():
    async def _boom(_prompt):
        raise RuntimeError("the model is down")

    result = await ContextCompressor(summarizer=_boom).compact(
        _long(60, chars=600), model="llama3"
    )
    assert result["compressed"] is True
    assert result["summary"]          # a deterministic digest, never empty


async def test_a_compaction_that_would_grow_the_transcript_is_abandoned():
    """Inherited from the compressor's salvage rule, and it still holds through
    the policy: a "compression" that grew the transcript must not replace it."""
    async def _rambling(_prompt):
        return "y" * 100_000

    turns = _long(30, chars=600)
    result = await ContextCompressor(summarizer=_rambling).compact(turns, model="llama3")
    assert result["compressed"] is False
    assert len(result["kept"]) == len(turns)


# ── the old entry point is untouched ─────────────────────────────────────────

async def test_compress_still_behaves_exactly_as_it_did():
    """`orchestrator.get_context` calls compress(), not compact(). Growing the
    module must not change what the existing caller gets."""
    compressor = ContextCompressor(max_tokens=50, keep_recent=2)
    result = await compressor.compress(_long(20, chars=400))
    assert set(result) == {
        "compressed", "kept", "kept_first", "summary", "evicted", "tokens", "covered"
    }


async def test_compact_leaves_the_compressor_configuration_alone():
    """It borrows keep_first/keep_recent for one call; a leaked change would
    silently alter every later compress()."""
    compressor = ContextCompressor(keep_first=1, keep_recent=4, max_tokens=2000)
    await compressor.compact(
        _long(60, chars=600), model="llama3",
        policy=CompactionPolicy(protect_head=2, protect_last_n=9),
    )
    assert (compressor.keep_first, compressor.keep_recent) == (1, 4)
    assert compressor.max_tokens == 2000


async def test_compact_restores_the_configuration_even_when_compress_raises():
    class _Exploding(ContextCompressor):
        async def compress(self, turns, prior=None):
            raise RuntimeError("boom")

    compressor = _Exploding(keep_first=1, keep_recent=4, max_tokens=2000)
    with pytest.raises(RuntimeError):
        await compressor.compact(_long(60, chars=600), model="llama3")
    assert (compressor.keep_first, compressor.keep_recent) == (1, 4)
    assert compressor.max_tokens == 2000


async def test_compaction_targets_the_soft_threshold_not_the_edge_of_the_window():
    """Compacting only to the edge leaves the next turn back over it. The target
    is the tier where the cheap moves are enough again."""
    policy = CompactionPolicy(protect_head=1, protect_last_n=2)
    result = await ContextCompressor(
        summarizer=_summarizer("s"), max_tokens=10_000_000
    ).compact(_long(200, chars=800), model="llama3", policy=policy)
    assert result["compressed"] is True
    assert result["tokens"] < policy.soft * policy.window("llama3")
