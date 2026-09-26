"""H677 — warm up before accepting work; every shutdown wait has a short explicit budget.

Hermes waits for its model before it opens, and every step of its shutdown is bounded.
Nerva fired its warm-up and forgot it (a message right after boot raced the cold load),
awaited each channel's stop, each cancelled task and each close with no bound (one wedged
step could use up the service manager's stop budget), and its Telegram poll loop awaited
every turn before reading the next update (one chat's slow answer held every other chat).
"""
from __future__ import annotations

import asyncio
import contextlib
import gc
import inspect
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from agents.core import lifecycle_budget as lb  # noqa: E402
from agents.core.channels.chat_lanes import ChatLanes  # noqa: E402
from agents.core.lifecycle_budget import (  # noqa: E402
    WarmupState,
    bounded,
    gate_warmup,
    wait_task,
    warmup_timeout,
)


@pytest.fixture(autouse=True)
def _fresh_warmup():
    lb.WARMUP.reset()
    yield
    lb.WARMUP.reset()


# ── the setting ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "seconds"), [
    (20, 20.0), ("7.5", 7.5), (0, 0.0), (-5, 0.0), (1e9, 300.0), ("nan", 20.0), ("inf", 20.0),
    (True, 20.0), (None, 20.0), ("abc", 20.0), ([5], 20.0),
])
def test_warmup_timeout_reads_the_setting(value, seconds):
    assert warmup_timeout(value) == seconds


def test_the_setting_is_declared():
    from agents.core import settings_db

    (row,) = [r for r in settings_db.DEFAULTS
              if r["category"] == "system" and r["key"] == "startup_warmup_timeout_seconds"]
    assert row["value"] == 20 and row["kind"] == "number"
    assert lb.WARMUP_SETTING == "system.startup_warmup_timeout_seconds"


# ── the warm-up gate ─────────────────────────────────────────────────────────


async def _warm(delay: float, result=True):
    await asyncio.sleep(delay)
    if isinstance(result, Exception):
        raise result
    return result


async def test_no_warmup_means_no_wait_and_off():
    assert (await gate_warmup(None, 20))["phase"] == "off"
    await gate_warmup(asyncio.ensure_future(_warm(0)), 2)
    assert (await gate_warmup(None, 20)) == {"phase": "off", "warming": False, "gate_expired": False,
                                              "seconds": None}, "a boot with none forgets the last one"


async def test_the_gate_waits_for_a_warmup_that_finishes_in_time():
    task = asyncio.ensure_future(_warm(0.05))
    started = time.monotonic()
    snap = await gate_warmup(task, 5.0)
    assert time.monotonic() - started < 2
    assert snap["phase"] == "ready" and snap["warming"] is False and snap["gate_expired"] is False
    assert snap["seconds"] >= 0.04


async def test_the_gate_opens_after_its_budget_and_the_warmup_goes_on(caplog):
    task = asyncio.ensure_future(_warm(0.6))
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
        snap = await gate_warmup(task, 0.1)
    assert time.monotonic() - started < 0.5, "never past its budget"
    assert snap["phase"] == "warming" and snap["warming"] is True and snap["gate_expired"] is True
    assert not task.cancelled(), "the gate expiring never cancels the warm-up"
    assert any(lb.WARMUP_SETTING in r.getMessage() for r in caplog.records)
    await task
    assert lb.WARMUP.snapshot()["phase"] == "ready" and lb.WARMUP.warming is False


async def test_a_zero_budget_does_not_wait(caplog):
    task = asyncio.ensure_future(_warm(0.3))
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
        snap = await gate_warmup(task, 0)
    assert time.monotonic() - started < 0.1 and snap["phase"] == "warming"
    assert snap["gate_expired"] is False, "0 means the owner chose not to wait: nothing expired"
    assert not caplog.records
    await task


