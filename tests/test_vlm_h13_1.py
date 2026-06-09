"""H13.1 — VLM adapter (image preprocessing + vision messages + backend). Offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import base64
import pytest

from agents.core.llm.vlm import (
    to_data_uri, encode_image_block, build_vision_messages, VLMBackend,
)


class _Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _Client:
    def __init__(self, data):
        self.calls = []
        self._data = data

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _Resp(self._data)


def test_to_data_uri():
    uri = to_data_uri(b"abc", "image/png")
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == b"abc"


def test_encode_image_block_bytes_and_url():
    # raw bytes (not a real image → Pillow passthrough) → data URI block
    block = encode_image_block(b"rawbytes")
    assert block["type"] == "image_url" and block["image_url"]["url"].startswith("data:")
    # http url → passed through verbatim
    assert encode_image_block("https://x/i.png")["image_url"]["url"] == "https://x/i.png"
    # data uri → passed through
    assert encode_image_block("data:image/png;base64,AAA")["image_url"]["url"].startswith("data:")


def test_encode_image_block_bad_path_returns_none():
    assert encode_image_block("/no/such/file.png") is None


def test_untrusted_input_rejects_local_files():
    # path injection guard: untrusted callers must not be able to open host files
    assert encode_image_block("/etc/hostname", allow_local_files=False) is None
    assert encode_image_block("relative/path.png", allow_local_files=False) is None
    # URLs and data-URIs are still allowed from untrusted input
    assert encode_image_block("https://x/i.png", allow_local_files=False)["image_url"]["url"] == "https://x/i.png"
    assert encode_image_block("data:image/png;base64,AAA", allow_local_files=False) is not None


def test_build_vision_messages():
    msgs = build_vision_messages("what is this?", images=[b"img"], system="be terse")
    assert msgs[0] == {"role": "system", "content": "be terse"}
    user = msgs[1]
    assert user["role"] == "user"
    assert user["content"][0] == {"type": "text", "text": "what is this?"}
    assert user["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_generate_vision_sends_images_and_strips_thinking():
    client = _Client({"choices": [{"message": {"content": "a receipt <think>hmm</think>"}}]})
    vlm = VLMBackend(api_key="sk-vlm", client=client)
    out = await vlm.generate_vision("qwen3-vl", "describe", images=[b"img"])
    assert out == "a receipt"                          # thinking stripped
    call = client.calls[0]
    assert call["url"] == "/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-vlm"
    content = call["json"]["messages"][-1]["content"]
    assert any(c["type"] == "image_url" for c in content)


@pytest.mark.asyncio
async def test_text_only_generate_has_no_image_blocks():
    client = _Client({"choices": [{"message": {"content": "hello"}}]})
    out = await VLMBackend(client=client).generate("qwen3-vl", "hi")
    assert out == "hello"
    content = client.calls[0]["json"]["messages"][-1]["content"]
    assert all(c["type"] != "image_url" for c in content)


@pytest.mark.asyncio
async def test_error_is_caught():
    class _Boom:
        async def post(self, *a, **k):
            raise RuntimeError("vlm down")

    out = await VLMBackend(client=_Boom()).generate_vision("m", "p", images=[b"x"])
    assert out.startswith("[VLM error")
