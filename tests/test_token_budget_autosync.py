"""
test_token_budget_autosync.py — the output budget ("max tokens") is a *single*
dial, synced to the model's loaded context, not a second Jarvis-side cap.

`max_tokens <= 0` means **auto**: local backends (LM Studio, Ollama) answer using
the full loaded context — LM Studio by omitting the cap, Ollama via num_predict=-1
— while cloud backends, which need a concrete positive ceiling, fall back to
CLOUD_AUTO_MAX_TOKENS. A positive value is always honored verbatim as a hard cap.
"""
import pytest

from agents.core.llm.base import (
    CLOUD_AUTO_MAX_TOKENS,
    LMStudioBackend,
    OllamaBackend,
    cloud_cap,
    is_auto_max_tokens,
)
from agents.core.llm.gemini import GeminiBackend


# ── helpers ────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _PostClient:
    """Captures the JSON body of a non-streaming POST."""
    def __init__(self, data):
        self.payloads = []
        self._data = data

    async def post(self, url, json):
        self.payloads.append(json)
        return _Resp(self._data)


class _StreamCtx:
    def __init__(self, sink, json, lines):
        sink.append(json)
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _StreamClient:
    def __init__(self, lines):
        self.payloads = []
        self._lines = lines

    def stream(self, method, url, json):
        return _StreamCtx(self.payloads, json, self._lines)


# ── unit: the resolution helpers ───────────────────────────────────────────────
@pytest.mark.parametrize("value", [0, -1, None])
def test_is_auto_for_nonpositive(value):
    assert is_auto_max_tokens(value) is True


@pytest.mark.parametrize("value", [1, 512, 8192])
def test_not_auto_for_positive(value):
    assert is_auto_max_tokens(value) is False


def test_cloud_cap_falls_back_when_auto():
    assert cloud_cap(0) == CLOUD_AUTO_MAX_TOKENS
    assert cloud_cap(-1) == CLOUD_AUTO_MAX_TOKENS


def test_cloud_cap_honors_positive():
    assert cloud_cap(500) == 500


# ── LM Studio: omit the cap when auto, honor it otherwise ──────────────────────
@pytest.mark.asyncio
async def test_lmstudio_omits_max_tokens_when_auto():
    be = LMStudioBackend()
    be.client = _PostClient({"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]})
    out = await be.generate(model="m", prompt="p", max_tokens=0)
    assert out == "hi"
    assert "max_tokens" not in be.client.payloads[0]


@pytest.mark.asyncio
async def test_lmstudio_sends_max_tokens_when_capped():
    be = LMStudioBackend()
    be.client = _PostClient({"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]})
    await be.generate(model="m", prompt="p", max_tokens=512)
    assert be.client.payloads[0]["max_tokens"] == 512


@pytest.mark.asyncio
async def test_lmstudio_stream_omits_max_tokens_when_auto():
    be = LMStudioBackend()
    be.client = _StreamClient([
        'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ])
    await be.generate_stream(model="m", prompt="p", max_tokens=0)
    assert "max_tokens" not in be.client.payloads[0]


# ── Ollama: num_predict = -1 when auto (its "infinite") ────────────────────────
@pytest.mark.asyncio
async def test_ollama_num_predict_infinite_when_auto():
    be = OllamaBackend()
    be.client = _PostClient({"response": "hi", "done_reason": "stop"})
    await be.generate(model="m", prompt="p", max_tokens=0)
    assert be.client.payloads[0]["options"]["num_predict"] == -1


@pytest.mark.asyncio
async def test_ollama_num_predict_honors_cap():
    be = OllamaBackend()
    be.client = _PostClient({"response": "hi", "done_reason": "stop"})
    await be.generate(model="m", prompt="p", max_tokens=256)
    assert be.client.payloads[0]["options"]["num_predict"] == 256


# ── Cloud: auto -> concrete ceiling, positive honored ──────────────────────────
def test_gemini_payload_uses_cloud_cap_when_auto():
    be = GeminiBackend(api_key="x")
    payload = be._build_payload("p", "", max_tokens=0)
    assert payload["generationConfig"]["maxOutputTokens"] == CLOUD_AUTO_MAX_TOKENS


def test_gemini_payload_honors_positive():
    be = GeminiBackend(api_key="x")
    payload = be._build_payload("p", "", max_tokens=500)
    assert payload["generationConfig"]["maxOutputTokens"] == 500
