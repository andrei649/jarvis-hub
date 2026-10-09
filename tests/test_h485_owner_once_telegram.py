"""One-use Telegram callback lane bypass and physical delivery proof."""

import asyncio
import json
import uuid

import httpx
import pytest

from agents.core.autonomy.inbox import build_owner_once_card, parse_owner_once_callback_data
from agents.core.channels.chat_lanes import ChatLanes
from agents.core.channels.telegram import TelegramChannel
from agents.core.owner_once_context import current_owner_reply_source

NONCE = "0123456789abcdef0123456789abcdef"


def _tap(data=f"aut1:{NONCE}:a", *, callback_id="tap", user_id=42, chat_id=-500):
    return {"callback_query": {"id": callback_id, "data": data,
                               "from": {"id": user_id},
                               "message": {"message_id": 17, "chat": {"id": chat_id}}}}


def test_strict_nonce_parser_and_two_button_redacted_card():
    assert parse_owner_once_callback_data(f"aut1:{NONCE}:a") == (NONCE, "once")
    assert parse_owner_once_callback_data(f"aut1:{NONCE}:r") == (NONCE, "deny")
    for bad in (f"aut1:{NONCE.upper()}:a", f"aut1:{NONCE}:accept", f"aut1:{NONCE}:a:x",
                "aut1:short:a", f" aut1:{NONCE}:a", f"aut:{NONCE}:a"):
        assert parse_owner_once_callback_data(bad) is None
    task = {"id": 9, "payload": {"tool": "terminal_run", "args": {
        "target": "local", "command": "curl -H 'Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz123456' example.test"}}}
    card = build_owner_once_card(task, NONCE)
    buttons = card["reply_markup"]["inline_keyboard"]
    assert len(buttons) == 1 and len(buttons[0]) == 2
    assert [button["callback_data"] for button in buttons[0]] == [f"aut1:{NONCE}:a", f"aut1:{NONCE}:r"]
    assert "guardian" in card["text"].lower()
    assert "terminal_run" in card["text"] and "local" in card["text"]
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in card["text"]
    assert len(card["text"].encode()) <= 4096


def test_owner_once_card_preserves_full_valid_four_thousand_character_command():
    prefix, suffix = "echo safe; ", "rm -rf /tmp/example"
    command = prefix + " " * (4000 - len(prefix) - len(suffix)) + suffix
    assert len(command) == 4000
    task = {"id": 9, "payload": {"tool": "terminal_run", "args": {
        "target": "local", "command": command}}}
    card = build_owner_once_card(task, NONCE)
    assert command in card["text"]
    assert "parse_mode" not in card


