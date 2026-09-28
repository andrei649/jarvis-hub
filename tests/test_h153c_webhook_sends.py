"""H153 third review round: Deliver to reaches the owner's channels for real.

The second review found that no delivery reached an owner channel as shipped:

- Every push to telegram, voice or ntfy answered HTTP 500 after the turn had run,
  because the quiet-hours rule imported a name that does not exist.
- ``web`` has no receiver in the hub.
- ntfy refused the label's own separator.

No test saw it, because every delivery test replaced ``send_to_target`` and the
quiet-hours rule with fakes.

These tests run the real path: the router's ``_deliver``, the real quiet-hours rule on a
fixed clock, ``send_to_target``, then ``ChannelManager.send`` and its contract, down to a
recording adapter per channel. For Telegram, they also check the real adapter's HTTP body.

They also pin the minors:

- a delivery that fails is recorded, never a 500 after the turn;
- deliver-only needs a channel;
- the text arrives as plain text (a link shows its address);
- a push is capped per hook;
- a change the owner makes during the turn reaches the push;
- a workflow delivers its last step's output or nothing, and every path after a call is
  recorded;
- the receiver is read by one request at a time;
- a typed model id and free text are audited by name only.

The rest pin the guards the review's mutants showed were untested.
"""
import threading
import time
from types import SimpleNamespace

import pytest

from agents.core.channels.manager import ChannelManager
from agents.core.webhooks import WebhookStore
from tests.test_h10_8_webhooks import _ADMIN, _hook, hub  # noqa: F401  (hub is a fixture)
from tests.test_h153b_webhook_delivery import (  # noqa: F401  (receiver is a fixture)
    _listed,
    _post,
    receiver,
)

CHANNELS = ("telegram", "voice", "ntfy")


def _at(hour: int) -> float:
    """Today at *hour* o'clock, local time."""
    return time.mktime((2026, 9, 24, hour, 0, 0, 0, 0, -1))


class _Recorder:
    """A channel adapter that keeps what it was handed and answers *answer*."""

    def __init__(self, channel_id: str, answer: bool = True) -> None:
        self.channel_id = channel_id
        self.answer = answer
        self.sent: list[dict] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, message, **kwargs):
        self.sent.append({"text": message, **kwargs})
        return self.answer


@pytest.fixture
def clock(monkeypatch):
    """The router's clock at 3 pm local time, outside the default quiet hours (22 to 7)."""
    from agents.core.routers import webhooks as router

    now = {"t": _at(15)}
    monkeypatch.setattr(router, "_now", lambda: now["t"])
    return now


@pytest.fixture
def owner(hub, monkeypatch, clock):
    """The owner's channels on a real ChannelManager, each one a recording adapter, and
    an owner chat for Telegram."""
    from agents.core import webhooks
    from agents.core.app_state import get_orch

    manager = ChannelManager()
    adapters = {name: _Recorder(name) for name in CHANNELS}
    for adapter in adapters.values():
        manager.register(adapter)
    monkeypatch.setattr(get_orch(), "channel_manager", manager)
    monkeypatch.setenv("AUTONOMY_OWNER_CHAT_ID", "4242")
    webhooks.PUSHES.reset()
    yield hub, adapters
    webhooks.PUSHES.reset()


# ── every offered channel receives a delivery ────────────────────────────────────

@pytest.mark.parametrize("channel", CHANNELS)
def test_each_offered_channel_receives_the_reply(owner, channel):
    (client, _events, turns), adapters = owner
    hook = _hook(client, name="ci", deliver=channel)
    reply = _post(client, hook, {"text": "build 12 failed"}, **{"X-GitHub-Event": "check_run"})
    assert reply.status_code == 200 and turns == ["build 12 failed"]
    assert reply.json()["delivery"] == {"channel": channel, "ok": True}
    assert [name for name, adapter in adapters.items() if adapter.sent] == [channel]
    sent = adapters[channel].sent
    if channel == "ntfy":                   # a native title, the text as written
        assert sent == [{"text": "done", "title": "Webhook ci - check_run", "plain": True}]
    elif channel == "telegram":             # the owner's chat, as plain text, never spoken
        assert sent == [{"text": "Webhook ci - check_run\n\ndone", "chat_id": 4242, "plain": True, "voice": False}]
    else:                                   # ChannelManager hands the voice adapter the text alone
        assert sent == [{"text": "Webhook ci - check_run\n\ndone"}]
    last = _listed(client, hook["id"])["last_delivery"]
    assert last["channel"] == channel and last["ok"] is True and last["reason"] == ""


@pytest.mark.parametrize("channel", CHANNELS)
def test_deliver_only_reaches_each_channel_without_a_turn(owner, channel):
    (client, _events, turns), adapters = owner
    hook = _hook(client, name="gh", deliver=channel, deliver_only=True, prompt="New {event} on {repo}")
    reply = _post(client, hook, {"repo": "nerva"}, **{"X-GitHub-Event": "push"})
    assert reply.status_code == 200 and turns == []
    assert reply.json()["delivery"] == {"channel": channel, "ok": True}
    assert adapters[channel].sent[0]["text"].endswith("New push on nerva")


