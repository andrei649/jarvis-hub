"""Native Bot API receipts and the independent reusable-consent callback lane."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from agents.core.autonomy.consent_types import ConsentOffer
from agents.core.autonomy.inbox import build_consent_card, parse_consent_callback_data
from agents.core.channels.chat_lanes import ChatLanes
from agents.core.channels.telegram import TelegramChannel


def _task(command="git reset --hard"):
    return {"id": 41, "kind": "toolrpc.terminal_run", "payload": {
        "tool": "terminal_run", "args": {"target": "local-host", "command": command},
    }}


def _offer(count=2):
    from agents.core.autonomy.consent_ledger import ConsentCategory

    return ConsentOffer(41, "f" * 64, tuple(range(41, 41 + count)),
                        (ConsentCategory("terminal.warning.git_reset"),))


def test_consent_callback_alphabet_and_card_are_bounded():
    nonce = "a" * 32
    assert parse_consent_callback_data(f"autc:{nonce}:s") == (nonce, "session")
    assert parse_consent_callback_data(f"autc:{nonce}:a") == (nonce, "always")
    assert parse_consent_callback_data(f"autc:{nonce}:d") == (nonce, "deny")
    for bad in (f"autc:{nonce.upper()}:s", f"autc:{nonce}:x", f"autc:{nonce}:s:extra",
                f"aut1:{nonce}:a", "aut:41:accept", None, 1):
        assert parse_consent_callback_data(bad) is None
    card = build_consent_card(_task(), _offer(), nonce)
    assert "git reset --hard" in card["text"]
    assert "2" in card["text"]
    buttons = [button for row in card["reply_markup"]["inline_keyboard"] for button in row]
    assert {parse_consent_callback_data(button["callback_data"])[1] for button in buttons} == {
        "session", "always", "deny",
    }
    assert all(len(button["callback_data"].encode()) <= 64 for button in buttons)
    with pytest.raises(ValueError):
        build_consent_card(_task("x" * 4001), _offer(), nonce)
    with pytest.raises(ValueError):
        build_consent_card(_task(), _offer(), "not-a-nonce")


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    {"ok": False, "result": {"message_id": 17}}, {"ok": True, "result": {}},
    {"ok": True, "result": {"message_id": 0}},
])
async def test_consent_send_requires_native_positive_receipt(reply):
    calls = []

    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=reply)

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    try:
        assert await channel.send_consent_card(99, build_consent_card(_task(), _offer(), "a" * 32)) is None
        assert len(calls) == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_consent_multipart_receipt_buttons_only_on_final_part():
    cards = []

    def transport(request):
        payload = json.loads(request.content)
        cards.append(payload)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 30 + len(cards)}})

    channel = TelegramChannel("test-token")
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    try:
        card = build_consent_card(_task("x" * 4000), _offer(), "b" * 32)
        assert await channel.send_consent_card(99, card) == 30 + len(cards)
        assert len(cards) >= 2
        assert all("reply_markup" not in part for part in cards[:-1])
        assert "reply_markup" in cards[-1]
        assert "x" in cards[-1]["text"]
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_consent_callback_bypasses_occupied_chat_lane_and_replay_refuses():
    acknowledgements = []
    entered = asyncio.Event()
    release = asyncio.Event()
    committed = asyncio.Event()
    nonce = "c" * 32

    async def handler(_text, **_kwargs):
        entered.set()
        await release.wait()

    def transport(request):
        if request.url.path.endswith("/answerCallbackQuery"):
            acknowledgements.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel("test-token", handler=handler)
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    channel._lanes = ChatLanes(name="consent-callback-test")
    pending = {nonce}
    channel.consent_pending = lambda cb: cb["data"] == f"autc:{nonce}:s" and nonce in pending

    async def callback(received_nonce, choice, **_kwargs):
        assert received_nonce == nonce and choice == "session"
        pending.remove(nonce)
        committed.set()
        return "accepted"

    channel.on_consent_callback = callback
    cb = {"id": "tap", "data": f"autc:{nonce}:s", "from": {"id": 99},
          "message": {"message_id": 17, "chat": {"id": 99}}}
    try:
        await channel._deliver_turn(99, 99, "run")
        await asyncio.wait_for(entered.wait(), 1)
        await channel._handle_update({"callback_query": cb})
        await asyncio.wait_for(committed.wait(), 1)
        await asyncio.gather(*tuple(channel._consent_fast.values()))
        assert acknowledgements[0]["text"] == "OK: session"
        await channel._handle_update({"callback_query": cb})
        assert acknowledgements[-1]["text"] == "Not applied."
        malformed = {**cb, "data": f"autc:{nonce}:invalid"}
        before = len(acknowledgements)
        await asyncio.wait_for(channel._handle_update({"callback_query": malformed}), 1)
        assert len(acknowledgements) == before + 1
        assert acknowledgements[-1]["text"] == "Not applied."
    finally:
        release.set()
        await channel.stop()
