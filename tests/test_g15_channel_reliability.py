"""G15 — channel reliability, from the owner's side (H081 delivery ledger and dead targets,
H100 reconnect ladder and fatal errors on the status surface, H116 bounded backfill).

What the owner can rely on, proven against fake Telegram and ntfy servers (no network):

* every reply has a receipt — sent, failed, partial, unknown or skipped — and none stores
  the reply's text;
* a crash never sends a reply twice: open rows are closed as failed/unknown at startup and
  nothing is resent; a keyed send is never repeated over a sent, in-flight or unknown one;
* a chat that is gone (bot blocked) stops being retried and is listed; it heals when the
  chat writes again;
* a dropped connection climbs one shared ladder with jitter and resets after being healthy;
  a revoked token stops the channel and says so on ``/status`` instead of retrying forever;
* messages sent while the hub was down are processed once after the restart, through the
  same gates as live ones (a stranger's backfilled message is held like a live one), within
  a bounded window and budget; a queued button tap is never applied.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import sqlite3
import time

import httpx
import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels import telegram as tg
from agents.core.channels.backfill import BackfillBudget, is_backlog
from agents.core.channels.delivery_ledger import ReliabilityStore
from agents.core.channels.gateway import Gateway
from agents.core.channels.manager import ChannelManager
from agents.core.channels.ntfy import NtfyChannel
from agents.core.channels.pairing import SenderPairing
from agents.core.channels.reconnect import Backoff, ChannelHealth, PollingCircuit, classify_status
from agents.core.channels.telegram import TelegramChannel

OWNER = 7
STRANGER = 666
_ids = itertools.count(5000)


# ── fake servers ─────────────────────────────────────────────────────────────


class FakeTelegram:
    """Bot API enough for the poll loop and sendMessage: getUpdates drops what an offset
    confirms, exactly like Telegram's server-side queue."""

    def __init__(self):
        self.queue: list[dict] = []
        self.offsets: list[int] = []
        self.poll_failures: list[tuple[int, dict]] = []
        self.sent: list[dict] = []
        self.send_failure: tuple[int, dict] | None = None
        self.answered: list[dict] = []
        self.requests = 0
        self.page_size = 100

    def message(self, text, *, uid=OWNER, chat_id=None, age=0.0):
        update = {"update_id": next(_ids), "message": {
            "message_id": next(_ids), "from": {"id": uid},
            "chat": {"id": uid if chat_id is None else chat_id, "type": "private"},
            "date": int(time.time() - age), "text": text}}
        self.queue.append(update)
        return update

    def tap(self, data="aut:1:approve", *, uid=OWNER):
        update = {"update_id": next(_ids), "callback_query": {
            "id": f"cb{next(_ids)}", "from": {"id": uid}, "data": data,
            "message": {"chat": {"id": uid}, "message_id": 1}}}
        self.queue.append(update)
        return update

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 999, "username": "nerva_bot"}})
        if method == "getUpdates":
            if self.poll_failures:
                status, body = self.poll_failures.pop(0)
                return httpx.Response(status, json=body)
            offset = int(request.url.params.get("offset", "0"))
            self.offsets.append(offset)
            self.queue = [u for u in self.queue if u["update_id"] >= offset]
            if not self.queue and request.url.params.get("timeout") not in (None, "0"):
                await asyncio.sleep(0.01)
            return httpx.Response(200, json={"ok": True, "result": list(self.queue[:self.page_size])})
        if method == "sendMessage":
            body = json.loads(request.content)
            if self.send_failure is not None:
                status, payload = self.send_failure
                return httpx.Response(status, json=payload)
            self.sent.append(body)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": next(_ids)}})
        if method == "answerCallbackQuery":
            self.answered.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(404, json={"ok": False})


def _telegram(server: FakeTelegram, handler, token="t"):
    channel = TelegramChannel(token=token, handler=handler)
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(server.handle))
    return channel


