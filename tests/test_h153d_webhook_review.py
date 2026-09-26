"""H153 fourth review round (review-H153d): a push cannot freeze the hub, and the
sender's text arrives as it was written.

The fourth review found:

- MAJOR: a push rendered the whole untrimmed text with ``to_plain`` and only then cut it.
  The renderer's regexes are quadratic on one long line and hold the GIL on the event
  loop, so one GitHub issue of 65,536 ``[`` froze the whole hub for about 40 s.
- ``to_plain`` rewrote the sender's addresses and file names (``pkg/__init__.py`` became
  ``pkg/init.py``), and ntfy got it twice.
- A fresh receiver refused a burst of deliveries while its first read ran.
- A workflow hook answered 500 after its push when the run's context held a lone
  surrogate or a NaN, and its answer echoed the whole context to the sender.
- Bidi overrides and zero-width characters reached the owner's phone.
- Twelve behaviours no test pinned: the receiver re-read after the turn when it cannot be
  read, a Telegram refusal of a push, the hour of the push allowance, quiet hours and the
  allowance, the live label, a non-dict workflow result, an overtaken failed read, a
  slider's audited value.

These tests pin each fix.
"""
import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from tests.test_h10_8_webhooks import _ADMIN, _hook, hub  # noqa: F401  (hub is a fixture)
from tests.test_h153b_webhook_delivery import (  # noqa: F401  (receiver is a fixture)
    _listed,
    _post,
    receiver,
)
from tests.test_h153c_webhook_sends import _at, _TelegramHttp, _workflow, clock, owner  # noqa: F401


def _plain_post(client, hook, text: str):
    """A delivery whose body is the text itself (text/plain), as a CI system sends it."""
    return client.post(f"/api/webhooks/{hook['id']}", content=text.encode("utf-8"),
                       headers={"X-Webhook-Token": hook["token"], "Content-Type": "text/plain"})


def _body(sent: dict) -> str:
    """What a recording adapter was handed, without the subject line Telegram carries."""
    text = sent["text"]
    return text.split("\n\n", 1)[1] if "title" not in sent else text


# ── MAJOR: a push is never rendered, so one long line cannot stall the loop ─────

@pytest.mark.parametrize("channel", ("telegram", "ntfy"))
def test_a_long_line_of_brackets_is_pushed_at_once(owner, channel):
    """32,000 ``[`` took the old path about 9 s of a frozen event loop."""
    (client, _events, _turns), adapters = owner
    hook = _hook(client, name="gh", deliver=channel, deliver_only=True)
    started = time.perf_counter()
    reply = _plain_post(client, hook, "[" * 32_000)
    took = time.perf_counter() - started
    assert reply.status_code == 200 and reply.json()["delivery"] == {"channel": channel, "ok": True}
    assert took < 1.0
    body = _body(adapters[channel].sent[0])
    assert body.startswith("[" * 1_000) and body.endswith("… (cut: the rest was not kept)")


@pytest.mark.parametrize("channel", ("telegram", "ntfy"))
def test_a_senders_text_arrives_as_written(owner, channel):
    """No markup is rendered and nothing is rewritten: a file name, an address with
    underscores or asterisks, and a Markdown link all arrive exactly as sent."""
    (client, _events, _turns), adapters = owner
    text = ("pkg/__init__.py, app/_utils_/x.py https://github.com/o/r/blob/main/pkg/__init__.py "
            "https://x.example/*draft*/notes **kept** [Sign in](https://login.example/o) `code`")
    hook = _hook(client, name="gh", deliver=channel, deliver_only=True)
    assert _post(client, hook, {"text": text}).json()["delivery"] == {"channel": channel, "ok": True}
    sent = adapters[channel].sent[0]
    assert _body(sent) == text and sent["plain"] is True


