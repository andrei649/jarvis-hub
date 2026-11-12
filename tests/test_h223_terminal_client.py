"""H223 — `nerva chat -i` as the terminal client: streamed answers, start, resume, crash.

Pinned from the owner's side:

* the answer is drawn as its tokens arrive (whole lines, the prompt redrawn under them),
  with a one-line tool trail, and nothing the stream carries can drive the terminal;
* the streamed turn is still stopped by Ctrl+C for the caller's own credential only, and
  its questions still come through ``GET /chat/pending`` (so a secret prompt still works);
* a hub without the stream route gets ``POST /chat``;
* ``nerva chat -i MESSAGE --image PATH`` starts with that message;
* a clean exit and an internal error both print how to resume, and an internal error
  never leaves a traceback or a changed SIGINT handler behind.
"""

from __future__ import annotations

import asyncio
import io
import json
import signal
import threading
import time
import urllib.error

import httpx
import pytest

from agents import web
from agents.cli import repl as R
from agents.cli.client import STREAM_LINE_LIMIT, HubClient, HubError, HubUnavailable, _sse_events
from agents.cli.nerva import EXIT_USAGE, Context, main
from tests.test_h224_terminal_interaction import FakeHub, _repl

# ── the SSE reader ────────────────────────────────────────────────────────────


def _sse(*events, raw=b""):
    body = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events) + raw
    return io.BytesIO(body)


def test_sse_reader_yields_json_objects_only():
    raw = b"data: not json\n\ndata: [1,2]\n\n: comment\nevent: x\ndata: {\"type\":\ndata: \"end\"}\n\n"
    events = list(_sse_events(_sse({"type": "start"}, {"type": "token", "text": "hi"}, raw=raw), "hub"))
    assert events == [{"type": "start"}, {"type": "token", "text": "hi"}, {"type": "end"}]


def test_sse_reader_refuses_an_unbounded_line():
    huge = io.BytesIO(b"data: " + b"x" * (STREAM_LINE_LIMIT + 10) + b"\n\n")
    with pytest.raises(HubUnavailable):
        list(_sse_events(huge, "hub"))


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_hub_client_stream_sends_credentials_and_its_headers():
    seen = {}

    def opener(request, timeout):
        seen.update(headers={k.lower(): v for k, v in request.header_items()}, timeout=timeout,
                    body=json.loads(request.data), url=request.full_url, method=request.get_method())
        return _Response(_sse({"type": "token", "text": "a"}, {"type": "end", "text": "a"}).getvalue())

    client = HubClient("http://127.0.0.1:8080", user_token="u-token", opener=opener)
    events = list(client.stream("/chat/stream", {"message": "hi"}, timeout=5,
                                headers={"X-Nerva-Turn-Id": "a" * 32, "x-user-token": "forged"}))
    assert [e["type"] for e in events] == ["token", "end"]
    assert seen["url"].endswith("/chat/stream") and seen["method"] == "POST" and seen["timeout"] == 5
    assert seen["headers"]["accept"] == "text/event-stream"
    assert seen["headers"]["x-user-token"] == "u-token"          # a caller header never replaces it
    assert seen["headers"]["x-nerva-turn-id"] == "a" * 32


def test_hub_client_stream_errors_are_hub_errors():
    def refused(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "nope", {}, io.BytesIO(b'{"error":"x"}'))

    with pytest.raises(HubError) as caught:
        list(HubClient(opener=refused).stream("/chat/stream", {}))
    assert caught.value.status == 404

    def down(request, timeout):
        raise urllib.error.URLError("refused")

    with pytest.raises(HubUnavailable):
        list(HubClient(opener=down).stream("/chat/stream", {}))


# ── drawing a streamed answer ─────────────────────────────────────────────────

def test_answer_feed_draws_whole_lines_and_wraps_at_a_space():
    drawn = []
    feed = R.AnswerFeed(drawn.append, width=20)
    for token in ("Hello ", "wor", "ld\nsecond", " line that is long enough to wrap"):
        feed.feed(token)
    assert drawn[:2] == ["Hello world", "second line that is"]
    assert feed.close() is True
    assert " ".join(drawn[2:]) == "long enough to wrap"
    assert R.AnswerFeed(drawn.append).close() is False


def test_an_escape_split_across_tokens_never_reaches_the_terminal(tmp_path, monkeypatch):
    repl, _hub, out, _err = _repl(tmp_path, monkeypatch)
    feed = R.AnswerFeed(repl.answer, width=200)
    for token in ("ok \x1b", "]0;owned\x07 then \x1b[", "2J and ‮", "rlo\x9b31m\n"):
        feed.feed(token)
    feed.close()
    text = out.getvalue()
    assert "\x1b" not in text and "\x07" not in text and "‮" not in text and "\x9b" not in text
    assert text.startswith("ok ")


