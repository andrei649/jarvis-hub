"""H673 — context pressure measured from the provider's own number.

A chars/4 estimate errs across the whole conversation and the error compounds.
Anchoring on the last response's reported prompt tokens shrinks the error window
to a single turn and re-anchors on every response. The direction of the error is
what matters: the estimate says a transcript fits when it does not, and the
provider's answer to a request that does not fit is to cut the TAIL — the turn
that is happening right now.
"""

import pytest

from agents.core.context_compressor import (
    IMAGE_TOKEN_COST,
    CompactionPolicy,
    ContextCompressor,
    UsageAnchor,
)


def _turns(n: int, size: int = 400) -> list[dict]:
    return [{"role": "user", "content": "x" * size} for _ in range(n)]


@pytest.fixture
def compressor():
    return ContextCompressor()


@pytest.fixture
def policy():
    return CompactionPolicy()


# ── the fallback stays the fallback ──────────────────────────────────────────

async def test_without_an_anchor_the_estimate_is_what_it_always_was(compressor, policy):
    """Every local backend reports nothing, so this is the common path, not a corner."""
    rows = _turns(10)
    plain = await compressor.compact(rows, model="llama-3-8b", policy=policy)
    assert plain["tier"] == "none"
    assert plain["tokens"] == sum(compressor._cost(t) for t in rows)


async def test_an_anchor_that_measured_nothing_reads_as_no_anchor(compressor, policy):
    rows = _turns(10)
    plain = await compressor.compact(rows, model="llama-3-8b", policy=policy)
    empty = await compressor.compact(rows, model="llama-3-8b", policy=policy,
                     anchor=UsageAnchor())
    assert not UsageAnchor().usable
    assert empty == plain


# ── the failure the row is named after ───────────────────────────────────────

async def test_the_estimate_says_it_fits_and_the_providers_number_says_it_does_not(
    compressor, policy
):
    """The whole point. Ten short turns estimate at ~1k on a 32k window — 'none'.
    The request that actually went out was 28k, because the system prompt and the
    tool schemas are not in the transcript at all and the estimate cannot see
    them. 28k/32k is past the hard threshold."""
    rows = _turns(10)
    plain = await compressor.compact(rows, model="llama-3-8b", policy=policy)
    assert plain["tier"] == "none"
    anchored = await compressor.compact(rows, model="llama-3-8b", policy=policy,
                        anchor=UsageAnchor(prompt_tokens=28_000, covers=10))
    assert anchored["tier"] == "summarize"


def test_only_what_was_appended_since_the_anchor_is_estimated(compressor, policy):
    """The error window is one turn, not the conversation."""
    rows = _turns(10)
    one_turn = compressor._cost(rows[0])
    used = compressor._used(rows, UsageAnchor(prompt_tokens=5_000, covers=9))
    assert used == 5_000 + one_turn


def test_an_anchor_cannot_cover_more_turns_than_exist(compressor):
    rows = _turns(3)
    assert compressor._used(rows, UsageAnchor(prompt_tokens=900, covers=99)) == 900


def test_the_anchor_never_reads_lower_than_the_plain_estimate(compressor):
    """An anchor may make compaction happen sooner or at the same point, never
    later — the same direction the window bound already runs in. A number that
    somehow came back smaller than the text it covers is not trusted downward."""
    rows = _turns(10, size=4_000)
    estimate = sum(compressor._cost(t) for t in rows)
    used = compressor._used(rows, UsageAnchor(prompt_tokens=1, covers=10))
    assert used == estimate


# ── images rewrite the prefix the anchor described ───────────────────────────

def test_an_image_dropped_from_the_anchored_prefix_comes_off_the_anchor(compressor):
    """The provider counted that image at its real cost and never said what it
    was, so the flat figure comes back for exactly the turns that were rewritten."""
    rows = _turns(4)
    anchor = UsageAnchor(prompt_tokens=50_000, covers=4)
    assert compressor._used(rows, anchor) == 50_000
    assert compressor._used(rows, anchor, dropped_in_prefix=2) == 50_000 - 2 * IMAGE_TOKEN_COST


