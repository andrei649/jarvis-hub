"""H674 — a compaction summary never holds the owner's turn past a short bound.

Hermes compresses in the background of a turn with two clocks: how long the
summary may make the user wait, and how long the summarizer may go silent. Nerva
awaited the strict-local summarizer inline with neither — its only limit was the
httpx read timeout (120 s for Ollama), a total-duration wait on a non-streaming
call — so a slow or wedged local model held the arriving turn for minutes, and
nothing said why.

Now the turn waits at most ``memory.compression_max_turn_hold_seconds`` (10 s).
On expiry it goes on with the turns verbatim when they still fit the window, or
the deterministic digest when they do not, and says so; the summary finishes in
the background and seeds the next turn's iterative merge (never the compaction
clock). The summarizer streams and is cut after
``memory.compression_summary_idle_seconds`` (60 s) with nothing received; a slow
stream that keeps talking is not cut.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from agents.core import compaction_hold as ch  # noqa: E402
from agents.core.compaction_hold import SummaryHold, stream_summary  # noqa: E402
from agents.core.context_compressor import CompactionPolicy, ContextCompressor  # noqa: E402
from agents.core.orchestrator import Orchestrator  # noqa: E402


def _turn(role, content):
    return {"role": role, "content": content, "agent_id": None}


def _long(n, tag, size=1200):
    return [_turn("user", f"{tag} {i}. " + "x" * size) for i in range(n)]


# ── the settings ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "seconds"), [
    (10, 10.0), ("2.5", 2.5), (0, 0.0), (-3, 0.0), (1e9, 120.0), ("nan", 10.0), ("inf", 10.0),
    (True, 10.0), (None, 10.0), ("soon", 10.0),
])
def test_hold_seconds(value, seconds):
    assert ch.hold_seconds(value) == seconds


@pytest.mark.parametrize(("value", "seconds"), [
    (60, 60.0), ("5", 5.0), (0, 60.0), (-1, 60.0), (1e9, 600.0), ("nan", 60.0), (False, 60.0), (None, 60.0),
])
def test_idle_seconds(value, seconds):
    """0 is not "no deadline": a summarizer with no idle bound is exactly the bug."""
    assert ch.idle_seconds(value) == seconds


def test_the_settings_are_declared():
    from agents.core import settings_db

    rows = {(r["category"], r["key"]): r for r in settings_db.DEFAULTS}
    hold = rows[("memory", "compression_max_turn_hold_seconds")]
    idle = rows[("memory", "compression_summary_idle_seconds")]
    assert hold["value"] == 10 and idle["value"] == 60
    assert hold["kind"] == idle["kind"] == "number"
    assert ch.HOLD_SETTING == "memory.compression_max_turn_hold_seconds"
    assert ch.IDLE_SETTING == "memory.compression_summary_idle_seconds"


# ── the inactivity deadline ──────────────────────────────────────────────────


class _Stream:
    """A local backend whose stream says ``pieces`` with ``gap`` seconds between them,
    then hangs forever if ``hang``; ``thinking`` pieces are activity with no text."""

    def __init__(self, pieces, gap=0.0, hang=False, thinking=0, reply=None, close_takes=0.0):
        self.pieces, self.gap, self.hang, self.thinking, self.reply = pieces, gap, hang, thinking, reply
        self.close_takes = close_takes
        self.cancelled = False
        self.kwargs = None

    async def generate_stream(self, model, prompt, system="", max_tokens=1024, temperature=0.7,
                              on_token=None, on_activity=None):
        self.kwargs = {"model": model, "prompt": prompt, "system": system, "max_tokens": max_tokens,
                       "temperature": temperature}
        try:
            for _ in range(self.thinking):
                await asyncio.sleep(self.gap)
                on_activity()
            text = ""
            for piece in self.pieces:
                await asyncio.sleep(self.gap)
                if on_activity is not None:
                    on_activity()
                text += piece
                await on_token(piece)
            if self.hang:
                await asyncio.sleep(3600)
            return self.reply if self.reply is not None else text
        except asyncio.CancelledError:
            await asyncio.sleep(self.close_takes)      # closing an HTTP response takes a moment
            self.cancelled = True
            raise


async def _summarize(backend, idle):
    return await stream_summary(backend, idle, model="m", prompt="p", system="s", max_tokens=64,
                                temperature=0.2)


async def test_a_silent_summarizer_is_cut_at_the_idle_deadline():
    backend = _Stream(["one "], hang=True, close_takes=0.05)
    started = time.monotonic()
    with pytest.raises(ch.SummaryStalled):
        await _summarize(backend, 0.15)
    assert time.monotonic() - started < 1.0
    assert backend.cancelled, "the stalled stream is closed, not left running"


async def test_a_slow_stream_that_keeps_talking_is_not_cut():
    backend = _Stream(["a ", "b ", "c ", "d ", "e."], gap=0.06)
    assert await _summarize(backend, 0.15) == "a b c d e."      # 0.30 s in all, never 0.15 s quiet
    assert backend.kwargs == {"model": "m", "prompt": "p", "system": "s", "max_tokens": 64, "temperature": 0.2}


async def test_a_stream_that_only_reports_tokens_is_alive_while_they_come():
    """A backend with no ``on_activity`` still streams: each token is a sign of life."""
    class TokensOnly:
        async def generate_stream(self, model, prompt, system="", max_tokens=1024, temperature=0.7,
                                  on_token=None):
            for piece in ("a ", "b ", "c ", "d."):
                await asyncio.sleep(0.06)
                await on_token(piece)
            return "a b c d."

    assert await _summarize(TokensOnly(), 0.15) == "a b c d."


async def test_a_model_that_is_thinking_is_alive():
    """Reasoning arrives with no visible text; it still counts as the stream talking."""
    backend = _Stream(["summary."], gap=0.06, thinking=4)
    assert await _summarize(backend, 0.15) == "summary."


async def test_a_degraded_reply_is_never_a_summary():
    for reply in ("⚠️ Ollama is not answering.", "[backend error: 500]", "   "):
        with pytest.raises(ch.SummaryUnusable):
            await _summarize(_Stream(["x"], reply=reply), 1.0)


async def test_a_backend_without_a_stream_is_awaited_whole():
    class Whole:
        async def generate(self, **kw):
            return "whole summary"

    assert await _summarize(Whole(), 1.0) == "whole summary"


# ── the hold ─────────────────────────────────────────────────────────────────


async def _slow(delay, text="late summary"):
    await asyncio.sleep(delay)
    return text


async def test_a_summary_ready_in_time_is_used():
    hold, late = SummaryHold(), []
    assert await hold.wait("s", lambda: _slow(0.01, "quick"), 1.0, late.append) == "quick"
    assert late == [] and not hold.busy("s")


async def test_the_turn_goes_on_at_the_bound_and_the_summary_lands_later():
    hold, late = SummaryHold(), []
    started = time.monotonic()
    assert await hold.wait("s", lambda: _slow(0.3), 0.05, late.append) is None
    assert time.monotonic() - started < 0.25, "the turn waited no longer than the hold"
    assert hold.busy("s")
    await asyncio.sleep(0.4)
    assert late == ["late summary"] and not hold.busy("s")
    assert hold._flights == {}, "a finished summary is not kept"


async def test_one_summary_per_session_at_a_time():
    hold, late, calls = SummaryHold(), [], []

    def make():
        calls.append(1)
        return _slow(0.2)

    assert await hold.wait("s", make, 0.01, late.append) is None
    started = time.monotonic()
    assert await hold.wait("s", make, 5.0, late.append) is None, "the next turn does not wait on it again"
    assert time.monotonic() - started < 0.05 and calls == [1], "nor starts a second one beside it"
    assert await hold.wait("other", lambda: _slow(0, "theirs"), 1.0, late.append) == "theirs"
    await asyncio.sleep(0.3)
    assert late == ["late summary"]


async def test_a_turn_cancelled_while_it_waits_still_leaves_its_summary_for_the_next():
    """The owner pressed Stop (or the client went away) during the hold: the summary
    being written is not wasted."""
    hold, late = SummaryHold(), []
    waiting = asyncio.ensure_future(hold.wait("s", lambda: _slow(0.1), 5.0, late.append))
    await asyncio.sleep(0.02)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await asyncio.sleep(0.15)
    assert late == ["late summary"]


async def test_a_zero_hold_never_waits():
    hold, late = SummaryHold(), []
    assert await hold.wait("s", lambda: _slow(0), 0, late.append) is None
    await asyncio.sleep(0.05)
    assert late == ["late summary"]


async def test_a_late_summary_that_failed_seeds_nothing(caplog):
    hold, late = SummaryHold(), []

    async def boom():
        await asyncio.sleep(0.05)
        raise ch.SummaryStalled("quiet for 60s")

    with caplog.at_level(logging.INFO, logger="jarvis.compaction"):
        assert await hold.wait("s", boom, 0.01, late.append) is None
        await asyncio.sleep(0.1)
    assert late == [] and not hold.busy("s")
    assert any("deferred summary for this session was not written" in r.getMessage() for r in caplog.records)


async def test_a_failure_within_the_hold_reaches_the_caller():
    async def boom():
        raise RuntimeError("no local backend")

    with pytest.raises(RuntimeError):
        await SummaryHold().wait("s", boom, 1.0, lambda _s: None)


async def test_aclose_stops_what_is_still_being_written():
    hold, late, closed = SummaryHold(), [], []

    async def writing():
        try:
            await asyncio.sleep(3600)
        finally:
            await asyncio.sleep(0.02)                 # closing its stream takes a moment
            closed.append(True)

    loop = asyncio.get_running_loop()
    reports = []
    loop.set_exception_handler(lambda _loop, context: reports.append(context))
    try:
        assert await hold.wait("s", writing, 0.01, late.append) is None
        started = time.monotonic()
        await hold.aclose(0.5)
        assert time.monotonic() - started < 0.6 and not hold.busy("s")
        assert closed == [True], "aclose waits for the summary to stop, not just asks it to"
        await asyncio.sleep(0.01)
    finally:
        loop.set_exception_handler(None)
    assert late == [] and reports == [], "a cancelled summary seeds nothing and reports nothing"


# ── the compressor ───────────────────────────────────────────────────────────


def _gate(result):
    async def gate(make, covered):
        gate.covered = covered
        return result
    return gate


def _deferred_gate():
    return _gate(None)


async def test_compress_uses_the_digest_and_says_so_when_the_summary_is_deferred():
    comp = ContextCompressor(summarizer=lambda _p: _slow(0), max_tokens=500, keep_recent=2,
                             structured=True, gate=_deferred_gate())
    out = await comp.compress(_long(8, "t", 400))
    assert out["compressed"] is True and out["summary_deferred"] is True
    assert out["summary"].startswith("[summary of earlier conversation]")
    assert comp._gate.covered == 6


async def test_the_summary_covers_every_older_turn_with_a_prior():
    comp = ContextCompressor(summarizer=lambda _p: _slow(0), max_tokens=500, keep_recent=2,
                             structured=True, gate=_gate("Historical context: merged."))
    out = await comp.compress(_long(8, "t", 400), prior={"summary": "earlier", "covered": 3})
    assert comp._gate.covered == 6 and out["covered"] == 6


async def test_compress_uses_a_summary_the_gate_returned():
    comp = ContextCompressor(summarizer=lambda _p: _slow(0), max_tokens=500, keep_recent=2,
                             structured=True, gate=_gate("Historical context: gated."))
    out = await comp.compress(_long(8, "t", 400))
    assert out["summary"] == "Historical context: gated." and not out.get("summary_deferred")


def _policy(window):
    return CompactionPolicy(soft=0.5, hard=0.85, protect_head=0, protect_last_n=2, per_model={"m": window})


async def test_compact_keeps_the_turns_verbatim_when_they_still_fit():
    turns = _long(8, "t", 400)                                     # ~800 tokens
    with_image = [dict(turns[0], images=["data:image/png;base64," + "A" * 40000])] + turns[1:]
    comp = ContextCompressor(summarizer=lambda _p: _slow(0), max_tokens=0, keep_recent=2,
                             structured=True, gate=_deferred_gate())
    out = await comp.compact(with_image, model="m", policy=_policy(1000))
    assert out["summary_deferred"] is True and out["summary"] == "" and out["evicted"] == 0
    assert [t["content"] for t in out["kept"][1:]] == [t["content"] for t in turns[1:]], "every turn, verbatim"
    assert out["kept"][0]["content"].startswith(turns[0]["content"])   # its image dropped, its words kept
    assert out["images_dropped"] == 1 and out["tier"] == "images"


async def test_compact_uses_the_digest_when_the_turns_would_not_fit():
    comp = ContextCompressor(summarizer=lambda _p: _slow(0), max_tokens=0, keep_recent=2,
                             structured=True, gate=_deferred_gate())
    out = await comp.compact(_long(8, "t", 400), model="m", policy=_policy(900))
    assert out["summary_deferred"] is True and out["compressed"] is True
    assert out["summary"].startswith("[summary of earlier conversation]") and out["tier"] == "summarize"


async def test_compact_respects_the_owners_budget_over_verbatim():
    """memory.compression_max_tokens is the owner's own cap: a deferral never overrides it."""
    comp = ContextCompressor(summarizer=lambda _p: _slow(0), max_tokens=500, keep_recent=2,
                             structured=True, gate=_deferred_gate())
    out = await comp.compact(_long(8, "t", 400), model="m", policy=_policy(100000))
    assert out["summary_deferred"] is True and out["compressed"] is True and out["evicted"] == 6