@pytest.mark.parametrize("event,expected", [
    ({"event": "tool_start", "tool": "web.search", "call_id": "1"}, "  ⋯ web.search"),
    ({"event": "tool_end", "tool": "web.search", "status": "ok"}, "  ✓ web.search (ok)"),
    ({"event": "tool_end", "tool": "fs.write", "status": "denied"}, "  ✗ fs.write (denied)"),
    ({"event": "tool_heartbeat", "tool": "x"}, None),
    ({"event": "tool_start", "tool": "\x1b[2Jx‮y"}, "  ⋯ [2Jx y"),
    ("not a dict", None),
])
def test_tool_trail_lines(event, expected):
    assert R.tool_line(event) == expected


# ── a streamed turn in the REPL ───────────────────────────────────────────────

class StreamHub(FakeHub):
    """FakeHub with a ``stream`` method that plays a list of events (or raises)."""

    def __init__(self, events, answers=None, gate=None):
        super().__init__(answers)
        self.events = events
        self.streamed = []
        self.gate = gate

    def stream(self, path, body, *, timeout=None, headers=None):
        self.streamed.append((path, dict(body), dict(headers or {})))
        if isinstance(self.events, Exception):
            raise self.events
        for index, event in enumerate(self.events):
            if self.gate is not None and index == len(self.events) - 1:
                self.gate.wait(5)
            yield event


_END = {"type": "end", "text": "Hi there", "session_id": "web_s1", "pending_approvals": [9],
        "notices": [{"code": "x", "text": "note\x1b[2J"}], "outcome": None}


def test_a_streamed_turn_draws_tokens_tools_and_the_end(tmp_path, monkeypatch):
    events = [{"type": "start"}, {"type": "tool", "event": {"event": "tool_start", "tool": "clock"}},
              {"type": "token", "text": "Hi "}, {"type": "token", "text": "there"}, _END]
    hub = StreamHub(events, {("GET", "/chat/pending"): {"questions": []}})
    repl, hub, out, err = _repl(tmp_path, monkeypatch, hub, agent="athena")
    repl.run_turn(R.Outgoing("hello"))
    path, body, headers = hub.streamed[0]
    assert path == "/chat/stream" and body["message"] == "hello" and body["agent"] == "athena"
    assert body["tool_events"] is True
    assert headers["X-Nerva-Pending"] == "poll" and len(headers["X-Nerva-Turn-Id"]) == 32
    assert out.getvalue() == "Hi there\n"                  # drawn once, from the tokens
    assert "⋯ clock" in err.getvalue() and "ℹ note" in err.getvalue() and "\x1b" not in err.getvalue()
    assert repl.session_id == "web_s1"
    assert ("approvals", [9], None) in repl.asks
    assert not [c for c in hub.calls if c[1] == "/chat"]   # POST /chat was not used


def test_an_end_without_tokens_draws_the_end_text(tmp_path, monkeypatch):
    hub = StreamHub([{"type": "start"}, {**_END, "text": "busy\x1b[2J"}])
    repl, hub, out, _err = _repl(tmp_path, monkeypatch, hub)
    repl.run_turn(R.Outgoing("hello"))
    assert out.getvalue() == "busy\n"


def test_a_hub_without_the_stream_route_gets_post_chat(tmp_path, monkeypatch):
    hub = StreamHub(HubError(404, "not found"),
                    {("POST", "/chat"): {"reply": "plain"}, ("GET", "/chat/pending"): {"questions": []}})
    repl, hub, out, _err = _repl(tmp_path, monkeypatch, hub)
    repl.run_turn(R.Outgoing("one"))
    repl.run_turn(R.Outgoing("two"))
    assert len(hub.streamed) == 1                           # asked once, then remembered
    assert [c[2]["message"] for c in hub.calls if c[1] == "/chat"] == ["one", "two"]
    assert out.getvalue() == "plain\nplain\n"


def test_a_refused_stream_is_said_and_not_retried_as_post(tmp_path, monkeypatch):
    hub = StreamHub(HubError(403, "forbidden\x1b[2J"))
    repl, hub, _out, err = _repl(tmp_path, monkeypatch, hub)
    repl.run_turn(R.Outgoing("one"))
    assert "HTTP 403" in err.getvalue() and "\x1b" not in err.getvalue()
    assert not [c for c in hub.calls if c[1] == "/chat"]