def test_a_spoken_push_reads_the_text_without_its_markup(owner):
    """Voice is the one channel where markup is noise: the words are spoken, not the
    asterisks, and a link says where it goes."""
    (client, _events, _turns), adapters = owner
    hook = _hook(client, name="ci", deliver="voice", deliver_only=True)
    _post(client, hook, {"text": "**build** [log](https://ci.example/1) done"})
    assert adapters["voice"].sent == [{"text": "Webhook ci\n\nbuild log (https://ci.example/1) done"}]


async def test_the_ntfy_adapter_sends_a_plain_push_as_it_is():
    from agents.core.channels.ntfy import NtfyChannel

    class _Http:
        def __init__(self):
            self.bodies = []

        async def post(self, url, content=None, headers=None, **kwargs):
            self.bodies.append(content.decode("utf-8"))
            return SimpleNamespace(raise_for_status=lambda: None)

        async def aclose(self):
            pass

    text = "pkg/__init__.py **kept** [a](https://b.example)"
    plain = NtfyChannel("https://ntfy.example", "topic", client=_Http())
    assert await plain.send(text, title="t", plain=True) is True
    assert plain.client.bodies == [text]
    rendered = NtfyChannel("https://ntfy.example", "topic", client=_Http())
    assert await rendered.send("**kept**", title="t") is True
    assert rendered.client.bodies == ["kept"]                 # a reply is still rendered


def test_characters_that_hide_or_reorder_text_are_dropped_from_a_push(owner):
    (client, _events, _turns), adapters = owner
    hook = _hook(client, name="issues", deliver="telegram", deliver_only=True)
    family = "\U0001F468‍\U0001F469‍\U0001F467"          # joined by ZWJ: kept whole
    text = (f"invoice ‮fdp.exe https://x.example/​login ⁦iso⁩ ﻿bom\x07\r\n"
            f"next\tline ­soft {family}")
    _post(client, hook, {"text": text, "event": "issu‮es"})
    head, body = adapters["telegram"].sent[0]["text"].split("\n\n", 1)
    assert body == f"invoice fdp.exe https://x.example/login iso bom\nnext\tline soft {family}"
    assert "‮" not in head


@pytest.mark.parametrize("text", [
    "[" * 16_000, "**a " * 4_000, "*a " * 5_400, "_a " * 5_400, "__a " * 4_000,
    "# x" + " " * 16_000 + "y", "# x" + "#" * 16_000 + "y", "[a](https://" * 3_000,
], ids=["brackets", "bold", "italic", "underscore", "bold-underscore", "heading-spaces", "heading-hashes",
        "link-urls"])
@pytest.mark.parametrize("render", ["to_plain", "to_telegram_html", "to_slack_mrkdwn"])
def test_rendering_one_long_line_costs_linear_time(text, render):
    """Every other caller of the renderers (a model's reply, a streamed preview) still
    renders; a marker span is bounded, so one long line costs linear time."""
    from agents.core.channels import render as renderers

    started = time.perf_counter()
    getattr(renderers, render)(text)
    assert time.perf_counter() - started < 0.5


def test_a_bounded_span_still_renders_the_markup_it_did():
    from agents.core.channels.render import to_plain, to_telegram_html

    assert to_plain("**bold** *it* _it_ __b__ [a](https://x.example) # h") == "bold it it b a (https://x.example) # h"
    assert to_plain("## Title ##") == "Title"
    assert to_telegram_html("**" + "b" * 400 + "**") == "<b>" + "b" * 400 + "</b>"
    long_span = "**" + "b" * 2_000 + "**"
    assert to_plain(long_span) == long_span                 # past the bound it is left as written


# ── the receiver's first read: a burst waits for it ─────────────────────────────

