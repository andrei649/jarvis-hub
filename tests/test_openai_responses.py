"""Public Responses path: injected transport, real router and tool-loop boundaries."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest


def completed(text="answer", calls=()):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
            *calls,
        ],
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 60},
            "output_tokens": 7,
            "output_tokens_details": {"reasoning_tokens": 3},
        },
    }


@pytest.mark.asyncio
async def test_actual_router_constructs_responses_and_retains_local_only(monkeypatch):
    from agents.core.llm.hybrid_router import HybridRouter, LocalBackendUnavailableError
    from agents.core.llm.router import LLMRouter

    settings = {"compatible_provider": "openai-responses", "compatible_model": "gpt-4.1"}
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://must-not-be-used.invalid")
    monkeypatch.setattr(LLMRouter, "detect", AsyncMock())
    monkeypatch.setattr(HybridRouter, "_check", AsyncMock(return_value=False))
    monkeypatch.setattr(
        HybridRouter, "_admin_setting", staticmethod(lambda k, d: settings.get(k, d))
    )
    router = HybridRouter()
    await router.detect()
    try:
        backend, model, route = router.select_backend("athena", "")
        assert backend.profile.id == "openai-responses"
        assert model == "gpt-4.1" and route == "cloud-compatible"
        requests = []
        await backend.client.aclose()
        backend.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: requests.append(req) or httpx.Response(200, json=completed())
            )
        )
        assert await backend.generate(model, "hello") == "answer"
        assert str(requests[0].url) == "https://api.openai.com/v1/responses"
        with pytest.raises(LocalBackendUnavailableError):
            router.select_backend("frigga", "")
    finally:
        await router.aclose()


@pytest.mark.asyncio
async def test_two_turn_calls_use_call_id_and_session_scoped_cache():
    from agents.core.llm.request_context import session_scope
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.llm.tool_protocol import ToolSpec

    requests = []
    call = {
        "type": "function_call",
        "id": "provider-item",
        "call_id": "call-one",
        "name": "echo",
        "arguments": '{"text":"hello"}',
    }

    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(
            200, json=completed("", [call]) if len(requests) == 1 else completed()
        )

    backend = ResponsesBackend("fixture-only", transport=httpx.MockTransport(handler))
    messages = [{"role": "system", "content": "stable"}, {"role": "user", "content": "hello"}]
    try:
        with session_scope("private-session"):
            first = await backend.generate_tool_turn("gpt-4.1", messages, [ToolSpec("echo")])
            assert first.tool_calls[0].id == "call-one"
            messages += [
                first.as_assistant_message(),
                {"role": "tool", "tool_call_id": "call-one", "content": "hello"},
            ]
            second = await backend.generate_tool_turn("gpt-4.1", messages, [ToolSpec("echo")])
        assert second.content == "answer"
        assert second.usage.input_tokens == 40 and second.usage.cache_read == 60
        assert second.usage.output_tokens == 7
        assert requests[0]["store"] is False and requests[0]["tools"][0]["strict"] is False
        assert requests[0]["prompt_cache_key"] == requests[1]["prompt_cache_key"]
        assert "private-session" not in requests[0]["prompt_cache_key"]
        assert requests[1]["input"][-1] == {
            "type": "function_call_output",
            "call_id": "call-one",
            "output": "hello",
        }
        assert "previous_response_id" not in requests[1]
    finally:
        await backend.aclose()


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data, width=7):
        self.data, self.width, self.closed = data, width, False

    async def __aiter__(self):
        for start in range(0, len(self.data), self.width):
            yield self.data[start : start + self.width]

    async def aclose(self):
        self.closed = True


def sse(*events):
    return b"".join(
        ("data: " + json.dumps(e, ensure_ascii=False) + "\r\n\r\n").encode() for e in events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["text", "stream", "tools"])
@pytest.mark.parametrize("model", ["gpt-5", "gpt-4.1-mini", "", None, []])
async def test_unsupported_models_refuse_before_http(mode, model):
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.llm.responses_dialect import ResponsesRefused

    requests = []
    backend = ResponsesBackend(
        "fixture-only", transport=httpx.MockTransport(lambda req: requests.append(req))
    )
    try:
        with pytest.raises(ResponsesRefused):
            if mode == "tools":
                await backend.generate_tool_turn(model, [], [])
            elif mode == "stream":
                await backend.generate_stream(model, "hello")
            else:
                await backend.generate(model, "hello")
        assert not requests
    finally:
        await backend.aclose()


@pytest.mark.parametrize("retention", ["", "forever", None, [], True])
async def test_invalid_retention_refuses_locally(retention):
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.llm.responses_dialect import ResponsesRefused

    with pytest.raises(ResponsesRefused):
        ResponsesBackend("fixture-only", retention=retention)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal", ["complete", "duplicate", "missing", "failed", "incomplete", "error", "mismatch"]
)
async def test_stream_terminal_once_and_chunked_utf8(terminal):
    from agents.core.llm.responses import ERROR, ResponsesBackend
    from agents.core.llm.usage_context import text_usage_scope

    events = [{"type": "response.output_text.delta", "delta": "héllo"}]
    done = {"type": "response.completed", "response": completed("héllo")}
    if terminal in {"complete", "duplicate"}:
        events += [done] * (2 if terminal == "duplicate" else 1)
    elif terminal == "mismatch":
        events += [{"type": "response.completed", "response": completed("other")}]
    elif terminal != "missing":
        events += [
            {"type": "error" if terminal == "error" else "response." + terminal, "error": "SECRET"}
        ]
    stream = Chunks(sse(*events), width=1)
    requests, observed, tokens = [], [], []
    backend = ResponsesBackend(
        "fixture-only",
        transport=httpx.MockTransport(
            lambda req: requests.append(req) or httpx.Response(200, stream=stream)
        ),
    )
    try:
        with text_usage_scope(observed.append):
            result = await backend.generate_stream("gpt-4.1", "hello", on_token=tokens.append)
        assert result == ("héllo" if terminal == "complete" else ERROR)
        assert len(observed) == (1 if terminal == "complete" else 0)
        assert tokens == ["héllo"] and len(requests) == 1 and stream.closed
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_stream_refusal_is_not_lost():
    from agents.core.llm.responses import ResponsesBackend

    response = completed("")
    response["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot comply"}]
    stream = Chunks(
        sse(
            {"type": "response.refusal.delta", "delta": "Cannot comply"},
            {"type": "response.completed", "response": response},
        )
    )
    backend = ResponsesBackend(
        "fixture-only",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream)),
    )
    try:
        assert await backend.generate_stream("gpt-4.1", "hello") == "Cannot comply"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["text", "stream", "tools"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_error_or_cancellation_never_retried(mode, cancel):
    import asyncio

    from agents.core.llm.responses import ERROR, ResponsesBackend
    from agents.core.llm.usage_context import text_usage_scope

    requests, observed = [], []

    async def handler(req):
        requests.append(req)
        if cancel:
            raise asyncio.CancelledError
        return httpx.Response(429, text="secret-provider-body")

    backend = ResponsesBackend("fixture-only", transport=httpx.MockTransport(handler))

    async def run():
        if mode == "tools":
            return (await backend.generate_tool_turn("gpt-4.1", [], [])).content
        if mode == "stream":
            return await backend.generate_stream("gpt-4.1", "hello")
        return await backend.generate("gpt-4.1", "hello")

    try:
        with text_usage_scope(observed.append):
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await run()
            else:
                assert await run() == ERROR
        assert len(requests) == 1 and not observed
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_concurrent_session_cache_keys_are_private_and_stable():
    import asyncio

    from agents.core.llm.request_context import session_scope
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.llm.usage_context import text_usage_scope

    requests, observed = [], []
    backend = ResponsesBackend(
        "fixture-only",
        retention="24h",
        transport=httpx.MockTransport(
            lambda req: (
                requests.append(json.loads(req.content)) or httpx.Response(200, json=completed())
            )
        ),
    )

    async def run(session):
        with session_scope(session), text_usage_scope(observed.append):
            await asyncio.sleep(0)
            await backend.generate("gpt-4.1", session)
            await backend.generate("gpt-4.1", session)

    try:
        await asyncio.gather(run("alice-private"), run("bob-private"))
        groups = {}
        for request in requests:
            groups.setdefault(request["input"][-1]["content"], set()).add(
                request["prompt_cache_key"]
            )
            assert request["prompt_cache_retention"] == "24h"
            assert "reasoning" not in request and "previous_response_id" not in request
        assert all(len(keys) == 1 for keys in groups.values())
        assert groups["alice-private"] != groups["bob-private"]
        assert all("private" not in next(iter(keys)) for keys in groups.values())
        assert len(observed) == 4
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("gated", [False, True])
async def test_real_agent_loop_tool_output_or_approval_stop(gated):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.tool_rpc import ToolRPCServer

    enqueued, handled, requests = [], [], []

    def enqueue(agent, kind, title, **kwargs):
        enqueued.append(agent)
        return 17

    server = ToolRPCServer(enqueue=enqueue)

    async def echo(args):
        handled.append(args)
        return {"echo": args["value"]}

    server.register_tool(
        "echo",
        echo,
        gated=gated,
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    )
    call = {
        "type": "function_call",
        "id": "item",
        "call_id": "call-one",
        "name": "echo",
        "arguments": '{"value":"hi"}',
    }

    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(
            200, json=completed("", [call]) if len(requests) == 1 else completed("done")
        )

    backend = ResponsesBackend("fixture-only", transport=httpx.MockTransport(handler))
    try:
        result = await AgentToolRuntime(server, enabled=lambda: True).run(
            agent_id="trusted-athena",
            backend=backend,
            model="gpt-4.1",
            prompt="echo hi",
            system="help",
            max_tokens=256,
            temperature=0.2,
        )
        if gated:
            assert "approval" in result.lower() and enqueued == ["trusted-athena"]
            assert len(requests) == 1 and not handled
        else:
            assert result == "done" and handled == [{"value": "hi"}] and len(requests) == 2
            output = requests[1]["input"][-1]
            assert output["type"] == "function_call_output" and output["call_id"] == "call-one"
            assert json.loads(output["output"])["result"] == {"echo": "hi"}
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["event", "total", "text", "json", "events"])
async def test_transport_limits_refuse_without_usage(monkeypatch, boundary):
    from agents.core.llm import responses
    from agents.core.llm.usage_context import text_usage_scope

    raw = sse(
        {"type": "response.output_text.delta", "delta": "answer"},
        {"type": "response.completed", "response": completed()},
    )
    if boundary == "event":
        monkeypatch.setattr(responses, "MAX_EVENT", 8)
    elif boundary == "total":
        monkeypatch.setattr(responses, "MAX_STREAM", 8)
    elif boundary == "text":
        monkeypatch.setattr(responses, "MAX_TEXT", 3)
    elif boundary == "events":
        monkeypatch.setattr(responses, "MAX_EVENTS", 1)
    else:
        monkeypatch.setattr(responses, "MAX_BYTES", 8)
        raw = json.dumps(completed()).encode()
    observed = []
    stream = Chunks(raw)
    backend = responses.ResponsesBackend(
        "fixture-only",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream)),
    )
    try:
        with text_usage_scope(observed.append):
            method = backend.generate if boundary == "json" else backend.generate_stream
            assert await method("gpt-4.1", "hello") == responses.ERROR
        assert not observed and stream.closed
    finally:
        await backend.aclose()


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 60},
                "output_tokens": 7,
            },
            (40, 60, 7),
        ),
        ({"input_tokens": 60, "input_tokens_details": {"cached_tokens": 60}}, (0, 60, 0)),
        ({"input_tokens": 1, "input_tokens_details": {"cached_tokens": 2}}, (1, 0, 0)),
        ({"input_tokens": True, "output_tokens": "7"}, (0, 0, 0)),
        ({"input_tokens": -1, "output_tokens": 2**70}, (0, 0, 0)),
        (None, (0, 0, 0)),
    ],
)
def test_usage_counts_are_strict_and_cached_input_is_not_double_counted(raw, expected):
    from agents.core.llm.responses_dialect import usage

    value = usage(raw)
    assert (value.input_tokens, value.cache_read, value.output_tokens) == expected
    assert value.cache_write == 0


@pytest.mark.parametrize(
    "mutation", ["unknown", "reasoning", "duplicate", "missing-id", "incomplete"]
)
def test_response_unsupported_items_and_ambiguous_calls_fail_closed(mutation):
    from agents.core.llm.responses_dialect import ResponsesRefused, parse_response

    value = completed()
    call = {"type": "function_call", "call_id": "one", "name": "echo", "arguments": "{}"}
    if mutation in {"unknown", "reasoning"}:
        value["output"].append({"type": mutation})
    elif mutation == "duplicate":
        value["output"] += [call, call]
    elif mutation == "missing-id":
        del call["call_id"]
        value["output"].append(call)
    else:
        value["status"] = "incomplete"
    with pytest.raises(ResponsesRefused):
        parse_response(value)


@pytest.mark.parametrize("arguments", ["not json", "[]", '{"a":NaN}'])
def test_invalid_function_arguments_remain_nonexecutable(arguments):
    from agents.core.llm.responses_dialect import parse_response

    turn = parse_response(
        completed(
            "",
            [{"type": "function_call", "call_id": "one", "name": "echo", "arguments": arguments}],
        )
    )
    assert turn.tool_calls[0].parse_error and turn.tool_calls[0].arguments is None


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": [{"type": "input_image"}]}],
        [{"role": "tool", "tool_call_id": "unknown", "content": "value"}],
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "one",
                        "type": "function",
                        "function": {"name": "echo", "arguments": "{}"},
                    }
                ],
            }
        ],
    ],
)
def test_lossy_or_orphan_transcripts_refuse(messages):
    from agents.core.llm.responses_dialect import ResponsesRefused, input_items

    with pytest.raises(ResponsesRefused):
        input_items(messages)


@pytest.mark.asyncio
async def test_actual_router_model_allowlist_and_guardrails_before_transport(monkeypatch):
    from agents.core.llm.hybrid_router import HybridRouter, ModelNotApprovedError
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.security.guardrails import (
        GuardrailsEngine,
        SecurityBlockError,
        bind_guardrails,
    )
    from agents.core.security.types import RedactionMode

    requests = []
    backend = ResponsesBackend(
        "fixture-only",
        transport=httpx.MockTransport(
            lambda req: requests.append(req) or httpx.Response(200, json=completed())
        ),
    )
    router = HybridRouter()
    router._compatible_backend, router._compatible_model, router._cloud_available = (
        backend,
        "gpt-4.1",
        True,
    )
    monkeypatch.setattr(router, "approved_models", lambda agent: ["different-model"])
    try:
        with pytest.raises(ModelNotApprovedError):
            router.select_backend("athena", "hello")
        monkeypatch.setattr(router, "approved_models", lambda agent: ["gpt-4.1"])
        selected, model, route = router.select_backend("athena", "hello")
        assert selected is backend and route == "cloud-compatible"
        bound = bind_guardrails(GuardrailsEngine(mode=RedactionMode.BLOCK), selected)
        with pytest.raises(SecurityBlockError):
            await bound.generate(model, "alice@example.com")
        assert not requests
    finally:
        await router.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["text", "stream", "tools"])
async def test_total_deadline_cancels_transport_without_retry(monkeypatch, mode):
    import asyncio

    from agents.core.llm import responses

    requests = []

    async def handler(req):
        requests.append(req)
        await asyncio.Event().wait()

    monkeypatch.setattr(responses, "TIMEOUT", 0.01)
    backend = responses.ResponsesBackend("fixture-only", transport=httpx.MockTransport(handler))
    try:
        if mode == "tools":
            result = (await backend.generate_tool_turn("gpt-4.1", [], [])).content
        elif mode == "stream":
            result = await backend.generate_stream("gpt-4.1", "hello")
        else:
            result = await backend.generate("gpt-4.1", "hello")
        assert result == responses.ERROR and len(requests) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_callback_failure_closes_stream_without_usage_or_retry():
    from agents.core.llm.responses import ERROR, ResponsesBackend
    from agents.core.llm.usage_context import text_usage_scope

    stream = Chunks(
        sse(
            {"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response.completed", "response": completed()},
        )
    )
    requests, observed = [], []
    backend = ResponsesBackend(
        "fixture-only",
        transport=httpx.MockTransport(
            lambda req: requests.append(req) or httpx.Response(200, stream=stream)
        ),
    )

    def broken(delta):
        raise RuntimeError("private callback detail")

    try:
        with text_usage_scope(observed.append):
            assert await backend.generate_stream("gpt-4.1", "hello", on_token=broken) == ERROR
        assert stream.closed and len(requests) == 1 and not observed
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["close", "trailer", "delta-after-complete"])
async def test_completed_stream_is_not_accepted_until_clean_close(failure):
    from agents.core.llm.responses import ERROR, ResponsesBackend
    from agents.core.llm.usage_context import text_usage_scope

    events = [
        {"type": "response.output_text.delta", "delta": "answer"},
        {"type": "response.completed", "response": completed()},
    ]
    if failure == "trailer":
        events.append({"type": "error", "message": "private"})
    elif failure == "delta-after-complete":
        events.append({"type": "response.output_text.delta", "delta": "late"})

    class ClosingStream(Chunks):
        async def aclose(self):
            await super().aclose()
            if failure == "close":
                raise RuntimeError("private close error")

    stream = ClosingStream(sse(*events))
    requests, observed = [], []
    backend = ResponsesBackend(
        "fixture-only",
        transport=httpx.MockTransport(
            lambda req: requests.append(req) or httpx.Response(200, stream=stream)
        ),
    )
    try:
        with text_usage_scope(observed.append):
            assert await backend.generate_stream("gpt-4.1", "hello") == ERROR
        assert not observed and len(requests) == 1 and stream.closed
    finally:
        await backend.aclose()


@pytest.mark.parametrize("kind", ["message", "function_call"])
@pytest.mark.parametrize("status", ["in_progress", "incomplete"])
def test_completed_response_cannot_dispatch_incomplete_items(kind, status):
    from agents.core.llm.responses_dialect import ResponsesRefused, parse_response

    value = completed()
    if kind == "message":
        value["output"][0]["status"] = status
    else:
        value["output"].append(
            {"type": kind, "status": status, "call_id": "one", "name": "echo", "arguments": "{}"}
        )
    with pytest.raises(ResponsesRefused):
        parse_response(value)


@pytest.mark.parametrize('nested_null', [False, True])
async def test_prebuilt_responses_request_rechecks_invocation_lifetime(nested_null):
    import asyncio
    from contextlib import nullcontext

    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import reasoning_scope
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.llm.usage_context import text_usage_scope
    requests, usage = [], []
    backend = ResponsesBackend('fixture', transport=httpx.MockTransport(
        lambda request: requests.append(request) or httpx.Response(200, json=completed())))
    entered, release = asyncio.Event(), asyncio.Event()
    async def child():
        with reasoning_scope(None) if nested_null else nullcontext():
            payload = backend._payload('gpt-4.1', [{'role': 'user', 'content': 'hi'}], 100, 0.7)
            assert 'reasoning' not in payload and 'reasoning_effort' not in payload
            entered.set()
            await release.wait()
            return await backend._request(payload)
    try:
        with text_usage_scope(usage.append), reasoning_scope('low'):
            task = asyncio.create_task(child())
            await entered.wait()
        release.set()
        with pytest.raises(ReasoningEffortRefused):
            await task
        assert not requests and not usage
    finally:
        release.set()
        await backend.aclose()


@pytest.mark.parametrize('mode', ['text', 'stream', 'tools'])
@pytest.mark.parametrize('nested_null', [False, True])
async def test_public_responses_expired_scope_never_dispatches(mode, nested_null):
    import asyncio
    from contextlib import nullcontext

    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import reasoning_scope
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.llm.usage_context import text_usage_scope
    requests, usage = [], []
    backend = ResponsesBackend('fixture', transport=httpx.MockTransport(
        lambda request: requests.append(request) or httpx.Response(200, json=completed())))
    entered, release = asyncio.Event(), asyncio.Event()
    async def child():
        with reasoning_scope(None) if nested_null else nullcontext():
            entered.set()
            await release.wait()
            if mode == 'tools':
                return await backend.generate_tool_turn('gpt-4.1', [], [])
            method = backend.generate_stream if mode == 'stream' else backend.generate
            return await method('gpt-4.1', 'hi')
    try:
        with text_usage_scope(usage.append), reasoning_scope('low'):
            task = asyncio.create_task(child())
            await entered.wait()
        release.set()
        with pytest.raises(ReasoningEffortRefused):
            await task
        assert not requests and not usage
    finally:
        release.set()
        await backend.aclose()
