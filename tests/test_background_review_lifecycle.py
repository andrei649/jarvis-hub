"""H403 — the per-turn background review's lifecycle around the session it reviews.

Hermes cancels its review fork the moment a new user turn arrives, attributes the fork's
usage back to the parent session, and prints a review action summary line. Nerva's review
is one strict-local structured call spawned fire-and-forget after a turn; these tests pin
the three pieces this row still lacked: a new turn on the session cancels its in-flight
review (and only that session's), the task registry never leaks a task or logs a
cancellation as a failure, the review's provider-certified usage lands on the parent
session in the cost ledger under a ``background_review`` purpose, and the action summary
reaches the owner beside the session's next reply (H674 turn notices) instead of only
the log.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from types import SimpleNamespace

import httpx
import pytest

from agents.core import cost_tracker
from agents.core import orchestrator as orch_module
from agents.core.learning.background_review import BackgroundReviewer, action_summary
from agents.core.llm.egress import llm_async_client
from agents.core.llm.tool_protocol import TokenUsage
from agents.core.llm.usage_context import report_text_usage
from agents.core.orchestrator import Orchestrator
from agents.core.turn_notices import open_turn_notices, reset_turn_notices
from agents.core.turn_usage import model_usage_scope

NOTHING = '{"nothing": true}'
ONE_FACT = '{"user_facts": ["prefers tea"], "agent_facts": [], "corrections": [], "skill_updates": []}'


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


class _Memory:
    def __init__(self):
        self.conversation = SimpleNamespace(foreign_origins=set(), sessions={})

    async def get_history(self, key, last_n=None):
        return [{"role": "user", "content": "hello"}]


def _reviewer(llm, **settings):
    values = {"learning.review_daily_budget": 20, **settings}
    return BackgroundReviewer(llm, living=_Living(), get_setting=lambda k, d=None: values.get(k, d))


def _orch(monkeypatch, reviewer, session="web-1"):
    monkeypatch.setattr("agents.core.foreign_history.status", lambda *a: SimpleNamespace(tainted=False))
    orch = Orchestrator.__new__(Orchestrator)
    orch.memory = _Memory()
    orch.checkpoints = None
    orch.cognition = SimpleNamespace(sub_enabled=lambda name: name == "review_enabled")
    orch.reviewer = reviewer
    orch._session_id_default = session
    return orch


@contextlib.contextmanager
def _on_session(sid):
    token = orch_module._active_session.set(sid)
    try:
        yield
    finally:
        orch_module._active_session.reset(token)


def _stuck():
    gate = asyncio.Event()

    async def llm(prompt):
        await gate.wait()
        return NOTHING

    return gate, llm


@pytest.fixture(autouse=True)
def _own_cost_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(cost_tracker, "_store_path", lambda: tmp_path / "cost_usage.json")
    cost_tracker.reset()
    yield
    cost_tracker.reset()


# ── cancellation on a new user turn ───────────────────────────────────────────

def test_a_new_turn_cancels_the_sessions_in_flight_review_and_leaves_no_task(monkeypatch, caplog):
    gate, llm = _stuck()
    reviewer = _reviewer(llm)
    orch = _orch(monkeypatch, reviewer)

    async def scenario():
        assert orch._spawn_background_review("hi", "hello", "web") is None
        task = orch._review_tasks["web-1"]
        await asyncio.sleep(0.05)
        assert reviewer._in_flight == 1 and reviewer._day_count == 1
        with caplog.at_level(logging.DEBUG, logger="jarvis"):
            cancelled = await orch._settle_background_review("web-1")
        return task, cancelled

    task, cancelled = asyncio.run(scenario())
    assert cancelled is True and task.cancelled()
    assert orch._review_tasks == {}
    # The pass that was cut short ran no review: it costs no budget and holds no flag.
    assert reviewer._in_flight == 0 and reviewer._day_count == 0
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_turn_on_another_session_leaves_the_review_running(monkeypatch):
    gate, llm = _stuck()
    orch = _orch(monkeypatch, _reviewer(llm))

    async def scenario():
        with _on_session("web-1"):
            orch._spawn_background_review("hi", "hello", "web")
        task = orch._review_tasks["web-1"]
        await asyncio.sleep(0)
        assert await orch._settle_background_review("web-2") is False
        assert not task.done() and orch._review_tasks == {"web-1": task}
        gate.set()
        await task
        return task

    task = asyncio.run(scenario())
    assert task.done() and not task.cancelled() and orch._review_tasks == {}


def test_a_new_review_for_the_session_replaces_the_one_in_flight(monkeypatch):
    gate, llm = _stuck()
    orch = _orch(monkeypatch, _reviewer(llm))

    async def scenario():
        orch._spawn_background_review("a", "b", "web")
        first = orch._review_tasks["web-1"]
        await asyncio.sleep(0)
        orch._spawn_background_review("c", "d", "web")
        second = orch._review_tasks["web-1"]
        with contextlib.suppress(asyncio.CancelledError):
            await first
        gate.set()
        await second
        return first, second

    first, second = asyncio.run(scenario())
    assert first is not second and first.cancelled() and second.done()
    assert orch._review_tasks == {}


def test_cancelling_a_review_does_not_swallow_the_callers_own_cancellation(monkeypatch):
    gate, llm = _stuck()
    orch = _orch(monkeypatch, _reviewer(llm))

    async def scenario():
        orch._spawn_background_review("hi", "hello", "web")
        await asyncio.sleep(0)
        settler = asyncio.create_task(orch._settle_background_review("web-1"))
        await asyncio.sleep(0)
        settler.cancel()
        with pytest.raises(asyncio.CancelledError):
            await settler

    asyncio.run(scenario())


def test_user_turns_settle_the_review_before_the_turn_is_recorded():
    for method in (Orchestrator._handle_input, Orchestrator._handle_input_stream_prepared):
        source = inspect.getsource(method)
        settle = source.index("_settle_background_review(")
        assert source.index("self._resolve_session(") < settle < source.index('add_turn(self.session_id, "user"')


# ── usage attribution to the parent session ───────────────────────────────────

async def _local_review_call(prompt):
    """A review call the way production makes it: one accepted local dispatch whose
    provider-certified counts are published to the task's usage collector."""
    client = llm_async_client("lm-studio", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": True})))
    try:
        with model_usage_scope(model="google/gemma-4-31b-a4b", route="local"):
            await client.post("http://127.0.0.1:1234/v1/chat/completions",
                              json={"model": "google/gemma-4-31b-a4b"})
            report_text_usage(TokenUsage(input_tokens=120, output_tokens=30, counts_complete=True))
    finally:
        await client.aclose()
    return ONE_FACT


def test_review_usage_is_attributed_to_the_parent_session(monkeypatch):
    reviewer = _reviewer(_local_review_call)
    orch = _orch(monkeypatch, reviewer)

    async def scenario():
        with _on_session("web-1"):
            await orch._background_review_task("hi", "hello")

    asyncio.run(scenario())
    session = cost_tracker.session_usage("web-1")
    assert session["input_tokens"] == 120 and session["output_tokens"] == 30 and session["calls"] == 1
    assert session["purposes"]["background_review"] == {
        "calls": 1, "input_tokens": 120, "output_tokens": 30, "cost_usd": 0.0}
    meter = cost_tracker.get_summary()["agents"]["background_review"]
    assert (meter["input_tokens"], meter["output_tokens"], meter["cost_usd"]) == (120, 30, 0.0)
    usage = reviewer.last_result["usage"]
    assert usage["session_id"] == "web-1" and usage["purpose"] == "background_review"
    assert (usage["input_tokens"], usage["output_tokens"]) == (120, 30)
    assert usage["model"] == "google/gemma-4-31b-a4b" and usage["usage_basis"] == "provider_complete"


def test_a_review_whose_counts_are_unknown_is_named_not_invented(monkeypatch):
    async def llm(prompt):
        with model_usage_scope(model="google/gemma-4-31b-a4b", route="local"):
            pass                    # a generation scope that sent nothing: unknown, not zero
        return NOTHING

    reviewer = _reviewer(llm)
    orch = _orch(monkeypatch, reviewer)
    asyncio.run(orch._background_review_task("hi", "hello"))
    assert cost_tracker.session_usage("web-1") is None
    assert "background_review" not in cost_tracker.get_summary()["agents"]
    assert reviewer.last_result["usage"]["usage_basis"] == "unknown"
    assert reviewer.last_result["usage"]["input_tokens"] is None


def test_the_session_ledger_sums_turns_and_reviews_and_is_bounded(monkeypatch):
    cost_tracker.record("jarvis", 100, 40, model="local", route="local", session_id="s-1", purpose="turn")
    cost_tracker.record("background_review", 50, 10, model="local", route="local",
                        session_id="s-1", purpose="background_review")
    cost_tracker.record("jarvis", 7, 3, model="local", route="local", session_id="s-1")
    session = cost_tracker.session_usage("s-1")
    assert (session["input_tokens"], session["output_tokens"], session["calls"]) == (157, 53, 3)
    assert session["purposes"]["turn"]["calls"] == 2 and session["purposes"]["background_review"]["calls"] == 1
    assert cost_tracker.session_usage("") is None and cost_tracker.session_usage("nope") is None
    monkeypatch.setattr(cost_tracker, "_MAX_SESSIONS", 2)
    cost_tracker.record("jarvis", 1, 1, model="local", route="local", session_id="s-2")
    cost_tracker.record("jarvis", 1, 1, model="local", route="local", session_id="s-3")
    assert cost_tracker.session_usage("s-1") is None          # the oldest went
    assert cost_tracker.session_usage("s-2") and cost_tracker.session_usage("s-3")
    # The ledger survives a reload the way the per-agent rollup does.
    cost_tracker._state["loaded"] = False
    cost_tracker._sessions.clear()
    assert cost_tracker.session_usage("s-3")["calls"] == 1


def test_the_turn_record_site_names_its_session():
    source = inspect.getsource(Orchestrator._record_interactions)
    assert 'purpose="turn"' in source and 'session_id=getattr(self, "session_id", None) or ""' in source


# ── the action summary reaches the owner ──────────────────────────────────────

def test_action_summary_is_one_line_or_nothing():
    assert action_summary(None) == ""
    assert action_summary({"ran": False, "reason": "llm_error", "actions": []}) == ""
    assert action_summary({"ran": True, "nothing": True, "actions": []}) == ""
    assert action_summary({"ran": True, "actions": ["User profile updated (+1)",
                                                      "Skill 'deploy' patch proposed (pending approval)"]}) == \
        "Background review: User profile updated (+1); Skill 'deploy' patch proposed (pending approval)"


def test_the_action_summary_reaches_the_owner_beside_the_sessions_next_reply(monkeypatch):
    async def llm(prompt):
        return ONE_FACT

    orch = _orch(monkeypatch, _reviewer(llm))

    async def scenario():
        await orch._background_review_task("I like tea", "noted")
        assert orch._review_notices == {"web-1": "Background review: User profile updated (+1)"}
        # No collector open (a channel without the HUD): the summary is kept for a reply
        # that can show it, not dropped.
        await orch._settle_background_review("web-1")
        assert orch._review_notices == {"web-1": "Background review: User profile updated (+1)"}
        sink, token = open_turn_notices()
        try:
            await orch._settle_background_review("web-1")
            await orch._settle_background_review("web-1")            # shown once
        finally:
            reset_turn_notices(token)
        return sink

    sink = asyncio.run(scenario())
    assert sink == [{"code": "background_review", "text": "Background review: User profile updated (+1)"}]
    assert orch._review_notices == {}


def test_a_review_that_found_nothing_leaves_no_notice(monkeypatch):
    async def llm(prompt):
        return NOTHING

    orch = _orch(monkeypatch, _reviewer(llm))
    asyncio.run(orch._background_review_task("hi", "hello"))
    assert not orch.__dict__.get("_review_notices")


def test_pending_summaries_are_bounded_per_process(monkeypatch):
    async def llm(prompt):
        return ONE_FACT

    orch = _orch(monkeypatch, _reviewer(llm, **{"learning.review_daily_budget": 1000}))
    monkeypatch.setattr(orch_module, "_REVIEW_NOTICES_LIMIT", 3)

    async def scenario():
        for n in range(5):
            with _on_session(f"s-{n}"):
                await orch._background_review_task("hi", "hello")

    asyncio.run(scenario())
    assert list(orch._review_notices) == ["s-2", "s-3", "s-4"]


def test_the_orchestrator_declares_the_registry_and_the_notices():
    source = inspect.getsource(Orchestrator.__init__)
    assert "self._review_tasks: dict[str, asyncio.Task] = {}" in source
    assert "self._review_notices: dict[str, str] = {}" in source
