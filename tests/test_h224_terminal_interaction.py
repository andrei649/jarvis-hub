"""H224 — the interactive terminal chat's keyboard model (`nerva chat -i`).

prompt_toolkit is not a dependency of this repository, so the client is built on the
standard library's GNU readline. The key logic is tested as pure functions and on the
``Repl`` object with a fake hub; the readline bindings themselves are driven through a
real pseudo-terminal (the equivalent of prompt_toolkit's pipe input); the interrupt
route is tested over the real ASGI app with two credentials.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import stat
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pytest

from agents import web
from agents.cli import repl as R
from agents.cli.client import HubError
from agents.cli.nerva import EXIT_USAGE, Context, build_parser, main

# ── the Ctrl+C ladder ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("draft,running,armed,expected", [
    ("hello", True, True, "clear"),
    ("hello", False, False, "clear"),
    (" ", False, False, "clear"),
    ("", True, False, "interrupt"),
    ("", True, True, "interrupt"),
    ("", False, False, "arm"),
    ("", False, True, "exit"),
])
def test_ctrl_c_has_three_meanings_in_order(draft, running, armed, expected):
    assert R.ctrl_c_action(draft, turn_running=running, exit_armed=armed) == expected


class FakeHub:
    """A synchronous hub client: records calls, answers from a table."""

    base_url = "http://127.0.0.1:8080"

    def __init__(self, answers=None):
        self.calls = []
        self.answers = dict(answers or {})

    def request(self, method, path, body=None, *, timeout=None):
        self.calls.append((method, path, body))
        answer = self.answers.get((method, path.split("?")[0]))
        if isinstance(answer, Exception):
            raise answer
        return answer(body) if callable(answer) else answer

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None, *, timeout=None):
        return self.request("POST", path, body if body is not None else {}, timeout=timeout)


def _repl(tmp_path, monkeypatch, hub=None, lines=(), **kwargs):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    hub = hub or FakeHub()
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"EDITOR": "true"}, out=out, err=err, inp=io.StringIO(),
                  client_factory=lambda env: hub)
    feed = list(lines)

    def reader(prompt):
        if not feed:
            raise EOFError
        item = feed.pop(0)
        if isinstance(item, BaseException) or (isinstance(item, type) and issubclass(item, BaseException)):
            raise item
        return item

    return R.Repl(ctx, reader=reader, **kwargs), hub, out, err


def test_ctrl_c_clears_then_arms_then_exits(tmp_path, monkeypatch):
    repl, hub, _out, err = _repl(tmp_path, monkeypatch)
    assert repl.on_ctrl_c("half a thought") == "clear"
    assert "(draft cleared)" in err.getvalue()
    assert repl.on_ctrl_c("") == "arm" and not repl.stopped
    assert "press Ctrl+C again" in err.getvalue()
    assert repl.on_ctrl_c("") == "exit" and repl.stopped
    assert hub.calls == []                     # idle: nothing was sent to the hub


def test_the_exit_arm_expires(tmp_path, monkeypatch):
    repl, *_ = _repl(tmp_path, monkeypatch)
    assert repl.on_ctrl_c("") == "arm"
    repl.exit_armed_at = time.monotonic() - R.EXIT_ARM_SECONDS - 1
    assert repl.on_ctrl_c("") == "arm" and not repl.stopped


def test_a_continued_draft_counts_as_a_draft(tmp_path, monkeypatch):
    repl, *_ = _repl(tmp_path, monkeypatch)
    repl.continued = ["first line"]
    assert repl.on_ctrl_c("") == "clear" and repl.continued == []


def test_ctrl_c_during_a_turn_interrupts_the_callers_own_turn(tmp_path, monkeypatch):
    hub = FakeHub({("POST", "/chat/interrupt"): {"ok": True, "interrupted": 1}})
    repl, hub, _out, err = _repl(tmp_path, monkeypatch, hub, session_id="sess_1")
    repl.running = True
    assert repl.on_ctrl_c("") == "interrupt"
    assert hub.calls == [("POST", "/chat/interrupt", {"session_id": "sess_1"})]
    assert "stopping the turn" in err.getvalue()
    assert not repl.stopped


@pytest.mark.parametrize("status,said", [(404, "cannot stop a turn"), (403, "cannot stop the turn")])
def test_an_interrupt_the_hub_refuses_is_said(tmp_path, monkeypatch, status, said):
    hub = FakeHub({("POST", "/chat/interrupt"): HubError(status, "x")})
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch, hub)
    repl.running = True
    repl.on_ctrl_c("")
    assert said in err.getvalue()


def test_read_line_turns_ctrl_c_into_the_ladder_and_eof_into_none(tmp_path, monkeypatch):
    repl, *_ = _repl(tmp_path, monkeypatch, lines=[KeyboardInterrupt, KeyboardInterrupt])
    assert repl.read_line("> ") == "" and repl.exit_armed_at is not None
    assert repl.read_line("> ") == "" and repl.stopped
    assert repl.read_line("> ") is None


# ── routing lines ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("line,expected", [
    ("", ("empty", "")),
    ("   ", ("empty", "")),
    ("hello", ("send", "hello")),
    ("/help", ("send", "/help")),              # a hub command goes to the hub
    ("/sessions", ("send", "/sessions")),
    ("/edit some text", ("local", "/edit some text")),
    ("/model 2", ("local", "/model 2")),
    ("first line\\", ("continue", "first line")),
    ("ends in a real backslash \\\\", ("send", "ends in a real backslash \\\\")),
])
def test_route_line(line, expected):
    assert R.route_line(line) == expected


def test_a_backslash_continues_and_alt_enter_text_is_one_message(tmp_path, monkeypatch):
    repl, *_ = _repl(tmp_path, monkeypatch, lines=["first\\", "second", "a\nb"])
    sent = []
    repl.submit = sent.append
    assert repl.step() and repl.step() and repl.step()
    assert sent == ["first\nsecond", "a\nb"]


# ── completion sources ────────────────────────────────────────────────────────

def test_slash_completion_merges_the_hubs_catalog_and_local_commands():
    got = R.completions("/s", line="/s", begin=0, commands=["/status", "/sessions", "/help"])
    assert got == ["/sessions", "/status", "/switch"]
    assert "/edit" in R.completions("/", line="/", begin=0, commands=[])
    # not at the start of the line: a slash is just text
    assert R.completions("/s", line="see /s", begin=4, commands=["/status"]) == []


def test_file_reference_completion_asks_the_hub():
    asked = []

    def refs(prefix):
        asked.append(prefix)
        return ["docs/", "docs/ARCHITECTURE.md"]

    got = R.completions("@file:do", line="read @file:do", begin=5, commands=[], refs=refs)
    assert got == ["@file:docs/", "@file:docs/ARCHITECTURE.md"] and asked == ["do"]
    assert R.completions("@f", line="@f", begin=0, commands=[], refs=refs) == ["@file:"]


def test_catalog_and_refs_come_from_the_hubs_routes_and_are_filtered(tmp_path, monkeypatch):
    hub = FakeHub({
        ("GET", "/api/commands"): {"ok": True, "commands": [
            {"command": "/recap"}, {"command": "/bad name"}, {"command": "/\x1b[31mx"}, {"nope": 1}]},
        ("GET", "/api/context-refs"): {"ok": True, "items": [
            {"ref": "a.txt", "kind": "file"}, {"ref": "bad\x07", "kind": "file"}]},
    })
    repl, hub, *_ = _repl(tmp_path, monkeypatch, hub)
    repl.load_catalog()
    assert repl.commands == ["/recap"]
    assert repl.file_refs("a b") == ["a.txt"]
    assert hub.calls[-1][1] == "/api/context-refs?prefix=a%20b"


def test_a_catalog_the_hub_refuses_leaves_local_commands_only(tmp_path, monkeypatch):
    hub = FakeHub({("GET", "/api/commands"): HubError(401, "no")})
    repl, *_ = _repl(tmp_path, monkeypatch, hub)
    repl.load_catalog()
    assert repl.commands == []


# ── readline bindings ─────────────────────────────────────────────────────────

def test_the_binding_table_covers_the_rows_keys():
    table = "\n".join(R.READLINE_BINDINGS)
    for needle in ("enable-bracketed-paste on", r'"\e\r": "\C-v\C-j"', r'"\e[13;2u"', r'"\e[27;2;13~"',
                   r'"\C-x\C-e": "\C-a/edit \C-j"', r'"\e\e": kill-whole-line', "menu-complete",
                   "menu-complete-backward", "clear-screen"):
        assert needle in table


class FakeReadline:
    __doc__ = "GNU readline"

    def __init__(self):
        self.bound, self.history, self.buffer = [], [], ""
        self.completer = self.hook = None

    def set_auto_history(self, flag):
        self.auto = flag

    def set_completer_delims(self, delims):
        self.delims = delims

    def parse_and_bind(self, text):
        self.bound.append(text)

    def set_completer(self, fn):
        self.completer = fn

    def add_history(self, entry):
        self.history.append(entry)

    def set_pre_input_hook(self, fn):
        self.hook = fn

    def insert_text(self, text):
        self.buffer += text

    def redisplay(self):
        pass

    def get_line_buffer(self):
        return self.buffer

    def get_begidx(self):
        return 0


def test_install_readline_binds_loads_history_and_completes(tmp_path, monkeypatch):
    rl = FakeReadline()
    repl, *_ = _repl(tmp_path, monkeypatch, readline_module=rl)
    R.append_history(repl.history_file, "earlier\nmessage")
    repl.commands = ["/recap"]
    repl.install_readline()
    assert rl.auto is False and rl.bound == list(R.READLINE_BINDINGS)
    assert rl.history == ["earlier\nmessage"]
    rl.buffer = "/re"
    assert rl.completer("/re", 0) == "/recap" and rl.completer("/re", 1) is None
    repl._prefill = "from the editor"
    rl.buffer = ""
    rl.hook()
    assert rl.buffer == "from the editor" and repl._prefill == ""


def test_sigint_handler_captures_the_draft_before_readline_drops_it(tmp_path, monkeypatch):
    rl = FakeReadline()
    rl.buffer = "typed so far"
    repl, *_ = _repl(tmp_path, monkeypatch, readline_module=rl)
    with pytest.raises(KeyboardInterrupt):
        repl._on_sigint(2, None)
    assert repl._draft_at_interrupt == "typed so far"


# ── persistent history ────────────────────────────────────────────────────────

def test_history_file_is_owner_only_and_keeps_multiline_entries(tmp_path):
    path = tmp_path / "cli" / "chat_history.jsonl"
    assert R.append_history(path, "one")
    assert R.append_history(path, "two\nlines")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert R.load_history(path) == ["one", "two\nlines"]


def test_history_never_keeps_a_secret_looking_line(tmp_path):
    path = tmp_path / "h.jsonl"
    assert not R.append_history(path, "my key is sk-abcdefghijklmnop1234")
    assert R.load_history(path) == []


def test_a_readable_history_file_is_repermissioned_and_bad_rows_skipped(tmp_path):
    path = tmp_path / "h.jsonl"
    path.write_text('"ok"\nnot json\n42\n"also"\n', encoding="utf-8")
    os.chmod(path, 0o644)
    assert R.load_history(path) == ["ok", "also"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_history_is_bounded(tmp_path):
    path = tmp_path / "h.jsonl"
    for index in range(12):
        R.append_history(path, f"m{index}", limit=5)
    assert R.load_history(path) == [f"m{index}" for index in range(7, 12)]


def test_no_history_keeps_no_file(tmp_path, monkeypatch):
    repl, *_ = _repl(tmp_path, monkeypatch, history=False)
    repl.submit("hello")
    assert repl.history_file is None
    assert not (tmp_path / "home" / "cli").exists()


# ── $EDITOR ───────────────────────────────────────────────────────────────────

def test_editor_gets_an_owner_only_temp_file_that_is_removed(tmp_path):
    seen = {}

    def run(argv, path):
        seen["argv"], seen["path"] = argv, path
        seen["mode"] = stat.S_IMODE(os.stat(path).st_mode)
        seen["before"] = Path(path).read_text(encoding="utf-8")
        Path(path).write_text("edited text\n", encoding="utf-8")
        return 0

    got = R.compose_in_editor({"EDITOR": "myeditor --wait"}, "draft", err=io.StringIO(), run=run)
    assert got == "edited text"
    assert seen["argv"] == ["myeditor", "--wait"] and seen["mode"] == 0o600 and seen["before"] == "draft"
    assert not os.path.exists(seen["path"])


def test_an_editor_that_fails_leaves_the_draft(tmp_path):
    err = io.StringIO()
    assert R.compose_in_editor({"EDITOR": "x"}, "d", err=err, run=lambda a, p: 3) is None
    assert "exited 3" in err.getvalue()

    def missing(argv, path):
        raise FileNotFoundError(argv[0])

    assert R.compose_in_editor({"EDITOR": "nope"}, "d", err=err, run=missing) is None
    assert "not found" in err.getvalue()


def test_slash_edit_prefills_the_next_draft(tmp_path, monkeypatch):
    rl = FakeReadline()
    repl, *_ = _repl(tmp_path, monkeypatch, readline_module=rl)
    monkeypatch.setattr(R, "compose_in_editor", lambda env, draft, err: draft.upper())
    repl.local("/edit hello there")
    assert repl._prefill == "HELLO THERE"


# ── the queue and the turn worker ─────────────────────────────────────────────

def test_messages_typed_while_a_turn_runs_are_queued_and_managed(tmp_path, monkeypatch):
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch)
    repl.running = True
    repl.submit("one")
    repl.submit("two")
    repl.submit("three")
    assert [item.message for item in repl.queue] == ["one", "two", "three"]
    assert "(queued: 3 waiting" in err.getvalue()
    repl.local("/queue drop 2")
    assert [item.message for item in repl.queue] == ["one", "three"]
    repl.local("/queue")
    assert "1. one" in err.getvalue() and "2. three" in err.getvalue()
    repl.local("/queue clear")
    assert not repl.queue


def test_the_worker_sends_in_order_adopts_the_session_and_sanitises(tmp_path, monkeypatch):
    sent = []

    def chat(body):
        sent.append(dict(body))
        return {"reply": f"re: {body['message']}\x1b]0;title\x07", "session_id": "web_abc",
                "pending_approvals": [7] if body["message"] == "two" else [],
                "notices": [{"code": "turn_interrupted", "text": "You stopped\x1b[2J this turn"}]}

    hub = FakeHub({("POST", "/chat"): chat, ("GET", "/chat/pending"): {"questions": []}})
    repl, hub, out, err = _repl(tmp_path, monkeypatch, hub, agent="athena")
    repl.submit("one")
    repl.submit("two")
    import threading

    worker = threading.Thread(target=repl._work, daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    while (repl.queue or repl.running or len(sent) < 2) and time.monotonic() < deadline:
        time.sleep(0.02)
    repl.stopped = True
    worker.join(5)
    assert [b["message"] for b in sent] == ["one", "two"]
    assert "session_id" not in sent[0] and sent[1]["session_id"] == "web_abc"
    assert sent[0]["agent"] == "athena"
    assert "re: one" in out.getvalue() and "\x1b" not in out.getvalue()
    assert "\x1b" not in err.getvalue() and "ℹ You stopped" in err.getvalue()
    assert ("approvals", [7]) in repl.asks


def test_a_question_mid_turn_is_handed_to_the_keyboard_thread(tmp_path, monkeypatch):
    import threading

    gate = threading.Event()

    def chat(body):
        gate.wait(5)
        return {"reply": "done"}

    question = {"id": "a" * 32, "kind": "clarify", "question": "Which?"}
    hub = FakeHub({("POST", "/chat"): chat, ("GET", "/chat/pending"): {"questions": [question]}})
    repl, *_rest = _repl(tmp_path, monkeypatch, hub)
    monkeypatch.setattr("agents.cli.chat_prompts.POLL_SECONDS", 0.01)
    worker = threading.Thread(target=repl.run_turn, args=(R.Outgoing("hi"),), daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while not repl.asks and time.monotonic() < deadline:
        time.sleep(0.01)
    gate.set()
    worker.join(5)
    assert list(repl.asks) == [("question", question)]          # asked once, not per poll
    answered = []
    monkeypatch.setattr("agents.cli.chat_prompts._answer_clarify",
                        lambda ctx, client, q, sid=None: answered.append(q["id"]))
    repl.answer_asks()
    assert answered == [question["id"]] and not repl.asks


def test_staged_images_make_the_next_message_a_vision_turn(tmp_path, monkeypatch):
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    repl, *_ = _repl(tmp_path, monkeypatch)
    repl.local(f"/image {png}")
    repl.local("/paste-image")
    repl.submit("what is this?")
    item = repl.queue.popleft()
    assert item.images == [str(png)] and item.clipboard_image is True
    assert repl.staged_images == [] and repl.staged_clipboard is False
    seen = {}
    monkeypatch.setattr("agents.cli.nerva._vision_turn",
                        lambda ns, ctx, message, **kw: seen.update(ns=ns, message=message))
    repl.run_turn(item)
    assert seen["message"] == "what is this?" and seen["ns"].image == [str(png)]
    assert seen["ns"].session is None and seen["ns"].agent is None


def test_a_non_image_is_not_attached(tmp_path, monkeypatch):
    bad = tmp_path / "x.png"
    bad.write_text("#!/bin/sh\n", encoding="utf-8")
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch)
    repl.local(f"/image {bad}")
    assert repl.staged_images == [] and "not attached" in err.getvalue()


# ── session switcher and model picker ─────────────────────────────────────────

def test_session_switcher_lists_and_switches_only_listed_sessions(tmp_path, monkeypatch):
    hub = FakeHub({("GET", "/sessions"): {"sessions": [
        {"session_id": "web_a", "title": "Plans\x1b[31m"}, {"session_id": "web_b", "title": "B"},
        {"session_id": "bad id!", "title": "x"}]}})
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch, hub)
    repl.local("/switch")
    text = err.getvalue()
    assert "1. web_a  Plans" in text and "2. web_b" in text and "bad id" not in text and "\x1b" not in text
    repl.local("/switch 2")
    assert repl.session_id == "web_b"
    repl.local("/switch web_zzz")
    assert repl.session_id == "web_b" and "not one of your sessions" in err.getvalue()
    repl.local("/switch new")
    assert repl.session_id is None


def test_model_picker_offers_only_switchable_local_models(tmp_path, monkeypatch):
    switched = []
    hub = FakeHub({
        ("GET", "/api/models/local"): {"models": [
            {"id": "qwen", "provider": "ollama", "available": True, "active": True},
            {"id": "gone", "provider": "lm-studio", "available": False},
            {"id": "mystery", "provider": "unknown", "available": None},
            {"id": "llama", "provider": "lm-studio", "available": True}]},
        ("POST", "/api/models/local/switch"): lambda body: switched.append(body) or {"active": body["model"]},
    })
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch, hub)
    repl.local("/model")
    text = err.getvalue()
    assert "* 1. qwen" in text and "2. llama" in text and "gone" not in text and "mystery" not in text
    repl.local("/model 2")
    assert switched == [{"model": "llama", "provider": "lm-studio"}]
    repl.local("/model gone")
    assert len(switched) == 1


def test_model_picker_without_the_owners_credential_says_so(tmp_path, monkeypatch):
    hub = FakeHub({("GET", "/api/models/local"): HubError(403, "admin")})
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch, hub)
    repl.local("/model 1")
    assert "only the owner picks the model" in err.getvalue()
    assert [c for c in hub.calls if c[0] == "POST"] == []


# ── the verb ──────────────────────────────────────────────────────────────────

def test_chat_dash_i_is_parsed_and_refuses_a_script_shape():
    ns = build_parser().parse_args(["chat", "-i"])
    assert ns.interactive is True and ns.no_history is False
    err = io.StringIO()
    ctx = Context(environ={}, out=io.StringIO(), err=err, inp=io.StringIO("x"),
                  client_factory=lambda env: FakeHub())
    assert main(["chat", "-i", "hello"], context=ctx) == EXIT_USAGE
    assert "MESSAGE" in err.getvalue()
    err.truncate(0)
    assert main(["chat", "-i"], context=ctx) == EXIT_USAGE      # stdin is not a terminal
    assert "needs a terminal" in err.getvalue()


def test_chat_help_names_the_interactive_chat():
    text = build_parser()._subparsers._group_actions[0].choices["chat"].format_help()
    assert "--interactive" in text and "nerva chat -i" in text


# ── the interrupt route (real app, two credentials) ───────────────────────────

def test_turn_registry_interrupts_only_the_named_actor():
    from agents.core import turn_interrupts as T

    async def scenario():
        started = asyncio.Event()

        async def turn(actor, session):
            with T.track(actor, session) as live:
                started.set()
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    assert T.absorb(live)
                    return "interrupted"
            return "finished"

        mine = asyncio.create_task(turn("actor-a", "s1"))
        await started.wait()
        assert T.interrupt("actor-b") == 0 and T.interrupt(None) == 0
        assert T.interrupt("actor-a", "other-session") == 0
        assert T.running("actor-a") == 1
        assert T.interrupt("actor-a", "s1") == 1
        assert await asyncio.wait_for(mine, 2) == "interrupted"
        assert T.running("actor-a") == 0
        assert not asyncio.current_task().cancelling()

    asyncio.run(scenario())


def test_a_cancel_from_elsewhere_is_not_absorbed():
    from agents.core import turn_interrupts as T

    async def scenario():
        async def turn():
            with T.track("actor", "s") as live:
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    assert not T.absorb(live)
                    raise

        task = asyncio.create_task(turn())
        await asyncio.sleep(0)
        task.cancel()                       # a disconnect, a shutdown
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_interrupt_route_stops_only_the_callers_own_turn(tmp_path, monkeypatch):
    from agents.core.security.token_store import TokenStore
    from agents.core.turn_interrupts import INTERRUPTED_REPLY, NOTICE_CODE
    from tests.test_h226_cli_governance_prompts import _host

    store = TokenStore(str(tmp_path / "tokens.db"))
    owner, stranger = store.issue("user"), store.issue("user")
    orch, _cap, stream = await _host(tmp_path, monkeypatch, store=store)
    entered = asyncio.Event()

    async def model(*_args, **_kwargs):
        entered.set()
        await asyncio.sleep(60)
        return "never"

    orch.handle_input = model
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            turn = asyncio.create_task(client.post("/chat", json={"message": "long job"},
                                                   headers={"x-user-token": owner}))
            await asyncio.wait_for(entered.wait(), 5)
            other = await client.post("/chat/interrupt", json={}, headers={"x-user-token": stranger})
            assert other.status_code == 200 and other.json()["interrupted"] == 0
            anonymous = await client.post("/chat/interrupt", json={})
            assert anonymous.status_code in (401, 403)
            bad = await client.post("/chat/interrupt", json={"session_id": "../x"},
                                    headers={"x-user-token": owner})
            assert bad.status_code == 422
            extra = await client.post("/chat/interrupt", json={"turn": 1}, headers={"x-user-token": owner})
            assert extra.status_code == 422
            assert not turn.done()
            mine = await client.post("/chat/interrupt", json={}, headers={"x-user-token": owner})
            assert mine.status_code == 200 and mine.json()["interrupted"] == 1
            response = await asyncio.wait_for(turn, 5)
        assert response.status_code == 200
        body = response.json()
        assert body["reply"] == INTERRUPTED_REPLY
        assert [n["code"] for n in body["notices"]] == [NOTICE_CODE]
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
        store._conn.close()


# ── the real readline, through a pseudo-terminal ──────────────────────────────

_CHILD = textwrap.dedent("""
    import io, json, sys
    sys.path.insert(0, {root!r})
    from agents.cli import repl as R
    from agents.cli.nerva import Context

    class Hub:
        base_url = "http://127.0.0.1:8080"
        def get(self, path):
            if path.startswith("/api/commands"):
                return {{"commands": [{{"command": "/recap"}}]}}
            return {{"questions": []}}
        def post(self, path, body=None, *, timeout=None):
            if path == "/chat":
                print("SENT " + json.dumps(body["message"]), flush=True)
                return {{"reply": "ok"}}
            return {{}}

    ctx = Context(environ={{}}, out=sys.stdout, err=sys.stdout, inp=sys.stdin,
                  client_factory=lambda env: Hub())
    code = R.Repl(ctx, history=True, readline_module=R.load_readline()).run()
    print("EXITED", code, flush=True)
