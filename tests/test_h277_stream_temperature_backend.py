"""H277: scoped LM Studio auxiliary temperature repair at the streaming egress."""

import asyncio
import json

import httpx
import pytest

from agents.core.llm.auxiliary_recovery import auxiliary_temperature_recovery_scope
from agents.core.llm.base import LMStudioBackend, is_degraded_reply
from agents.core.llm.egress import llm_async_client

REJECTION = {"error": {"code": "unsupported_parameter", "param": "temperature",
                       "message": "Unsupported parameter: temperature"}}
UNLOADED = {"error": "Model unloaded by user or API request."}


def sse(answer="recovered", *, finish="stop", done=True, prefix=""):
    frames = [prefix, f'data: {json.dumps({"choices": [{"delta": {"content": answer}}]})}\n\n',
              f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]})}\n\n']
    if done:
        frames.append("data: [DONE]\n\n")
    return httpx.Response(200, text="".join(frames))


def route(handler):
    backend = LMStudioBackend("http://127.0.0.1:1234", trust_env=False)
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, transport=httpx.MockTransport(handler))
    return backend


@pytest.mark.parametrize("scoped", [False, True])
async def test_temperature_repair_requires_exact_scope(scoped):
    sent = []
    seen = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=REJECTION) if len(sent) == 1 else sse()

    backend = route(handler)
    try:
        if scoped:
            with auxiliary_temperature_recovery_scope(backend, "m"):
                out = await backend.generate_stream("m", "p", "s", 55, 0.2, seen.append)
        else:
            out = await backend.generate_stream("m", "p", "s", 55, 0.2, seen.append)
        if scoped:
            assert out == "recovered" and "".join(seen) == "recovered"
            assert len(sent) == 2
            assert sent[1] == {key: value for key, value in sent[0].items()
                               if key != "temperature"}
        else:
            assert is_degraded_reply(out) and len(sent) == 1
            assert sent[0]["temperature"] == 0.2
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("order", [(REJECTION, UNLOADED), (UNLOADED, REJECTION)])
async def test_temperature_and_unload_each_have_one_retry_in_either_order(order):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) < 3:
            return httpx.Response(400, json=order[len(sent) - 1])
        return sse("answer")

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert await backend.generate_stream("m", "p", "s", 55, 0.2) == "answer"
        assert len(sent) == 3
        assert ["temperature" in body for body in sent] == (
            [True, False, False] if order[0] == REJECTION else [True, True, False])
        assert all(body["messages"] == sent[0]["messages"] and body["max_tokens"] == 55
                   and body["model"] == "m" for body in sent)
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("failure", [REJECTION, UNLOADED])
async def test_same_rejection_twice_stops_after_two_sends(failure):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=failure)

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert is_degraded_reply(await backend.generate_stream("m", "p"))
        assert len(sent) == 2
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("response", [
    httpx.Response(400, json={"error": "unsupported temperature"}),
    httpx.Response(503, json=REJECTION),
    httpx.ConnectError("unsupported temperature"),
])
async def test_generic_failures_do_not_repair_temperature(response):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if isinstance(response, Exception):
            raise response
        return response

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert is_degraded_reply(await backend.generate_stream("m", "p"))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_successful_repair_is_cached_only_for_same_scoped_route():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=REJECTION) if len(sent) == 1 else sse()

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert await backend.generate_stream("m", "p") == "recovered"
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert await backend.generate_stream("m", "p") == "recovered"
        assert await backend.generate_stream("m", "p") == "recovered"
        with auxiliary_temperature_recovery_scope(backend, "other"):
            assert await backend.generate_stream("other", "p") == "recovered"
        assert ["temperature" in body for body in sent] == [True, False, False, True, True]
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("prefix", [
    'data: {"choices":[{"delta":{"reasoning_content":"thought"}}]}\n\n',
    'data: {bad-json}\n\n',
])
async def test_received_stream_activity_blocks_unload_replay(prefix):
    sent = []

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield prefix.encode()
            raise httpx.ReadError("stream interrupted")

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, stream=Interrupted())

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert is_degraded_reply(await backend.generate_stream("m", "p"))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_reasoning_frame_blocks_replay_even_if_callback_raises_unload_status():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return sse("answer", prefix=(
            'data: {"choices":[{"delta":{"reasoning_content":"thought"}}]}\n\n'))

    backend = route(handler)

    def on_activity():
        request = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
        response = httpx.Response(400, json=UNLOADED, request=request)
        raise httpx.HTTPStatusError("unloaded", request=request, response=response)

    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert is_degraded_reply(await backend.generate_stream(
                "m", "p", on_activity=on_activity))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("repaired", [
    sse("partial", done=False),
    sse("partial", prefix='data: {bad-json}\n\n'),
    sse("partial", prefix='data: {"error":{"message":"failed"}}\n\n'),
    sse("partial", prefix='data: {"refusal":"policy"}\n\n'),
    sse("refused", finish="content_filter"),
    sse("⚠️ degraded"),
])
async def test_incomplete_error_refused_or_degraded_repair_is_not_learned(repaired):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) in (1, 3):
            return httpx.Response(400, json=REJECTION)
        return repaired

    backend = route(handler)
    try:
        for _ in range(2):
            with auxiliary_temperature_recovery_scope(backend, "m"):
                await backend.generate_stream("m", "p")
        assert ["temperature" in body for body in sent] == [True, False, True, False]
    finally:
        await backend.client.aclose()


