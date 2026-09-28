"""H153 review round — where a delivery goes, and a receiver switch that fails closed.

The review of the H153 build found two majors:

- **Deliver to.** A Hermes subscription names where its result goes (Deliver to: log,
  Telegram, Discord, Slack, email, a GitHub comment) and can skip the agent (deliver
  only). Nerva's hook answered only the sender. Now a hook has ``deliver`` — ``log``
  (the default: the reply stays in the response and the session) or one of the owner's
  own channels (telegram, voice, ntfy; ``web`` was dropped in the third round, nothing
  receives it) — and ``deliver_only``, which sends the rendered text without a turn.
  The send is the audited ``send_to_target``; quiet hours hold a push, which is noted on
  the hook, never a buzz. The Hermes destinations Nerva does not offer are refused by name:
  email (an inbound delivery never gains an outbound mail side effect), a GitHub
  comment (a write to someone else's system goes through governed write-back, one
  approval each), Discord and Slack (reply-only transports here, no home channel).
- **The receiver switch fails closed.** A settings store that cannot be read used to
  read as "on", so a receiver switched off came back on by itself. Now the last value
  read stands, a receiver never read answers 503 with its own reason, only a literal
  true is on, and the read is off the event loop and cached for a second (a write in
  this process is seen at once).

And the minors and nits: audit rows that say off or on, a reseed that is audited, event
lists a hand edit broke read as unreadable, rendering whose work is bounded, a body cap,
event names that are not cut to fit, commas refused in names, an empty render skipped,
``{payload.x}`` for a payload key the template reserves, and a create that refuses fields
it does not know.

The fakes here (``sends``, ``daytime``) stand in for the send and the clock; the real path,
down to each channel's adapter, is ``test_h153c_webhook_sends.py``.
"""
import json
import sqlite3
import threading

import pytest

from agents.core.webhooks import MAX_FIELD, MAX_RENDERED, WebhookStore, render_prompt
from tests.test_h10_8_webhooks import _ADMIN, _hook, hub  # noqa: F401  (hub is a fixture)


def _post(client, hook, body, **headers):
    raw = json.dumps(body).encode()
    return client.post(f"/api/webhooks/{hook['id']}", content=raw,
                       headers={"X-Webhook-Token": hook["token"], "Content-Type": "application/json", **headers})


def _listed(client, hook_id):
    return next(h for h in client.get("/api/webhooks", headers=_ADMIN).json()["webhooks"] if h["id"] == hook_id)


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    """A private settings database and a fresh receiver state."""
    from agents.core import settings_db, webhooks

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.ensure_initialized()          # seeded once, as a running hub is: no re-seed per read
    webhooks.RECEIVER.reset()
    yield settings_db
    webhooks.RECEIVER.reset()


@pytest.fixture
def sends(monkeypatch):
    """Every owner-channel send the trigger makes, answered ok unless told otherwise."""
    from agents.core.channels import outbound

    calls, answer = [], {"value": None}

    async def send_to_target(orch, channel, text, *, subject="", source="api", **kwargs):
        calls.append({"channel": channel, "text": text, "subject": subject, "source": source, **kwargs})
        return answer["value"] or {"ok": True, "channel": channel, "audited": True}

    monkeypatch.setattr(outbound, "send_to_target", send_to_target)
    return calls, answer


@pytest.fixture
def daytime(monkeypatch):
    from agents.core.routers import webhooks as router

    state = {"night": False}
    monkeypatch.setattr(router, "_quiet_hours", lambda orch: state["night"])
    return state


# ── Deliver to ───────────────────────────────────────────────────────────────────

def test_a_hook_keeps_its_reply_in_the_log_unless_told_otherwise(hub, sends, daytime):
    client, _events, turns = hub
    hook = _hook(client)
    listed = _listed(client, hook["id"])
    assert listed["deliver"] == "log" and listed["deliver_only"] is False and listed["description"] == ""
    reply = _post(client, hook, {"text": "hi"})
    assert reply.status_code == 200 and reply.json()["response"] == "done" and turns == ["hi"]
    assert reply.json()["delivery"] == {"channel": "log", "ok": True}
    calls, _ = sends
    assert calls == []