async def test_a_burst_on_a_fresh_receiver_waits_for_its_first_read(hub, receiver, monkeypatch):
    from agents import web
    from agents.core import settings_db, webhooks

    client, _events, turns = hub
    hook = _hook(client)
    real = settings_db.read_setting

    def slow(category, key):
        time.sleep(0.2)
        return real(category, key)

    monkeypatch.setattr(settings_db, "read_setting", slow)
    webhooks.RECEIVER.reset()                     # a hub that just started
    transport = httpx.ASGITransport(app=web.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub") as ac:
        answers = await asyncio.gather(*[
            ac.post(f"/api/webhooks/{hook['id']}", json={"text": f"n{i}"},
                    headers={"X-Webhook-Token": hook["token"]}) for i in range(10)])
    assert [answer.status_code for answer in answers] == [200] * 10
    assert sorted(turns) == sorted(f"n{i}" for i in range(10))


def test_a_caller_with_nothing_known_waits_for_the_first_read_but_not_forever(receiver, monkeypatch):
    import threading

    from agents.core import settings_db, webhooks

    switch = webhooks.ReceiverSwitch()
    switch.first_read_wait = 0.3
    release = threading.Event()
    started = threading.Event()

    def held(category, key):
        started.set()
        release.wait(5)
        return (True, False)

    monkeypatch.setattr(settings_db, "read_setting", held)
    first = threading.Thread(target=switch.state)
    first.start()
    try:
        assert started.wait(5)
        began = time.monotonic()
        assert switch.state() is None                           # the read still runs: fail closed
        assert 0.25 <= time.monotonic() - began < 2
        switch.first_read_wait = 30.0
        answer = {}

        def wait():
            answer["state"] = switch.state()
            answer["at"] = time.monotonic()

        waiter = threading.Thread(target=wait)
        waiter.start()
        time.sleep(0.05)
        landed = time.monotonic()
        release.set()                                           # the first read lands: off
        waiter.join(5)
        assert answer["state"] is False and answer["at"] - landed < 1.0   # woken when it lands
    finally:
        release.set()
        first.join(5)


def test_a_caller_with_a_state_known_never_waits_for_a_read(receiver, monkeypatch):
    import threading

    from agents.core import settings_db, webhooks

    switch = webhooks.ReceiverSwitch(ttl=0.0)
    switch.first_read_wait = 30.0
    switch.written(False)                                      # a state is known: off
    release, started = threading.Event(), threading.Event()

    def held(category, key):
        started.set()
        release.wait(5)
        return (True, True)

    monkeypatch.setattr(settings_db, "read_setting", held)
    first = threading.Thread(target=switch.state)
    first.start()
    try:
        assert started.wait(5)
        began = time.monotonic()
        assert [switch.state() for _ in range(5)] == [False] * 5    # the last state, at once
        assert time.monotonic() - began < 0.5
    finally:
        release.set()
        first.join(5)


def test_the_hub_waits_for_a_first_read_by_default():
    from agents.core import webhooks

    assert 0 < webhooks.RECEIVER_FIRST_READ_WAIT <= 5
    assert webhooks.ReceiverSwitch().first_read_wait == webhooks.RECEIVER_FIRST_READ_WAIT


# ── a workflow hook: its answer carries no run context, and always encodes ──────

def test_a_workflow_answer_names_the_steps_and_echoes_no_context(owner, monkeypatch):
    (client, _events, _turns), adapters = owner
    _workflow(monkeypatch, {"fetch": "the owner's calendar: dentist at 9", "summarize": "the digest",
                            "_ok": True, "_structured": {"fetch": {"data": {"score": float("nan")}}}})
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": "the week \ud800"})
    assert reply.status_code == 200
    assert reply.json() == {"ok": True, "target": "digest", "steps": ["fetch", "summarize"],
                            "delivery": {"channel": "telegram", "ok": True}}
    assert "calendar" not in reply.text and len(adapters["telegram"].sent) == 1


def test_a_real_workflow_whose_output_holds_nan_answers_200(owner, monkeypatch):
    from agents.core.routers import workflows
    from agents.core.workflows.pipeline import Pipeline

    (client, _events, _turns), adapters = owner
    pipeline = Pipeline.from_dict({"id": "digest", "name": "digest", "steps": [
        {"id": "score", "agent_id": "_passthrough", "prompt_template": "{_input}",
         "output_schema": {"fields": {"score": {"type": "float"}}}},
        {"id": "summarize", "agent_id": "_passthrough", "prompt_template": "summary of {_input}",
         "depends_on": ["score"]}]})
    monkeypatch.setattr(workflows, "resolve_pipeline", lambda orch, target: pipeline)
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": '{"score": NaN}'})
    assert reply.status_code == 200 and reply.json()["delivery"] == {"channel": "telegram", "ok": True}
    assert len(adapters["telegram"].sent) == 1


def test_a_real_workflow_whose_input_holds_a_lone_surrogate_answers_200(owner, monkeypatch):
    from agents.core.routers import workflows
    from agents.core.workflows.pipeline import Pipeline

    (client, _events, _turns), adapters = owner
    pipeline = Pipeline.from_dict({"id": "digest", "name": "digest", "steps": [
        {"id": "summarize", "agent_id": "_passthrough", "prompt_template": "{_input}"}]})
    monkeypatch.setattr(workflows, "resolve_pipeline", lambda orch, target: pipeline)
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = client.post(f"/api/webhooks/{hook['id']}", content=b'{"text": "the week \\ud800"}',
                        headers={"X-Webhook-Token": hook["token"], "Content-Type": "application/json"})
    assert reply.status_code == 200 and reply.json()["delivery"] == {"channel": "telegram", "ok": True}
    assert adapters["telegram"].sent[0]["text"].endswith("the week �")


def test_an_agent_reply_with_a_lone_surrogate_answers_200(owner, monkeypatch):
    from agents.core.app_state import get_orch

    (client, _events, _turns), adapters = owner

    async def reply(text, **kwargs):
        return "done \udc80"

    monkeypatch.setattr(get_orch(), "handle_input", reply)
    hook = _hook(client, deliver="telegram")
    answer = _post(client, hook, {"text": "hi"})
    assert answer.status_code == 200 and answer.json()["response"] == "done �"
    assert adapters["telegram"].sent[0]["text"].endswith("done �")


def test_an_agent_reply_that_is_not_text_answers_200_whatever_it_holds(owner, monkeypatch):
    from agents.core.app_state import get_orch

    (client, _events, _turns), adapters = owner

    async def reply(text, **kwargs):
        return {"score": float("nan"), "note": "x \ud800", "items": [float("inf"), 1.5], "k\udc80": 1}

    monkeypatch.setattr(get_orch(), "handle_input", reply)
    hook = _hook(client, deliver="telegram")
    answer = _post(client, hook, {"text": "hi"})
    assert answer.status_code == 200
    assert answer.json()["response"] == {"score": None, "note": "x \ufffd", "items": [None, 1.5], "k\ufffd": 1}


@pytest.mark.parametrize("result", [["not", "a", "dict"], None, "text"])
def test_a_workflow_that_returns_no_result_delivers_nothing_and_says_so(owner, monkeypatch, result):
    from agents.core.app_state import get_orch
    from agents.core.routers import workflows

    (client, _events, _turns), adapters = owner

    async def run(pipeline, initial_input=""):
        return result

    monkeypatch.setattr(get_orch().workflow_engine, "run", run)
    monkeypatch.setattr(workflows, "resolve_pipeline",
                        lambda orch, target: SimpleNamespace(steps=[SimpleNamespace(id="s")]))
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": "x"})
    assert reply.status_code == 200 and reply.json()["ok"] is False
    reason = "the workflow returned no result"
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False, "reason": reason}
    assert adapters["telegram"].sent == [] and _listed(client, hook["id"])["last_delivery"]["reason"] == reason