async def test_a_warmup_that_did_not_warm_is_cold_and_one_that_raised_failed(caplog):
    with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
        assert (await gate_warmup(asyncio.ensure_future(_warm(0.01, False)), 2))["phase"] == "cold"
    assert not caplog.records, "cold is not a failure"
    with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
        snap = await gate_warmup(asyncio.ensure_future(_warm(0.01, RuntimeError("no model"))), 2)
    assert snap["phase"] == "failed"
    assert any("warm-up failed" in r.getMessage() for r in caplog.records)
    # A backend whose warm_up answers nothing still loaded the model; a cancelled one did not.
    assert (await gate_warmup(asyncio.ensure_future(_warm(0.01, None)), 2))["phase"] == "ready"
    cancelled = asyncio.ensure_future(_warm(5))
    cancelled.cancel()
    await asyncio.wait({cancelled})
    assert (await gate_warmup(cancelled, 2))["phase"] == "failed"
    done = asyncio.ensure_future(_warm(0, True))
    await done
    assert (await gate_warmup(done, 2))["phase"] == "ready", "an already-finished warm-up"


async def test_a_later_warmup_owns_the_state():
    state = WarmupState()
    first = asyncio.ensure_future(_warm(0.2, RuntimeError("old")))
    state.track(first)
    second = asyncio.ensure_future(_warm(0.01))
    state.track(second)
    await second
    await asyncio.wait({first})
    assert state.phase == "ready"