# ── the orchestrator ─────────────────────────────────────────────────────────


class _Memory:
    def __init__(self, turns):
        self.turns = turns

    async def get_context(self, session_id, last_n=10):
        return ""

    async def get_history(self, session_id, last_n=None):
        return [dict(t) for t in (self.turns[-last_n:] if last_n else self.turns)]


class _Local:
    def __init__(self, delay, text="Historical context: the real summary."):
        self.delay, self.text, self.calls = delay, text, 0

    async def generate_stream(self, model, prompt, system="", max_tokens=1024, temperature=0.7,
                              on_token=None, on_activity=None):
        self.calls += 1
        waited = 0.0
        while waited < self.delay:                     # alive while it works: never idle-cut
            await asyncio.sleep(0.02)
            waited += 0.02
            if on_activity is not None:
                on_activity()
        await on_token(self.text)
        return self.text


def _orch(turns, backend, **settings):
    o = Orchestrator.__new__(Orchestrator)
    o.memory = _Memory(turns)
    o.session_id = "s"
    o.llm_router = SimpleNamespace(local_backend=backend, active_model="local-m", _backend=None)
    values = {"memory.context_compression": True, "memory.compression_summarizer": True,
              "memory.compression_max_tokens": 1500, **settings}
    o.get_setting = lambda key, default=None: values.get(key, default)
    return o