def test_owner_once_card_refuses_malformed_or_unredactable_command(monkeypatch):
    task = {"id": 9, "payload": {"tool": "terminal_run", "args": {
        "target": "local", "command": "x" * 4001}}}
    with pytest.raises(ValueError):
        build_owner_once_card(task, NONCE)
    task["payload"]["args"]["command"] = "echo safe"
    from agents.core.security.scanner import SecretScanner
    monkeypatch.setattr(SecretScanner, "redact", lambda *_: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(ValueError):
        build_owner_once_card(task, NONCE)


def test_owner_once_card_shows_literal_shell_metacharacters_without_markup():
    command = "printf '%s' '`[demo]*_\\suffix'"
    task = {"id": 10, "payload": {"tool": "terminal_run", "args": {
        "target": "local", "command": command}}}
    card = build_owner_once_card(task, NONCE)
    assert "parse_mode" not in card
    assert command in card["text"]


async def test_reserved_callback_bypasses_occupied_same_chat_lane_and_replay_does_not():
    turn_entered = asyncio.Event()
    release_turn = asyncio.Event()
    dispatched = asyncio.Event()
    answers = []

    async def handler(_text, **_kwargs):
        assert current_owner_reply_source() is not None
        turn_entered.set()
        await release_turn.wait()

    def transport(req):
        assert req.url.path.endswith("/answerCallbackQuery")
        answers.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel("test-token", handler=handler)
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    channel._lanes = ChatLanes(name="test")
    called = []

    def pending(cb):
        return cb.get("id") == "first"

    async def callback(nonce, choice, *, chat_id, user_id, message_id):
        called.append((nonce, choice, chat_id, user_id, message_id))
        release_turn.set()
        dispatched.set()
        return "approved"

    channel.owner_once_pending = pending
    channel.on_owner_once_callback = callback
    try:
        await channel._deliver_turn(-500, 42, "hello")
        await asyncio.wait_for(turn_entered.wait(), 1)
        await channel._handle_update(_tap(callback_id="first"))
        await asyncio.wait_for(dispatched.wait(), 1)
        assert called == [(NONCE, "once", -500, 42, 17)]
        await channel._handle_update(_tap(callback_id="replay"))
        await asyncio.sleep(0)
        assert len(called) == 1
        assert any(a["callback_query_id"] == "first" and a["text"].startswith("OK") for a in answers)
    finally:
        release_turn.set()
        await channel.stop()


async def test_send_owner_once_card_requires_strict_telegram_receipt_and_liveness():
    payloads = [
        {"ok": True, "result": {"message_id": 18}},
        {"ok": False, "result": {"message_id": 19}},
        {"ok": 1, "result": {"message_id": 20}},
        {"ok": True, "result": {"message_id": True}},
        {"ok": True, "result": {"message_id": -1}},
        {"ok": True, "result": {}},
    ]
    def transport(req):
        return httpx.Response(200, json=payloads.pop(0))

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    card = {"text": "test", "reply_markup": {"inline_keyboard": []}}
    try:
        assert await channel.send_owner_once_card(-500, card) == 18
        for _ in range(5):
            assert await channel.send_owner_once_card(-500, card) is None
        assert await channel.send_owner_once_card(-500, card) is None
    finally:
        channel._poll_task.cancel()
        await asyncio.gather(channel._poll_task, return_exceptions=True)
        await channel.client.aclose()


async def test_send_owner_once_card_refuses_http_json_and_generation_race():
    def transport(req):
        text = json.loads(req.content)["text"]
        if text == "http":
            return httpx.Response(500, json={"ok": True, "result": {"message_id": 9}})
        if text == "json":
            return httpx.Response(200, content=b"not json")
        channel._owner_once_generation = uuid.uuid4().hex
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    try:
        for value in ("http", "json", "race"):
            assert await channel.send_owner_once_card(-500, {"text": value}) is None
    finally:
        channel._poll_task.cancel()
        await asyncio.gather(channel._poll_task, return_exceptions=True)
        await channel.client.aclose()


async def test_multipart_uses_utf16_units_and_only_final_part_has_keyboard():
    command = "😀" * 4000
    card = build_owner_once_card({"id": 9, "payload": {"tool": "terminal_run", "args": {
        "target": "local", "command": command}}}, NONCE)
    bodies = []

    def transport(request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(bodies)}})

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    try:
        assert await channel.send_owner_once_card(-500, card) == len(bodies)
        assert len(bodies) >= 2
        assert "".join(body["text"] for body in bodies) == card["text"]
        assert all(len(body["text"].encode("utf-16-le")) // 2 <= 4096 for body in bodies)
        assert all("reply_markup" not in body and "parse_mode" not in body for body in bodies[:-1])
        assert bodies[-1]["reply_markup"] == card["reply_markup"]
        assert "parse_mode" not in bodies[-1]
    finally:
        channel._poll_task.cancel()
        await asyncio.gather(channel._poll_task, return_exceptions=True)
        await channel.client.aclose()


@pytest.mark.parametrize("failure", ["false", "missing", "generation"])
async def test_intermediate_failure_never_sends_actionable_final_part(failure):
    card = build_owner_once_card({"id": 9, "payload": {"tool": "terminal_run", "args": {
        "target": "local", "command": "😀" * 4000}}}, NONCE)
    bodies = []

    def transport(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            if failure == "false":
                return httpx.Response(200, json={"ok": False, "result": {"message_id": 1}})
            if failure == "missing":
                return httpx.Response(200, json={"ok": True, "result": {}})
            channel._owner_once_generation = uuid.uuid4().hex
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(bodies)}})

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    try:
        assert await channel.send_owner_once_card(-500, card) is None
        assert len(bodies) == 1 and "reply_markup" not in bodies[0]
    finally:
        channel._poll_task.cancel()
        await asyncio.gather(channel._poll_task, return_exceptions=True)
        await channel.client.aclose()