def test_ctrl_c_stops_a_streamed_turn_by_its_own_turn_id(tmp_path, monkeypatch):
    gate = threading.Event()
    hub = StreamHub([{"type": "start"}, {"type": "token", "text": "work"}, _END],
                    {("POST", "/chat/interrupt"): {"ok": True, "interrupted": 1},
                     ("GET", "/chat/pending"): {"questions": []}}, gate=gate)
    repl, hub, *_ = _repl(tmp_path, monkeypatch, hub)
    worker = threading.Thread(target=repl.run_turn, args=(R.Outgoing("long"),), daemon=True)
    repl.running = True
    worker.start()
    deadline = time.monotonic() + 5
    while not hub.streamed and time.monotonic() < deadline:
        time.sleep(0.01)
    turn_id = hub.streamed[0][2]["X-Nerva-Turn-Id"]
    assert repl.on_ctrl_c("") == "interrupt"
    gate.set()
    worker.join(5)
    (call,) = [c for c in hub.calls if c[1] == "/chat/interrupt"]
    assert call[2] == {"turn_id": turn_id}


def test_questions_during_a_streamed_turn_are_handed_to_the_keyboard(tmp_path, monkeypatch):
    gate = threading.Event()
    question = {"id": "b" * 32, "kind": "secret", "name": "X_KEY"}
    hub = StreamHub([{"type": "start"}, _END], {("GET", "/chat/pending"): {"questions": [question]}}, gate=gate)
    repl, *_ = _repl(tmp_path, monkeypatch, hub, session_id="web_s0")
    monkeypatch.setattr("agents.cli.chat_prompts.POLL_SECONDS", 0.01)
    worker = threading.Thread(target=repl.run_turn, args=(R.Outgoing("go"),), daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while not repl.asks and time.monotonic() < deadline:
        time.sleep(0.01)
    gate.set()
    worker.join(5)
    assert ("question", question, "web_s0") in repl.asks
    assert [q for q in repl.asks if q[0] == "question"] == [("question", question, "web_s0")]
    polled = [c for c in hub.calls if c[1].startswith("/chat/pending")]
    assert polled and all("session_id=web_s0" in c[1] for c in polled)


# ── start, resume, crash ──────────────────────────────────────────────────────

def test_start_with_a_message_and_an_image(tmp_path, monkeypatch):
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    repl, *_ = _repl(tmp_path, monkeypatch)
    assert repl.start_with("what is this?", [str(png)]) is True
    repl.send_startup()
    item = repl.queue.popleft()
    assert item.message == "what is this?" and item.images == [str(png)]


def test_start_with_a_bad_image_refuses(tmp_path, monkeypatch):
    bad = tmp_path / "notes.txt"
    bad.write_text("x")
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch)
    assert repl.start_with("hi", [str(bad)]) is False
    assert "not attached" in err.getvalue() and repl._startup is None


def test_the_first_message_is_sent_when_the_chat_starts(tmp_path, monkeypatch):
    sent = []
    hub = FakeHub({("POST", "/chat"): lambda b: sent.append(b["message"]) or {"reply": "ok", "session_id": "web_9"},
                   ("GET", "/chat/pending"): {"questions": []}, ("GET", "/api/commands"): {"commands": []}})
    repl, hub, _out, err = _repl(tmp_path, monkeypatch, hub, lines=[])
    repl.start_with("first\x1b[2J")
    monkeypatch.setattr(repl, "step", lambda: (time.sleep(0.3), False)[1])
    assert repl.run() == 0
    deadline = time.monotonic() + 5
    while not sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sent == ["first\x1b[2J"]                        # sent as typed …
    assert "> first [2J" in err.getvalue()                 # … echoed card-safe


def test_a_clean_exit_prints_the_resume_hint(tmp_path, monkeypatch):
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch, session_id="web_abc", lines=[])
    assert repl.run() == 0
    assert "resume this conversation: nerva chat -i -r web_abc" in err.getvalue()
    repl2, _hub, _out, err2 = _repl(tmp_path, monkeypatch, lines=[])
    assert repl2.run() == 0 and "resume" not in err2.getvalue()


def test_an_internal_error_ends_the_chat_cleanly(tmp_path, monkeypatch):
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch, session_id="web_abc")
    before = signal.getsignal(signal.SIGINT)

    def boom():
        raise RuntimeError("bad \x1b[2J state")

    monkeypatch.setattr(repl, "step", boom)
    assert repl.run() == 1
    text = err.getvalue()
    assert "the chat stopped on an internal error (RuntimeError: bad  [2J state)" in text
    assert "Traceback" not in text and "\x1b" not in text
    assert "resume this conversation: nerva chat -i -r web_abc" in text
    assert signal.getsignal(signal.SIGINT) is before
    assert repl.stopped