def test_a_channel_that_refuses_is_recorded_with_its_reason(owner):
    (client, _events, _turns), adapters = owner
    adapters["voice"].answer = False
    hook = _hook(client, deliver="voice")
    reply = _post(client, hook, {"text": "hi"})
    assert reply.json()["delivery"] == {"channel": "voice", "ok": False, "reason": "voice refused the message"}
    assert _listed(client, hook["id"])["last_delivery"]["reason"] == "voice refused the message"


def test_web_is_not_offered_because_nothing_in_the_hub_receives_it(hub):
    from agents.core import webhooks

    client, _events, _turns = hub
    assert webhooks.DELIVER_CHOICES == ("log", "telegram", "voice", "ntfy")
    refused = client.post("/api/webhooks", json={"target": "jarvis", "deliver": "web"}, headers=_ADMIN)
    assert refused.status_code == 422 and "no receiver" in refused.text
    hook = _hook(client)
    patched = client.patch(f"/api/webhooks/{hook['id']}", json={"deliver": "web"}, headers=_ADMIN)
    assert patched.status_code == 422 and "no receiver" in patched.text
    assert WebhookStore.destination({"deliver": "web"}) == "log"      # a record from before: the log


@pytest.mark.parametrize("destination, reason", [
    ("email", "email is never an outbound side effect of an inbound delivery"),
    ("github_comment", "governed write-back"),
    ("discord", "Discord is a reply-only transport here"),
    ("slack", "Slack is a reply-only transport here"),
    ("web", "the HUD has no receiver for a pushed message"),
    ("pigeon", "deliver is one of log, telegram, voice, ntfy"),
])
def test_a_refused_destination_says_why(hub, destination, reason):
    client, _events, _turns = hub
    refused = client.post("/api/webhooks", json={"target": "jarvis", "deliver": destination}, headers=_ADMIN)
    assert refused.status_code == 422 and reason in refused.text


@pytest.mark.parametrize("spelling", ["Telegram", " telegram", "NTFY", "Log"])
def test_a_destination_is_named_exactly(hub, spelling):
    client, _events, _turns = hub
    refused = client.post("/api/webhooks", json={"target": "jarvis", "deliver": spelling}, headers=_ADMIN)
    assert refused.status_code == 422


def test_the_schema_names_the_destinations():
    from agents import web

    schemas = web.app.openapi()["components"]["schemas"]
    for name in ("WebhookCreateBody", "WebhookUpdateBody"):
        assert schemas[name]["properties"]["deliver"]["enum"] == ["log", "telegram", "voice", "ntfy"]


# ── what the owner sees ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, body, headers, starts", [
    ("Alertă build " + "x" * 90, {"text": "hi"}, {"X-GitHub-Event": "deployment_status." + "y" * 50},
     "Webhook Alerta build xxx"),
    ("ci", {"text": "hi", "event": "déploiement · fini"}, {}, "Webhook ci - deploiement ? fini"),
    ("n" * 80, {"text": "hi"}, {"X-GitHub-Event": "e" * 28 + " tail"}, "Webhook " + "n" * 80 + " - " + "e" * 28),
])
def test_an_ntfy_title_is_printable_ascii_whatever_the_hook_and_event_are_called(owner, name, body, headers,
                                                                                  starts):
    (client, _events, _turns), adapters = owner
    hook = _hook(client, name=name, deliver="ntfy")
    reply = _post(client, hook, body, **headers)
    assert reply.json()["delivery"] == {"channel": "ntfy", "ok": True}
    title = adapters["ntfy"].sent[0]["title"]
    assert title.isascii() and title.isprintable() and len(title) <= 120 and title == title.strip()
    assert title.startswith(starts)


def test_a_senders_link_arrives_with_its_address_never_as_markup(owner):
    """The sender's text is shown as written (H153 fourth review: nothing rendered and
    nothing rewritten), so a Markdown link is its literal source, address in view."""
    (client, _events, _turns), adapters = owner
    hook = _hook(client, name="issues", deliver="telegram", deliver_only=True, prompt="{title}")
    _post(client, hook, {"title": "**Nerva notice** [Sign in](https://nerva-login.example/owner)"},
          **{"X-GitHub-Event": "issues"})
    sent = adapters["telegram"].sent[0]
    assert sent["plain"] is True and sent["voice"] is False
    assert sent["text"] == "Webhook issues - issues\n\n**Nerva notice** [Sign in](https://nerva-login.example/owner)"


