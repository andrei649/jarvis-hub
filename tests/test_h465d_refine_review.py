"""H465, the third review (review-H465c) — its findings, pinned.

- m-1: a per-turn review cut off by the token cap was refunded, so a model that always
  truncates ran a local review on every turn. Only the owner's /refine gets the unit
  back; a per-turn cut-off spends it, and is logged once a day.
- m-2: the replies named ``learning.review_max_tokens``, which no surface could set. The
  learning loop's knobs are declared settings now, with bounds.
- m-3: the survivors: an empty reply, a reply cut after an inner ``}``, a thinking cut-off's
  stored result, a cancelled /refine that must stay cancelled.
- nits: a JSON object that is not a review, a reply that starts with ``[``, the budget's
  edge values and 0's own wording, a per-turn skip's log line.
"""

from __future__ import annotations

import asyncio
import logging
import re

import pytest

from agents.core import settings_db
from agents.core.commands import _REFINE_REFUSALS
from agents.core.learning.background_review import BackgroundReviewer, parse_review_json
from agents.core.llm.base import THINKING_EXHAUSTED_REPLY
from tests.test_h465c_refine_review import _LLM, _Living, _reviewer

CUT_AFTER_INNER = '{"corrections": [{"original": "a", "corrected": "b"}], "user_facts": ["prefers te'


# ── m-1: the daily budget caps a model that always truncates ───────────────────────

@pytest.mark.parametrize("reply", [CUT_AFTER_INNER, "no json here", THINKING_EXHAUSTED_REPLY])
def test_a_model_that_always_truncates_stops_at_the_budget(reply, caplog):
    llm = _LLM(reply)
    reviewer = _reviewer(llm, **{"learning.review_daily_budget": 3})
    caplog.set_level(logging.INFO, logger="jarvis")
    for _ in range(30):
        if reviewer.should_run()[0]:
            asyncio.run(reviewer.run("hi", "hello"))
    assert len(llm.prompts) == 3
    assert sum("raise learning.review_max_tokens" in r.getMessage() for r in caplog.records) == 1


def test_the_owner_who_asked_gets_the_unit_back():
    reviewer = _reviewer(_LLM(CUT_AFTER_INNER), **{"learning.review_daily_budget": 1})
    for _ in range(3):
        assert asyncio.run(reviewer.run_on_demand("user: x"))["reason"] == "review_unparsed"
    assert reviewer._day_count == 0


# ── m-2: what the replies name, the owner can set ──────────────────────────────────

def test_every_setting_a_refine_reply_names_is_declared_and_writable(tmp_path, monkeypatch):
    named = {m for text in _REFINE_REFUSALS.values() for m in re.findall(r"learning\.\w+", text)}
    assert named >= {"learning.review_max_tokens", "learning.review_daily_budget"}
    for dotted in named:
        assert tuple(dotted.split(".")) in settings_db._SPEC, dotted
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db()
    updated, skipped = settings_db.put_category("learning", {"review_max_tokens": 4096})
    assert (updated, skipped) == (1, [])
    assert settings_db.get_value("learning", "review_max_tokens") == 4096


@pytest.mark.parametrize("key, bad", [("review_max_tokens", 0), ("review_max_tokens", 1.5),
                                      ("review_daily_budget", -1), ("review_every_n", 0),
                                      ("review_cadence", "hourly"), ("review_max_facts", 21)])
def test_the_learning_knobs_are_bounded(key, bad):
    assert settings_db.validate_category("learning", {key: bad})


def test_the_declared_defaults_are_the_ones_the_code_used():
    spec = {k: settings_db._SPEC[("learning", k)]["value"] for (c, k) in settings_db._SPEC if c == "learning"}
    assert spec == {"review_max_tokens": 512, "review_daily_budget": 20, "review_cadence": "every_turn",
                    "review_every_n": 3, "review_idle_gap_s": 90, "review_max_facts": 3}


# ── m-3: the survivors ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reply", ["", CUT_AFTER_INNER, "{}", '{"error": "context too long"}'])
def test_an_empty_cut_or_foreign_reply_is_not_nothing(reply):
    assert parse_review_json(reply).get("unparsed") is True
    reviewer = _reviewer(_LLM(reply))
    result = asyncio.run(reviewer.run_on_demand("user: x"))
    assert result["reason"] == "review_unparsed" and reviewer.last_result == result


