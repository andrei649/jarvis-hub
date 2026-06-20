"""Tests for local-model warm-up (perf quick win #2).

Preloading the detected model removes the cold-load cost from the first turn.
All offline: fake backends, no real LM Studio/Ollama.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import LLMBackend, OllamaBackend
from agents.core.llm.router import LLMRouter


class _FakeBackend(LLMBackend):
    """Exercises the default LLMBackend.warm_up (which routes through generate)."""
    def __init__(self, ret="ok", raises=False):
        self._ret = ret
        self._raises = raises
        self.calls = []

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        self.calls.append(dict(model=model, prompt=prompt, max_tokens=max_tokens))
        if self._raises:
            raise RuntimeError("boom")
        return self._ret


async def test_default_warm_up_uses_minimal_generation():
    be = _FakeBackend(ret="ok")
    assert await be.warm_up("m") is True
    assert be.calls[0]["max_tokens"] == 1   # minimal, not a full generation
    assert be.calls[0]["model"] == "m"


async def test_default_warm_up_treats_error_string_as_failure():
    be = _FakeBackend(ret="[LM Studio error: down]")
    assert await be.warm_up("m") is False


async def test_default_warm_up_swallows_exceptions():
    be = _FakeBackend(raises=True)
    assert await be.warm_up("m") is False


class _FakeResp:
    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, raises=False):
        self.raises = raises
        self.posts = []

    async def post(self, url, json):
        self.posts.append((url, json))
        if self.raises:
            raise RuntimeError("conn refused")
        return _FakeResp()

    async def aclose(self):
        return None


async def test_ollama_warm_up_pins_model_resident():
    ob = OllamaBackend(base_url="http://x")
    ob.client = _FakeClient()
    assert await ob.warm_up("mymodel") is True
    url, body = ob.client.posts[0]
    assert url == "/api/generate"
    assert body["prompt"] == ""          # empty prompt = load without generating
    assert body["keep_alive"] == -1      # pin resident across turns
    assert body["model"] == "mymodel"
    await ob.aclose()


async def test_ollama_warm_up_failure_is_false():
    ob = OllamaBackend(base_url="http://x")
    ob.client = _FakeClient(raises=True)
    assert await ob.warm_up("mymodel") is False
    await ob.aclose()


async def test_router_warm_up_noops_without_backend_or_model():
    r = LLMRouter()
    assert await r.warm_up() is False        # no backend
    r._backend = _FakeBackend(ret="ok")
    r._detected_model = None
    assert await r.warm_up() is False        # backend but no detected model


async def test_router_warm_up_delegates_to_backend():
    r = LLMRouter()
    r._backend = _FakeBackend(ret="ok")
    r._detected_model = "qwen3:7b"
    assert await r.warm_up() is True
    assert r._backend.calls[0]["model"] == "qwen3:7b"