async def test_a_slow_summary_does_not_hold_the_turn_and_seeds_the_next_one(caplog):
    from agents.core.turn_notices import open_turn_notices, reset_turn_notices

    backend = _Local(0.4)
    o = _orch(_long(10, "Old"), backend, **{ch.HOLD_SETTING: 0.05})
    notices, token = open_turn_notices()
    try:
        started = time.monotonic()
        with caplog.at_level(logging.INFO, logger="jarvis.orchestrator"):
            out = await o._history_for_prompt(10)
        assert time.monotonic() - started < 0.3, "the turn went on at the hold"
    finally:
        reset_turn_notices(token)
    assert "[summary of earlier conversation]" in out and "the real summary" not in out
    assert [n["code"] for n in notices] == ["compaction_deferred"]
    assert "summary" in notices[0]["text"].lower()
    assert any("compaction summary deferred" in r.getMessage() for r in caplog.records)
    assert "s" not in o._ctx_summary_cache, "a digest never becomes the merge prior of a deferral"
    await asyncio.sleep(0.5)
    assert o._ctx_summary_cache["s"]["summary"] == "Historical context: the real summary."
    assert o._ctx_summary_cache["s"]["covered"] == 6
    # The next turn merges from the real summary and is in time.
    o.memory.turns = o.memory.turns + [_turn("user", "Newest? " + "q" * 1200)]
    backend.delay = 0.0
    out = await o._history_for_prompt(11)
    assert "Historical context: the real summary." in out and backend.calls == 2