def test_a_failed_run_with_an_odd_error_list_is_recorded_not_a_500(owner, monkeypatch):
    (client, _events, _turns), adapters = owner
    _workflow(monkeypatch, {"summarize": "x", "_ok": False, "_errors": 3}, steps=("summarize",))
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": "x"})
    assert reply.status_code == 200 and reply.json()["ok"] is False
    assert reply.json()["delivery"]["reason"] == "the workflow run failed: nothing delivered"


def test_a_workflow_output_that_cannot_be_read_is_recorded_not_a_500(owner, monkeypatch):
    from agents.core.routers import webhooks as router

    (client, _events, _turns), adapters = owner
    _workflow(monkeypatch, {"summarize": "the digest", "_ok": True}, steps=("summarize",))

    def broken(pipeline, result):
        raise RuntimeError("a bug")

    monkeypatch.setattr(router, "_workflow_output", broken)
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": "x"})
    assert reply.status_code == 200
    reason = "the workflow's output could not be read: nothing delivered"
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False, "reason": reason}
    assert adapters["telegram"].sent == []


def test_the_last_step_is_the_last_to_run_not_the_last_listed(owner, monkeypatch):
    """A pipeline listed out of dependency order still delivers what ran last."""
    from agents.core.routers import workflows
    from agents.core.workflows.pipeline import Pipeline

    (client, _events, _turns), adapters = owner
    pipeline = Pipeline.from_dict({"id": "digest", "name": "digest", "steps": [
        {"id": "summarize", "agent_id": "_passthrough", "prompt_template": "SUMMARY", "depends_on": ["fetch"]},
        {"id": "fetch", "agent_id": "_passthrough", "prompt_template": "RAW: {_input}"}]})
    monkeypatch.setattr(workflows, "resolve_pipeline", lambda orch, target: pipeline)
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": "click [here](https://x.example)"})
    assert reply.json()["steps"] == ["fetch", "summarize"]
    assert adapters["telegram"].sent[0]["text"].endswith("\n\nSUMMARY")


# ── what the third review's mutants showed no test pinned ───────────────────────

def test_a_receiver_that_cannot_be_read_after_the_turn_stops_the_push(owner, monkeypatch):
    from agents.core import webhooks

    (client, _events, turns), adapters = owner
    hook = _hook(client, deliver="telegram")
    real = webhooks.RECEIVER.astate
    reads = []

    async def astate():
        reads.append(1)
        return None if len(reads) >= 3 else await real()   # the read after the turn cannot be made

    monkeypatch.setattr(webhooks.RECEIVER, "astate", astate)
    reply = _post(client, hook, {"text": "hi"})
    assert reply.status_code == 200 and turns == ["hi"]
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False,
                                        "reason": "the webhook receiver's state cannot be read: not sent"}
    assert adapters["telegram"].sent == []


