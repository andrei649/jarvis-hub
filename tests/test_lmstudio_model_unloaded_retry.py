"""A model unloaded out from under a request is recoverable, not a dead turn.

Observed in a real session: the owner swapped models in LM Studio and sent a
message seconds later. LM Studio answered

    POST /v1/chat/completions → 400 {"error":"Model unloaded by user or API request."}

and `LMStudioBackend.generate()`'s blanket `except Exception` turned that into a
degraded "⚠️ … check the LM Studio server" bubble. Nothing was wrong with the
server: LM Studio JIT-loads the model named in the *next* request, so a single
retry answers normally.

The retry is deliberately narrow — this 400 only, once only, and never after a
token has already reached the user.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import (  # noqa: E402
    LMStudioBackend,
    is_degraded_reply,
    is_model_unloaded_error,
)

UNLOADED_BODY = {"error": "Model unloaded by user or API request."}


def _with_transport(backend, handler):
    backend.client = httpx.AsyncClient(
        base_url=backend.base_url,
        transport=httpx.MockTransport(handler),
        timeout=backend.client.timeout,
    )
    return backend


def _answer(text: str, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]},
        request=request,
    )


def _sse(text: str, request: httpx.Request) -> httpx.Response:
    body = (
        f'data: {{"choices":[{{"delta":{{"content":"{text}"}}}}]}}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )
    return httpx.Response(200, text=body, request=request)


# ── the predicate ────────────────────────────────────────────────────────────

def test_the_unload_400_is_recognised():
    request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    response = httpx.Response(400, json=UNLOADED_BODY, request=request)
    exc = httpx.HTTPStatusError("400", request=request, response=response)

    assert is_model_unloaded_error(exc) is True


@pytest.mark.parametrize(
    "status,body",
    [
        # A real application error from a running server: not retryable.
        (400, {"error": "This model does not support the given sampler settings."}),
        (500, {"error": "Model unloaded by user or API request."}),
        (404, {"error": "model not found"}),
    ],
)
def test_other_failures_are_not_mistaken_for_an_unload(status, body):
    request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    response = httpx.Response(status, json=body, request=request)
    exc = httpx.HTTPStatusError(str(status), request=request, response=response)

    assert is_model_unloaded_error(exc) is False


def test_a_non_http_failure_is_not_an_unload():
    assert is_model_unloaded_error(httpx.ConnectError("refused")) is False


# ── generate() ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_retries_once_and_answers():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(400, json=UNLOADED_BODY, request=request)
        return _answer("Reloaded and answering, sir.", request)

    backend = _with_transport(LMStudioBackend(), handler)
    out = await backend.generate("gemma-4-12b", "status?")

    assert len(calls) == 2
    assert out == "Reloaded and answering, sir."
    assert not is_degraded_reply(out)


@pytest.mark.asyncio
async def test_generate_gives_up_after_one_retry():
    """A model that stays unloaded degrades — the retry must not become a loop."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json=UNLOADED_BODY, request=request)

    backend = _with_transport(LMStudioBackend(), handler)
    out = await backend.generate("gemma-4-12b", "status?")

    assert len(calls) == 2
    assert is_degraded_reply(out)


@pytest.mark.asyncio
async def test_an_ordinary_400_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            400, json={"error": "unsupported sampler settings"}, request=request
        )

    backend = _with_transport(LMStudioBackend(), handler)
    out = await backend.generate("gemma-4-12b", "status?")

    assert len(calls) == 1, "only the unload case is retryable"
    assert is_degraded_reply(out)


@pytest.mark.asyncio
async def test_a_healthy_request_is_sent_once():
    calls = []

    def handler(request):
        calls.append(request)
        return _answer("All systems are operational, sir.", request)

    backend = _with_transport(LMStudioBackend(), handler)
    out = await backend.generate("gemma-4-12b", "status?")

    assert len(calls) == 1
    assert out == "All systems are operational, sir."


# ── generate_tool_turn() ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_turn_retries_once_and_answers():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(400, json=UNLOADED_BODY, request=request)
        return _answer("Tool turn recovered.", request)

    backend = _with_transport(LMStudioBackend(), handler)
    turn = await backend.generate_tool_turn("gemma-4-12b", [], [])

    assert len(calls) == 2
    assert turn.content == "Tool turn recovered."


# ── generate_stream() ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_retries_before_any_token_reaches_the_user():
    calls = []
    seen: list[str] = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(400, json=UNLOADED_BODY, request=request)
        return _sse("streamed", request)

    backend = _with_transport(LMStudioBackend(), handler)
    out = await backend.generate_stream(
        "gemma-4-12b", "status?", on_token=seen.append
    )

    assert len(calls) == 2
    assert out == "streamed"
    assert "".join(seen) == "streamed", "the user must not see the failed attempt"


@pytest.mark.asyncio
async def test_stream_surfaces_the_server_body_when_it_keeps_failing(caplog):
    """A streaming error response arrives unread, hiding the server's own text.

    Before the `aread()` added alongside the retry, `_server_error_detail` could
    never extract anything from a failed *stream*, so operators saw only
    "Client error '400 Bad Request'" with no explanation attached.
    """
    import logging

    def handler(request):
        return httpx.Response(
            400, json={"error": "context length exceeded"}, request=request
        )

    backend = _with_transport(LMStudioBackend(), handler)
    with caplog.at_level(logging.ERROR, logger="jarvis.llm"):
        out = await backend.generate_stream("gemma-4-12b", "status?")

    assert is_degraded_reply(out)
    assert "context length exceeded" in caplog.text