@pytest.mark.parametrize("change", ["generation", "callback", "pending"])
async def test_queued_fast_callback_rechecks_registration_before_dispatch(change):
    answers = []
    called = []

    def transport(request):
        answers.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    async def original(*_args, **_kwargs):
        called.append("original")
        return "allowed"

    async def replacement(*_args, **_kwargs):
        called.append("replacement")
        return "allowed"

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    channel._lanes = ChatLanes(name="test")
    channel.owner_once_pending = lambda _cb: True
    channel.on_owner_once_callback = original
    try:
        await channel._handle_update(_tap(callback_id="queued"))
        if change == "generation":
            channel._owner_once_generation = uuid.uuid4().hex
        elif change == "callback":
            channel.on_owner_once_callback = replacement
        else:
            channel.owner_once_pending = lambda _cb: True
        await asyncio.sleep(0)
        assert called == []
        assert all(not body.get("text", "").startswith("OK") for body in answers)
    finally:
        await channel.stop()


async def test_physical_poll_callback_resolves_occupied_lane_and_stop_revokes_first():
    turn_entered = asyncio.Event()
    release_turn = asyncio.Event()
    delivered = asyncio.Event()
    callback_release = asyncio.Event()
    stop_seen = []
    answers = []

    async def handler(_text, **_kwargs):
        source = current_owner_reply_source()
        assert source is not None and source.chat_id == -500
        turn_entered.set()
        await release_turn.wait()

    async def callback(_nonce, _choice, **_kwargs):
        delivered.set()
        release_turn.set()
        await callback_release.wait()
        return "allowed"

    def transport(request):
        answers.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel("test-token", handler=handler)
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel.owner_once_pending = lambda cb: cb.get("id") == "first"
    channel.on_owner_once_callback = callback
    channel.on_owner_once_stop = lambda generation: stop_seen.append(
        (generation, channel._running, channel._owner_once_generation)
    )
    sent = False

    async def get_updates(**_kwargs):
        nonlocal sent
        if not sent:
            sent = True
            await channel._deliver_turn(-500, 42, "question")
            await asyncio.wait_for(turn_entered.wait(), 1)
            return [{"update_id": 1, **_tap(callback_id="first")}]
        await asyncio.sleep(100)

    channel._get_updates = get_updates
    channel._poll_task = asyncio.create_task(channel._poll_loop())
    try:
        await asyncio.wait_for(delivered.wait(), 1)
        assert channel._owner_once_fast
        await channel.stop()
        assert stop_seen == [(stop_seen[0][0], False, None)]
        assert not channel._owner_once_fast
        assert answers == []  # cancelled callback never claims completed approval
    finally:
        callback_release.set()
        release_turn.set()
        if channel._running:
            await channel.stop()


async def test_duplicate_nonce_does_not_dispatch_second_callback_while_first_active():
    entered = asyncio.Event()
    release = asyncio.Event()
    acknowledged = asyncio.Event()
    count = 0
    answers = []

    async def callback(*_args, **_kwargs):
        nonlocal count
        count += 1
        entered.set()
        await release.wait()
        return "allowed"

    def transport(req):
        answers.append(json.loads(req.content))
        if answers[-1]["callback_query_id"] == "first":
            acknowledged.set()
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    channel._lanes = ChatLanes(name="test")
    channel.owner_once_pending = lambda _cb: True
    channel.on_owner_once_callback = callback
    try:
        await channel._handle_update(_tap(callback_id="first"))
        await asyncio.wait_for(entered.wait(), 1)
        await channel._handle_update(_tap(callback_id="duplicate"))
        await asyncio.sleep(0)
        assert count == 1
        release.set()
        await asyncio.wait_for(acknowledged.wait(), 1)
    finally:
        release.set()
        await channel.stop()
    assert count == 1
    assert any(a["callback_query_id"] == "first" for a in answers)
    assert all(not a["text"].startswith("OK") for a in answers if a["callback_query_id"] == "duplicate")
