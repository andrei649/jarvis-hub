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
import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from agents.core import cost_tracker
from agents.core import orchestrator as orch_module
from agents.core.commands import Principal
from agents.core.learning.background_review import BackgroundReviewer, action_summary
from agents.core.llm.egress import llm_async_client
from agents.core.llm.tool_protocol import TokenUsage
from agents.core.llm.usage_context import report_text_usage
from agents.core.orchestrator import Orchestrator, bind_turn_principal, reset_turn_principal
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
def _owner_principal():
    """The review summary is the owner's: these tests run as the admin unless one says
    otherwise (``_as``)."""
    token = bind_turn_principal(Principal(channel="telegram", sender="1", admin=True))
    yield
    reset_turn_principal(token)


@contextlib.contextmanager
def _as(*, admin, channel="telegram", sender="999"):
    token = bind_turn_principal(Principal(channel=channel, sender=sender, admin=admin, chat="-100group"))
    try:
        yield
    finally:
        reset_turn_principal(token)


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


def test_the_turn_record_site_names_its_session_under_the_reviews_key():
    source = inspect.getsource(Orchestrator._record_interactions)
    assert 'purpose="turn"' in source
    assert 'session_id=self._review_key(getattr(self, "session_id", None))' in source
    assert Orchestrator._review_key(None) == Orchestrator._review_key("") == "default"


def test_a_stored_session_row_missing_counters_loads_whole(monkeypatch, tmp_path):
    path = tmp_path / "cost_usage.json"
    path.write_text(json.dumps({"agents": {}, "daily": {}, "sessions": {
        "old": {"purposes": {"turn": {"calls": "3"}}, "calls": 1},
        "bad": [], "worse": {"purposes": 7}}}), encoding="utf-8")
    monkeypatch.setattr(cost_tracker, "_store_path", lambda: path)
    cost_tracker._state["loaded"] = False
    cost_tracker._sessions.clear()
    assert cost_tracker.session_usage("old") == {
        "calls": 1, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "updated_at": 0.0,
        "purposes": {"turn": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}}}
    assert cost_tracker.session_usage("bad") is None and cost_tracker.session_usage("worse") is None
    cost_tracker.record("jarvis", 1, 1, model="local", route="local", session_id="old")
    assert cost_tracker.session_usage("old")["calls"] == 2


# ── one refund, not two ───────────────────────────────────────────────────────

def test_a_refine_that_times_out_is_refunded_once_above_zero(monkeypatch):
    from agents.core.learning import background_review as br
    monkeypatch.setattr(br, "REFINE_TIMEOUT_S", 0.2)
    gate, llm = _stuck()
    reviewer = _reviewer(llm, **{"learning.review_daily_budget": 5})
    reviewer.should_run()
    reviewer._day_count = 2                                   # two real reviews already had
    assert asyncio.run(reviewer.run_on_demand("user: x"))["reason"] == "llm_timeout"
    assert reviewer.status()["reviews_today"] == 2


def test_a_cancelled_per_turn_review_is_refunded_once_above_zero(monkeypatch):
    gate, llm = _stuck()
    reviewer = _reviewer(llm, **{"learning.review_daily_budget": 5})
    reviewer.should_run()
    reviewer._day_count = 2
    orch = _orch(monkeypatch, reviewer)

    async def scenario():
        orch._spawn_background_review("hi", "hello", "web")
        await asyncio.sleep(0.05)
        assert reviewer.status()["reviews_today"] == 3            # the pass spent its unit
        assert await orch._settle_background_review("web-1") is True

    asyncio.run(scenario())
    assert reviewer.status()["reviews_today"] == 2 and reviewer._in_flight == 0


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


def test_a_channel_turn_carries_the_summary_in_its_reply(monkeypatch):
    """A Telegram/Slack/voice owner has no HUD: the channel turn collects the notices
    the way /chat does and the reply carries them as system lines."""
    async def llm(prompt):
        return ONE_FACT

    orch = _orch(monkeypatch, _reviewer(llm))
    seen = []

    async def handle_input(text, channel):
        # stands for the real prologue, whose order the source test above pins
        await orch._settle_background_review(orch.session_id)
        seen.append((text, channel))
        return "Noted."

    orch.handle_input = handle_input

    async def scenario():
        await orch._background_review_task("I like tea", "noted")
        return await orch._channel_turn("thanks", "telegram", observe_only=False)

    reply = asyncio.run(scenario())
    assert seen == [("thanks", "telegram")]
    assert reply == "Noted.\n\nℹ Background review: User profile updated (+1)"
    assert orch._review_notices == {}
    assert asyncio.run(orch._channel_turn("again", "telegram", observe_only=False)) == "Noted."


