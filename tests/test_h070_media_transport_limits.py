"""The owner media budget reaches settings validation and actual transports."""

from email.message import EmailMessage

import pytest

from agents.core import settings_db
from agents.core.channels.email import EmailChannel
from agents.core.channels.inbound_media import classify
from agents.core.channels.inbound_voice import InboundVoiceReader
from agents.core.channels.media_reader import InboundImageReader
from agents.core.channels.telegram import TelegramChannel
from tests.test_inbound_media_read import PNG, _Client, _Config, _Spy


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1024", 20 * 1024 * 1024 + 1])
def test_invalid_media_budget_is_rejected_before_settings_write(value):
    assert settings_db.validate_category("channels", {"max_inbound_media_bytes": value})


def test_media_budget_is_declared_for_existing_settings_surfaces():
    row = next(row for row in settings_db.DEFAULTS
               if (row["category"], row["key"]) == ("channels", "max_inbound_media_bytes"))
    assert row["value"] == 8 * 1024 * 1024 and row["kind"] == "number"
    assert settings_db.validate_category("channels", {"max_inbound_media_bytes": 1024}) == []


def test_email_extraction_uses_current_owner_budget(monkeypatch):
    limit = [3]
    original = settings_db.get_value
    monkeypatch.setattr(settings_db, "get_value", lambda cat, key, default=None:
                        limit[0] if (cat, key) == ("channels", "max_inbound_media_bytes")
                        else original(cat, key, default))
    message = EmailMessage()
    message.set_content("attached")
    message.add_attachment(b"four", maintype="text", subtype="plain", filename="note.txt")
    channel = EmailChannel()
    assert channel._parse(message.as_bytes())["attachments"][0].data is None
    limit[0] = 4
    assert channel._parse(message.as_bytes())["attachments"][0].data == b"four"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["photo", "voice"])
async def test_telegram_stream_obeys_live_budget_even_if_sender_claims_one_byte(monkeypatch, kind):
    limit = [len(PNG) - 1]
    original = settings_db.get_value
    monkeypatch.setattr(settings_db, "get_value", lambda cat, key, default=None:
                        limit[0] if (cat, key) == ("channels", "max_inbound_media_bytes")
                        else original(cat, key, default))
    channel = TelegramChannel(token="offline")
    channel.client = _Client(chunks=[PNG])
    calls = []

    async def transcribe(data, language):
        calls.append(data)
        return "a short voice message"

    spy = _Spy()
    channel._image_reader = InboundImageReader(config=_Config(is_local=True), vlm_generate=spy)
    channel._voice_reader = InboundVoiceReader(transcribe=transcribe, available=True)
    payload = {"file_id": "offline", "file_size": 1}
    attachment = classify({kind: [payload] if kind == "photo" else payload})
    read = channel._read_image if kind == "photo" else channel._read_voice
    result = await read(attachment)
    assert not result.ok and not calls and not spy.seen
    limit[0] = len(PNG)
    assert (await read(attachment)).ok
    assert len(calls if kind == "voice" else spy.seen) == 1