async def test_a_late_summary_never_overwrites_a_newer_prior():
    backend = _Local(0.3)
    o = _orch(_long(10, "Old"), backend, **{ch.HOLD_SETTING: 0.02})
    await o._history_for_prompt(10)
    newer = {"summary": "a newer turn's summary", "covered": 7}
    o._ctx_summary_cache["s"] = newer
    await asyncio.sleep(0.4)
    assert o._ctx_summary_cache["s"] is newer


async def test_the_idle_setting_reaches_the_summarizer():
    from agents.core.turn_notices import open_turn_notices, reset_turn_notices

    class Silent:
        async def generate_stream(self, model, prompt, system="", max_tokens=1024, temperature=0.7,
                                  on_token=None, on_activity=None):
            await asyncio.sleep(3600)

    o = _orch(_long(10, "Old"), Silent(), **{ch.IDLE_SETTING: 0.1, ch.HOLD_SETTING: 5})
    notices, token = open_turn_notices()
    try:
        started = time.monotonic()
        out = await o._history_for_prompt(10)
    finally:
        reset_turn_notices(token)
    assert time.monotonic() - started < 1.5, "cut at 0.1 s quiet, well inside the 5 s hold"
    assert "[summary of earlier conversation]" in out and notices == [], "a failed summary is the digest, not a deferral"