def test_channel_notices_leave_silent_and_typed_replies_alone():
    from agents.core.channels.ephemeral import EphemeralReply
    notes = [{"code": "x", "text": "a note"}, {"code": "y", "text": " "}, "junk"]
    assert Orchestrator._with_channel_notices("", notes) == ""
    assert Orchestrator._with_channel_notices(None, notes) is None
    typed = EphemeralReply("busy")
    assert Orchestrator._with_channel_notices(typed, notes) is typed
    assert Orchestrator._with_channel_notices("ok \n", notes) == "ok\n\nℹ a note"
    assert Orchestrator._with_channel_notices("ok", []) == "ok"


def test_a_summary_from_another_conversation_reaches_the_owners_next_turn(monkeypatch):
    async def llm(prompt):
        return ONE_FACT

    orch = _orch(monkeypatch, _reviewer(llm))

    async def scenario():
        with _on_session("s-old"):                 # the review ran after that chat's last reply
            await orch._background_review_task("I like tea", "noted")
        await orch._background_review_task("I like tea", "noted")      # and one on web-1
        sink, token = open_turn_notices()
        try:
            await orch._settle_background_review("web-1")
        finally:
            reset_turn_notices(token)
        return sink

    sink = asyncio.run(scenario())
    assert sink == [{"code": "background_review", "text":
                     "Background review: User profile updated (+1)\n"
                     "Background review: User profile updated (+1) (conversation s-old)"}]
    assert orch._review_notices == {}


def test_one_reply_shows_a_few_summaries_and_keeps_the_rest(monkeypatch):
    async def llm(prompt):
        return ONE_FACT

    orch = _orch(monkeypatch, _reviewer(llm, **{"learning.review_daily_budget": 1000}))
    monkeypatch.setattr(orch_module, "_REVIEW_NOTICE_LINES", 2)

    async def scenario():
        for n in range(4):
            with _on_session(f"s-{n}"):
                await orch._background_review_task("hi", "hello")
        sink, token = open_turn_notices()
        try:
            await orch._settle_background_review("s-3")
        finally:
            reset_turn_notices(token)
        return sink

    sink = asyncio.run(scenario())
    assert sink[0]["text"].splitlines() == ["Background review: User profile updated (+1)",
                                            "Background review: User profile updated (+1) (conversation s-0)"]
    assert list(orch._review_notices) == ["s-1", "s-2"]


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


# ── the summary is the owner's: no leak to anyone else ────────────────────────

OWNER_LINE = "Background review: User profile updated (+1)"


def _owner_review_pending(orch, sessions=("owner-private-session",)):
    async def scenario():
        for sid in sessions:
            with _on_session(sid):
                await orch._background_review_task("my secret", "noted")

    asyncio.run(scenario())
    assert set(orch._review_notices) == set(sessions)


def _stranger_orch(monkeypatch):
    async def llm(prompt):
        return ONE_FACT

    orch = _orch(monkeypatch, _reviewer(llm, **{"learning.review_daily_budget": 1000}))

    async def handle_input(text, channel):
        await orch._settle_background_review(orch.session_id)
        return "hi"

    orch.handle_input = handle_input
    return orch


def test_regression_a_strangers_channel_turn_gets_nothing_of_the_owners_reviews(monkeypatch):
    """The reproduced leak: a non-admin Telegram sender in a group got the owner's
    summary and the owner's session id appended to the reply."""
    orch = _stranger_orch(monkeypatch)
    _owner_review_pending(orch)
    before = dict(orch._review_notices)

    async def scenario():
        with _as(admin=False), _on_session("stranger-session"):
            return await orch._channel_turn("hello", "telegram", observe_only=False)

    reply = asyncio.run(scenario())
    assert reply == "hi" and "owner-private-session" not in reply and "ℹ" not in reply
    assert orch._review_notices == before                  # kept, for the owner