def _gated(tmp_path):
    """The real gateway with the real pairing gate: the owner paired, nobody else."""
    pairing = SenderPairing(tmp_path / "pairing.json")
    pairing.approve("telegram", str(OWNER))
    seen = []

    async def handler(text, channel="telegram", **kwargs):
        seen.append((text, kwargs.get("sender"), kwargs.get("chat_id")))
        return None

    return Gateway(handler=handler, pairing=pairing), seen


async def _until(condition, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


@pytest.fixture
def quick_batches(monkeypatch):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "10")
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MAX_MS", "40")


# ── H116: backfill after a restart ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_missed_messages_are_processed_once_after_restart_through_full_gating(
        tmp_path, quick_batches):
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    live = server.message("before the restart")
    first = _telegram(server, gateway.route)
    await first.start()
    await _until(lambda: len(seen) == 1)
    await first.stop()

    # While the hub is down: the owner writes, a stranger writes, an old message from
    # yesterday is still queued, and someone taps an approval button.
    server.queue.append(live)                           # Telegram would resend it unconfirmed
    server.message("while you were away", age=5)
    server.message("let me in", uid=STRANGER, age=30)
    server.message("seven hours ago", age=7 * 3600)
    server.tap()

    second = _telegram(server, gateway.route)
    await second.start()
    try:
        await _until(lambda: len(seen) == 2 and server.answered)
        await asyncio.sleep(0.15)
    finally:
        await second.stop()

    texts = [t for t, _sender, _chat in seen]
    assert texts == ["before the restart", "while you were away"]       # each once
    assert server.offsets[0] == 0                       # the first run had no saved offset
    # the stranger's backfilled message met the pairing gate exactly like a live one
    assert gateway.get_channel_info("telegram")["held_senders"] == 1
    assert all(sender != str(STRANGER) for _t, sender, _c in seen)
    # the queued tap was answered "not applied", never handed to a decision hook
    assert "offline" in server.answered[0]["text"]
    counts = second.health_snapshot()["backfill"]
    assert counts == {"processed": 2, "skipped_stale": 1, "skipped_over_budget": 0,
                      "refused_commands": 0, "refused_taps": 1}


@pytest.mark.asyncio
async def test_restart_resumes_from_the_saved_offset_so_a_handled_update_never_returns(
        tmp_path, quick_batches):
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    handled = server.message("answered once")
    first = _telegram(server, gateway.route)
    await first.start()
    await _until(lambda: len(seen) == 1)
    # The cursor is durable before shutdown. A second adapter in this process
    # must not impersonate a dead process while the first still owns its kernel
    # polling lease; actual process-death release is covered by H083 claim tests.
    await _until(lambda: first._cursor_store.cursor(first._cursor_name)
                 == str(handled["update_id"] + 1))
    await first.stop()

    server.queue.append(handled)                # unconfirmed on Telegram's side
    second = _telegram(server, gateway.route)
    await second.start()
    try:
        await _until(lambda: len(server.offsets) >= 3)
    finally:
        await second.stop()
    assert server.offsets[-1] == handled["update_id"] + 1
    assert [t for t, *_ in seen] == ["answered once"]