def test_a_thinking_cut_off_is_stored_as_the_last_result():
    reviewer = _reviewer(_LLM(THINKING_EXHAUSTED_REPLY))
    result = asyncio.run(reviewer.run_on_demand("user: x"))
    assert reviewer.last_result == result == {"ran": False, "reason": "review_cut_off", "actions": []}


def test_a_cancelled_refine_stays_cancelled():
    gate = asyncio.Event()

    async def stuck(prompt):
        await gate.wait()

    reviewer = _reviewer(stuck)

    async def scenario():
        task = asyncio.create_task(reviewer.run_on_demand("user: a"))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return task.cancelled()

    assert asyncio.run(scenario()) is True


# ── nits ─────────────────────────────────────────────────────────────────────────────

def test_a_reply_that_starts_with_a_bracket_is_the_models_answer():
    reviewer = BackgroundReviewer(_LLM('[{"user_facts": ["prefers tea"]}]'), living=_Living(),
                                  get_setting=lambda k, d=None: d)
    result = asyncio.run(reviewer.run_on_demand("user: x"))
    assert result["ran"] is True and result["actions"] == ["User profile updated (+1)"]
    failed = asyncio.run(_reviewer(_LLM("[backend error: connection refused]")).run_on_demand("user: x"))
    assert failed["reason"] == "llm_error"


@pytest.mark.parametrize("raw, budget", [("2.5", 2), (2.9, 2), (float("inf"), 20), ("abc", 20), (True, 20)])
def test_the_budget_reads_edge_values_without_a_crash(raw, budget):
    assert _reviewer(_LLM(), **{"learning.review_daily_budget": raw})._budget() == budget


def test_a_garbage_budget_is_warned_about_once(caplog):
    reviewer = _reviewer(_LLM(), **{"learning.review_daily_budget": "abc"})
    caplog.set_level(logging.WARNING, logger="jarvis")
    for _ in range(5):
        reviewer.should_run()
    assert sum("review_daily_budget" in r.getMessage() for r in caplog.records) == 1


def test_a_budget_of_zero_says_reviews_are_off():
    reviewer = _reviewer(_LLM(), **{"learning.review_daily_budget": 0})
    assert asyncio.run(reviewer.run_on_demand("user: x"))["reason"] == "reviews_off"
    assert "is 0" in _REFINE_REFUSALS["reviews_off"] and "tomorrow" not in _REFINE_REFUSALS["reviews_off"]


def test_a_per_turn_skip_leaves_a_log_line(caplog):
    from agents.core.orchestrator import Orchestrator

    class Memory:
        async def get_history(self, key, last_n=None):
            return []

    orch = Orchestrator.__new__(Orchestrator)
    orch.memory = Memory()
    orch.reviewer = _reviewer(_LLM())
    orch.reviewer._on_demand = True                     # a /refine is running
    orch._session_id_default = "web-1"
    caplog.set_level(logging.DEBUG, logger="jarvis")
    asyncio.run(orch._background_review_task("hi", "hello"))
    assert any("learning review skipped: on_demand" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("gap, runs", [(0, 3), (None, 1), ("x", 1)])
def test_an_idle_gap_of_zero_is_no_gap_and_an_unset_one_is_the_default(gap, runs):
    llm = _LLM('{"nothing": true}')
    reviewer = _reviewer(llm, **{"learning.review_cadence": "idle_gap", "learning.review_idle_gap_s": gap})
    for _ in range(3):
        if reviewer.should_run()[0]:
            asyncio.run(reviewer.run("hi", "hello"))
    assert len(llm.prompts) == runs


def test_max_facts_zero_keeps_no_fact():
    living = _Living()
    reviewer = _reviewer(_LLM('{"user_facts": ["prefers tea"]}'), living=living, **{"learning.review_max_facts": 0})
    result = asyncio.run(reviewer.run_on_demand("user: x"))
    assert "User profile updated (+1)" not in result["actions"]