class _TelegramHttp:
    """The Bot API as the real adapter sees it: every POST recorded, answered 200."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []

    async def post(self, url, json=None, **kwargs):
        self.posts.append((url, dict(json or {})))
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               json=lambda: {"ok": True, "result": {"message_id": len(self.posts)}})

    async def aclose(self) -> None:
        pass


async def test_the_telegram_adapter_sends_plain_text_as_it_is_and_speaks_none_of_it():
    from agents.core.channels.telegram import TelegramChannel

    channel = TelegramChannel("tok")
    channel.client = _TelegramHttp()
    channel._voice_turns.add(7)               # the owner just sent a voice message
    text = "[x](https://a.example) <b>hi</b> **y**"
    assert await channel.send(text, chat_id=7, plain=True, voice=False) is True
    assert channel.client.posts == [(f"{channel.api_base}/sendMessage",
                                     {"chat_id": 7, "text": text, "link_preview_options": {"is_disabled": True}})]
    assert 7 in channel._voice_turns          # the reply to that voice message is still spoken
    rendered = TelegramChannel("tok")
    rendered.client = _TelegramHttp()
    assert await rendered.send("**y**", chat_id=7, voice=False) is True
    assert rendered.client.posts[0][1]["parse_mode"] == "HTML"      # the default is unchanged


def test_a_hook_name_with_a_line_break_still_makes_a_one_line_label(owner):
    (client, _events, _turns), adapters = owner
    hook = _hook(client, name="ci\nfake: approved", deliver="telegram")
    reply = _post(client, hook, {"text": "hi"}, **{"X-GitHub-Event": "push"})
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": True}
    assert adapters["telegram"].sent[0]["text"].split("\n")[0] == "Webhook ci fake: approved - push"


def test_a_long_reply_is_cut_and_says_where_the_rest_is(owner, monkeypatch):
    from agents.core.app_state import get_orch
    from agents.core.channels.outbound import MAX_TEXT_CHARS

    (client, _events, _turns), adapters = owner

    async def long_reply(text, **kwargs):
        return "x" * 10_000

    monkeypatch.setattr(get_orch(), "handle_input", long_reply)
    hook = _hook(client, name="n", deliver="telegram")
    assert _post(client, hook, {"text": "hi"}).json()["delivery"] == {"channel": "telegram", "ok": True}
    text = adapters["telegram"].sent[0]["text"]
    assert len(text) <= MAX_TEXT_CHARS and text.endswith("… (cut: the whole reply is in the session)")


# ── quiet hours, on the real rule ────────────────────────────────────────────────

@pytest.mark.parametrize("channel", CHANNELS)
def test_quiet_hours_hold_every_push_on_the_real_clock(owner, clock, channel):
    (client, _events, turns), adapters = owner
    hook = _hook(client, deliver=channel)
    clock["t"] = _at(3)
    night = _post(client, hook, {"text": "at 3 am"})
    assert night.status_code == 200 and turns == ["at 3 am"]
    assert night.json()["delivery"] == {"channel": channel, "ok": False,
                                        "reason": "quiet hours: not pushed; the reply is in the session"}
    assert adapters[channel].sent == []
    assert _listed(client, hook["id"])["last_delivery"]["ok"] is False
    clock["t"] = _at(15)
    assert _post(client, hook, {"text": "at 3 pm"}).json()["delivery"] == {"channel": channel, "ok": True}
    assert len(adapters[channel].sent) == 1


def test_quiet_hours_follow_the_owners_settings(monkeypatch):
    from agents.core.routers import webhooks as router

    settings = {}
    orch = SimpleNamespace(get_setting=lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(router, "_now", lambda: _at(3))
    assert router._quiet_hours(orch) is True                                   # the default, 22 to 7
    settings.update({"ambient.quiet_hours_start": 46, "ambient.quiet_hours_end": 31})
    assert router._quiet_hours(orch) is True                                   # 22 and 7, modulo 24
    settings.update({"ambient.quiet_hours_start": 1, "ambient.quiet_hours_end": 2})
    assert router._quiet_hours(orch) is False
    settings.update({"ambient.quiet_hours_start": 5, "ambient.quiet_hours_end": 5})
    assert router._quiet_hours(orch) is False                                  # no night at all
    settings.update({"ambient.quiet_hours_start": "late", "ambient.quiet_hours_end": None})
    assert router._quiet_hours(orch) is True                                   # unreadable: the defaults
    monkeypatch.setattr(router, "_now", lambda: _at(12))
    assert router._quiet_hours(orch) is False


def test_the_log_is_never_held_and_is_recorded(owner, clock):
    (client, _events, turns), _adapters = owner
    clock["t"] = _at(3)
    hook = _hook(client)
    assert _post(client, hook, {"text": "hi"}).json()["delivery"] == {"channel": "log", "ok": True}
    last = _listed(client, hook["id"])["last_delivery"]
    assert last["channel"] == "log" and last["ok"] is True and turns == ["hi"]


# ── a delivery that fails is recorded, never a 500 after the turn ────────────────

@pytest.mark.parametrize("where", ["send", "quiet hours"])
def test_a_delivery_that_raises_is_recorded_not_a_500_after_the_turn(owner, monkeypatch, where):
    from agents.core.channels import outbound
    from agents.core.routers import webhooks as router

    (client, _events, turns), _adapters = owner
    if where == "send":
        async def send_to_target(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(outbound, "send_to_target", send_to_target)
    else:
        def quiet_hours(orch):
            raise RuntimeError("boom")

        monkeypatch.setattr(router, "_quiet_hours", quiet_hours)
    hook = _hook(client, deliver="telegram")
    reply = _post(client, hook, {"text": "hi"})
    assert reply.status_code == 200 and reply.json()["response"] == "done" and turns == ["hi"]
    reason = "the delivery failed: RuntimeError"
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False, "reason": reason}
    assert _listed(client, hook["id"])["last_delivery"]["reason"] == reason


def test_a_delivery_record_that_cannot_be_saved_does_not_fail_the_delivery(owner, monkeypatch):
    from agents.core.routers import webhooks as router

    (client, _events, _turns), adapters = owner
    hook = _hook(client, deliver="ntfy")

    def disk_full(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(router._webhook_store, "mark_delivered", disk_full)
    reply = _post(client, hook, {"text": "hi"})
    assert reply.status_code == 200 and reply.json()["delivery"] == {"channel": "ntfy", "ok": True}
    assert len(adapters["ntfy"].sent) == 1


def test_a_turn_that_raises_is_recorded_on_the_hook(owner, monkeypatch):
    from agents.core.app_state import get_orch

    (client, _events, _turns), adapters = owner

    async def broken(text, **kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(get_orch(), "handle_input", broken)
    hook = _hook(client, deliver="telegram")
    with pytest.raises(RuntimeError):
        _post(client, hook, {"text": "hi"})
    last = _listed(client, hook["id"])["last_delivery"]
    assert (last["channel"], last["ok"], last["reason"]) == ("telegram", False, "the turn failed: RuntimeError")
    assert adapters["telegram"].sent == []


# ── deliver only needs a channel ─────────────────────────────────────────────────

def test_deliver_only_needs_a_channel(hub):
    client, _events, _turns = hub
    needs = "deliver only needs a channel"
    refused = client.post("/api/webhooks", json={"target": "jarvis", "deliver_only": True}, headers=_ADMIN)
    assert refused.status_code == 422 and needs in refused.text
    logged = _hook(client)
    patched = client.patch(f"/api/webhooks/{logged['id']}", json={"deliver_only": True}, headers=_ADMIN)
    assert patched.status_code == 422 and needs in patched.text
    pushed = _hook(client, deliver="telegram", deliver_only=True)
    patched = client.patch(f"/api/webhooks/{pushed['id']}", json={"deliver": "log"}, headers=_ADMIN)
    assert patched.status_code == 422 and needs in patched.text
    both = client.patch(f"/api/webhooks/{pushed['id']}", json={"deliver": "log", "deliver_only": False},
                        headers=_ADMIN)
    assert both.status_code == 200 and both.json()["webhook"]["deliver"] == "log"


def test_the_store_refuses_deliver_only_to_the_log_too(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    with pytest.raises(ValueError, match="deliver only needs a channel"):
        store.create("jarvis", deliver_only=True)
    rec = store.create("jarvis")
    with pytest.raises(ValueError, match="deliver only needs a channel"):
        store.update(rec["id"], deliver_only=True)
    assert store.get(rec["id"])["deliver_only"] is False


def test_a_deliver_only_hook_left_on_the_log_says_its_text_went_nowhere(owner):
    from agents.core.routers import webhooks as router

    (client, _events, turns), _adapters = owner
    hook = _hook(client)
    router._webhook_store._hooks[hook["id"]]["deliver_only"] = True       # a record from before the rule
    switched = client.patch(f"/api/webhooks/{hook['id']}", json={"enabled": True}, headers=_ADMIN)
    assert switched.status_code == 200                                     # it can still be switched
    reply = _post(client, hook, {"text": "noted"})
    assert reply.status_code == 200 and turns == []
    assert reply.json()["delivery"] == {"channel": "log", "ok": False,
                                        "reason": "deliver only to the log keeps nothing: the text was dropped"}


def test_deliver_only_says_its_text_was_not_kept(owner, clock):
    (client, _events, _turns), adapters = owner
    hook = _hook(client, deliver="telegram", deliver_only=True)
    clock["t"] = _at(3)
    night = _post(client, hook, {"text": "at night"}).json()["delivery"]
    assert night["reason"] == "quiet hours: not pushed; the text was not kept"
    clock["t"] = _at(15)
    _post(client, hook, {"text": "y" * 9_000})
    text = adapters["telegram"].sent[0]["text"]
    assert text.endswith("… (cut: the rest was not kept)") and "session" not in text


# ── a push is capped per hook ────────────────────────────────────────────────────

def test_a_hook_pushes_at_most_its_hourly_limit(owner, monkeypatch):
    from agents.core import webhooks

    (client, _events, _turns), adapters = owner
    assert webhooks.PUSH_LIMIT == 30
    now = {"t": 1_000.0}
    monkeypatch.setattr(webhooks, "PUSHES", webhooks.PushLimit(limit=2, window=3_600, clock=lambda: now["t"]))
    loud = _hook(client, name="loud", deliver="ntfy", deliver_only=True)
    other = _hook(client, name="other", deliver="ntfy", deliver_only=True)
    answers = [_post(client, loud, {"text": f"n{i}"}).json()["delivery"] for i in range(3)]
    assert [answer["ok"] for answer in answers] == [True, True, False]
    assert answers[2]["reason"] == "over this hook's push limit (2 an hour): not pushed; the text was not kept"
    assert _post(client, other, {"text": "mine"}).json()["delivery"]["ok"] is True      # each hook its own
    now["t"] += 3_601
    assert _post(client, loud, {"text": "later"}).json()["delivery"]["ok"] is True
    assert [sent["text"] for sent in adapters["ntfy"].sent] == ["n0", "n1", "mine", "later"]


# ── a change during the turn reaches the push ────────────────────────────────────

@pytest.mark.parametrize("change, reason", [
    ("off", "the hook was switched off before its delivery: not sent"),
    ("deleted", "the hook was deleted before its delivery: not sent"),
    ("receiver", "the webhook receiver was switched off before this delivery: not sent"),
])
def test_a_switch_thrown_during_the_turn_stops_the_push(owner, receiver, monkeypatch, change, reason):
    from agents.core.app_state import get_orch
    from agents.core.routers import webhooks as router

    (client, _events, turns), adapters = owner
    hook = _hook(client, name="ci", deliver="telegram")
    store = router._webhook_store

    async def turn(text, **kwargs):
        turns.append(text)
        if change == "off":
            store.update(hook["id"], enabled=False)
        elif change == "deleted":
            store.delete(hook["id"])
        else:
            receiver.put_category("webhooks", {"receiver_enabled": False})
        return "the agent's summary"

    monkeypatch.setattr(get_orch(), "handle_input", turn)
    reply = _post(client, hook, {"text": "build failed"})
    assert reply.status_code == 200 and turns == ["build failed"]
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False, "reason": reason}
    assert adapters["telegram"].sent == []
    if change != "deleted":
        assert _listed(client, hook["id"])["last_delivery"]["reason"] == reason


@pytest.mark.parametrize("now_to", ["ntfy", "log"])
def test_the_push_goes_where_the_hook_says_when_it_is_sent(owner, monkeypatch, now_to):
    from agents.core.app_state import get_orch
    from agents.core.routers import webhooks as router

    (client, _events, _turns), adapters = owner
    hook = _hook(client, deliver="telegram")

    async def turn(text, **kwargs):
        router._webhook_store.update(hook["id"], deliver=now_to)
        return "summary"

    monkeypatch.setattr(get_orch(), "handle_input", turn)
    reply = _post(client, hook, {"text": "hi"})
    assert reply.json()["delivery"] == {"channel": now_to, "ok": True}
    assert adapters["telegram"].sent == []
    assert [sent["text"] for sent in adapters["ntfy"].sent] == (["summary"] if now_to == "ntfy" else [])


def test_a_switch_off_that_lands_during_the_second_receiver_read_stops_the_delivery(hub, monkeypatch):
    from agents.core.routers import webhooks as router

    client, _events, turns = hub
    hook = _hook(client)
    real = router._receiver_refusal
    reads = []

    async def refusal():
        reads.append(1)
        if len(reads) == 2:
            router._webhook_store.update(hook["id"], enabled=False)       # lands while the read runs
        return await real()

    monkeypatch.setattr(router, "_receiver_refusal", refusal)
    reply = _post(client, hook, {"text": "hi"})
    assert reply.status_code == 403 and turns == []


# ── a workflow delivers its last step's output, or nothing, and says why ─────────

def _workflow(monkeypatch, result, steps=("fetch", "summarize")):
    from agents.core.app_state import get_orch
    from agents.core.routers import workflows

    async def run(pipeline, initial_input=""):
        return {"_input": initial_input, **result}

    monkeypatch.setattr(get_orch().workflow_engine, "run", run)
    pipeline = SimpleNamespace(steps=[SimpleNamespace(id=step) for step in steps])
    monkeypatch.setattr(workflows, "resolve_pipeline", lambda orch, target: pipeline)


def test_a_failed_workflow_run_delivers_nothing_not_an_earlier_step(owner, monkeypatch):
    (client, _events, _turns), adapters = owner
    _workflow(monkeypatch, {"fetch": "RAW SENDER TEXT: click [here](https://x.example)",
                            "summarize": "[error: backend timeout]", "_ok": False, "_errors": ["summarize"]})
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": "the week"})
    assert reply.status_code == 200 and reply.json()["ok"] is False
    reason = "the workflow run failed at summarize: nothing delivered"
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False, "reason": reason}
    assert adapters["telegram"].sent == []
    assert _listed(client, hook["id"])["last_delivery"]["reason"] == reason


def test_a_last_step_that_returned_an_error_is_not_delivered(owner, monkeypatch):
    (client, _events, _turns), adapters = owner
    _workflow(monkeypatch, {"fetch": "raw notes", "summarize": "[error: guardrail]", "_ok": True})
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": "the week"})
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False,
                                        "reason": "the workflow's last step failed: nothing delivered"}
    assert adapters["telegram"].sent == []


def test_a_run_that_stopped_early_delivers_the_last_step_that_ran(owner, monkeypatch):
    (client, _events, _turns), adapters = owner
    _workflow(monkeypatch, {"fetch": "raw", "triage": "urgent: the build is broken", "_ok": True,
                            "_terminated": True}, steps=("fetch", "triage", "summarize"))
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    assert _post(client, hook, {"text": "x"}).json()["delivery"] == {"channel": "telegram", "ok": True}
    assert adapters["telegram"].sent[0]["text"].endswith("\n\nurgent: the build is broken")


@pytest.mark.parametrize("path, reason", [
    ("no text", "the workflow's last step produced no text"),
    ("not found", "workflow not found"),
    ("invalid", "the stored workflow is invalid"),
    ("no engine", "workflow execution is not available on this hub"),
    ("raises", "the workflow run failed: RuntimeError"),
])
def test_every_workflow_outcome_after_a_call_is_recorded(owner, monkeypatch, path, reason):
    from agents.core.app_state import get_orch
    from agents.core.routers import workflows

    (client, _events, _turns), _adapters = owner
    _workflow(monkeypatch, {"fetch": "raw", "summarize": "the digest", "_ok": True})
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    assert _post(client, hook, {"text": "first"}).json()["delivery"]["ok"] is True
    if path == "no text":
        _workflow(monkeypatch, {"fetch": "raw", "summarize": "  ", "_ok": True})
    elif path == "not found":
        monkeypatch.setattr(workflows, "resolve_pipeline", lambda orch, target: None)
    elif path == "invalid":
        def invalid(orch, target):
            raise ValueError("steps is not a list")

        monkeypatch.setattr(workflows, "resolve_pipeline", invalid)
    elif path == "no engine":
        monkeypatch.setattr(get_orch(), "workflow_engine", None)
    else:
        async def run(pipeline, initial_input=""):
            raise RuntimeError("engine bug")

        monkeypatch.setattr(get_orch().workflow_engine, "run", run)
    _post(client, hook, {"text": "second"})
    listed = _listed(client, hook["id"])
    assert listed["calls"] == 2
    assert (listed["last_delivery"]["ok"], listed["last_delivery"]["reason"]) == (False, reason)


# ── the receiver is read by one request at a time ────────────────────────────────

def test_the_receiver_is_read_by_one_request_at_a_time(receiver, monkeypatch):
    from agents.core import settings_db, webhooks

    started, release = threading.Event(), threading.Event()
    reads = []
    real = settings_db.read_setting

    def slow(category, key):
        reads.append(1)
        started.set()
        release.wait(5)
        return real(category, key)

    monkeypatch.setattr(settings_db, "read_setting", slow)
    webhooks.RECEIVER.written(False)
    webhooks.RECEIVER.expire()
    first = threading.Thread(target=webhooks.RECEIVER.state)
    first.start()
    try:
        assert started.wait(5)
        answers = [webhooks.RECEIVER.state() for _ in range(20)]         # while that read runs
    finally:
        release.set()
        first.join(5)
    assert len(reads) == 1 and answers == [False] * 20                  # the last state, at once
    assert webhooks.RECEIVER.state() is True                            # then the read lands: on


def test_a_receiver_never_read_is_unreadable_while_its_first_read_runs(receiver, monkeypatch):
    """Past the wait for its first read (H153 fourth review), it is refused, closed."""
    from agents.core import settings_db, webhooks

    monkeypatch.setattr(webhooks.RECEIVER, "first_read_wait", 0.1)
    started, release = threading.Event(), threading.Event()
    real = settings_db.read_setting

    def slow(category, key):
        started.set()
        release.wait(5)
        return real(category, key)

    monkeypatch.setattr(settings_db, "read_setting", slow)
    first = threading.Thread(target=webhooks.RECEIVER.state)
    first.start()
    try:
        assert started.wait(5)
        assert webhooks.RECEIVER.state() is None
    finally:
        release.set()
        first.join(5)


def test_a_read_in_flight_across_a_reset_does_not_land(receiver, monkeypatch):
    from agents.core import settings_db, webhooks

    switch = webhooks.ReceiverSwitch()             # a fresh one: its first generation
    real = settings_db.read_setting
    reads = []

    def read_then_reset(category, key):
        reads.append(1)
        found, value = real(category, key)
        if len(reads) == 1:
            switch.reset()                         # the state is forgotten while this read runs,
            switch.state()                         # another request reads the store afresh,
            return found, False                    # and this first, stale read saw "off"
        return found, value

    monkeypatch.setattr(settings_db, "read_setting", read_then_reset)
    switch.state()
    monkeypatch.setattr(settings_db, "read_setting", real)
    assert len(reads) == 2
    assert switch.state() is True                  # the fresh read stands, not the stale "off"


def test_a_read_in_flight_across_a_reseed_does_not_land(receiver, monkeypatch):
    from agents.core import settings_db, webhooks

    real = settings_db.read_setting

    def read_then_reseed(category, key):
        found, _value = real(category, key)
        webhooks.RECEIVER.expire()                 # a reseed lands while this read runs
        return found, False                        # and this read saw the store before it

    monkeypatch.setattr(settings_db, "read_setting", read_then_reseed)
    webhooks.RECEIVER.state()
    monkeypatch.setattr(settings_db, "read_setting", real)
    assert webhooks.RECEIVER.state() is True       # read again after the reseed


def test_a_read_in_flight_across_a_store_swap_does_not_land(receiver, monkeypatch, tmp_path):
    from agents.core import settings_db, webhooks

    real = settings_db.read_setting

    def read_then_swap(category, key):
        found, _value = real(category, key)
        monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "other.db")   # swapped meanwhile
        monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
        webhooks.RECEIVER.state()                  # a request notices the swap
        return found, False                        # and this old read saw "off"

    monkeypatch.setattr(settings_db, "read_setting", read_then_swap)
    webhooks.RECEIVER.state()
    monkeypatch.setattr(settings_db, "read_setting", real)
    assert webhooks.RECEIVER.state() is True       # the new store, not the old read


def test_a_failed_read_is_retried_once_a_second_not_on_every_request(receiver, monkeypatch):
    from agents.core import settings_db, webhooks

    attempts = []

    def locked(category, key):
        attempts.append(1)
        raise settings_db.SettingsUnreadable("database is locked")

    now = {"t": 100.0}
    monkeypatch.setattr(settings_db, "read_setting", locked)
    monkeypatch.setattr(webhooks.RECEIVER, "_clock", lambda: now["t"])
    assert [webhooks.RECEIVER.state() for _ in range(5)] == [None] * 5
    assert len(attempts) == 1
    now["t"] += 1.5
    webhooks.RECEIVER.state()
    assert len(attempts) == 2


def test_another_settings_store_forgets_what_the_last_one_said(receiver, monkeypatch, tmp_path):
    from agents.core import settings_db, webhooks

    receiver.put_category("webhooks", {"receiver_enabled": False})
    assert webhooks.RECEIVER.state() is False
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "fresh.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    assert webhooks.RECEIVER.state() is True       # the new store's own value, read at once


def test_a_stored_value_that_cannot_be_decoded_is_unreadable_not_missing(hub, receiver):
    from agents.core import webhooks

    client, _events, turns = hub
    hook = _hook(client)
    conn = receiver.get_conn()
    conn.execute("UPDATE settings SET value='{not json' WHERE category='webhooks' AND key='receiver_enabled'")
    conn.commit()
    conn.close()
    with pytest.raises(receiver.SettingsUnreadable):
        receiver.read_setting("webhooks", "receiver_enabled")
    webhooks.RECEIVER.reset()
    refused = _post(client, hook, {"text": "hi"})
    assert refused.status_code == 503 and refused.json()["error"] == "the webhook receiver's state cannot be read"
    assert turns == []


def test_a_settings_listener_that_raises_never_fails_the_write(receiver):
    def broken(category, values):
        raise RuntimeError("listener bug")

    receiver.on_change(broken)
    try:
        receiver.put_category("webhooks", {"receiver_enabled": False})
        assert receiver.read_setting("webhooks", "receiver_enabled") == (True, False)
    finally:
        receiver._change_listeners.remove(broken)


# ── the audit row names a free-text key, never its value ─────────────────────────

def _settings_rows(events):
    return [event.content_preview for event in events if event.action_taken == "settings_update"]


def test_a_typed_model_id_is_audited_by_name_only(hub, receiver):
    client, events, _turns = hub
    value = "claude settings.llm updated: ['nothing']"
    reply = client.put("/api/admin/settings/llm", json={"values": {"default_model": value}}, headers=_ADMIN)
    assert reply.status_code == 200
    row = _settings_rows(events)[-1]
    assert "default_model" in row and "claude" not in row and " " not in row


def test_a_free_text_setting_is_audited_by_name_only(hub, receiver):
    client, events, _turns = hub
    row = next(spec for spec in receiver.DEFAULTS
               if spec["kind"] == "text" and spec["key"] not in receiver.SECRET_KEYS
               and not receiver.validate_category(spec["category"], {spec["key"]: "https://h.example/?token=abc123"}))
    reply = client.put(f"/api/admin/settings/{row['category']}",
                       json={"values": {row["key"]: "https://h.example/?token=abc123"}}, headers=_ADMIN)
    assert reply.status_code == 200
    audited = _settings_rows(events)[-1]
    assert row["key"] in audited and "abc123" not in audited


def test_an_audited_value_is_cut_at_64_characters(hub, receiver):
    client, events, _turns = hub
    big = 10 ** 80
    row = next(spec for spec in receiver.DEFAULTS
               if spec["kind"] == "number" and not receiver.validate_category(spec["category"], {spec["key"]: big}))
    reply = client.put(f"/api/admin/settings/{row['category']}", json={"values": {row["key"]: big}},
                       headers=_ADMIN)
    assert reply.status_code == 200
    shown = _settings_rows(events)[-1].split(f"{row['key']}=", 1)[1]
    assert shown == str(big)[:64]


# ── the other guards the review's mutants showed were untested ───────────────────

def test_the_stated_body_cap_is_five_mebibytes():
    from agents.core.routers import webhooks as router

    assert router.MAX_BODY_BYTES == 5 * 1024 * 1024


def test_a_template_that_renders_only_whitespace_is_skipped(hub):
    client, _events, turns = hub
    hook = _hook(client, prompt="{note}")
    reply = _post(client, hook, {"note": "  \n\t "})
    assert reply.status_code == 202 and turns == []


def test_a_delivery_that_carries_no_text_is_skipped_as_such(hub):
    client, _events, turns = hub
    hook = _hook(client)
    reply = client.post(f"/api/webhooks/{hook['id']}", content=b"   ",
                        headers={"X-Webhook-Token": hook["token"], "Content-Type": "text/plain"})
    assert reply.status_code == 202 and reply.json()["skipped"] == "the delivery carries no text"
    assert turns == []


async def test_a_content_length_that_is_not_ascii_digits_is_not_trusted():
    from agents.core.routers import webhooks as router

    async def stream():
        yield b'{"text": "hi"}'

    request = SimpleNamespace(headers={"content-length": "²"}, stream=stream)
    assert await router._capped_body(request) == b'{"text": "hi"}'


def test_a_hand_edited_deliver_only_that_is_not_literally_true_runs_the_agent(owner):
    from agents.core.routers import webhooks as router

    (client, _events, turns), adapters = owner
    hook = _hook(client, deliver="ntfy")
    router._webhook_store._hooks[hook["id"]]["deliver_only"] = "yes"
    _post(client, hook, {"text": "hi"})
    assert turns == ["hi"] and adapters["ntfy"].sent[0]["text"] == "done"


@pytest.mark.parametrize("value", ["yes", 1, "true"])
def test_create_takes_deliver_only_as_a_real_boolean(hub, value):
    client, _events, _turns = hub
    body = {"target": "jarvis", "deliver": "ntfy", "deliver_only": value}
    assert client.post("/api/webhooks", json=body, headers=_ADMIN).status_code == 422


@pytest.mark.parametrize("stored, readable", [(["a,b"], False), (["x" * 65], False), (["x" * 64], True)])
def test_a_hand_edited_event_name_the_api_would_refuse_is_unreadable(tmp_path, stored, readable):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis")
    store._hooks[rec["id"]]["events"] = stored
    assert (store.stored_events(store.get(rec["id"])) is not None) is readable


def test_a_hand_edited_last_delivery_that_is_not_a_record_is_not_listed(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis")
    store._hooks[rec["id"]]["last_delivery"] = "delivered, trust me"
    assert "last_delivery" not in store.list()[0]
    store.mark_delivered(rec["id"], "ntfy", True)
    assert store.list()[0]["last_delivery"]["channel"] == "ntfy"


def test_a_delivery_reason_is_one_bounded_line(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis")
    store.mark_delivered(rec["id"], "telegram", False, "line one\nline two\x1b[31m" + "x" * 400)
    reason = store.list()[0]["last_delivery"]["reason"]
    assert reason.isprintable() and len(reason) == 300 and reason.startswith("line one line two")


def test_a_save_that_fails_undoes_a_destination_change(tmp_path, monkeypatch):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis", deliver="telegram", description="builds")

    def disk_full():
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save", disk_full)
    with pytest.raises(OSError):
        store.update(rec["id"], deliver="ntfy", deliver_only=True, description="changed")
    kept = store.get(rec["id"])
    assert (kept["deliver"], kept["deliver_only"], kept["description"]) == ("telegram", False, "builds")