def test_a_telegram_refusal_of_a_push_is_recorded_as_a_refusal(hub, monkeypatch, clock):
    from agents.core import webhooks
    from agents.core.app_state import get_orch
    from agents.core.channels.manager import ChannelManager
    from agents.core.channels.telegram import TelegramChannel

    client, _events, _turns = hub

    class _Forbidden(_TelegramHttp):
        async def post(self, url, json=None, **kwargs):
            self.posts.append((url, dict(json or {})))
            request = httpx.Request("POST", "https://api.telegram.org/bot/sendMessage")
            response = httpx.Response(403, request=request)
            return SimpleNamespace(status_code=403, raise_for_status=response.raise_for_status)

    telegram = TelegramChannel("tok")
    telegram.client = _Forbidden()
    manager = ChannelManager()
    manager.register(telegram)
    monkeypatch.setattr(get_orch(), "channel_manager", manager)
    monkeypatch.setenv("AUTONOMY_OWNER_CHAT_ID", "4242")
    webhooks.PUSHES.reset()
    hook = _hook(client, deliver="telegram", deliver_only=True)
    reply = _post(client, hook, {"text": "hi"})
    assert len(telegram.client.posts) == 1
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False, "reason": "telegram refused the message"}
    assert _listed(client, hook["id"])["last_delivery"]["ok"] is False


def test_the_push_allowance_is_thirty_an_hour():
    from agents.core import webhooks

    now = {"t": 0.0}
    allowance = webhooks.PushLimit(clock=lambda: now["t"])      # the module's own limit and window
    assert [allowance.allow("h") for _ in range(31)] == [True] * 30 + [False]
    for later in (61.0, 3_599.0):
        now["t"] = later
        assert allowance.allow("h") is False
    now["t"] = 3_600.0
    assert allowance.allow("h") is True
    assert (webhooks.PUSHES.limit, webhooks.PUSHES.window) == (30, 3_600.0)