async def test_a_summary_in_time_is_used_as_before():
    backend = _Local(0.0)
    o = _orch(_long(10, "Old"), backend)
    out = await o._history_for_prompt(10)
    assert "Historical context: the real summary." in out
    assert o._ctx_summary_cache["s"]["covered"] == 6


async def test_the_deferral_never_publishes_through_the_compaction_clock():
    """The clock CAS publishes what a prompt was built from; a summary no prompt used
    must not be committed as if one had."""
    commits = []
    backend = _Local(0.3)
    o = _orch(_long(10, "Old"), backend, **{ch.HOLD_SETTING: 0.02})
    o.checkpoints = SimpleNamespace(commit_clock=lambda snap, body: commits.append(json.loads(body)) or snap)
    import agents.core.orchestrator as orch_mod
    real = orch_mod.capture_clock
    orch_mod.capture_clock = lambda manager, sid: object()
    try:
        await o._history_for_prompt(10)
        await asyncio.sleep(0.4)
    finally:
        orch_mod.capture_clock = real
    assert len(commits) == 1, "only the digest this prompt was built from is committed"
    assert commits[0]["summary"].startswith("[summary of earlier conversation]")
    assert commits[0]["summary_deferred"] is True


async def test_aclose_stops_a_deferred_summary():
    from agents.core import lifecycle_budget as lb

    backend = _Local(3600)
    o = _orch(_long(10, "Old"), backend, **{ch.HOLD_SETTING: 0.02})
    await o._history_for_prompt(10)
    assert o._summary_holds.busy("s")
    o._flush_checkpoint = lambda: _slow(0)
    o.channel_manager = SimpleNamespace(channels={})
    o.llm_router = None
    lb_budget = lb.TASK_CANCEL_BUDGET
    started = time.monotonic()
    await o.aclose()
    assert time.monotonic() - started < lb_budget + 1 and not o._summary_holds.busy("s")


# ── the notice reaches the owner ─────────────────────────────────────────────


