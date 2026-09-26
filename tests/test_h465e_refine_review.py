"""H465, the fourth review (review-H465d) — its findings, pinned.

- m-1: after a day of per-turn reviews the model cut off, /refine said "try again
  tomorrow" and named the daily budget; it now names the token cap.
- m-2: the documented values are accepted, not only the bad ones refused; the degraded
  check never fires inside a review; a /refine cut-off leaves the day's INFO line to the
  per-turn pass; every skipped pass's reason reaches the DEBUG log.
- nits: a review that opens with ``[{`` is a review; a boolean or NaN budget warns once;
  corrections have their own cap; the knobs read within their bounds; the CLI masks every
  stored secret; a burst of passes cannot pass the budget; the INFO line's wording.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from agents.core import settings_db
from agents.core.commands import _REFINE_REFUSALS
from agents.core.learning.background_review import MAX_CORRECTIONS
from tests.test_h465c_refine_review import _LLM, _Living, _reviewer
from tests.test_h465d_refine_review import CUT_AFTER_INNER


class _Learning:
    def __init__(self):
        self.corrections = []

    def record_correction(self, original, corrected):
        self.corrections.append((original, corrected))


# ── m-1: a day spent on cut-offs names the token cap ─────────────────────────────

def test_a_budget_spent_on_cut_offs_names_the_token_cap():
    llm = _LLM(CUT_AFTER_INNER)
    reviewer = _reviewer(llm, **{"learning.review_daily_budget": 3})
    for _ in range(5):
        if reviewer.should_run()[0]:
            asyncio.run(reviewer.run("hi", "hello"))
    result = asyncio.run(reviewer.run_on_demand("user: x"))
    assert result["reason"] == "daily_budget_cut_off"
    text = _REFINE_REFUSALS["daily_budget_cut_off"]
    assert "learning.review_max_tokens" in text and "rather than the budget" in text
    assert reviewer.status()["cut_offs_today"] == 3


def test_a_budget_spent_on_real_reviews_still_says_so():
    reviewer = _reviewer(_LLM('{"nothing": true}'), **{"learning.review_daily_budget": 1})
    assert reviewer.should_run()[0]
    asyncio.run(reviewer.run("hi", "hello"))
    assert asyncio.run(reviewer.run_on_demand("user: x"))["reason"] == "daily_budget"


# ── m-2: the documented values are accepted ──────────────────────────────────────

@pytest.mark.parametrize("key, value", [
    ("review_daily_budget", 0), ("review_idle_gap_s", 0), ("review_max_facts", 0), ("review_max_tokens", 32768),
    ("review_max_tokens", 1), ("review_cadence", "idle_gap"), ("review_cadence", "every_n_turns"),
    ("review_every_n", 100), ("review_every_n", 1), ("review_daily_budget", 1000),
])
def test_every_documented_value_is_accepted_and_stored(tmp_path, monkeypatch, key, value):
    assert settings_db.validate_category("learning", {key: value}) == []
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db()
    assert settings_db.put_category("learning", {key: value}) == (1, [])
    assert settings_db.get_value("learning", key) == value


@pytest.mark.parametrize("reply", [
    '{"user_facts": ["prefers [short] error messages"]}',
    '[{"user_facts": ["prefers error messages in Romanian"]}]',
    '[analysis: no error found] {"user_facts": ["prefers tea"]}',
])
def test_a_review_that_mentions_an_error_is_a_review(reply):
    result = asyncio.run(_reviewer(_LLM(reply)).run_on_demand("user: x"))
    assert result["ran"] is True and result["actions"] == ["User profile updated (+1)"]


@pytest.mark.parametrize("reply", ["[Claude API error: context too long]", "[runner error]",
                                   "[error: backend down]", "⚠️ Local model unavailable"])
def test_a_backend_failure_is_still_no_local_model(reply):
    assert asyncio.run(_reviewer(_LLM(reply)).run_on_demand("user: x"))["reason"] == "llm_error"


def test_a_refine_cut_off_leaves_the_days_line_to_the_per_turn_pass(caplog):
    reviewer = _reviewer(_LLM(CUT_AFTER_INNER))
    caplog.set_level(logging.INFO, logger="jarvis")
    asyncio.run(reviewer.run_on_demand("user: x"))
    assert reviewer.should_run()[0]
    asyncio.run(reviewer.run("hi", "hello"))
    lines = [r.getMessage() for r in caplog.records if "logged once a day" in r.getMessage()]
    assert len(lines) == 1


def test_every_skipped_passes_reason_is_logged(caplog):
    from agents.core.orchestrator import Orchestrator

    class Memory:
        async def get_history(self, key, last_n=None):
            return []

    orch = Orchestrator.__new__(Orchestrator)
    orch.memory = Memory()
    orch.reviewer = _reviewer(_LLM(CUT_AFTER_INNER))
    orch.reviewer.should_run()
    orch._session_id_default = "web-1"
    caplog.set_level(logging.DEBUG, logger="jarvis")
    asyncio.run(orch._background_review_task("hi", "hello"))
    assert any("learning review skipped: review_unparsed" in r.getMessage() for r in caplog.records)


# ── nits ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [True, float("nan")])
def test_a_boolean_or_nan_budget_warns_once(caplog, raw):
    reviewer = _reviewer(_LLM(), **{"learning.review_daily_budget": raw})
    caplog.set_level(logging.WARNING, logger="jarvis")
    for _ in range(4):
        assert reviewer._budget() == 20
    assert sum("review_daily_budget" in r.getMessage() for r in caplog.records) == 1


def test_no_facts_kept_still_records_corrections_and_says_what_was_found():
    learning = _Learning()
    reply = ('{"user_facts": ["prefers tea"], "corrections": '
             '[{"original": "Bucuresti", "corrected": "Bucharest"}]}')
    reviewer = _reviewer(_LLM(reply), **{"learning.review_max_facts": 0})
    reviewer._learning = learning
    result = asyncio.run(reviewer.run_on_demand("user: x"))
    assert learning.corrections == [("Bucuresti", "Bucharest")]
    assert "1 fact(s) found but not kept: learning.review_max_facts is 0" in result["actions"]
    assert result["nothing"] is False and MAX_CORRECTIONS == 3


@pytest.mark.parametrize("raw, read", [(-1, 512), ("abc", 512), (0, 512), (40000, 512), (True, 512),
                                       (1024, 1024), ("2048", 2048)])
def test_the_token_cap_reads_within_its_bounds(raw, read):
    assert settings_db.bounded_learning_int("review_max_tokens", raw, 512) == read


def test_a_garbage_every_n_keeps_the_per_turn_loop_running():
    reviewer = _reviewer(_LLM(), **{"learning.review_cadence": "every_n_turns", "learning.review_every_n": "abc"})
    results = [reviewer.should_run()[1] for _ in range(4)]
    assert results.count("ok") >= 1                        # every third turn, as the default


def test_the_cli_masks_every_stored_secret(tmp_path, monkeypatch):
    from tests.test_nerva_cli import _run

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    settings_db.put_category("plugins", {"stark_ga4_service_account": '{"private_key": "-----BEGIN KEY"}'})
    code, out, _err, _hub = _run(["config", "get", "plugins.stark_ga4_service_account"])
    assert code == 0 and "BEGIN KEY" not in out and "••" in out


def test_a_burst_of_passes_cannot_pass_the_budget():
    llm = _LLM('{"nothing": true}')
    reviewer = _reviewer(llm, **{"learning.review_daily_budget": 1})

    async def burst():
        assert all(reviewer.should_run()[0] for _ in range(4))      # all four saw budget left
        return await asyncio.gather(*(reviewer.run("hi", "hello") for _ in range(4)))

    results = asyncio.run(burst())
    assert len(llm.prompts) == 1 and [r["reason"] for r in results if not r["ran"]] == ["daily_budget"] * 3


def test_the_days_line_names_the_cap_only_as_a_possible_cause(caplog):
    reviewer = _reviewer(_LLM('{"error": "context too long"}'))
    caplog.set_level(logging.INFO, logger="jarvis")
    reviewer.should_run()
    asyncio.run(reviewer.run("hi", "hello"))
    [line] = [r.getMessage() for r in caplog.records if "logged once a day" in r.getMessage()]
    assert "if it was cut off, raise learning.review_max_tokens" in line



def test_prose_that_mentions_an_error_midway_is_malformed_not_a_backend_failure():
    reply = "Here is my review, though [no error was found] I could not format it"
    assert asyncio.run(_reviewer(_LLM(reply)).run_on_demand("user: x"))["reason"] == "review_unparsed"


def test_an_out_of_range_every_n_reads_as_the_default():
    reviewer = _reviewer(_LLM(), **{"learning.review_cadence": "every_n_turns", "learning.review_every_n": 0})
    reasons = [reviewer.should_run()[1] for _ in range(3)]
    assert reasons == ["cadence_n", "cadence_n", "ok"]              # every third turn, not every turn
