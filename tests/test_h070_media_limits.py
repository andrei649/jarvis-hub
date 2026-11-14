"""H070: one bounded owner cap reaches both inbound readers and Telegram streams."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core.channels import media_limits
from agents.core.channels.inbound_voice import REASON_TOO_LARGE as AUDIO_LARGE
from agents.core.channels.inbound_voice import InboundVoiceReader
from agents.core.channels.media_reader import REASON_TOO_LARGE as IMAGE_LARGE
from agents.core.channels.media_reader import InboundImageReader
from agents.core.channels.telegram import TelegramChannel


def test_limit_shape_and_malformed_store_values_fall_back(monkeypatch):
    assert media_limits.DEFAULT_BYTES == 8 * 1024 * 1024
    assert media_limits.MAX_BYTES == 20 * 1024 * 1024
    assert media_limits.configuration_problem(media_limits.DEFAULT_BYTES) is None
    assert media_limits.configuration_problem(media_limits.MAX_BYTES) is None
    for bad in (None, True, False, 0, -1, 1.5, "4096", media_limits.MAX_BYTES + 1):
        assert media_limits.configuration_problem(bad) is not None
        monkeypatch.setattr("agents.core.settings_db.get_value", lambda *a, value=bad, **k: value)
        assert media_limits.current_max_bytes() == media_limits.DEFAULT_BYTES


@pytest.mark.asyncio
async def test_image_reader_uses_live_cap_and_refuses_bytes_before_vlm(monkeypatch):
    setting = {"value": 4}
    monkeypatch.setattr("agents.core.settings_db.get_value", lambda *a, **k: setting["value"])
    seen = []

    async def generate(prompt, images, system):
        seen.append(images[0])
        return "a small image"

    reader = InboundImageReader(config=SimpleNamespace(is_local=True), vlm_generate=generate)
    assert reader.max_bytes == 4
    refused = await reader(b"12345")
    assert (refused.ok, refused.reason) == (False, IMAGE_LARGE)
    assert seen == []
    setting["value"] = 5
    assert reader.max_bytes == 5
    accepted = await reader(b"12345")
    assert accepted.ok and seen == [b"12345"]
    setting["value"] = 3
    assert (await reader(b"12345")).reason == IMAGE_LARGE
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_voice_reader_uses_live_cap_and_refuses_bytes_before_stt(monkeypatch):
    setting = {"value": 4}
    monkeypatch.setattr("agents.core.settings_db.get_value", lambda *a, **k: setting["value"])
    seen = []

    async def transcribe(audio, language):
        seen.append(audio)
        return "hello"

    reader = InboundVoiceReader(available=True, transcribe=transcribe)
    assert reader.max_bytes == 4
    refused = await reader(b"12345")
    assert (refused.ok, refused.reason) == (False, AUDIO_LARGE)
    assert seen == []
    setting["value"] = 5
    assert (await reader(b"12345")).ok
    assert seen == [b"12345"]


def test_explicit_reader_overrides_are_fixed_across_setting_edits(monkeypatch):
    setting = {"value": 20}
    monkeypatch.setattr("agents.core.settings_db.get_value", lambda *a, **k: setting["value"])
    image = InboundImageReader(config=None, max_bytes=7)
    voice = InboundVoiceReader(available=True, max_bytes=9)
    setting["value"] = 2
    assert image.max_bytes == 7 and voice.max_bytes == 9


@pytest.mark.asyncio
async def test_telegram_streams_receive_live_reader_cap_and_inference_sees_no_oversize(monkeypatch):
    setting = {"value": 4}
    monkeypatch.setattr("agents.core.settings_db.get_value", lambda *a, **k: setting["value"])
    downloads, inferred = [], []
    channel = TelegramChannel("offline")

    async def download(file_id, max_bytes):
        downloads.append((file_id, max_bytes))
        return b"12345"  # a defensive second check still refuses after a bad download

    async def describe(prompt, images, system):
        inferred.append(images[0])
        return "image"

    async def transcribe(audio, language):
        inferred.append(audio)
        return "hello"

    channel._download_file = download
    channel._image_reader = InboundImageReader(config=SimpleNamespace(is_local=True),
                                                vlm_generate=describe)
    channel._voice_reader = InboundVoiceReader(available=True, transcribe=transcribe)
    photo = SimpleNamespace(file_id="photo", caption="")
    voice = SimpleNamespace(file_id="voice")
    assert (await channel._read_image(photo)).reason == IMAGE_LARGE
    assert (await channel._read_voice(voice)).reason == AUDIO_LARGE
    assert downloads == [("photo", 4), ("voice", 4)] and inferred == []
    setting["value"] = 5
    assert (await channel._read_image(photo)).ok
    assert (await channel._read_voice(voice)).ok
    assert downloads[-2:] == [("photo", 5), ("voice", 5)]
    assert inferred == [b"12345", b"12345"]
