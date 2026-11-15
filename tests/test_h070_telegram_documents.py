"""Telegram documents enter a bounded, fenced context only after sender admission."""

from __future__ import annotations

import pytest

from agents.core.channels.inbound_document import InboundDocumentReader
from agents.core.channels.inbound_media import KIND_DOCUMENT, classify
from agents.core.channels.pairing import SenderPairing
from agents.core.channels.telegram import TelegramChannel


def _channel(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    pairing = SenderPairing(tmp_path / "pairing.json")
    turns, sent, downloads = [], [], []

    async def handler(text, **kwargs):
        turns.append((text, kwargs))

    channel = TelegramChannel("offline", handler=handler, pairing=pairing)
    channel._bot_id, channel._bot_username = 99, "nerva_bot"

    async def send(text, **kwargs):
        sent.append(text)
        return True

    async def download(file_id, max_bytes):
        downloads.append((file_id, max_bytes))
        return b"notes from the attached document"

    channel.send = send
    channel.send_action = lambda *args, **kwargs: _send_action()
    channel._download_file = download
    return channel, pairing, turns, sent, downloads


async def _send_action():
    return None


def _message(*, filename="notes.txt", caption="What does this say?", sender=42):
    return {"message": {"message_id": 1, "from": {"id": sender},
                        "chat": {"id": sender, "type": "private"},
                        "caption": caption,
                        "document": {"file_id": "opaque-secret", "file_size": 5,
                                     "file_name": filename, "mime_type": "image/png"}}}


def test_document_envelope_keeps_sender_filename_private_but_readable():
    attachment = classify(_message()["message"])
    assert attachment.kind == KIND_DOCUMENT and attachment.readable
    assert attachment.filename == "notes.txt"
    assert "notes.txt" not in str(attachment.to_dict())
    assert "opaque-secret" not in str(attachment.to_dict())


@pytest.mark.asyncio
async def test_paired_document_is_extracted_fenced_and_routed_as_untrusted_context(tmp_path, monkeypatch):
    channel, pairing, turns, sent, downloads = _channel(tmp_path, monkeypatch)
    pairing.approve("telegram", "42")
    await channel._handle_update(_message())
    assert downloads and downloads[0][0] == "opaque-secret"
    assert sent == []
    assert len(turns) == 1
    text, metadata = turns[0]
    assert "What does this say?" in text
    assert "notes from the attached document" in text
    assert "UNTRUSTED" in text and "telegram.document" in text
    assert metadata["pending_input_eligible"] is False
    assert "opaque-secret" not in text and "notes.txt" not in text


@pytest.mark.asyncio
async def test_unpaired_sender_never_downloads_or_extracts_document(tmp_path, monkeypatch):
    channel, _pairing, turns, _sent, downloads = _channel(tmp_path, monkeypatch)
    await channel._handle_update(_message(caption=""))
    assert downloads == [] and turns == []


@pytest.mark.asyncio
async def test_unwired_pairing_store_defaults_to_no_media_fetch(tmp_path, monkeypatch):
    channel, _pairing, turns, _sent, downloads = _channel(tmp_path, monkeypatch)
    channel._pairing = None
    await channel._handle_update(_message(caption=""))
    assert downloads == [] and turns == []


@pytest.mark.asyncio
async def test_unpaired_photo_and_voice_bytes_are_not_fetched_before_gateway(tmp_path, monkeypatch):
    channel, _pairing, _turns, _sent, downloads = _channel(tmp_path, monkeypatch)

    class ReadyReader:
        max_bytes = 1024

        def refusal(self):
            return None

        async def __call__(self, *args, **kwargs):
            raise AssertionError("unpaired media reached inference")

    channel._image_reader = ReadyReader()
    channel._voice_reader = ReadyReader()
    for field, payload in (("photo", [{"file_id": "photo"}]),
                           ("voice", {"file_id": "voice"})):
        message = _message(caption="")["message"]
        message.pop("document")
        message[field] = payload
        await channel._handle_update({"message": message})
    assert downloads == []


@pytest.mark.asyncio
async def test_unsupported_or_spoofed_document_does_not_enter_model_context(tmp_path, monkeypatch):
    channel, pairing, turns, sent, downloads = _channel(tmp_path, monkeypatch)
    pairing.approve("telegram", "42")
    await channel._handle_update(_message(filename="photo.jpg", caption=""))
    assert downloads == [] and turns == []
    assert sent and "not" in sent[-1].lower()
    await channel._handle_update(_message(filename="report.pdf", caption=""))
    assert len(downloads) == 1 and turns == []
    assert "not" in sent[-1].lower()


@pytest.mark.asyncio
async def test_caption_command_does_not_consume_document_bytes(tmp_path, monkeypatch):
    channel, pairing, turns, _sent, downloads = _channel(tmp_path, monkeypatch)
    pairing.approve("telegram", "42")
    await channel._handle_update(_message(caption="/stop"))
    assert downloads == []
    assert [text for text, _meta in turns] == ["/stop"]
    assert turns[0][1]["pending_input_eligible"] is False


@pytest.mark.asyncio
async def test_document_reader_checks_actual_bytes_before_extractor(monkeypatch):
    from agents.core.workspace import extract

    calls = []

    async def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("extractor invoked")

    monkeypatch.setattr(extract, "extract_document", forbidden)
    reader = InboundDocumentReader(max_bytes=4)
    result = await reader(b"five!", filename="notes.txt")
    assert result.ok is False and calls == []
    result = await reader(b"%PDF- not a real pdf", filename="notes.txt")
    assert result.ok is False and calls == []


@pytest.mark.asyncio
async def test_document_reader_rechecks_live_limit_after_download(monkeypatch):
    from agents.core.channels import inbound_document

    cap = [64]
    monkeypatch.setattr(inbound_document, "current_max_bytes", lambda: cap[0])
    reader = InboundDocumentReader()
    assert reader.max_bytes == 64
    cap[0] = 4
    assert reader.max_bytes == 4
    result = await reader(b"five!", filename="notes.txt")
    assert result.ok is False and result.reason == inbound_document.REASON_TOO_LARGE