def test_a_stranger_sharing_the_owners_session_gets_its_summary_neither(monkeypatch):
    """memory.cross_channel_sessions: one session id for everyone on the box."""
    orch = _stranger_orch(monkeypatch)
    _owner_review_pending(orch, ("shared",))

    async def scenario():
        with _as(admin=False), _on_session("shared"):
            return await orch._channel_turn("hello", "slack", observe_only=False)

    assert asyncio.run(scenario()) == "hi"
    assert orch._review_notices == {"shared": OWNER_LINE}


def test_a_non_admin_web_turn_gets_no_lines_and_consumes_none(monkeypatch):
    """agents/web.py binds the token's principal and opens the collector around the
    turn: the orchestrator's gate is what the HUD path rests on."""
    orch = _stranger_orch(monkeypatch)
    _owner_review_pending(orch, ("owner-private-session", "other"))

    async def web_turn(admin, sid):
        sink, token = open_turn_notices()
        try:
            with _as(admin=admin, channel="web", sender=None), _on_session(sid):
                await orch._settle_background_review(sid)
        finally:
            reset_turn_notices(token)
        return sink

    assert asyncio.run(web_turn(False, "other")) == []
    assert asyncio.run(web_turn(False, "somebody-else")) == []
    assert set(orch._review_notices) == {"owner-private-session", "other"}
    sink = asyncio.run(web_turn(True, "owner-private-session"))        # the owner still gets them
    assert sink[0]["text"].splitlines() == [OWNER_LINE, OWNER_LINE + " (conversation other)"]
    assert orch._review_notices == {}


def test_the_owners_next_channel_turn_still_gets_what_a_stranger_could_not(monkeypatch):
    orch = _stranger_orch(monkeypatch)
    _owner_review_pending(orch)

    async def turn(admin, sid):
        with _as(admin=admin), _on_session(sid):
            return await orch._channel_turn("hello", "telegram", observe_only=False)

    assert asyncio.run(turn(False, "stranger-session")) == "hi"
    owner = asyncio.run(turn(True, "owner-session"))
    assert owner == f"hi\n\nℹ {OWNER_LINE} (conversation owner-private-session)"
    assert orch._review_notices == {}


def test_a_strangers_own_review_is_not_queued_for_the_owner(monkeypatch):
    async def llm(prompt):
        return ONE_FACT

    orch = _orch(monkeypatch, _reviewer(llm))

    async def scenario():
        with _as(admin=False), _on_session("stranger-session"):
            await orch._background_review_task("hi", "hello")

    asyncio.run(scenario())
    assert not orch.__dict__.get("_review_notices")


@pytest.mark.parametrize("channel", ["voice", "webhook", "gateway", "email", "mcp"])
def test_voice_and_machine_replies_carry_no_footer_and_the_summary_waits(monkeypatch, channel):
    orch = _stranger_orch(monkeypatch)
    _owner_review_pending(orch, ("owner-private-session",))

    async def scenario():
        with _on_session("owner-session"):                   # the owner, admin
            return await orch._channel_turn("hello", channel, observe_only=False)

    assert asyncio.run(scenario()) == "hi"
    assert orch._review_notices == {"owner-private-session": OWNER_LINE}


def test_a_streamed_draft_finishes_with_the_notice_bearing_owner_reply(monkeypatch):
    class Draft:
        def __init__(self):
            self.pushed, self.final = [], None

        async def push(self, token):
            self.pushed.append(token)

        async def finish(self, text):
            self.final = text

    async def llm(prompt):
        return ONE_FACT

    orch = _orch(monkeypatch, _reviewer(llm))
    _owner_review_pending(orch, ("old",))
    draft = Draft()

    async def handle_input_stream(text, channel, on_token=None):
        await orch._settle_background_review(orch.session_id)
        await on_token("Hel")
        await on_token("lo")
        return "Hello"

    orch.handle_input_stream = handle_input_stream

    async def scenario():
        with _on_session("web-1"):
            reply = await orch._channel_turn("hi", "telegram", observe_only=False, draft=draft)
        await draft.finish(reply)               # what the channel router does with the response
        return reply

    reply = asyncio.run(scenario())
    assert draft.pushed == ["Hel", "lo"]
    assert draft.final == reply == f"Hello\n\nℹ {OWNER_LINE} (conversation old)"