def test_chat_carries_the_notice(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.turn_notices import record_turn_notice

    async def handle_input(*args, **kwargs):
        record_turn_notice("compaction_deferred", ch.DEFERRED_NOTICE)
        record_turn_notice("compaction_deferred", ch.DEFERRED_NOTICE)   # once per turn
        return "ok"

    mock = MagicMock()
    mock.handle_input = AsyncMock(side_effect=handle_input)
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    body = client.post("/chat", json={"message": "hi"}).json()
    assert body["notices"] == [{"code": "compaction_deferred", "text": ch.DEFERRED_NOTICE}]
    mock.handle_input = AsyncMock(return_value="ok")
    assert client.post("/chat", json={"message": "hi"}).json()["notices"] == [], "one turn's notice never leaks into the next"


async def test_chat_leaves_no_collector_bound(monkeypatch):
    from starlette.requests import Request

    from agents import web
    from agents.core import turn_notices

    mock = MagicMock()
    mock.handle_input = AsyncMock(return_value="ok")
    mock.notes = None
    monkeypatch.setattr(web, "orch", mock)
    request = Request({"type": "http", "method": "POST", "path": "/chat", "headers": [], "query_string": b""})
    reply = await web.chat(web.ChatRequest(message="hi"), request)
    assert reply.reply == "ok" and turn_notices._turn_notices.get() is None


async def test_every_stream_end_event_carries_the_notices():
    from agents import web
    from agents.core.turn_notices import record_turn_notice

    class Works:
        async def handle_input_stream(self, message, channel, on_token, agent_override=None):
            record_turn_notice("compaction_deferred", ch.DEFERRED_NOTICE)
            return "ok"

    class Fails:
        async def handle_input_stream(self, message, channel, on_token, agent_override=None):
            record_turn_notice("compaction_deferred", ch.DEFERRED_NOTICE)
            raise RuntimeError("boom")

    for orch in (Works(), Fails()):
        chunks = [c async for c in web._chat_event_stream(orch, "hi", "jarvis", None)]
        end = [json.loads(c[6:]) for c in chunks if c.startswith("data: ")][-1]
        assert end["type"] == "end"
        assert end["notices"] == [{"code": "compaction_deferred", "text": ch.DEFERRED_NOTICE}]


def test_a_notice_outside_a_turn_goes_nowhere():
    from agents.core.turn_notices import record_turn_notice

    record_turn_notice("compaction_deferred", "nobody is listening")   # no raise, no leak


# ── the local backends say they are alive, reasoning included ────────────────


async def test_ollama_reports_every_chunk_as_activity_even_a_thinking_one():
    import httpx

    from agents.core.llm.base import OllamaBackend

    lines = [{"thinking": "let me see"}, {"thinking": " more"}, {"response": "Summary."},
             {"done": True, "done_reason": "stop"}]
    body = "\n".join(json.dumps(line) for line in lines) + "\n"
    backend = OllamaBackend("http://ollama.invalid")
    backend.client = httpx.AsyncClient(base_url="http://ollama.invalid",
                                       transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body)))
    seen = []
    try:
        text = await backend.generate_stream("m", "p", on_activity=lambda: seen.append(1))
    finally:
        await backend.client.aclose()
    assert text == "Summary." and len(seen) == 4


async def test_lmstudio_reports_every_chunk_as_activity_even_a_thinking_one():
    import httpx

    from agents.core.llm.base import LMStudioBackend

    chunks = [{"choices": [{"delta": {"reasoning_content": "hmm"}}]},
              {"choices": [{"delta": {"content": "Summary."}}]},
              {"choices": [{"delta": {}, "finish_reason": "stop"}]}]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    backend = LMStudioBackend("http://lmstudio.invalid")
    backend.client = httpx.AsyncClient(base_url="http://lmstudio.invalid",
                                       transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body)))
    seen = []
    try:
        text = await backend.generate_stream("m", "p", on_activity=lambda: seen.append(1))
    finally:
        await backend.client.aclose()
    assert text == "Summary." and len(seen) == 4


async def test_a_backend_that_cannot_stream_still_takes_the_argument():
    from agents.core.llm.base import LLMBackend

    class Whole(LLMBackend):
        async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
            return "whole"

        async def generate_tool_turn(self, *a, **k):   # pragma: no cover - abstract filler
            raise NotImplementedError

    assert await Whole().generate_stream("m", "p", on_activity=lambda: None) == "whole"