def test_a_reply_goes_to_the_owners_channel_labelled_as_the_hook(hub, sends, daytime):
    client, _events, turns = hub
    hook = _hook(client, name="ci", deliver="telegram", description="builds on main")
    reply = _post(client, hook, {"text": "build 12 failed"}, **{"X-GitHub-Event": "check_run"})
    assert reply.status_code == 200 and turns == ["build 12 failed"]
    calls, _ = sends
    assert calls == [{"channel": "telegram", "text": "done", "subject": "Webhook ci - check_run",
                      "source": f"webhook:{hook['id']}", "plain": True}]
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": True}
    listed = _listed(client, hook["id"])
    assert listed["last_delivery"]["channel"] == "telegram" and listed["last_delivery"]["ok"] is True
    assert listed["description"] == "builds on main"


def test_deliver_only_sends_the_rendered_text_and_runs_no_turn(hub, sends, daytime):
    client, _events, turns = hub
    hook = _hook(client, name="gh", deliver="telegram", deliver_only=True, prompt="New {event} on {repo}")
    reply = _post(client, hook, {"repo": "nerva"}, **{"X-GitHub-Event": "push"})
    assert reply.status_code == 200 and turns == []
    calls, _ = sends
    assert [(c["channel"], c["text"]) for c in calls] == [("telegram", "New push on nerva")]
    assert _listed(client, hook["id"])["calls"] == 1


def test_deliver_only_to_the_log_is_refused_it_would_keep_nothing(hub, sends, daytime):
    client, _events, turns = hub
    refused = client.post("/api/webhooks", json={"target": "jarvis", "deliver_only": True}, headers=_ADMIN)
    assert refused.status_code == 422 and turns == [] and sends[0] == []


@pytest.mark.parametrize("destination, reason", [
    ("email", "email"),
    ("github_comment", "write-back"),
    ("discord", "reply-only"),
    ("slack", "reply-only"),
    ("pigeon", "log, telegram, voice, ntfy"),
])
def test_destinations_nerva_does_not_offer_are_refused_by_name(hub, destination, reason):
    client, _events, _turns = hub
    refused = client.post("/api/webhooks", json={"target": "jarvis", "deliver": destination}, headers=_ADMIN)
    assert refused.status_code == 422 and reason in refused.text
    hook = _hook(client)
    patched = client.patch(f"/api/webhooks/{hook['id']}", json={"deliver": destination}, headers=_ADMIN)
    assert patched.status_code == 422 and reason in patched.text


def test_quiet_hours_keep_a_push_off_the_phone_and_say_so(hub, sends, daytime):
    client, _events, turns = hub
    daytime["night"] = True
    pushed = _hook(client, deliver="telegram")
    reply = _post(client, pushed, {"text": "at 3 am"})
    assert reply.status_code == 200 and turns == ["at 3 am"] and sends[0] == []
    delivery = reply.json()["delivery"]
    assert delivery["ok"] is False and "quiet hours" in delivery["reason"]
    assert "quiet hours" in _listed(client, pushed["id"])["last_delivery"]["reason"]
    logged = _hook(client)                                 # the log wakes nobody
    assert _post(client, logged, {"text": "also at 3 am"}).json()["delivery"]["ok"] is True


def test_a_send_that_fails_is_recorded_not_raised(hub, sends, daytime):
    client, _events, _turns = hub
    calls, answer = sends
    answer["value"] = {"ok": False, "reason": "no owner chat is configured (autonomy.owner_chat_id)"}
    hook = _hook(client, deliver="telegram")
    reply = _post(client, hook, {"text": "hi"})
    assert reply.status_code == 200 and reply.json()["response"] == "done"
    assert reply.json()["delivery"] == {"channel": "telegram", "ok": False,
                                        "reason": "no owner chat is configured (autonomy.owner_chat_id)"}
    assert _listed(client, hook["id"])["last_delivery"]["ok"] is False


def test_a_long_reply_is_cut_to_what_the_channel_carries(hub, sends, daytime, monkeypatch):
    from agents.core.app_state import get_orch
    from agents.core.channels.outbound import MAX_TEXT_CHARS

    client, _events, _turns = hub

    async def long_reply(text, **kwargs):
        return "x" * 10_000

    monkeypatch.setattr(get_orch(), "handle_input", long_reply)
    hook = _hook(client, name="n", deliver="ntfy")
    _post(client, hook, {"text": "hi"})
    sent = sends[0][0]
    assert len(sent["text"]) + len(sent["subject"]) + 2 <= MAX_TEXT_CHARS
    assert sent["text"].endswith("(cut: the whole reply is in the session)")


