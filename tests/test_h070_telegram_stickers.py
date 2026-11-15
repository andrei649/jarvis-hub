"""Static Telegram stickers are locally captioned once under live policy gates."""

from __future__ import annotations

import asyncio
import io
from dataclasses import replace

import pytest
from PIL import Image

from agents.core.channels.inbound_media import KIND_STICKER, classify
from agents.core.channels.media_reader import REASON_POLICY, Description, InboundImageReader
from agents.core.channels.pairing import SenderPairing
from agents.core.channels.sticker_reader import StickerCaptioner, _valid_static_webp
from agents.core.channels.telegram import TelegramChannel


def _webp() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (24, 24), (255, 0, 0, 255)).save(out, format="WEBP")
    return out.getvalue()


def _attachment(*, unique="stable-one", animated=False, video=False):
    return classify({"sticker": {"file_id": "secret-handle", "file_unique_id": unique,
                                 "file_size": 100, "is_animated": animated, "is_video": video}})


class Reader:
    max_bytes = 8 * 1024 * 1024

    def __init__(self):
        self.calls = 0
        self.policy = None
        self.identity = ("local", "model-one")

    def refusal(self):
        return self.policy

    def cache_identity(self):
        return self.identity

    async def describe_sticker(self, data):
        self.calls += 1
        return Description(True, text="<<UNTRUSTED source=telegram.sticker>>\na red heart\n<<END UNTRUSTED>>")


def test_only_static_sticker_is_readable_and_unique_id_is_private():
    static = _attachment()
    assert static.kind == KIND_STICKER and static.readable
    assert static.file_unique_id == "stable-one"
    assert "stable-one" not in str(static.to_dict())
    assert "secret-handle" not in str(static.to_dict())
    assert not _attachment(animated=True).readable
    assert not _attachment(video=True).readable


@pytest.mark.asyncio
async def test_valid_sticker_is_cached_with_live_cap_policy_and_provider_identity():
    reader = Reader()
    captioner = StickerCaptioner()
    downloads = []
    data = _webp()

    async def download(file_id, cap):
        downloads.append((file_id, cap))
        return data

    att = _attachment()
    first = await captioner.describe(att, reader=reader, download=download, allowed=lambda: True)
    second = await captioner.describe(att, reader=reader, download=download, allowed=lambda: True)
    assert first.ok and second == first and reader.calls == 1 and len(downloads) == 1
    reader.max_bytes = len(data) - 1
    assert not (await captioner.describe(att, reader=reader, download=download,
                                        allowed=lambda: True)).ok
    assert reader.calls == 1 and len(downloads) == 1
    reader.max_bytes = 8 * 1024 * 1024
    reader.policy = Description(False, reason=REASON_POLICY)
    assert not (await captioner.describe(att, reader=reader, download=download,
                                        allowed=lambda: True)).ok
    reader.policy = None
    reader.identity = ("local", "model-two")
    assert (await captioner.describe(att, reader=reader, download=download,
                                    allowed=lambda: True)).ok
    assert reader.calls == 2 and len(downloads) == 2


@pytest.mark.asyncio
async def test_concurrent_duplicate_sticker_infers_once_and_revocation_blocks_cache():
    reader = Reader()
    captioner = StickerCaptioner()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    allowed = [True]

    async def download(file_id, cap):
        calls.append(file_id)
        entered.set()
        await release.wait()
        return _webp()

    att = _attachment()
    first = asyncio.create_task(captioner.describe(att, reader=reader, download=download,
                                                  allowed=lambda: allowed[0]))
    await entered.wait()
    second = asyncio.create_task(captioner.describe(att, reader=reader, download=download,
                                                   allowed=lambda: allowed[0]))
    release.set()
    assert (await first).ok and (await second).ok
    assert calls == ["secret-handle"] and reader.calls == 1
    allowed[0] = False
    assert not (await captioner.describe(att, reader=reader, download=download,
                                        allowed=lambda: allowed[0])).ok


@pytest.mark.asyncio
async def test_cap_lowered_during_download_refuses_before_inference():
    reader = Reader()
    captioner = StickerCaptioner()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def download(file_id, cap):
        calls.append(file_id)
        entered.set()
        await release.wait()
        return _webp()

    attachment = replace(_attachment(), size=0)
    first = asyncio.create_task(captioner.describe(attachment, reader=reader,
                                                  download=download, allowed=lambda: True))
    await entered.wait()
    second = asyncio.create_task(captioner.describe(attachment, reader=reader,
                                                   download=download, allowed=lambda: True))
    await asyncio.sleep(0)
    reader.max_bytes = len(_webp()) - 1
    release.set()
    assert not (await first).ok and not (await second).ok and reader.calls == 0
    assert calls == ["secret-handle"]


@pytest.mark.asyncio
async def test_clear_during_download_fences_old_inference():
    reader = Reader()
    captioner = StickerCaptioner()
    entered, release = asyncio.Event(), asyncio.Event()

    async def download(file_id, cap):
        entered.set()
        await release.wait()
        return _webp()

    old = asyncio.create_task(captioner.describe(_attachment(), reader=reader,
                                                download=download, allowed=lambda: True))
    await entered.wait()
    captioner.clear()
    release.set()
    assert not (await old).ok and reader.calls == 0


