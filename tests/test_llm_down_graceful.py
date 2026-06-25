"""H23.12 — local LLM down/unreachable degrades gracefully (no hang, no crash).

Two guarantees, proven offline with httpx.MockTransport (no real server):

* **No hang.** The local backends use a *split* timeout — a short connect budget
  so an unreachable server fails in ~5s instead of blocking on the long read
  budget meant for generation.
* **No crash, no leak.** generate()/generate_stream() never raise on a backend
  failure; they return a *clean* degraded message (guidance to start the server)
  — never the raw exception, which used to leak into the chat bubble and poison
  conversation memory.
"""

import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import (
    LMStudioBackend,
    OllamaBackend,
    is_degraded_reply,
    local_backend_degraded_reply,
)


def _with_transport(backend, handler):
    """Swap the backend's client for one whose transport runs *handler*,
    preserving the backend's real (split) timeout config."""
    backend.client = httpx.AsyncClient(
        base_url=backend.base_url,
        transport=httpx.MockTransport(handler),
        timeout=backend.client.timeout,
    )
    return backend


def _raise_connect(request):
    raise httpx.ConnectError("Connection refused", request=request)


def _raise_read_timeout(request):
    raise httpx.ReadTimeout("timed out", request=request)


# ── split timeouts: down-detection is bounded (no multi-minute hang) ─────────

@pytest.mark.parametrize("backend,read", [(LMStudioBackend(), 300.0), (OllamaBackend(), 120.0)])
def test_local_backends_use_short_connect_timeout(backend, read):
    t = backend.client.timeout
    assert t.connect == 5.0, "connect must be short so a down server fails fast"
    assert t.read == read, "read stays long enough for real generation"


# ── helper classifies and never leaks the raw exception ──────────────────────

def test_degraded_reply_unreachable_is_clean_and_actionable():
    reply = local_backend_degraded_reply(
        "LM Studio", "LM Studio (http://localhost:1234)",
        httpx.ConnectError("Connection refused to 1.2.3.4:1234"),
    )
    assert "LM Studio" in reply
    assert "reach" in reply.lower()
    # no raw-exception leak into the user-facing bubble
    assert "Connection refused" not in reply
    assert "1.2.3.4" not in reply
    assert not reply.startswith("[LM Studio error")


def test_degraded_reply_other_error_is_generic():
    reply = local_backend_degraded_reply("Ollama", "Ollama", ValueError("boom"))
    assert "Ollama" in reply
    assert "boom" not in reply


def test_is_degraded_reply_detects_both_new_and_legacy_forms():
    # the warm_up failure-detector must catch the new ⚠️ message AND legacy [..] form
    assert is_degraded_reply(local_backend_degraded_reply("LM Studio", "LM Studio", httpx.ConnectError("x")))
    assert is_degraded_reply("[Cloud LLM error: down]")     # legacy cloud-backend form
    assert not is_degraded_reply("Here is a real answer.")
    assert not is_degraded_reply(None)


@pytest.mark.asyncio
async def test_warm_up_treats_down_backend_as_failure():
    """End-to-end: the real warm_up → generate() (degraded ⚠️ reply) →
    is_degraded_reply must return False so startup doesn't think a down server
    warmed up successfully (regression guard for the message-format change)."""
    b = _with_transport(LMStudioBackend(), _raise_connect)
    assert await b.warm_up("m") is False
    await b.aclose()


# ── generate(): down + timeout → clean reply, no raise ───────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [_raise_connect, _raise_read_timeout])
async def test_lmstudio_generate_degrades(handler):
    b = _with_transport(LMStudioBackend(), handler)
    reply = await b.generate("model", "hello")
    assert "reach" in reply.lower() and "LM Studio" in reply
    assert "[LM Studio error" not in reply
    await b.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [_raise_connect, _raise_read_timeout])
async def test_ollama_generate_degrades(handler):
    b = _with_transport(OllamaBackend(), handler)
    reply = await b.generate("model", "hello")
    assert "reach" in reply.lower() and "Ollama" in reply
    assert "[Ollama error" not in reply
    await b.aclose()


# ── generate_stream(): emits the clean reply via on_token, returns it ────────

@pytest.mark.asyncio
async def test_lmstudio_stream_degrades_and_emits():
    b = _with_transport(LMStudioBackend(), _raise_connect)
    tokens = []

    async def on_token(t):
        tokens.append(t)

    reply = await b.generate_stream("model", "hello", on_token=on_token)
    assert "reach" in reply.lower() and "LM Studio" in reply
    assert "".join(tokens) == reply                 # user saw the degraded message
    assert "Connection refused" not in reply
    await b.aclose()


@pytest.mark.asyncio
async def test_ollama_stream_degrades_and_emits():
    b = _with_transport(OllamaBackend(), _raise_connect)
    tokens = []

    async def on_token(t):
        tokens.append(t)

    reply = await b.generate_stream("model", "hello", on_token=on_token)
    assert "reach" in reply.lower() and "Ollama" in reply
    assert "".join(tokens) == reply
    await b.aclose()