def test_a_workflow_result_is_delivered_too(hub, sends, daytime, monkeypatch):
    from agents.core.app_state import get_orch
    from agents.core.routers import workflows

    client, _events, _turns = hub
    orch = get_orch()

    from types import SimpleNamespace

    async def run(pipeline, initial_input=""):
        # the engine's shape: every step's output by id, plus its own underscored keys
        return {"_input": initial_input, "fetch": "raw notes", "summarize": f"summary of {initial_input}",
                "_ok": True, "_elapsed": 0.1}

    monkeypatch.setattr(orch.workflow_engine, "run", run)
    pipeline = SimpleNamespace(steps=[SimpleNamespace(id="fetch"), SimpleNamespace(id="summarize")])
    monkeypatch.setattr(workflows, "resolve_pipeline", lambda orch, target: pipeline)
    hook = _hook(client, target_type="workflow", target="digest", deliver="telegram")
    reply = _post(client, hook, {"text": "the week"})
    assert reply.status_code == 200
    assert [c["text"] for c in sends[0]] == ["summary of the week"]


def test_a_destination_change_is_audited(hub):
    client, events, _turns = hub
    hook = _hook(client)
    changed = client.patch(f"/api/webhooks/{hook['id']}", json={"deliver": "ntfy", "deliver_only": True,
                                                                "description": "from CI"}, headers=_ADMIN)
    assert changed.status_code == 200 and changed.json()["webhook"]["deliver"] == "ntfy"
    row = events[-1].content_preview
    assert "deliver=ntfy" in row and "deliver_only=True" in row and events[-1].action_taken == "webhook_update"


@pytest.mark.parametrize("extra", [{"skills": ["triage"]}, {"enabled": False}, {"deliver_chat_id": "42"}])
def test_create_refuses_fields_it_does_not_know(hub, extra):
    client, _events, _turns = hub
    refused = client.post("/api/webhooks", json={"target": "jarvis", **extra}, headers=_ADMIN)
    assert refused.status_code == 422


def test_a_description_is_bounded(hub):
    client, _events, _turns = hub
    assert client.post("/api/webhooks", json={"target": "jarvis", "description": "d" * 500},
                       headers=_ADMIN).status_code == 200
    assert client.post("/api/webhooks", json={"target": "jarvis", "description": "d" * 501},
                       headers=_ADMIN).status_code == 422