async def test_the_duration_stops_when_the_warmup_ends_and_restarts_with_the_next(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(lb.time, "time", lambda: clock[0])
    state = WarmupState()
    first = asyncio.ensure_future(_warm(0))
    state.track(first)
    await first
    await asyncio.sleep(0)
    clock[0] = 1004.0
    assert state.snapshot()["seconds"] == 0.0, "a finished warm-up's time is frozen"
    running = asyncio.ensure_future(_warm(0.05))
    state.track(running)
    clock[0] = 1006.5
    assert state.snapshot() == {"phase": "warming", "warming": True, "gate_expired": False, "seconds": 2.5}
    await running


def test_the_hub_gates_before_any_channel_opens():
    from agents import web

    life = inspect.getsource(web.lifespan)
    assert life.index("await orch.load_agents()") < life.index("await gate_warmup(") \
        < life.index("await orch.start_channels()")
    assert "warmup_timeout(get_value(*WARMUP_SETTING.split" in life


# ── what the hub says while warming ──────────────────────────────────────────


def test_status_and_readyz_report_the_warmup(monkeypatch):
    from agents import web

    client = TestClient(web.app)
    assert client.get("/api/status").json()["warmup"]["phase"] == "off"
    lb.WARMUP.track(asyncio.Future(loop=asyncio.new_event_loop()))
    body = client.get("/api/status").json()["warmup"]
    assert body["phase"] == "warming" and body["warming"] is True
    from agents.core.routers.ops import readiness_snapshot

    assert readiness_snapshot()["warmup"]["warming"] is True


def test_a_turn_served_while_warming_is_marked(monkeypatch):
    from agents import web

    mock = MagicMock()
    mock.handle_input = AsyncMock(return_value="Salut!")
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    assert client.post("/chat", json={"message": "hi"}).json()["warming"] is False
    lb.WARMUP.track(asyncio.Future(loop=asyncio.new_event_loop()))
    reply = client.post("/chat", json={"message": "hi"}).json()
    assert reply == {"reply": "Salut!", "pending_approvals": [], "warming": True, "notices": []}


def test_a_streamed_turn_served_while_warming_is_marked(monkeypatch):
    from agents import web

    mock = MagicMock()
    mock.agents = {}
    mock.observer = None

    async def stream(message, channel, on_token, agent_override=None, **kwargs):
        await on_token("ok")
        return "ok"

    mock.handle_input_stream = stream
    monkeypatch.setattr(web, "orch", mock)
    lb.WARMUP.track(asyncio.Future(loop=asyncio.new_event_loop()))
    body = TestClient(web.app).post("/chat/stream", json={"message": "hi"}).text
    ends = [json.loads(c[6:]) for c in body.split("\n\n") if c.startswith("data: ")
            and json.loads(c[6:]).get("type") == "end"]
    assert ends and ends[-1]["warming"] is True


async def test_every_end_event_carries_the_mark_the_failed_one_too():
    from agents import web

    class Fails:
        async def handle_input_stream(self, message, channel, on_token, agent_override=None):
            raise RuntimeError("boom")

    class Works:
        async def handle_input_stream(self, message, channel, on_token, agent_override=None):
            return "ok"

    async def end(orch):
        chunks = [c async for c in web._chat_event_stream(orch, "hi", "jarvis", None)]
        return [json.loads(c[6:]) for c in chunks if c.startswith("data: ")][-1]

    lb.WARMUP.track(asyncio.get_running_loop().create_future())
    assert (await end(Fails()))["warming"] is True, "a client never branches on the failure end event"
    lb.WARMUP.reset()
    assert (await end(Works()))["warming"] is False


async def test_a_channel_turn_while_warming_is_logged(caplog):
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.handle_input = AsyncMock(return_value="ok")
    lb.WARMUP.track(asyncio.get_running_loop().create_future())
    with caplog.at_level(logging.INFO, logger="jarvis.orchestrator"):
        assert await orch._channel_turn("hi", "telegram", observe_only=False) == "ok"
    assert any("telegram turn served while the local model is still warming up" in r.getMessage()
               for r in caplog.records)


# ── bounded shutdown steps ───────────────────────────────────────────────────


async def _hang():
    await asyncio.sleep(3600)


async def _stubborn():
    """A step that swallows its first cancellation and carries on (a second one — the
    abandonment, or the test loop's teardown — ends it)."""
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.sleep(3600)
    await asyncio.sleep(3600)


async def test_bounded_runs_a_quick_step():
    ran = []

    async def step():
        ran.append(1)

    assert await bounded(step(), 1.0, "quick") is True and ran == [1]


async def test_bounded_names_and_leaves_a_hung_step(caplog):
    for step in (_hang(), _stubborn()):
        started = time.monotonic()
        with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
            assert await bounded(step, 0.1, "the widget close") is False
        assert time.monotonic() - started < 0.5
    assert any("shutdown: the widget close did not finish within 0.1s" in r.getMessage() for r in caplog.records)


async def test_an_abandoned_step_is_cancelled_and_its_late_error_is_not_left_unretrieved():
    seen = []

    async def step():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            seen.append("cancelled")
            raise RuntimeError("late failure on the way out") from None

    loop = asyncio.get_running_loop()
    reports = []
    loop.set_exception_handler(lambda _loop, context: reports.append(context.get("message", "")))
    try:
        assert await bounded(step(), 0.05, "the widget close") is False
        for _ in range(3):
            await asyncio.sleep(0)
        gc.collect()
    finally:
        loop.set_exception_handler(None)
    assert seen == ["cancelled"], "abandoned means cancelled, not left running"
    assert not [m for m in reports if "never retrieved" in m], reports


async def test_a_step_that_was_cancelled_did_not_finish():
    async def gives_up():
        raise asyncio.CancelledError

    assert await bounded(gives_up(), 1.0, "the widget close") is False


async def test_bounded_reports_a_failing_step_without_raising(caplog):
    async def boom():
        raise OSError("disk gone")

    with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
        assert await bounded(boom(), 1.0, "checkpoint flush") is False
    assert any("checkpoint flush failed: OSError: disk gone" in r.getMessage() for r in caplog.records)


async def test_wait_task_cancels_and_waits_a_bounded_time(caplog):
    quick = asyncio.ensure_future(_hang())
    await asyncio.sleep(0)
    assert await wait_task(quick, 1.0, "watcher") is True and quick.cancelled()
    stubborn = asyncio.ensure_future(_stubborn())
    await asyncio.sleep(0)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
        assert await wait_task(stubborn, 0.1, "the learning loop") is False
    assert time.monotonic() - started < 0.5
    assert any("the learning loop did not stop within 0.1s" in r.getMessage() for r in caplog.records)
    stubborn.cancel()


async def test_wait_task_reports_a_task_that_fails_on_its_way_out(caplog):
    async def cleanup_fails():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise OSError("flush failed") from None

    task = asyncio.ensure_future(cleanup_fails())
    await asyncio.sleep(0)
    with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
        assert await wait_task(task, 1.0, "_settings_watcher_task") is True
    assert any("Error stopping _settings_watcher_task: flush failed" in r.getMessage() for r in caplog.records)


async def test_wait_task_reports_a_task_that_had_failed(caplog):
    async def fail():
        raise ValueError("bad state")

    failed = asyncio.ensure_future(fail())
    await asyncio.wait({failed})
    with caplog.at_level(logging.WARNING, logger="jarvis.lifecycle"):
        assert await wait_task(failed, 1.0, "_autonomy_task") is True
    assert any("Error stopping _autonomy_task: bad state" in r.getMessage() for r in caplog.records)


async def test_one_hung_channel_does_not_hold_the_others(monkeypatch):
    from agents.core.channels.manager import ChannelManager

    monkeypatch.setattr(lb, "CHANNEL_STOP_BUDGET", 0.1)
    stopped = []

    def channel(name, hang):
        async def stop():
            if hang:
                await _stubborn()
            stopped.append(name)
        return SimpleNamespace(stop=stop)

    manager = ChannelManager.__new__(ChannelManager)
    manager.channels = {"telegram": channel("telegram", True), "voice": channel("voice", False),
                        "discord": channel("discord", False)}
    started = time.monotonic()
    await manager.stop_all()
    assert time.monotonic() - started < 0.6
    assert stopped == ["voice", "discord"]


async def test_a_stubborn_background_task_does_not_hold_stop_channels(monkeypatch):
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setattr(lb, "TASK_CANCEL_BUDGET", 0.1)
    orch = Orchestrator.__new__(Orchestrator)
    orch._learning_task = asyncio.ensure_future(_stubborn())
    await asyncio.sleep(0)
    started = time.monotonic()
    await orch._cancel_task("_learning_task")
    assert time.monotonic() - started < 0.5 and orch._learning_task is None
    await orch._cancel_task("_learning_task")   # already gone: nothing to do


async def test_a_hung_close_step_does_not_stop_the_rest_of_aclose(monkeypatch):
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setattr(lb, "CLOSE_STEP_BUDGET", 0.1)
    monkeypatch.setattr(lb, "TASK_CANCEL_BUDGET", 0.1)
    closed = []

    async def note(name):
        closed.append(name)

    orch = Orchestrator.__new__(Orchestrator)
    orch._flush_checkpoint = _stubborn
    orch._warmup_task = asyncio.ensure_future(_stubborn())
    orch.llm_router = SimpleNamespace(aclose=_hang)
    orch.ollama = SimpleNamespace(aclose=lambda: note("ollama"))
    orch.mcp = SimpleNamespace(close_all=lambda: note("mcp"))
    orch.channel_manager = SimpleNamespace(channels={"telegram": SimpleNamespace(aclose=_hang),
                                                     "slack": SimpleNamespace(aclose=lambda: note("slack"))})
    started = time.monotonic()
    await orch.aclose()
    assert time.monotonic() - started < 2.0
    assert {"ollama", "mcp", "slack"} <= set(closed)
    orch._warmup_task.cancel()


async def test_aclose_waits_for_cancelled_cache_tasks_and_stops_the_warmup():
    from agents.core.orchestrator import Orchestrator

    cleaned = []

    async def cache_task():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(0.01)          # its own cleanup, which aclose waits for
            cleaned.append("cache")
            raise

    orch = Orchestrator.__new__(Orchestrator)
    orch._flush_checkpoint = AsyncMock()
    orch._cache_tasks = {asyncio.ensure_future(cache_task())}
    orch._warmup_task = asyncio.ensure_future(_hang())
    orch.channel_manager = SimpleNamespace(channels={})
    await asyncio.sleep(0)
    await orch.aclose()
    assert cleaned == ["cache"] and orch._cache_tasks == set()
    assert orch._warmup_task.cancelled(), "a warm-up still loading at stop is cancelled"


def test_the_budgets_are_short_and_nest():
    from agents.core.channels import telegram as tg

    # Telegram's lane drain runs inside its channel stop, so it must fit in that budget.
    assert tg.LANE_DRAIN_BUDGET < lb.CHANNEL_STOP_BUDGET <= 5
    assert lb.TASK_CANCEL_BUDGET <= 2 and lb.CLOSE_STEP_BUDGET <= 5


def test_every_teardown_wait_is_bounded_in_the_source():
    from agents.core import orchestrator

    stop = inspect.getsource(orchestrator.Orchestrator.stop_channels)
    close = inspect.getsource(orchestrator.Orchestrator.aclose)
    for bare in ("await self.plugin_manager.close_all()", "await stop_watcher()", "await router.aclose()",
                 "await close_all()", "await ollama_close()", "await cache_close()", "await closer()",
                 "await self._flush_checkpoint()", "await task\n"):
        assert bare not in stop and bare not in close, bare


# ── chat lanes ───────────────────────────────────────────────────────────────


async def test_a_chats_turns_run_in_order_and_other_chats_do_not_wait():
    lanes = ChatLanes()
    log = []
    gate = asyncio.Event()

    async def turn(name, wait=None):
        log.append(f"start {name}")
        if wait is not None:
            await wait.wait()
        log.append(f"end {name}")

    lanes.submit("A", lambda: turn("a1", gate))
    lanes.submit("A", lambda: turn("a2"))
    lanes.submit("B", lambda: turn("b1"))
    await asyncio.sleep(0.05)
    assert "end b1" in log, "chat B was not held behind chat A's slow turn"
    assert "start a2" not in log, "chat A's second turn waits for its first"
    gate.set()
    assert await lanes.drain(1.0) is True
    assert log.index("end a1") < log.index("start a2")
    assert lanes.busy == 0


async def test_a_lane_keeps_its_order_after_an_earlier_turn_ends():
    lanes = ChatLanes()
    log = []
    slow = asyncio.Event()

    async def turn(name, wait=None):
        log.append(f"start {name}")
        if wait is not None:
            await wait.wait()
        log.append(f"end {name}")

    lanes.submit("A", lambda: turn("a1"))
    lanes.submit("A", lambda: turn("a2", slow))
    lanes.submit("B", lambda: turn("b1"))
    lanes.submit("B", lambda: turn("b2"))
    await asyncio.sleep(0.02)                     # a1 ended; a2 is the lane's tail and running
    lanes.submit("A", lambda: turn("a3"))
    await asyncio.sleep(0.02)
    assert "start a3" not in log, "a3 waits for a2, the turn before it"
    assert lanes.busy == 1, "busy counts lanes with work (A), not turns (a2, a3)"
    slow.set()
    assert await lanes.drain(1.0) is True
    assert log.index("end a2") < log.index("start a3")
    assert lanes.busy == 0 and not lanes._live, "a finished turn is not kept"


async def test_a_zero_limit_still_runs_turns():
    lanes = ChatLanes(max_active=0)
    ran = []

    async def turn():
        ran.append(1)

    lanes.submit(1, turn)
    assert await lanes.drain(1.0) is True and ran == [1]


async def test_a_failed_turn_does_not_block_its_lane(caplog):
    lanes = ChatLanes(name="telegram")
    ran = []

    async def boom():
        raise RuntimeError("model down")

    async def after():
        ran.append("after")

    with caplog.at_level(logging.WARNING, logger="jarvis.channels.lanes"):
        lanes.submit(1, boom)
        lanes.submit(1, after)
        await lanes.drain(1.0)
    assert ran == ["after"]
    assert any("telegram: a turn failed in its chat lane" in r.getMessage() for r in caplog.records)


async def test_lanes_bound_how_many_turns_run_at_once():
    lanes = ChatLanes(max_active=2)
    running, peak = 0, 0

    async def turn():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1

    for chat in range(6):
        lanes.submit(chat, turn)
    await lanes.drain(2.0)
    assert peak == 2


async def test_drain_is_bounded_and_names_what_it_left(caplog):
    lanes = ChatLanes(name="telegram")
    lanes.submit(1, _hang)
    lanes.submit(1, _hang)       # queued behind the first, in the same lane
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="jarvis.channels.lanes"):
        assert await lanes.drain(0.1) is False
    assert time.monotonic() - started < 0.5
    assert any("2 chat lane(s) still running after 0.1s" in r.getMessage() for r in caplog.records)
    await asyncio.sleep(0.01)
    assert lanes.busy == 0 and not lanes._live, "what drain abandons is cancelled, not left running"
    assert await ChatLanes().drain(0.1) is True