async def test_rejected_response_closes_before_repaired_send():
    sent = []
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(REJECTION).encode()

        async def aclose(self):
            closed.append(True)

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(400, stream=Body(), headers={"content-type": "application/json"})
        assert closed == [True]
        return sse()

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert await backend.generate_stream("m", "p") == "recovered"
        assert len(sent) == 2
    finally:
        await backend.client.aclose()


async def test_failed_response_cleanup_does_not_retry():
    sent = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(REJECTION).encode()

        async def aclose(self):
            raise RuntimeError("cleanup failed")

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, stream=Body(), headers={"content-type": "application/json"})

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert is_degraded_reply(await backend.generate_stream("m", "p"))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_cancelled_stream_propagates_without_retry_or_cache():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(400, json=REJECTION)
        if len(sent) == 2:
            raise asyncio.CancelledError()
        return sse()

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"), pytest.raises(asyncio.CancelledError):
            await backend.generate_stream("m", "p")
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert await backend.generate_stream("m", "p") == "recovered"
        assert ["temperature" in body for body in sent] == [True, False, True]
    finally:
        await backend.client.aclose()


async def test_revoked_scope_blocks_unload_retry():
    sent = []
    revoke = None

    def handler(request):
        sent.append(json.loads(request.content))
        revoke()
        return httpx.Response(400, json=UNLOADED)

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m") as revoke:
            assert is_degraded_reply(await backend.generate_stream("m", "p"))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_oversized_scoped_status_body_is_read_with_bounded_bytes():
    sent = []
    yielded = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in (b'{"error":', b'x' * 5000, b'x' * 5000):
                yielded.append(len(chunk))
                yield chunk

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, stream=Body())

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert is_degraded_reply(await backend.generate_stream("m", "p"))
        assert len(sent) == 1
        assert sum(yielded) < 10008
    finally:
        await backend.client.aclose()


async def test_cleanup_exception_that_looks_like_rejection_never_retries():
    sent = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(REJECTION).encode()

        async def aclose(self):
            request = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
            response = httpx.Response(400, json=REJECTION, request=request)
            raise httpx.HTTPStatusError("cleanup", request=request, response=response)

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, stream=Body(), headers={"content-type": "application/json"})

    backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert is_degraded_reply(await backend.generate_stream("m", "p"))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_repaired_response_cannot_cache_on_client_replaced_during_cleanup():
    first_sent = []
    second_sent = []

    def second_handler(request):
        second_sent.append(json.loads(request.content))
        return sse("new route")

    backend = LMStudioBackend("http://127.0.0.1:1234", trust_env=False)
    second_client = llm_async_client(
        "lm-studio", base_url=backend.base_url,
        transport=httpx.MockTransport(second_handler))

    class RepairedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"choices":[{"delta":{"content":"recovered"}}]}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b'data: [DONE]\n\n'
            )

        async def aclose(self):
            backend.client = second_client

    def first_handler(request):
        first_sent.append(json.loads(request.content))
        if len(first_sent) == 1:
            return httpx.Response(400, json=REJECTION)
        return httpx.Response(200, stream=RepairedBody())

    first_client = llm_async_client(
        "lm-studio", base_url=backend.base_url,
        transport=httpx.MockTransport(first_handler))
    backend.client = first_client
    try:
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert await backend.generate_stream("m", "p") == "recovered"
        with auxiliary_temperature_recovery_scope(backend, "m"):
            assert await backend.generate_stream("m", "p") == "new route"
        assert ["temperature" in body for body in first_sent] == [True, False]
        assert ["temperature" in body for body in second_sent] == [True]
    finally:
        await first_client.aclose()
        await second_client.aclose()