def test_dropping_an_image_can_never_take_the_count_below_the_estimate(compressor):
    rows = _turns(4, size=8_000)
    estimate = sum(compressor._cost(t) for t in rows)
    used = compressor._used(rows, UsageAnchor(prompt_tokens=estimate + 10, covers=4),
                            dropped_in_prefix=50)
    assert used == estimate


def test_an_image_outside_the_anchored_prefix_leaves_the_anchor_alone(compressor, policy):
    """It was never in the measured request, so removing it cannot change that
    measurement — only the estimated tail shrinks."""
    rows = _turns(3) + [{"role": "user", "content": "look", "image": "b64"}]
    anchor = UsageAnchor(prompt_tokens=9_000, covers=3)
    with_image = compressor._used(rows, anchor)
    without = compressor._used([dict(t) for t in rows[:3]], anchor)
    assert with_image - without == compressor._cost(rows[3])
    assert without == 9_000


# ── the orchestrator half ────────────────────────────────────────────────────

class _usage:
    """The one field the anchor reads, in the shape TokenUsage presents it."""

    def __init__(self, input_tokens: int):
        self.input_tokens = input_tokens


def _orch():
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch._context_anchor = {}
    orch._ctx_turns_at_build = 0
    return orch


def test_nothing_reported_means_no_anchor_at_all():
    """Not a zero anchor — no anchor, so the estimator stays in charge."""
    assert _orch()._usage_anchor(10) is None


def test_the_strongest_measured_request_wins_when_several_agents_answered():
    """They were each sent their own prompt over one shared transcript. Under-
    anchoring risks the truncation this row prevents; over-anchoring only
    compacts slightly early."""
    orch = _orch()
    orch._context_anchor = {"jarvis": (12_000, 8), "friday": (20_000, 8)}
    anchor = orch._usage_anchor(10)
    assert (anchor.prompt_tokens, anchor.covers) == (20_000, 8)


def test_an_anchor_covering_more_turns_than_remain_is_dropped_not_scaled():
    """History was compacted or trimmed under it, so the number no longer
    describes any prefix of these turns."""
    orch = _orch()
    orch._context_anchor = {"jarvis": (20_000, 40)}
    assert orch._usage_anchor(10) is None


def test_a_zero_measurement_is_never_promoted_to_an_anchor():
    orch = _orch()
    orch._context_anchor = {"jarvis": (0, 5)}
    assert orch._usage_anchor(10) is None


# ── the trap: a tool loop resends the prefix every iteration ─────────────────

def test_the_anchor_is_the_last_request_not_the_sum_of_the_loops_requests():
    """The one way this is easy to get wrong. `_last_reported_usage` sums on
    purpose — that is the bill, and one answer takes several requests which all
    cost. Context is the opposite question: how big the request that just went
    out was. A five-iteration tool loop resends the whole prefix each time, so
    billing the sum as context would report about five times the context that
    exists and compact a healthy session down to nothing."""
    orch = _orch()
    orch._ctx_turns_at_build = 6
    for size in (9_000, 9_100, 9_250):
        orch._record_context_anchor("jarvis", _usage(size))
    assert orch._context_anchor["jarvis"] == (9_250, 6)
    assert orch._usage_anchor(6).prompt_tokens == 9_250


def test_a_backend_that_reported_no_input_leaves_the_anchor_standing():
    """The transcript did not shrink because one backend stayed quiet."""
    orch = _orch()
    orch._ctx_turns_at_build = 4
    orch._record_context_anchor("jarvis", _usage(7_000))
    orch._record_context_anchor("jarvis", _usage(0))
    assert orch._context_anchor["jarvis"] == (7_000, 4)


def test_the_anchor_records_where_estimation_resumes():
    orch = _orch()
    orch._ctx_turns_at_build = 11
    orch._record_context_anchor("friday", _usage(3_300))
    assert orch._context_anchor["friday"] == (3_300, 11)


def test_a_session_reset_drops_the_anchor():
    """Otherwise a turn that measured nothing is judged against the previous
    turn's request size."""
    import inspect

    from agents.core.orchestrator import Orchestrator

    src = inspect.getsource(Orchestrator)
    reset = src[src.index("self._last_prompt_tokens = {}\n        # H673"):]
    assert "_context_anchor" in reset[:400]