def test_a_push_held_by_quiet_hours_spends_no_allowance(owner, clock, monkeypatch):
    from agents.core import webhooks

    (client, _events, _turns), adapters = owner
    monkeypatch.setattr(webhooks, "PUSHES", webhooks.PushLimit(clock=lambda: 0.0))
    hook = _hook(client, deliver="telegram", deliver_only=True)
    clock["t"] = _at(3)
    held = [_post(client, hook, {"text": f"n{i}"}).json()["delivery"]["reason"] for i in range(35)]
    assert all(reason.startswith("quiet hours") for reason in held)
    clock["t"] = _at(15)
    assert [_post(client, hook, {"text": f"d{i}"}).json()["delivery"]["ok"] for i in range(30)] == [True] * 30


def test_the_label_is_the_hooks_name_when_it_is_pushed(owner, monkeypatch):
    from agents.core.app_state import get_orch
    from agents.core.routers import webhooks as router

    (client, _events, _turns), adapters = owner
    hook = _hook(client, name="old", deliver="telegram")

    async def turn(text, **kwargs):
        router._webhook_store._hooks[hook["id"]]["name"] = "renamed"   # the record changed meanwhile
        return "done"

    monkeypatch.setattr(get_orch(), "handle_input", turn)
    _post(client, hook, {"text": "hi"})
    assert adapters["telegram"].sent[0]["text"].startswith("Webhook renamed\n\n")


def test_a_failed_read_that_a_reseed_overtook_sets_no_back_off(receiver, monkeypatch):
    from agents.core import settings_db, webhooks

    switch = webhooks.ReceiverSwitch()
    reads = []

    def read(category, key):
        reads.append(1)
        if len(reads) == 1:
            switch.expire()                          # a reseed lands while this read runs
            raise settings_db.SettingsUnreadable("database is locked")
        return (True, False)                         # the reseeded store: off

    monkeypatch.setattr(settings_db, "read_setting", read)
    assert switch.state() is None                    # nothing known, and that read failed
    assert switch.state() is False                   # read again at once, not a second later
    assert len(reads) == 2


def test_a_slider_value_is_audited(hub, receiver):
    client, events, _turns = hub
    reply = client.put("/api/admin/settings/llm", json={"values": {"temperature": 0.3}}, headers=_ADMIN)
    assert reply.status_code == 200
    row = [event.content_preview for event in events if event.action_taken == "settings_update"][-1]
    assert "temperature=0.3" in row


# ── quiet hours read from a setting that is not an hour ─────────────────────────

@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), "x", None, [3]])
def test_an_hour_setting_that_is_not_a_number_falls_back_to_the_default(monkeypatch, bad):
    from agents.core.autonomy.jobs import JobRunner
    from agents.core.routers import webhooks as router

    orch = SimpleNamespace(get_setting=lambda key, default=None: bad if key.endswith("start") else default)
    monkeypatch.setattr(router, "_now", lambda: _at(23))
    assert router._quiet_hours(orch) is True                  # 22 to 7, the defaults
    runner = JobRunner.__new__(JobRunner)
    runner._quiet, runner._orch, runner._now = None, orch, lambda: _at(23)
    assert runner.quiet_hours() is True


# ── web is never listed as ready: nothing receives it ───────────────────────────

def test_web_is_not_ready_while_no_client_is_connected():
    from agents.core.channels import outbound
    from agents.core.channels.web import WebChannel

    web_channel = WebChannel()
    orch = SimpleNamespace(channels={"web": web_channel}, get_setting=lambda key, default=None: default)
    rows = {row["channel"]: row for row in outbound.configured_targets(orch)}
    assert rows["web"]["connected"] is True and rows["web"]["ready"] is False
    assert rows["web"]["reason"] == "web has no connected client: nothing would receive it"
    web_channel.connect()
    rows = {row["channel"]: row for row in outbound.configured_targets(orch)}
    assert rows["web"]["ready"] is True