async def test_settle_waits_for_everything_queued():
    lanes = ChatLanes()
    done = []

    async def turn(n):
        await asyncio.sleep(0.02 * n)
        done.append(n)

    for n in (3, 1, 2):
        lanes.submit(n, lambda n=n: turn(n))
    await lanes.settle()
    assert sorted(done) == [1, 2, 3]
    await ChatLanes().settle()


async def test_telegram_reads_the_next_update_while_a_chat_is_answered(monkeypatch):
    """The regression: the poll loop awaited every turn, so chat B's message waited for
    chat A's whole answer."""
    from agents.core.channels import telegram as tg

    channel = tg.TelegramChannel("t")
    channel._lanes = ChatLanes(name="telegram")
    started, finished = [], []
    slow = asyncio.Event()

    async def receive(text, chat_id=None, sender=None, **kwargs):
        started.append(chat_id)
        if chat_id == 1:
            await slow.wait()
        finished.append(chat_id)

    channel.receive = receive
    await channel._deliver_turn(1, 10, "a long question")
    await channel._deliver_turn(2, 20, "a quick one")
    await asyncio.sleep(0.05)
    assert finished == [2] and started == [1, 2]
    slow.set()
    await channel._lanes.drain(1.0)
    assert finished == [2, 1]


async def test_a_voice_note_read_while_its_chat_is_busy_marks_its_own_reply(monkeypatch):
    """The voice mark ("answer speech with speech") is set when the note is read. With
    lanes the chat's previous, typed, turn can still be running then: it must not take
    the mark (and be spoken), and the voice note's own reply must keep it."""
    from agents.core.channels import telegram as tg
    from agents.core.channels.inbound_media import KIND_VOICE
    from agents.core.channels.inbound_voice import Transcript

    channel = tg.TelegramChannel("t")
    channel._lanes = ChatLanes(name="telegram")
    channel.send_action = AsyncMock()
    monkeypatch.setattr(channel, "_echo_transcripts", lambda: False)
    monkeypatch.setattr(channel, "_read_voice", AsyncMock(return_value=Transcript(True, text="what time is it")))
    spoken, first = {}, asyncio.Event()

    async def receive(text, chat_id=None, sender=None, **kwargs):
        if "typed" in text:
            await first.wait()
        spoken[text] = chat_id in channel._voice_turns      # what _after_reply reads

    channel.receive = receive
    await channel._deliver_turn(1, 10, "a typed question")
    await asyncio.sleep(0.01)                               # the typed turn is running
    turn, note = await channel._read_attachment(SimpleNamespace(readable=True, kind=KIND_VOICE), "", 1)
    assert turn and not note
    await channel._deliver_turn(1, 10, turn)
    first.set()
    assert await channel._lanes.drain(1.0) is True
    await channel._deliver_turn(1, 10, "then a typed one")
    assert await channel._lanes.drain(1.0) is True
    assert spoken == {"a typed question": False, turn: True, "then a typed one": False}
    assert channel._voice_turns == set() and channel._voice_pending == set()


