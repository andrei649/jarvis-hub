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

import json
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


def _respond_400(request):
    """A local server rejecting the request (e.g. a model-template mismatch) —
    real-world observed 2026-07-08: LM Studio 400s on some chat completions
    while /v1/models stays reachable. The JSON body is the server's own
    diagnostic (its author's text, not the caller's secret)."""
    return httpx.Response(
        400, json={"error": {"message": "This model does not support the given sampler settings."}},
        request=request,
    )


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

# ── a real server error (400) must still log its OWN diagnostic ──────────────
# Root-cause finding from a real test-drive session (2026-07-08): the server
# reachably rejected a request (400) and the degraded-reply path swallowed the
# response body entirely — only the generic "Client error '400 Bad Request'"
# string reached the log, so neither the user nor the operator could ever learn
# *why* it failed. The user-facing reply stays identical; only the log detail
# changes, so this is additive/observability-only.

@pytest.mark.asyncio
async def test_lmstudio_generate_400_logs_the_server_error_body(caplog):
    b = _with_transport(LMStudioBackend(), _respond_400)
    with caplog.at_level("ERROR", logger="jarvis.llm.base"):
        reply = await b.generate("model", "hello")
    assert "hit an error" in reply  # user-facing text unchanged
    assert "sampler settings" in caplog.text  # but the real reason is now logged
    await b.aclose()


@pytest.mark.asyncio
async def test_ollama_generate_400_logs_the_server_error_body(caplog):
    b = _with_transport(OllamaBackend(), _respond_400)
    with caplog.at_level("ERROR", logger="jarvis.llm.base"):
        reply = await b.generate("model", "hello")
    assert "hit an error" in reply
    assert "sampler settings" in caplog.text
    await b.aclose()


# ── empty system message is a 400 trigger on strict chat templates ───────────
# Real-world finding (2026-07-08 test-drive): LM Studio 400'd /v1/chat/completions
# for a loaded minimax model while /v1/models stayed reachable. The one
# non-standard thing in our payload is an always-present system turn — a
# `{"role": "system", "content": ""}` entry that some models' chat templates
# reject. The warm-up path (generate(model, ".", ...)) always sends an empty
# system, so it 400s on those templates. Omit the system turn when it's blank.

def _capture_ok(store):
    """A 200 handler that records the request JSON body into *store*."""
    def handler(request):
        store["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]},
            request=request,
        )
    return handler


@pytest.mark.asyncio
async def test_lmstudio_omits_empty_system_message():
    store = {}
    b = _with_transport(LMStudioBackend(), _capture_ok(store))
    await b.generate("m", "hello")  # system="" (the warm-up / no-persona path)
    roles = [msg["role"] for msg in store["body"]["messages"]]
    assert roles == ["user"], "an empty system turn must not be sent (strict templates 400)"
    await b.aclose()


@pytest.mark.asyncio
async def test_lmstudio_keeps_nonempty_system_message():
    store = {}
    b = _with_transport(LMStudioBackend(), _capture_ok(store))
    await b.generate("m", "hello", system="You are Jarvis.")
    msgs = store["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "You are Jarvis."}
    assert msgs[1]["role"] == "user"
    await b.aclose()


@pytest.mark.asyncio
async def test_lmstudio_stream_omits_empty_system_message():
    store = {}

    def handler(request):
        store["body"] = json.loads(request.content)
        # minimal SSE stream: one content delta then [DONE]
        body = 'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body, request=request)

    b = _with_transport(LMStudioBackend(), handler)
    await b.generate_stream("m", "hello")  # system="" default
    roles = [msg["role"] for msg in store["body"]["messages"]]
    assert roles == ["user"]
    await b.aclose()


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