@pytest.mark.asyncio
async def test_backfill_is_bounded_and_keeps_the_newest(tmp_path, quick_batches, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_BACKFILL_MAX", "2")
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    for n, chat in enumerate((101, 102, 103, 104)):
        server.message(f"missed {n}", chat_id=chat, age=600 - n)
    channel = _telegram(server, gateway.route)
    await channel.start()
    try:
        await _until(lambda: len(seen) == 2)
        await asyncio.sleep(0.15)
    finally:
        await channel.stop()
    assert sorted(t for t, *_ in seen) == ["missed 2", "missed 3"]
    assert channel.health_snapshot()["backfill"]["skipped_over_budget"] == 2


@pytest.mark.asyncio
async def test_backfill_off_skips_every_old_message(tmp_path, quick_batches, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_BACKFILL_WINDOW_S", "0")
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    server.message("sent while down", age=5)
    channel = _telegram(server, gateway.route)
    await channel.start()
    try:
        await _until(lambda: len(server.offsets) >= 3)
        server.message("live now", age=-1)
        await _until(lambda: len(seen) == 1)
    finally:
        await channel.stop()
    assert [t for t, *_ in seen] == ["live now"]


def test_budget_admits_in_order_within_window_and_limit():
    budget = BackfillBudget(window_s=100, limit=2)
    now = 1000.0
    assert [budget.admit(t, now) for t in (850, 950, 960, 970)] == [False, True, True, False]
    assert budget.counts() == {"processed": 2, "skipped_stale": 1, "skipped_over_budget": 1,
                               "refused_commands": 0, "refused_taps": 0}
    assert is_backlog(999, 1000.5) and not is_backlog(1000, 1000.9)    # whole seconds


@pytest.mark.asyncio
async def test_the_newest_backfilled_messages_are_kept_across_pages(
        tmp_path, quick_batches, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_BACKFILL_MAX", "3")
    server = FakeTelegram()
    server.page_size = 4
    gateway, seen = _gated(tmp_path)
    for n in range(10):
        server.message(f"missed {n}", chat_id=200 + n, age=1000 - n)
    channel = _telegram(server, gateway.route)
    await channel.start()
    try:
        await _until(lambda: len(seen) == 3)
        await asyncio.sleep(0.15)
    finally:
        await channel.stop()
    assert sorted(t for t, *_ in seen) == ["missed 7", "missed 8", "missed 9"]
    assert channel.health_snapshot()["backfill"]["skipped_over_budget"] == 7


@pytest.mark.asyncio
async def test_a_backfilled_command_is_never_run_and_only_a_known_sender_is_told(
        tmp_path, quick_batches):
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    server.message("/resume", age=3 * 3600)              # typed 3 h ago, before an e-stop
    server.message("/approve 12", age=60)
    server.message("/start let-me-in", uid=STRANGER, age=30)
    channel = _telegram(server, gateway.route)
    channel.allowed_users = []
    channel._pairing = gateway.pairing
    await channel.start()
    try:
        await _until(lambda: len(server.offsets) >= 3)
        server.message("/status", age=-1)                 # live again: a command runs
        await _until(lambda: len(seen) == 1)
    finally:
        await channel.stop()
    assert [t for t, *_ in seen] == ["/status"]
    told = [m for m in server.sent if "offline" in m["text"]]
    assert [m["chat_id"] for m in told] == [OWNER, OWNER]    # the stranger hears nothing
    assert channel.health_snapshot()["backfill"]["refused_commands"] == 3


@pytest.mark.asyncio
async def test_a_backfilled_message_never_answers_a_pending_prompt(tmp_path, quick_batches):
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    asked = []

    async def pending(text, **kwargs):
        asked.append(text)
        return True                                      # would consume it as an answer

    server.message("yes", age=120)
    channel = _telegram(server, gateway.route)
    channel.pending_reply_handler = pending
    await channel.start()
    try:
        await _until(lambda: len(seen) == 1)
    finally:
        await channel.stop()
    assert asked == [] and [t for t, *_ in seen] == ["yes"]


@pytest.mark.asyncio
async def test_a_tap_queued_during_an_outage_is_refused(tmp_path, quick_batches, monkeypatch):
    server = FakeTelegram()
    gateway, _seen = _gated(tmp_path)
    channel = _telegram(server, gateway.route)

    async def no_wait(delay):
        server.tap()                                      # tapped while the API is down
        await asyncio.sleep(0)

    monkeypatch.setattr(tg, "_backoff_sleep", no_wait)
    await channel.start()
    try:
        await _until(lambda: len(server.offsets) >= 2)
        server.poll_failures = [(502, {"ok": False})]
        await _until(lambda: server.answered)
    finally:
        await channel.stop()
    assert "offline" in server.answered[0]["text"]


# ── ntfy: since= cursor ──────────────────────────────────────────────────────


class FakeNtfy:
    def __init__(self, status=200):
        self.cache: list[dict] = []
        self.params: list[dict] = []
        self.status = status

    def publish(self, key, text, *, age=0):
        self.cache.append({"event": "message", "id": key, "topic": "home", "message": text,
                           "time": int(time.time() - age)})

    async def handle(self, request):
        if request.method != "GET":
            return httpx.Response(200, json={"id": "published"})
        params = dict(request.url.params)
        self.params.append(params)
        if self.status != 200:
            return httpx.Response(self.status)
        since = int(params["since"]) if "since" in params else None
        frames = [m for m in self.cache if since is not None and m["time"] >= since]
        body = "".join(json.dumps(m) + "\n" for m in frames).encode()

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield body
                await asyncio.Event().wait()

        return httpx.Response(200, stream=Stream())


def _ntfy(tmp_path, server, *, paired=True):
    monkey_pairing = SenderPairing(tmp_path / f"ntfy-pairing-{paired}.json")
    if paired:
        monkey_pairing.approve("ntfy", "home")
    seen = []

    async def handler(text, **kwargs):
        seen.append(text)

    gateway = Gateway(handler=handler, pairing=monkey_pairing)
    channel = NtfyChannel("https://ntfy.example", "home",
                          client=httpx.AsyncClient(transport=httpx.MockTransport(server.handle)),
                          handler=gateway.route, pairing=monkey_pairing, inbound=True)
    return channel, gateway, seen


@pytest.mark.asyncio
@pytest.mark.parametrize("paired", [True, False])
async def test_ntfy_resumes_from_its_cursor_once_and_gated(tmp_path, paired):
    server = FakeNtfy()
    first, _gw, _seen = _ntfy(tmp_path, server)
    first._started_wall = None
    await first.start()
    first._taken("old", int(time.time()) - 120)        # the last message the hub took
    await first.stop()

    server.publish("old", "already handled", age=120)
    server.publish("m-down", "sent while down", age=60)
    second, gateway, seen = _ntfy(tmp_path, server, paired=paired)
    await second.start()
    try:
        if paired:
            await _until(lambda: seen == ["sent while down"])
        else:
            await _until(lambda: (gateway.get_channel_info("ntfy") or {}).get("held_senders") == 1)
        await asyncio.sleep(0.05)
    finally:
        await second.stop()
    assert "since" in server.params[-1]
    assert seen == (["sent while down"] if paired else [])


@pytest.mark.asyncio
async def test_ntfy_fatal_status_is_on_the_status_surface(tmp_path, monkeypatch):
    import agents.core.channels.ntfy as ntfy
    from agents.core.routers import status as status_router

    server = FakeNtfy(status=401)
    channel, *_ = _ntfy(tmp_path, server)
    waits = []

    async def sleep(delay):
        waits.append(delay)
        await asyncio.Event().wait()

    monkeypatch.setattr(ntfy, "sleep", sleep)
    await channel.start()
    try:
        await _until(lambda: waits)
        row = status_router._channel_health(channel)
    finally:
        await channel.stop()
    assert len(server.params) == 1 and waits == [600.0]    # no ladder: a slow re-probe
    assert row["state"] == "fatal" and row["fatal"] == "unauthorized"
    assert 590 <= row["retry_in_s"] <= 600


# ── H100: ladder, jitter, reset, fatal ───────────────────────────────────────


def test_ladder_climbs_with_jitter_and_resets_only_after_staying_healthy():
    clock = [0.0]
    backoff = Backoff(jitter=0, clock=lambda: clock[0], healthy_after=60)
    assert [backoff.failure() for _ in range(7)] == [1, 2, 5, 10, 30, 60, 60]
    backoff.success()
    clock[0] += 10
    backoff.success()
    assert backoff.failure() == 60              # a flap does not earn a fresh ladder
    backoff.success()
    clock[0] += 61
    backoff.success()
    assert backoff.failure() == 1               # sixty healthy seconds do
    low = Backoff(clock=lambda: 0.0, uniform=lambda a, b: a)
    high = Backoff(clock=lambda: 0.0, uniform=lambda a, b: b)
    assert low.failure() == pytest.approx(0.8) and high.failure() == pytest.approx(1.2)
    spread = {round(Backoff(clock=lambda: 0.0).failure(), 3) for _ in range(20)}
    assert len(spread) > 1 and all(0.8 <= d <= 1.2 for d in spread)


@pytest.mark.parametrize("status,kind,fatal", [
    (401, "unauthorized", True), (403, "forbidden", True), (404, "not_found", True),
    (409, "conflict", False), (429, "rate_limited", False), (502, "server_error", False),
])
def test_failures_are_classified(status, kind, fatal):
    failure = classify_status(status, {"parameters": {"retry_after": 9}})
    assert (failure.kind, failure.fatal) == (kind, fatal)
    if status == 429:
        assert failure.retry_after == 9


@pytest.mark.asyncio
async def test_telegram_climbs_the_ladder_then_heals(tmp_path, quick_batches, monkeypatch):
    server = FakeTelegram()
    server.poll_failures = [(502, {"ok": False}), (502, {"ok": False}),
                            (429, {"ok": False, "parameters": {"retry_after": 7}})]
    waits, states = [], []
    channel = _telegram(server, _gated(tmp_path)[0].route)
    now = [0.0]
    channel._poll_circuit = PollingCircuit(clock=lambda: now[0])

    async def no_wait(delay):
        waits.append(delay)
        states.append(channel.health_snapshot()["state"])
        # Advance the same clock that enforces the server's retry-after deadline.
        now[0] += delay

    monkeypatch.setattr(tg, "_backoff_sleep", no_wait)
    channel._ladder().jitter = 0
    await channel.start()
    try:
        await _until(lambda: len(server.offsets) >= 2)
    finally:
        await channel.stop()
    assert waits == [1, 2, 7]                    # the ladder, then the server's retry_after
    assert states == ["retrying"] * 3
    snapshot = channel.health.snapshot()
    assert snapshot["failures"] == 0 and snapshot["last_ok"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404])
async def test_a_revoked_token_stops_the_channel_and_shows_on_status(
        tmp_path, quick_batches, status, monkeypatch):
    from types import SimpleNamespace

    from agents.core.routers import status as status_router

    server = FakeTelegram()
    server.poll_failures = [(status, {"ok": False, "description": "Unauthorized"})] * 2
    channel = _telegram(server, _gated(tmp_path)[0].route)
    waits, rows = [], []

    async def probe_later(delay):
        waits.append(delay)
        rows.extend(status_router._channel_rows(SimpleNamespace(channels={"telegram": channel})))
        if len(waits) == 2:
            await asyncio.Event().wait()

    monkeypatch.setattr(tg, "_backoff_sleep", probe_later)
    monkeypatch.setattr(status_router, "get_gateway", lambda: None)
    await channel.start()
    try:
        await _until(lambda: len(waits) == 2)
        server.poll_failures = []
    finally:
        await channel.stop()
    assert waits == [600.0, 600.0]               # no ladder: one slow re-probe at a time
    assert rows[0]["health"]["state"] == "fatal"
    assert rows[0]["health"]["fatal"] in {"unauthorized", "not_found"}
    assert "t" not in {v for v in rows[0]["health"].values() if isinstance(v, str)}


def test_health_snapshot_carries_kinds_and_counts_only():
    health = ChannelHealth()
    health.retrying("network", 5)
    snap = health.snapshot()
    assert snap["state"] == "retrying" and snap["error"] == "network" and snap["failures"] == 1
    assert 0 <= snap["retry_in_s"] <= 5
    health.failed_fatally("unauthorized")
    health.stopped()
    assert health.snapshot()["state"] == "fatal"      # stopping keeps the reason visible


# ── H081: ledger, receipts, dead targets ─────────────────────────────────────


def _manager(server, tmp_path):
    manager = ChannelManager()
    channel = _telegram(server, None)
    manager.register(channel)
    return manager, channel


def _rows(store):
    return store.recent(50)


@pytest.mark.asyncio
async def test_every_reply_gets_a_receipt_and_no_body_is_stored(tmp_path):
    server = FakeTelegram()
    manager, _channel = _manager(server, tmp_path)
    store = delivery_ledger.store()
    secret = "the alarm code is 4321"
    assert await manager.send("telegram", secret, chat_id=OWNER) is True
    server.send_failure = (500, {"ok": False, "description": "Internal"})
    assert await manager.send("telegram", "second", chat_id=OWNER) is False
    states = [r["state"] for r in _rows(store)]
    assert states == ["unknown", "sent"]      # a 5xx may have been stored: never claimed failed
    raw = sqlite3.connect(store.path).iterdump()
    assert secret not in "\n".join(raw)
    assert store.stats()["needs_attention"] == 1


@pytest.mark.asyncio
async def test_a_partial_send_is_recorded_as_partial(tmp_path):
    server = FakeTelegram()
    manager, _channel = _manager(server, tmp_path)
    calls = {"n": 0}
    original = server.handle

    async def second_chunk_fails(request):
        if request.url.path.endswith("sendMessage"):
            calls["n"] += 1
            if calls["n"] > 1:
                return httpx.Response(400, json={"ok": False, "description": "Bad Request"})
        return await original(request)

    _channel.client = httpx.AsyncClient(transport=httpx.MockTransport(second_chunk_fails))
    assert await manager.send("telegram", "word " * 2000, chat_id=OWNER) is False
    assert _rows(delivery_ledger.store())[0]["state"] == "partial"


@pytest.mark.asyncio
async def test_a_dead_chat_is_not_retried_is_listed_and_heals(tmp_path):
    server = FakeTelegram()
    manager, channel = _manager(server, tmp_path)
    store = delivery_ledger.store()
    server.send_failure = (403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})
    assert await manager.send("telegram", "hello", chat_id=55) is False
    assert store.is_dead("telegram", 55)
    assert store.dead_targets()[0]["reason"] == "forbidden"
    before = server.requests
    assert await manager.send("telegram", "again", chat_id=55) is False
    assert server.requests == before                       # not even tried
    assert _rows(store)[0]["state"] == "skipped" and _rows(store)[0]["error"] == "dead_target"
    # the chat writes to the bot again: the flag lifts and the next reply is tried
    channel._heal_dead_target({"update_id": 1, "message": {"chat": {"id": 55}, "from": {"id": 55}}})
    assert not store.is_dead("telegram", 55)
    server.send_failure = None
    assert await manager.send("telegram", "back", chat_id=55) is True


@pytest.mark.asyncio
async def test_a_thread_level_not_found_does_not_kill_the_chat(tmp_path):
    server = FakeTelegram()
    manager, _channel = _manager(server, tmp_path)
    server.send_failure = (400, {"ok": False, "description": "Bad Request: message thread not found"})
    assert await manager.send("telegram", "hello", chat_id=56) is False
    assert not delivery_ledger.store().is_dead("telegram", 56)


@pytest.mark.asyncio
async def test_a_crash_never_double_sends(tmp_path, monkeypatch):
    server = FakeTelegram()
    manager, _channel = _manager(server, tmp_path)
    store = delivery_ledger.store()
    # A previous process wrote "attempting" for a keyed reply and died mid-send, and left
    # another reply "pending" (never handed to Telegram).
    in_flight = store.open_delivery("telegram", OWNER, "the reply", key="turn-1")
    in_flight.attempting()
    never_sent = store.open_delivery("telegram", OWNER, "other", key="turn-2")
    monkeypatch.setattr(delivery_ledger, "_BOOT", "next-process")
    assert store.recover(alive=lambda pid: False) == {"failed": 1, "unknown": 1}
    assert store.get(in_flight.id)["state"] == "unknown"
    assert store.get(never_sent.id)["state"] == "failed"
    # The restarted hub produces the same keyed reply: it is not sent again...
    assert await manager.send("telegram", "the reply", chat_id=OWNER, delivery_key="turn-1") is False
    assert server.sent == []
    # ...but the provably unsent one may go out, once.
    assert await manager.send("telegram", "other", chat_id=OWNER, delivery_key="turn-2") is True
    assert await manager.send("telegram", "other", chat_id=OWNER, delivery_key="turn-2") is True
    assert len(server.sent) == 1


def test_recovery_leaves_a_live_process_alone(tmp_path):
    store = ReliabilityStore(tmp_path / "r.db")
    row = store.open_delivery("telegram", 1, "x")
    row.attempting()
    assert store.recover() == {"failed": 0, "unknown": 0}       # this very process
    assert store.get(row.id)["state"] == "attempting"


def test_keyed_retries_are_capped(tmp_path):
    store = ReliabilityStore(tmp_path / "r.db")
    for _ in range(3):
        row = store.open_delivery("telegram", 1, "x", key="k")
        assert row.send
        row.finished(False)
    assert store.open_delivery("telegram", 1, "x", key="k").send is False
    assert store.recent(1)[0]["error"] == "attempts_exhausted"


@pytest.mark.asyncio
async def test_receipts_route_lists_states_dead_targets_and_health(tmp_path, monkeypatch):
    from agents.core.routers import integrations

    server = FakeTelegram()
    manager, channel = _manager(server, tmp_path)
    await manager.send("telegram", "hi", chat_id=OWNER)
    delivery_ledger.store().mark_dead("telegram", 77, "forbidden")
    from types import SimpleNamespace
    monkeypatch.setattr(integrations, "get_orch", lambda: SimpleNamespace(channel_manager=manager))
    response = await integrations.channels_deliveries(limit=10, state="")
    body = json.loads(response.body)
    assert body["stats"]["by_state"]["sent"] == 1
    assert body["deliveries"][0]["chars"] == 2 and "hi" not in json.dumps(body["deliveries"])
    assert body["dead_targets"][0]["target"] == "77"
    assert "telegram" in body["health"]
    cleared = await integrations.channels_dead_target_clear(
        integrations.DeadTargetClearBody(channel="telegram", target="77"))
    assert json.loads(cleared.body) == {"cleared": True}


# ── review fixes (G15 adversarial review) ────────────────────────────────────


def test_a_container_restart_with_the_same_pid_still_closes_open_rows(tmp_path, monkeypatch):
    import os

    store = ReliabilityStore(tmp_path / "r.db")
    row = store.open_delivery("telegram", 1, "x", key="k")
    row.attempting()
    monkeypatch.setattr(delivery_ledger, "_BOOT", "after-restart")   # PID 1 again, new boot
    assert store.recover(alive=lambda pid: pid == os.getpid()) == {"failed": 0, "unknown": 1}
    assert store.get(row.id)["state"] == "unknown"


def test_a_live_other_process_keeps_its_fresh_rows_but_not_stale_ones(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "r.db")
    fresh = store.open_delivery("telegram", 1, "x")
    stale = store.open_delivery("telegram", 2, "y")
    with store._conn:
        store._conn.execute("UPDATE deliveries SET pid=?", (424242,))
        store._conn.execute("UPDATE deliveries SET updated=updated-7200 WHERE id=?", (stale.id,))
    monkeypatch.setattr(delivery_ledger, "_BOOT", "other")
    assert store.recover(alive=lambda pid: True) == {"failed": 1, "unknown": 0}
    assert store.get(fresh.id)["state"] == "pending"
    assert store.get(stale.id)["state"] == "failed"


def test_the_ledger_keeps_nothing_derived_from_the_text(tmp_path):
    store = ReliabilityStore(tmp_path / "r.db")
    store.open_delivery("telegram", 1, "secret words")
    columns = [r[1] for r in store._conn.execute("PRAGMA table_info(deliveries)")]
    assert "digest" not in columns
    tables = {r[0] for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "meta" not in tables


def test_the_store_reopens_after_the_data_root_is_purged(tmp_path):
    first = ReliabilityStore(tmp_path / "purged" / "r.db")
    delivery_ledger.set_store(first)
    first.path.unlink()
    second = delivery_ledger.store()
    assert second is not first


@pytest.mark.asyncio
@pytest.mark.parametrize("text,fatal", [
    (b"[UNAVAILABLE] Temporary authentication failure.", False),
    (b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)", True),
])
async def test_imap_auth_failures_are_fatal_only_when_permanent(monkeypatch, text, fatal):
    import imaplib

    from agents.core.channels import email as em

    channel = em.EmailChannel()
    channel._running = True
    channel.imap = {"poll_interval": 0}
    waits = []

    async def boom():
        raise imaplib.IMAP4.error(text)

    async def sleep(delay):
        waits.append(delay)
        channel._running = False

    channel._check_imap = boom
    monkeypatch.setattr(em.asyncio, "sleep", sleep)
    await asyncio.wait_for(channel._poll_loop(), 2)
    assert channel.health.state == ("fatal" if fatal else "retrying")
    assert waits == [600.0] if fatal else 24 <= waits[0] <= 36


@pytest.mark.asyncio
async def test_a_fatal_channel_is_reported_on_another_channel(tmp_path):
    server = FakeNtfy()
    ntfy_channel, *_ = _ntfy(tmp_path, server)
    ntfy_channel._running = True
    manager = ChannelManager()
    manager.register(ntfy_channel)
    telegram = _telegram(FakeTelegram(), None)
    manager.register(telegram)
    posts = []
    original = server.handle

    async def record(request):
        if request.method == "POST":
            posts.append(request.content.decode())
        return await original(request)

    ntfy_channel.client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    try:
        telegram.health.failed_fatally("unauthorized")
        telegram.health.failed_fatally("unauthorized")      # once per episode
        await _until(lambda: posts)
        await asyncio.sleep(0.05)
        assert len(posts) == 1 and "telegram" in posts[0].lower()
        assert "unavailable" in posts[0] and "unauthorized" not in posts[0]
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_ntfy_backfilled_command_is_refused_and_replays_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_BACKFILL_MAX", "1")
    server = FakeNtfy()
    first, *_ = _ntfy(tmp_path, server)
    await first.start()
    first._taken("old", int(time.time()) - 300)
    await first.stop()
    server.publish("c1", "/resume", age=200)
    server.publish("m1", "first missed", age=100)
    server.publish("m2", "second missed", age=50)
    second, _gateway, seen = _ntfy(tmp_path, server)
    posts = []
    original = server.handle

    async def record(request):
        if request.method == "POST":
            posts.append(request.content.decode())
        return await original(request)

    second.client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    await second.start()
    try:
        await _until(lambda: seen and posts and second.health.backfill.get("skipped_over_budget"))
        await asyncio.sleep(0.05)
        counts = dict(second.health.backfill)
    finally:
        await second.stop()
    assert seen == ["first missed"]                       # budget 1, command never run
    assert any("offline" in p for p in posts)
    assert counts["refused_commands"] == 1 and counts["skipped_over_budget"] == 1


def test_backfill_variables_take_the_nerva_spelling(monkeypatch):
    from agents.core.channels.backfill import configured_max, configured_window

    monkeypatch.delenv("JARVIS_CHANNEL_BACKFILL_MAX", raising=False)
    monkeypatch.delenv("JARVIS_CHANNEL_BACKFILL_WINDOW_S", raising=False)
    monkeypatch.setenv("NERVA_CHANNEL_BACKFILL_MAX", "7")
    monkeypatch.setenv("NERVA_CHANNEL_BACKFILL_WINDOW_S", "60")
    assert configured_max() == 7 and configured_window() == 60