def _telegram(monkeypatch, on_turn):
    from agents.core.channels import telegram as tg

    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")          # each message its own turn at once

    async def handler(text, channel="telegram", **kwargs):
        await on_turn(text, kwargs.get("chat_id"))
        return "ok"

    channel = tg.TelegramChannel("t", handler=handler)
    channel._bot_id, channel._bot_username = 999, "nerva_bot"
    channel.send = AsyncMock(return_value=True)
    return channel


async def _poll(channel, batches):
    ids = iter(range(1, 100))

    async def fake_updates(timeout=25):
        if batches:
            delay, batch = batches.pop(0)
            await asyncio.sleep(delay)
            return [dict(u, update_id=next(ids)) for u in batch]
        channel._running = False
        return []

    channel._get_updates = fake_updates
    channel._running = True
    await asyncio.wait_for(channel._poll_loop(), 10)


def _text(chat, text):
    return {"message": {"message_id": 1, "chat": {"id": chat, "type": "private"},
                        "from": {"id": chat * 10, "first_name": "x"}, "text": text}}


async def test_the_poll_loop_answers_another_chat_while_one_is_busy(monkeypatch):
    b_done, saw = asyncio.Event(), {}

    async def on_turn(text, chat):
        if chat == 1:
            try:
                await asyncio.wait_for(b_done.wait(), 1.0)
                saw["b before a"] = True
            except TimeoutError:
                saw["b before a"] = False
        else:
            b_done.set()

    channel = _telegram(monkeypatch, on_turn)
    await _poll(channel, [(0, [_text(1, "a slow question"), _text(2, "hi")])])
    assert saw == {"b before a": True}, "chat 2 was held behind chat 1's turn"
    assert channel._lanes is None, "the loop drained its lanes on the way out"