def test_only_a_literal_true_skips_the_agent(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis", deliver="telegram", deliver_only=True)
    assert store.delivers_only(store.get(rec["id"])) is True
    for hand_edit in ("yes", 1, "true"):
        store._hooks[rec["id"]]["deliver_only"] = hand_edit
        assert store.delivers_only(store.get(rec["id"])) is False
    assert store.list()[0]["deliver_only"] is False


def test_a_hand_edited_destination_delivers_only_to_the_log(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis", deliver="ntfy")
    store._hooks[rec["id"]]["deliver"] = "email"          # a hand edit
    assert store.destination(store.get(rec["id"])) == "log"
    store._hooks[rec["id"]]["deliver"] = 7
    assert store.destination(store.get(rec["id"])) == "log"
    assert store.destination({"id": "legacy"}) == "log"    # written before the field existed


# ── the receiver fails closed ────────────────────────────────────────────────────

def _break_the_store(monkeypatch):
    from agents.core import settings_db

    def broken():
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(settings_db, "get_conn", broken)


def test_a_store_that_cannot_be_read_keeps_the_last_state_read(hub, receiver, monkeypatch):
    from agents.core import webhooks

    client, _events, turns = hub
    hook = _hook(client)
    assert client.put("/api/admin/settings/webhooks", json={"values": {"receiver_enabled": False}},
                      headers=_ADMIN).status_code == 200
    assert _post(client, hook, {"text": "hi"}).status_code == 503
    _break_the_store(monkeypatch)
    webhooks.RECEIVER.expire()                             # the cache is not what holds it off
    refused = _post(client, hook, {"text": "still off"})
    assert refused.status_code == 503 and refused.json()["error"] == "the webhook receiver is off"
    assert turns == []


def test_a_receiver_never_read_is_refused_with_its_own_reason(hub, receiver, monkeypatch):
    client, _events, turns = hub
    hook = _hook(client)
    _break_the_store(monkeypatch)
    refused = _post(client, hook, {"text": "hi"})
    assert refused.status_code == 503
    assert refused.json()["error"] == "the webhook receiver's state cannot be read"
    assert turns == []


@pytest.mark.parametrize("stored", ["true", 1, None, "on"])
def test_only_a_literal_true_turns_the_receiver_on(hub, receiver, stored):
    client, _events, turns = hub
    hook = _hook(client)
    receiver.put_category("webhooks", {"receiver_enabled": stored})   # a hand edit, not the route
    assert _post(client, hook, {"text": "hi"}).status_code == 503 and turns == []


def test_the_switch_itself_fails_closed_whichever_read_fails(receiver, monkeypatch):
    """The trigger reads the switch twice (before the body, after authentication); each
    read must fail closed on its own, not lean on the other."""
    from agents.core import webhooks

    _break_the_store(monkeypatch)
    assert webhooks.RECEIVER.state() is None              # never read: unreadable
    webhooks.RECEIVER.written(False)
    webhooks.RECEIVER.expire()
    assert webhooks.RECEIVER.state() is False             # the last state stands
    webhooks.RECEIVER.written(True)
    webhooks.RECEIVER.expire()
    assert webhooks.RECEIVER.state() is True


@pytest.mark.parametrize("stored", ['"true"', "1", "null", '"on"'])
def test_only_a_literal_true_read_from_the_store_is_on(receiver, stored):
    from agents.core import webhooks

    conn = receiver.get_conn()
    conn.execute("UPDATE settings SET value=? WHERE category='webhooks' AND key='receiver_enabled'", (stored,))
    conn.commit()
    conn.close()
    webhooks.RECEIVER.expire()
    assert webhooks.RECEIVER.state() is False


def test_a_missing_row_is_the_declared_default(hub, receiver):
    client, _events, turns = hub
    hook = _hook(client)
    conn = receiver.get_conn()
    conn.execute("DELETE FROM settings WHERE category='webhooks' AND key='receiver_enabled'")
    conn.commit()
    conn.close()
    from agents.core import webhooks

    webhooks.RECEIVER.expire()
    assert _post(client, hook, {"text": "hi"}).status_code == 200 and turns == ["hi"]


def test_a_write_in_this_process_is_seen_at_once_and_another_process_within_a_second(hub, receiver):
    from agents.core import webhooks

    client, _events, turns = hub
    hook = _hook(client)
    assert _post(client, hook, {"text": "one"}).status_code == 200
    receiver.put_category("webhooks", {"receiver_enabled": False})     # this process: seen at once
    assert _post(client, hook, {"text": "two"}).status_code == 503
    receiver.put_category("webhooks", {"receiver_enabled": True})
    conn = receiver.get_conn()                                         # another process: a raw write
    conn.execute("UPDATE settings SET value='false' WHERE category='webhooks' AND key='receiver_enabled'")
    conn.commit()
    conn.close()
    clock = webhooks.RECEIVER._clock
    webhooks.RECEIVER._clock = lambda: clock() + 1.5
    try:
        assert _post(client, hook, {"text": "three"}).status_code == 503
    finally:
        webhooks.RECEIVER._clock = clock
    assert turns == ["one"]


def test_a_write_that_lands_while_a_read_runs_is_not_overwritten_by_it(receiver, monkeypatch):
    from agents.core import settings_db, webhooks

    real = settings_db.read_setting

    def slow_read(category, key):
        found, value = real(category, key)          # reads "on"
        webhooks.RECEIVER.written(False)             # the owner switches it off meanwhile
        return found, value

    monkeypatch.setattr(settings_db, "read_setting", slow_read)
    assert webhooks.RECEIVER.state() is False
    monkeypatch.setattr(settings_db, "read_setting", real)
    assert webhooks.RECEIVER.state() is False       # still fresh: the write, not the stale read


def test_the_receiver_is_read_off_the_event_loop(hub, receiver, monkeypatch):
    import asyncio

    from agents.core import settings_db, webhooks

    client, _events, _turns = hub
    hook = _hook(client)
    seen = []
    real = settings_db.read_setting

    def recording(category, key):
        try:
            asyncio.get_running_loop()
            seen.append("on the loop")
        except RuntimeError:
            seen.append(threading.current_thread().name)
        return real(category, key)

    monkeypatch.setattr(settings_db, "read_setting", recording)
    webhooks.RECEIVER.expire()
    _post(client, hook, {"text": "hi"})
    assert seen and "on the loop" not in seen


# ── the audit says what changed ──────────────────────────────────────────────────

def test_the_receiver_audit_row_says_off_or_on(hub, receiver):
    client, events, _turns = hub
    for value in (False, True):
        client.put("/api/admin/settings/webhooks", json={"values": {"receiver_enabled": value}}, headers=_ADMIN)
    rows = [e.content_preview for e in events if e.action_taken == "settings_update"]
    assert rows[-2].endswith("receiver_enabled=false") and rows[-1].endswith("receiver_enabled=true")


def test_a_secret_setting_is_still_audited_by_name_only(hub, receiver):
    client, events, _turns = hub
    row = next(r for r in receiver.DEFAULTS if r["key"] in receiver.SECRET_KEYS)
    reply = client.put(f"/api/admin/settings/{row['category']}", json={"values": {row["key"]: "s3cr3t-value"}},
                       headers=_ADMIN)
    assert reply.status_code == 200
    assert any(row["key"] in e.content_preview for e in events)
    assert all("s3cr3t-value" not in e.content_preview for e in events)


def test_a_reseed_is_audited_and_turns_the_receiver_back_on_visibly(hub, receiver):
    client, events, turns = hub
    hook = _hook(client)
    client.put("/api/admin/settings/webhooks", json={"values": {"receiver_enabled": False}}, headers=_ADMIN)
    assert _post(client, hook, {"text": "off"}).status_code == 503
    assert client.post("/api/admin/settings/reseed", json={}, headers=_ADMIN).status_code == 200   # H259: JSON
    assert any(e.action_taken == "settings_reseed" for e in events)
    assert _post(client, hook, {"text": "on again"}).status_code == 200 and turns == ["on again"]


# ── event lists a hand edit broke ────────────────────────────────────────────────

@pytest.mark.parametrize("stored", [[1, 2], [None], [""], ["   "], [{"name": "push"}], None, "push"])
def test_a_broken_event_list_is_unreadable_and_skips_every_delivery(hub, stored):
    from agents.core.routers import webhooks as router

    client, _events, turns = hub
    hook = _hook(client)
    router._webhook_store._hooks[hook["id"]]["events"] = stored
    listed = _listed(client, hook["id"])
    assert listed["events_unreadable"] is True and listed["events"] == []
    reply = _post(client, hook, {"text": "hi"}, **{"X-GitHub-Event": "push"})
    assert reply.status_code == 202 and turns == []


def test_a_record_without_the_field_still_runs_every_event(tmp_path):
    store = WebhookStore(path=tmp_path / "wh.json")
    rec = store.create("jarvis")
    del store._hooks[rec["id"]]["events"]
    assert store.stored_events(store.get(rec["id"])) == []


# ── rendering is bounded by its caps ─────────────────────────────────────────────

class _Counted(list):
    """A list that counts how many of its items an encoder asked for."""

    def __init__(self, items):
        super().__init__(items)
        self.read = 0

    def __iter__(self):
        for item in super().__iter__():
            self.read += 1
            yield item


def test_a_placeholder_stops_encoding_at_its_cap():
    big = _Counted(range(1_000_000))
    out = render_prompt("{items}", {"items": big}, "push")
    assert len(out) == MAX_FIELD and big.read < 10_000


def test_each_path_is_read_once_and_the_render_stops_when_full():
    once = _Counted(range(100_000))
    render_prompt("{items}", {"items": once}, "push")
    big = _Counted(range(100_000))
    out = render_prompt("{items}" * 200, {"items": big}, "push")
    assert len(out) == MAX_RENDERED
    assert big.read == once.read              # encoded once, not once per placeholder


def test_substitution_stops_once_the_text_is_full():
    lists = {f"k{i}": _Counted(range(100_000)) for i in range(10)}
    out = render_prompt("".join(f"{{k{i}}}" for i in range(10)), lists, "")
    assert len(out) == MAX_RENDERED
    read = [lists[f"k{i}"].read for i in range(10)]
    assert all(read[:4]) and not any(read[4:])      # four values fill it; the rest are never encoded


def test_a_streamed_body_with_no_length_is_capped_too(hub):
    from agents.core.routers import webhooks as router

    client, _events, turns = hub
    hook = _hook(client)
    chunk = b"x" * 65536

    def body():                                   # no Content-Length: sent chunked
        yield b'{"text": "'
        for _ in range(router.MAX_BODY_BYTES // len(chunk) + 2):
            yield chunk
        yield b'"}'

    reply = client.post(f"/api/webhooks/{hook['id']}", content=body(),
                        headers={"X-Webhook-Token": hook["token"], "Content-Type": "application/json"})
    assert reply.status_code == 413 and turns == []


def test_a_body_over_the_cap_is_refused(hub):
    from agents.core.routers import webhooks as router

    client, _events, turns = hub
    hook = _hook(client)
    body = b'{"text": "' + b"x" * (router.MAX_BODY_BYTES + 10) + b'"}'
    reply = client.post(f"/api/webhooks/{hook['id']}", content=body,
                        headers={"X-Webhook-Token": hook["token"], "Content-Type": "application/json"})
    assert reply.status_code == 413 and turns == []


# ── the nits ─────────────────────────────────────────────────────────────────────

def test_an_event_name_longer_than_the_limit_is_not_cut_to_fit(hub):
    client, _events, turns = hub
    subscribed = "deployment_status." + "x" * 46                      # 64 characters
    hook = _hook(client, events=[subscribed])
    reply = _post(client, hook, {"text": "hi"}, **{"X-GitHub-Event": subscribed + ".rollback"})
    assert reply.status_code == 202 and turns == []


def test_event_names_match_ignoring_ascii_case_only(hub):
    client, _events, turns = hub
    hook = _hook(client, events=["strasse", "Push"])
    assert _post(client, hook, {"text": "a"}, **{"X-GitHub-Event": "push"}).status_code == 200
    assert _post(client, hook, {"text": "b", "event": "STRAßE"}).status_code == 202   # a header is ASCII
    assert turns == ["a"]


def test_a_comma_is_refused_in_an_event_name(hub):
    client, _events, _turns = hub
    assert client.post("/api/webhooks", json={"target": "jarvis", "events": ["repo:push,tag"]},
                       headers=_ADMIN).status_code == 422
    hook = _hook(client)
    assert client.patch(f"/api/webhooks/{hook['id']}", json={"events": ["a,b"]}, headers=_ADMIN).status_code == 422


def test_a_template_that_renders_nothing_is_skipped_not_run(hub):
    client, _events, turns = hub
    hook = _hook(client, prompt="{missing}")
    reply = _post(client, hook, {"text": "hi"})
    assert reply.status_code == 202 and turns == []
    listed = _listed(client, hook["id"])
    assert listed["calls"] == 0 and listed["skipped"] == 1


def test_payload_dot_reads_a_key_the_template_reserves():
    assert render_prompt("{event} / {payload.event}", {"event": "from the body"}, "push") == "push / from the body"
    assert render_prompt("{payload.a.b}", {"a": {"b": "deep"}}, "") == "deep"


def test_an_index_equal_to_the_list_length_is_empty():
    assert render_prompt("[{commits.2.id}]", {"commits": [{"id": "a"}, {"id": "b"}]}, "") == "[]"


@pytest.mark.parametrize("field, ok, too_big", [
    ("events", [f"e{i}" for i in range(32)], [f"e{i}" for i in range(33)]),
    ("events", ["x" * 64], ["x" * 65]),
    ("prompt", "p" * 2000, "p" * 2001),
], ids=["32-names", "64-chars", "2000-chars"])
def test_the_stated_limits_hold_at_their_boundary(hub, field, ok, too_big):
    client, _events, _turns = hub
    assert client.post("/api/webhooks", json={"target": "jarvis", field: ok}, headers=_ADMIN).status_code == 200
    assert client.post("/api/webhooks", json={"target": "jarvis", field: too_big},
                       headers=_ADMIN).status_code == 422
    hook = _hook(client)
    assert client.patch(f"/api/webhooks/{hook['id']}", json={field: ok}, headers=_ADMIN).status_code == 200
    assert client.patch(f"/api/webhooks/{hook['id']}", json={field: too_big}, headers=_ADMIN).status_code == 422


def test_a_disabled_hook_refuses_an_unsubscribed_event_without_counting_a_skip(hub):
    client, _events, turns = hub
    hook = _hook(client, events=["push"])
    client.patch(f"/api/webhooks/{hook['id']}", json={"enabled": False}, headers=_ADMIN)
    reply = _post(client, hook, {"text": "hi"}, **{"X-GitHub-Event": "ping"})
    assert reply.status_code == 403 and turns == [] and _listed(client, hook["id"])["skipped"] == 0


def test_a_patched_event_list_is_stored_stripped_and_once(hub):
    client, _events, _turns = hub
    hook = _hook(client)
    reply = client.patch(f"/api/webhooks/{hook['id']}", json={"events": ["push", "Push", " push ", "ping"]},
                         headers=_ADMIN)
    assert reply.json()["webhook"]["events"] == ["push", "ping"]


def test_the_update_schema_advertises_no_null():
    from agents import web

    schema = web.app.openapi()["components"]["schemas"]["WebhookUpdateBody"]["properties"]
    assert all("null" not in json.dumps(prop) for prop in schema.values())