class _TtyIn(io.StringIO):
    def isatty(self):
        return True


class _TtyOut(io.StringIO):
    def isatty(self):
        return True


def test_chat_dash_i_takes_a_first_message_and_images(tmp_path, monkeypatch):
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    seen = {}

    def run(self):
        seen.update(first=self._startup.message, images=list(self.staged_images))
        return 0

    monkeypatch.setattr(R.Repl, "run", run)
    err = io.StringIO()
    ctx = Context(environ={"XDG_CONFIG_HOME": str(tmp_path)}, out=_TtyOut(), err=err, inp=_TtyIn(),
                  client_factory=lambda env: FakeHub())
    assert main(["chat", "-i", "look", "--image", str(png)], context=ctx) == 0
    assert seen == {"first": "look", "images": [str(png)]}
    assert main(["chat", "-i", "x" * 5000], context=ctx) == EXIT_USAGE
    assert main(["chat", "-i", "--image", str(tmp_path / "missing.png")], context=ctx) == EXIT_USAGE
    assert main(["chat", "-i", "-z", "hi"], context=ctx) == EXIT_USAGE


# ── the hub side: interrupt and question polling on /chat/stream ──────────────

def _events(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


@pytest.mark.asyncio
async def test_a_streamed_turn_is_interrupted_only_by_its_own_credential(tmp_path, monkeypatch):
    from agents.core.security.token_store import TokenStore
    from agents.core.turn_interrupts import INTERRUPTED_REPLY, NOTICE_CODE
    from tests.test_h226_cli_governance_prompts import _host

    store = TokenStore(str(tmp_path / "tokens.db"))
    owner, stranger = store.issue("user"), store.issue("user")
    orch, _cap, stream = await _host(tmp_path, monkeypatch, store=store)
    entered = asyncio.Event()

    async def model(message, channel, on_token, **kwargs):
        await on_token("partial ")
        entered.set()
        await asyncio.sleep(60)
        return "never"

    orch.handle_input_stream = model
    turn_id = "e" * 32
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            turn = asyncio.create_task(client.post(
                "/chat/stream", json={"message": "long job"},
                headers={"x-user-token": owner, "X-Nerva-Turn-Id": turn_id, "X-Nerva-Pending": "poll"}))
            await asyncio.wait_for(entered.wait(), 5)
            other = await client.post("/chat/interrupt", json={"turn_id": turn_id},
                                      headers={"x-user-token": stranger})
            assert other.json()["interrupted"] == 0
            assert not turn.done()
            mine = await client.post("/chat/interrupt", json={"turn_id": turn_id},
                                     headers={"x-user-token": owner})
            assert mine.json()["interrupted"] == 1
            response = await asyncio.wait_for(turn, 5)
        events = _events(response.text)
        assert [e["text"] for e in events if e["type"] == "token"] == ["partial "]
        (end,) = [e for e in events if e["type"] == "end"]
        assert end["text"] == INTERRUPTED_REPLY
        assert [n["code"] for n in end["notices"]] == [NOTICE_CODE]
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
        store._conn.close()


@pytest.mark.asyncio
async def test_a_streamed_turn_with_the_poll_header_asks_through_chat_pending(tmp_path, monkeypatch):
    from tests.test_h226_cli_governance_prompts import _host

    orch, cap, stream = await _host(tmp_path, monkeypatch)
    results = []

    async def model(message, channel, on_token, **kwargs):
        results.append(await cap["server"].handle({"tool": "clarify", "args": {
            "question": "Which box?", "choices": ["A", "B"]}}))
        await on_token("Finished")
        return "Finished"

    orch.handle_input_stream = model
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            turn = asyncio.create_task(client.post("/chat/stream", json={"message": "go"},
                                                   headers={"X-Nerva-Pending": "poll"}))
            listed: list = []
            async with asyncio.timeout(5):
                while not listed:
                    listed = (await client.get("/chat/pending")).json()["questions"]
                    await asyncio.sleep(0.01)
            assert listed[0]["question"] == "Which box?"
            answered = await client.post(f"/chat/pending/{listed[0]['id']}/answer", json={"answer": "2"})
            assert answered.status_code == 200
            response = await asyncio.wait_for(turn, 5)
        events = _events(response.text)
        assert not [e for e in events if e.get("type") == "clarify"]     # not asked in the stream
        assert [e for e in events if e["type"] == "end"][0]["text"] == "Finished"
        assert "B" in json.dumps(results[0])
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
