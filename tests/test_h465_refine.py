"""H465 — run the self-improvement review on demand: ``/refine [focus]``.

Hermes' ``/refine [focus]`` forks the background memory/skill review against a snapshot
of the conversation, so the live session is untouched, refuses while a turn is in flight,
and reports what it added back into the chat. Nerva's review engine is the per-turn
``BackgroundReviewer`` (strict-local, budgeted); these tests pin the on-demand path:
a focus slot, a whole-conversation snapshot, the busy check on the session's turn lease
(critic note 1: excluding the command's own held lease) and the report in the reply.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.core.commands import Principal, build_default_registry
from agents.core.learning.background_review import (
    REFINE_SNAPSHOT_CHARS,
    BackgroundReviewer,
    conversation_snapshot,
)
from agents.core.orchestrator import Orchestrator


class _LLM:
    def __init__(self, reply='{"nothing": true}'):
        self.prompts = []
        self.reply = reply

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.reply


class _Store:
    def __init__(self):
        self.facts = []

    def put(self, fact):
        self.facts.append(fact)

    def list(self):
        return list(self.facts)


class _Living:
    def __init__(self):
        self.user_core = _Store()
        self.core = _Store()


def _reviewer(llm, **settings):
    values = {"learning.review_daily_budget": 20, **settings}
    return BackgroundReviewer(llm, living=_Living(), get_setting=lambda k, d=None: values.get(k, d))


# ── the reviewer ─────────────────────────────────────────────────────────────

def test_a_focus_reaches_the_prompt_as_one_line_and_none_leaves_no_slot():
    llm = _LLM()
    reviewer = _reviewer(llm)
    asyncio.run(reviewer.run_on_demand("user: deploy it\nassistant: done", focus="deployment\nsteps  "))
    assert "Focus for this review: deployment steps\n" in llm.prompts[0]
    asyncio.run(reviewer.run("hi", "hello"))
    assert "Focus for this review" not in llm.prompts[1]


def test_the_focus_is_bounded():
    llm = _LLM()
    asyncio.run(_reviewer(llm).run_on_demand("user: x", focus="f" * 5_000))
    line = next(row for row in llm.prompts[0].splitlines() if row.startswith("Focus for this review:"))
    assert len(line) <= len("Focus for this review: ") + 200


def test_on_demand_skips_the_cadence_but_spends_the_daily_budget():
    llm = _LLM()
    reviewer = _reviewer(llm, **{"learning.review_cadence": "every_n_turns", "learning.review_every_n": 50,
                                 "learning.review_daily_budget": 2})
    assert reviewer.should_run() == (False, "cadence_n")
    first = asyncio.run(reviewer.run_on_demand("user: a"))
    assert first["ran"] is True and len(llm.prompts) == 1
    asyncio.run(reviewer.run_on_demand("user: b"))
    spent = asyncio.run(reviewer.run_on_demand("user: c"))
    assert spent == {"ran": False, "reason": "daily_budget", "actions": []}
    assert len(llm.prompts) == 2


def test_two_on_demand_reviews_do_not_run_at_once():
    gate = asyncio.Event()

    async def slow(prompt):
        await gate.wait()
        return '{"nothing": true}'

    reviewer = _reviewer(slow)

    async def both():
        first = asyncio.create_task(reviewer.run_on_demand("user: a"))
        await asyncio.sleep(0)
        second = await reviewer.run_on_demand("user: b")
        gate.set()
        return await first, second

    first, second = asyncio.run(both())
    assert first["ran"] is True
    assert second == {"ran": False, "reason": "busy", "actions": []}


def test_the_on_demand_review_writes_what_the_model_found():
    llm = _LLM('{"user_facts": ["prefers terse replies"], "agent_facts": [], "corrections": [],'
               ' "skill_updates": [], "nothing": false}')
    reviewer = _reviewer(llm)
    result = asyncio.run(reviewer.run_on_demand("user: keep it short"))
    assert result["ran"] is True and result["actions"] == ["User profile updated (+1)"]
    assert reviewer._living.user_core.facts == ["prefers terse replies"]


# ── the snapshot ─────────────────────────────────────────────────────────────

def test_the_snapshot_keeps_the_newest_turns_whole_up_to_its_bound():
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + "x" * 200}
             for i in range(200)]
    text = conversation_snapshot(turns)
    assert len(text) <= REFINE_SNAPSHOT_CHARS
    assert text.endswith("turn 199 " + "x" * 200)
    assert "turn 0 " not in text
    assert text.splitlines()[0].startswith(("user: turn", "assistant: turn"))


def test_a_long_turn_is_cut_and_a_short_conversation_is_all_there():
    text = conversation_snapshot([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b" * 10_000}])
    assert text.startswith("user: a\nassistant: ") and len(text) < 3_000
    assert conversation_snapshot([]) == ""
    assert conversation_snapshot([{"role": "user", "content": None}, "junk", {"content": "c"}]) == "?: c"


# ── the orchestrator ─────────────────────────────────────────────────────────

class _Memory:
    def __init__(self, turns):
        self.turns = turns
        self.asked = []

    async def get_history(self, session_id, last_n=None):
        self.asked.append((session_id, last_n))
        return list(self.turns)


class _FakeReviewer:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"ran": True, "nothing": False, "actions": ["Core memory updated (+1)"]}

    async def run_on_demand(self, history, *, focus=""):
        self.calls.append((history, focus))
        return self.result


def _orch(turns=(), reviewer=None):
    orch = Orchestrator.__new__(Orchestrator)
    orch.memory = _Memory(list(turns))
    orch.reviewer = reviewer if reviewer is not None else _FakeReviewer()
    orch._session_id_default = "web-1"
    orch.last_learning_review = None
    return orch


def test_refine_reviews_a_snapshot_of_this_session_and_leaves_it_untouched():
    turns = [{"role": "user", "content": "how do I deploy"}, {"role": "assistant", "content": "run make ship"}]
    orch = _orch(turns)
    result = asyncio.run(orch.refine(focus="deployment"))
    assert result["ran"] is True
    assert orch.memory.asked == [("web-1", None)]
    history, focus = orch.reviewer.calls[0]
    assert history == "user: how do I deploy\nassistant: run make ship" and focus == "deployment"
    assert orch.memory.turns == turns
    assert orch.last_learning_review == result


def test_refine_refuses_while_another_turn_holds_the_session():
    orch = _orch([{"role": "user", "content": "x"}])

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def other_turn():
            async with orch.turn_lease("web-1") as held:
                assert held
                started.set()
                await release.wait()

        task = asyncio.create_task(other_turn())
        await started.wait()
        busy = await orch.refine()
        release.set()
        await task
        after = await orch.refine()
        return busy, after

    busy, after = asyncio.run(scenario())
    assert busy == {"ran": False, "reason": "turn_in_flight", "actions": []}
    assert orch.reviewer.calls and after["ran"] is True
    assert len(orch.reviewer.calls) == 1


def test_refine_from_inside_the_sessions_own_turn_is_not_busy():
    orch = _orch([{"role": "user", "content": "x"}])

    async def scenario():
        async with orch.turn_lease("web-1"):
            return await orch.refine()

    assert asyncio.run(scenario())["ran"] is True


def test_refine_with_no_reviewer_or_no_conversation_says_so():
    orch = _orch([], reviewer=_FakeReviewer())
    assert asyncio.run(orch.refine()) == {"ran": False, "reason": "empty_conversation", "actions": []}
    orch = _orch([{"role": "user", "content": "x"}])
    orch.reviewer = None
    assert asyncio.run(orch.refine()) == {"ran": False, "reason": "unavailable", "actions": []}


# ── the command ──────────────────────────────────────────────────────────────

def _dispatch(orch, text, admin=True):
    registry = build_default_registry()
    orch.commands = registry          # /help lists the orchestrator's own registry
    return asyncio.run(registry.dispatch(text, orch=orch, principal=Principal(channel="telegram", admin=admin)))


def test_refine_is_an_owner_command_that_reports_what_it_added():
    orch = _orch([{"role": "user", "content": "x"}], reviewer=_FakeReviewer(
        {"ran": True, "nothing": False, "actions": ["User profile updated (+1)",
                                                     "Skill 'deploy' patch proposed (pending approval)"]}))
    out = _dispatch(orch, "/refine deployment steps")
    assert out.status == "answered"
    assert orch.reviewer.calls[0][1] == "deployment steps"
    assert out.reply == ("Reviewed this conversation (focus: deployment steps):\n"
                         "- User profile updated (+1)\n"
                         "- Skill 'deploy' patch proposed (pending approval)\n"
                         "Skill changes wait for your approval in the Decision Inbox.")
    refused = _dispatch(orch, "/refine", admin=False)
    assert refused.status == "refused" and len(orch.reviewer.calls) == 1


@pytest.mark.parametrize("result,reply", [
    ({"ran": True, "nothing": True, "actions": []}, "Reviewed this conversation: nothing worth keeping."),
    ({"ran": False, "reason": "turn_in_flight", "actions": []},
     "A turn is still running in this conversation; try /refine again when it has answered."),
    ({"ran": False, "reason": "busy", "actions": []}, "A review is already running; try again in a moment."),
    ({"ran": False, "reason": "daily_budget", "actions": []},
     "Today's review budget (learning.review_daily_budget) is spent; try again tomorrow."),
    ({"ran": False, "reason": "llm_error", "actions": []},
     "The review could not run: it needs a local model, and none answered (reviews never leave this machine)."),
    ({"ran": False, "reason": "empty_conversation", "actions": []}, "There is no conversation here to review yet."),
    ({"ran": False, "reason": "unavailable", "actions": []}, "The learning reviewer is not available on this hub."),
])
def test_refine_names_why_it_did_nothing(result, reply):
    orch = _orch([{"role": "user", "content": "x"}], reviewer=_FakeReviewer(result))
    assert _dispatch(orch, "/refine").reply == reply


def test_refine_is_listed_in_help_for_the_owner_only():
    orch = _orch()
    assert "/refine [focus]" in _dispatch(orch, "/help").reply
    assert "/refine" not in _dispatch(orch, "/help", admin=False).reply


def test_the_whole_snapshot_reaches_the_prompt_not_only_the_per_turn_window():
    llm = _LLM()
    history = "user: " + "a" * 9_000 + " LAST-LINE"
    asyncio.run(_reviewer(llm).run_on_demand(history))
    assert "LAST-LINE" in llm.prompts[0]


def test_a_new_day_refills_the_budget_for_an_on_demand_review():
    llm = _LLM()
    reviewer = _reviewer(llm, **{"learning.review_daily_budget": 1})
    reviewer._day, reviewer._day_count = "2000-01-01", 1
    assert asyncio.run(reviewer.run_on_demand("user: a"))["ran"] is True