""")


def _drive(tmp_path, keystrokes):
    pty = pytest.importorskip("pty")
    import select

    readline = R.load_readline()
    if readline is None or "libedit" in (readline.__doc__ or ""):
        pytest.skip("GNU readline is not available")
    script = tmp_path / "child.py"
    script.write_text(_CHILD.format(root=str(Path(__file__).resolve().parents[1])), encoding="utf-8")
    env = {**os.environ, "JARVIS_HOME": str(tmp_path / "home"), "TERM": "xterm", "INPUTRC": "/dev/null"}
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover — the child
        os.execve(sys.executable, [sys.executable, str(script)], env)

    def read(wait=0.6):
        out, deadline = b"", time.monotonic() + wait
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
        return out.decode("utf-8", "replace")

    transcript = read(2.0)
    for keys in keystrokes:
        os.write(fd, keys)
        transcript += read()
    transcript += read(1.0)
    with __import__("contextlib").suppress(ChildProcessError):
        os.waitpid(pid, 0)
    os.close(fd)
    return transcript


def test_real_terminal_keys(tmp_path):
    transcript = _drive(tmp_path, [
        b"hello",           # a draft …
        b"\x03",            # … Ctrl+C clears it
        b"a\x1b\rb\r",      # Alt+Enter is a newline; Enter sends one message
        b"zz\x1b\x1bq\r",   # Esc Esc discards the draft
        b"\x1b[200~x\ny\x1b[201~\r",   # a bracketed multi-line paste is one message
        b"/rec\t\r",        # Tab completes the hub's command
        b"\x03",            # idle, empty: arm
        b"\x03",            # again: exit
    ])
    assert "(draft cleared)" in transcript
    assert 'SENT "a\\nb"' in transcript
    assert 'SENT "q"' in transcript and 'SENT "zz' not in transcript
    assert 'SENT "x\\ny"' in transcript
    assert 'SENT "/recap"' in transcript
    assert "press Ctrl+C again" in transcript
    assert "EXITED 0" in transcript
    history = tmp_path / "home" / "cli" / "chat_history.jsonl"
    assert stat.S_IMODE(history.stat().st_mode) == 0o600
    assert json.loads(history.read_text().splitlines()[0]) == "a\nb"