async def test_a_button_tap_in_one_chat_does_not_wait_for_another(monkeypatch):
    tapped, saw = asyncio.Event(), {}

    async def on_turn(text, chat):
        try:
            await asyncio.wait_for(tapped.wait(), 1.0)
            saw["tap during turn"] = True
        except TimeoutError:
            saw["tap during turn"] = False

    channel = _telegram(monkeypatch, on_turn)

    async def tap(cb):
        tapped.set()

    monkeypatch.setattr(channel, "_handle_callback", tap)
    await _poll(channel, [(0, [_text(1, "a slow question")]),
                          (0.02, [{"callback_query": {"id": "c", "data": "x",
                                                      "message": {"chat": {"id": 2}}}}])])
    assert saw == {"tap during turn": True}, "chat 2's tap was held behind chat 1's turn"


async def test_telegram_stop_drains_the_lanes_within_budget(monkeypatch):
    from agents.core.channels import telegram as tg

    monkeypatch.setattr(tg, "LANE_DRAIN_BUDGET", 0.1)
    channel = tg.TelegramChannel.__new__(tg.TelegramChannel)
    channel._running = True
    channel._poll_task = None
    channel.client = SimpleNamespace(aclose=AsyncMock())
    channel._lanes = ChatLanes(name="telegram")
    channel._lanes.submit(1, _hang)
    started = time.monotonic()
    await channel.stop()
    assert time.monotonic() - started < 0.5 and channel._lanes is None
    channel.client.aclose.assert_awaited()
