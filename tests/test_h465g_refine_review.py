"""H465, the sixth review (review-H465f) — its nits, pinned.

- 1: a /refine that timed out or was cancelled gives its unit back on the day _run spent
  it; the day taken before _run rolled could only differ where it was wrong.
- 2: a pass uses up the turns that admitted it and no more, so a burst of turns gets the
  passes the same turns one at a time would.
- 3: a later ``[1]`` or link no longer closes an ``[… error`` that was never closed.
- 4: the refusal says "at least half", as the rule is.
- 5: a hand-edited fraction below one is not "reviews off".
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from agents.core.commands import _REFINE_REFUSALS
from agents.core.learning import background_review as br
from tests.test_h465c_refine_review import _LLM, _reviewer


class _Midnight:
    """``date`` that turns over after its first ``today()`` call."""

    calls = 0

    @classmethod
    def today(cls):
        cls.calls += 1
        day = "2026-09-25" if cls.calls == 1 else "2026-09-26"
        return SimpleNamespace(isoformat=lambda: day)


@pytest.mark.parametrize("how", ["timeout", "cancel"])
def test_a_refine_cut_short_at_midnight_gives_back_the_new_days_unit(monkeypatch, how):
    monkeypatch.setattr(_Midnight, "calls", 0)
    monkeypatch.setattr(br, "date", _Midnight)
    monkeypatch.setattr(br, "REFINE_TIMEOUT_S", 0.2)
    hang = asyncio.Event()

    async def llm(prompt):
        await hang.wait()

    reviewer = _reviewer(llm, **{"learning.review_daily_budget": 1})

    async def refine():
        if how == "timeout":
            return await reviewer.run_on_demand("user: x")
        task = asyncio.create_task(reviewer.run_on_demand("user: x"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(refine())
    assert reviewer.status()["day"] == "2026-09-26" and reviewer.status()["reviews_today"] == 0
    assert reviewer.should_run() == (True, "ok")


def test_a_refine_that_times_out_the_same_day_is_refunded_once(monkeypatch):
    monkeypatch.setattr(br, "REFINE_TIMEOUT_S", 0.2)
    hang = asyncio.Event()

    async def llm(prompt):
        await hang.wait()

    reviewer = _reviewer(llm, **{"learning.review_daily_budget": 3})
    reviewer.should_run()
    reviewer._day_count = 2                                   # two real reviews already had
    assert asyncio.run(reviewer.run_on_demand("user: x"))["reason"] == "llm_timeout"
    assert reviewer.status()["reviews_today"] == 2


@pytest.mark.parametrize("turns, passes", [(6, 2), (9, 3), (4, 1)])
def test_a_burst_gets_the_passes_its_turns_ask_for(turns, passes):
    llm = _LLM()
    reviewer = _reviewer(llm, **{"learning.review_cadence": "every_n_turns", "learning.review_every_n": 3})

    async def burst():
        admitted = [reviewer.should_run()[0] for _ in range(turns)]
        return await asyncio.gather(*(reviewer.run("hi", "hello") for _ in range(admitted.count(True))))

    asyncio.run(burst())
    assert len(llm.prompts) == passes


def test_turns_one_at_a_time_keep_their_cadence():
    llm = _LLM()
    reviewer = _reviewer(llm, **{"learning.review_cadence": "every_n_turns", "learning.review_every_n": 3})
    for _ in range(9):
        if reviewer.should_run()[0]:
            asyncio.run(reviewer.run("hi", "hello"))
    assert len(llm.prompts) == 3


@pytest.mark.parametrize("reply", [
    "[Note: I hit an error formatting this.\n\nSee [1] below.",
    "[Note: an error here, see [the docs](http://x)]",
])
def test_a_later_bracket_does_not_close_an_unclosed_error(reply):
    assert br._degraded(reply) is False
    assert asyncio.run(_reviewer(_LLM(reply)).run_on_demand("user: x"))["reason"] == "review_unparsed"


def test_the_refusal_says_at_least_half():
    assert _REFINE_REFUSALS["daily_budget_cut_off"].startswith("At least half of today's")


@pytest.mark.parametrize("raw", [-0.5, 0.9, "-0.9", "0.5"])
def test_a_fraction_below_one_is_not_reviews_off(caplog, raw):
    reviewer = _reviewer(_LLM(), **{"learning.review_daily_budget": raw})
    caplog.set_level(logging.WARNING, logger="jarvis")
    assert reviewer._budget() == 20 and reviewer._budget() == 20
    assert sum("review_daily_budget" in r.getMessage() for r in caplog.records) == 1


@pytest.mark.parametrize("raw", [0, "0", 0.0, "0.0"])
def test_a_real_zero_still_switches_reviews_off(raw):
    reviewer = _reviewer(_LLM(), **{"learning.review_daily_budget": raw})
    assert reviewer._budget() == 0
    assert asyncio.run(reviewer.run_on_demand("user: x"))["reason"] == "reviews_off"