@pytest.mark.asyncio
async def test_bad_webp_and_missing_unique_id_never_get_false_cache_hits():
    reader = Reader()
    captioner = StickerCaptioner(max_entries=1)
    data = [b"RIFFxxxxWEBPnot-a-real-image"]
    downloads = []

    async def download(file_id, cap):
        downloads.append(file_id)
        return data[0]

    att = _attachment()
    assert not (await captioner.describe(att, reader=reader, download=download,
                                        allowed=lambda: True)).ok
    assert reader.calls == 0
    data[0] = _webp()
    assert (await captioner.describe(att, reader=reader, download=download,
                                    allowed=lambda: True)).ok
    no_id = _attachment(unique="")
    assert (await captioner.describe(no_id, reader=reader, download=download,
                                    allowed=lambda: True)).ok
    assert (await captioner.describe(no_id, reader=reader, download=download,
                                    allowed=lambda: True)).ok
    assert reader.calls == 3 and len(downloads) == 4


@pytest.mark.asyncio
async def test_lru_eviction_requires_a_fresh_caption():
    reader = Reader()
    captioner = StickerCaptioner(max_entries=1)
    downloads = []

    async def download(file_id, cap):
        downloads.append(file_id)
        return _webp()

    for unique in ("one", "two", "one"):
        assert (await captioner.describe(_attachment(unique=unique), reader=reader,
                                        download=download, allowed=lambda: True)).ok
    assert reader.calls == 3 and len(downloads) == 3


def test_only_a_decoded_single_frame_bounded_webp_passes_validation():
    assert _valid_static_webp(_webp())
    assert not _valid_static_webp(b"RIFFxxxxWEBPnot-real")
    animated = io.BytesIO()
    frames = [Image.new("RGBA", (24, 24), color) for color in ("red", "blue")]
    frames[0].save(animated, format="WEBP", save_all=True, append_images=frames[1:])
    assert not _valid_static_webp(animated.getvalue())
    large = io.BytesIO()
    Image.new("RGBA", (513, 1), "red").save(large, format="WEBP")
    assert not _valid_static_webp(large.getvalue())


@pytest.mark.asyncio
async def test_sticker_prompt_and_fence_are_distinct_from_photo():
    seen = []

    async def generate(prompt, images, system):
        seen.append((prompt, images, system))
        return "a waving cat"

    config = type("Local", (), {"is_local": True})()
    reader = InboundImageReader(config=config, vlm_generate=generate)
    result = await reader.describe_sticker(_webp())
    assert result.ok and "telegram.sticker" in result.text
    assert "sticker" in seen[0][0].lower() and seen[0][1][0] == _webp()


def test_reader_cache_identity_tracks_model_without_retaining_secret():
    from agents.core.llm.vlm import resolve_vlm_config

    config = resolve_vlm_config({
        "JARVIS_VLM_BACKEND": "custom", "JARVIS_VLM_MODEL": "vision-one",
        "JARVIS_VLM_URL": "http://sample-user:sample-password@127.0.0.1:1234/v1?token=sample-secret",
        "JARVIS_VLM_KEY": "secret-credential",
    })
    reader = InboundImageReader(config=config)
    first = reader.cache_identity()
    assert first is not None
    assert all(secret not in str(first) for secret in (
        "sample-user", "sample-password", "sample-secret", "secret-credential"))
    reader._config = replace(config, model="vision-two")
    second = reader.cache_identity()
    assert second != first
    reader._config = replace(config, api_key="rotated-credential")
    assert reader.cache_identity() != second


@pytest.mark.asyncio
async def test_telegram_adapter_refuses_animated_video_and_unpaired_before_download(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    pairing = SenderPairing(tmp_path / "pairing.json")
    seen, downloads = [], []

    async def handler(text, **kwargs):
        seen.append(text)

    channel = TelegramChannel("offline", handler=handler, pairing=pairing)
    channel._bot_id, channel._bot_username = 99, "nerva_bot"

    async def send(*args, **kwargs):
        return True

    async def download(file_id, cap):
        downloads.append(file_id)
        return _webp()

    channel.send = send
    channel.send_action = send
    channel._download_file = download
    channel._image_reader = Reader()
    for att in (_attachment(animated=True), _attachment(video=True), _attachment()):
        await channel._read_attachment(att, "", 42, 42)
    assert downloads == [] and seen == []
    pairing.approve("telegram", "42")
    for att in (_attachment(animated=True), _attachment(video=True)):
        assert (await channel._read_attachment(att, "", 42, 42)) == ("", "")
    assert downloads == []
    read, why = await channel._read_attachment(_attachment(), "", 42, 42)
    assert why == "" and "a red heart" in read
    assert downloads == ["secret-handle"]


@pytest.mark.asyncio
async def test_sticker_ingress_marks_pending_ineligible_and_caption_command_skips_pixels(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    pairing = SenderPairing(tmp_path / "pairing.json")
    pairing.approve("telegram", "42")
    turns, downloads = [], []

    async def handler(text, **kwargs):
        turns.append((text, kwargs))

    channel = TelegramChannel("offline", handler=handler, pairing=pairing)
    channel._bot_id, channel._bot_username = 99, "nerva_bot"

    async def send(*args, **kwargs):
        return True

    async def download(file_id, cap):
        downloads.append(file_id)
        return _webp()

    channel.send = send
    channel.send_action = send
    channel._download_file = download
    channel._image_reader = Reader()

    def update(caption):
        return {"message": {"from": {"id": 42}, "chat": {"id": 42, "type": "private"},
                            "caption": caption,
                            "sticker": {"file_id": "secret-handle", "file_unique_id": "stable-one"}}}

    await channel._handle_update(update("What does this show?"))
    assert len(turns) == 1 and "a red heart" in turns[0][0]
    assert turns[0][1]["pending_input_eligible"] is False
    assert downloads == ["secret-handle"]
    await channel._handle_update(update("/stop"))
    assert turns[-1][0] == "/stop" and downloads == ["secret-handle"]
