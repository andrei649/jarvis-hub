"""Explicit ordinary-chat Ollama disable uses an exact local capability and wire body."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.agent import Agent
from agents.core.llm.base import THINKING_EXHAUSTED_REPLY, OllamaBackend
from agents.core.llm.request_context import (
    primary_ollama_no_think,
    reasoning_scope,
)


def _backend(values, response=None):
    seen = []

    def answer(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"thinking": {"values": values}})
        if request.url.path == "/api/chat":
            return httpx.Response(200, json=response or {"message": {"content": "answer"}})
        if body["stream"]:
            rows = response or [{"response": "answer", "done": True}]
            return httpx.Response(200, text="".join(json.dumps(row) + "\n" for row in rows))
        return httpx.Response(200, json=response or {"response": "answer"})

    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)
    backend.client = httpx.AsyncClient(
        transport=httpx.MockTransport(answer), base_url="http://127.0.0.1:11434")
    return backend, seen


def _agent():
    agent = Agent.__new__(Agent)
    agent.id = "jarvis"
    agent._checkpoint_manager = None
    agent.tool_runtime = None
    agent.llm_router = SimpleNamespace(check_data_handling=lambda backend, model: None)
    return agent


@pytest.mark.parametrize("values", [[False, "low"], [0, "low"], ["low"], None])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_primary_chat_sends_only_supported_explicit_false(values, explicit, stream):
    backend, seen = _backend(values)
    try:
        with reasoning_scope("none" if explicit else None):
            answer = await _agent().generate_response(
                backend, "model", "hello", "system", 64, 0.2,
                on_token=(lambda piece: None) if stream else None,
            )
        assert answer == "answer"
        calls = [body for path, body in seen if path == "/api/generate"]
        assert len(calls) == 1
        supports_disable = values is not None and values[0] is False
        assert (calls[0].get("think") is False) == (explicit and supports_disable)
        assert "think" not in calls[0]["options"]
        assert len([path for path, _ in seen if path == "/api/show"]) == int(explicit)
    finally:
        await backend.aclose()


@pytest.mark.parametrize("method,path", [("generate", "/api/generate"),
                                        ("generate_stream", "/api/generate"),
                                        ("generate_tool_turn", "/api/chat")])
async def test_native_wire_shapes_and_expired_or_sibling_binding(method, path):
    backend, seen = _backend([False])

    async def call():
        if method == "generate_tool_turn":
            return await backend.generate_tool_turn("model", [], [])
        if method == "generate_stream":
            return await backend.generate_stream("model", "hi")
        return await backend.generate("model", "hi")

    try:
        released = asyncio.Event()

        async def late():
            await released.wait()
            return await call()

        with primary_ollama_no_think(backend, "model"):
            await call()
            await asyncio.create_task(call())
            pending = asyncio.create_task(late())
        released.set()
        await pending
        await call()
        bodies = [body for actual, body in seen if actual == path]
        assert [body.get("think") for body in bodies] == [False, None, None, None]
        assert all("think" not in body["options"] for body in bodies)
    finally:
        await backend.aclose()


async def test_explicit_stream_never_replays_ignored_native_reasoning():
    backend, seen = _backend([False], [{"thinking": "private chain", "done": True}])
    emitted = []
    try:
        with reasoning_scope("none"):
            answer = await _agent().generate_response(
                backend, "model", "hello", "system", 64, 0.2, on_token=emitted.append)
        assert answer == ""
        assert emitted == []
        assert [body for path, body in seen if path == "/api/generate"][0]["think"] is False
    finally:
        await backend.aclose()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reasoning", ["private chain", "Thinking Process:\nprivate chain"])
async def test_default_primary_retries_once_without_thinking_after_context_exhaustion(stream, reasoning):
    seen = []

    def answer(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"thinking": {"values": [False, "low"]}})
        if body.get("think") is False:
            result = {"response": "answer", "done": True, "done_reason": "stop",
                      "prompt_eval_count": 11, "eval_count": 3}
        else:
            result = {"response": "", "thinking": reasoning, "done": True,
                      "done_reason": "length", "prompt_eval_count": 10, "eval_count": 64}
        return (httpx.Response(200, text=json.dumps(result) + "\n") if stream
                else httpx.Response(200, json=result))

    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)
    backend.client = httpx.AsyncClient(
        transport=httpx.MockTransport(answer), base_url="http://127.0.0.1:11434")
    emitted, usage = [], []
    try:
        result = await _agent().generate_response(
            backend, "model", "hello", "system", 64, 0.2,
            on_token=emitted.append if stream else None, usage_sink=usage.append,
        )
        assert result == "answer"
        assert emitted == (["answer"] if stream else [])
        assert [path for path, _ in seen] == ["/api/generate", "/api/show", "/api/generate"]
        first, second = (body for path, body in seen if path == "/api/generate")
        assert "think" not in first and second["think"] is False
        assert {key: value for key, value in first.items() if key != "think"} == {
            key: value for key, value in second.items() if key != "think"}
        assert [(row.input_tokens, row.output_tokens) for row in usage] == [(10, 64), (11, 3)]
        assert sum(row.input_tokens for row in usage) == 21
        assert sum(row.output_tokens for row in usage) == 67
    finally:
        await backend.aclose()


@pytest.mark.parametrize("stream", [False, True])
async def test_default_primary_unsupported_disable_keeps_single_exhausted_attempt(stream):
    exhausted = {"response": "", "thinking": "private chain", "done": True,
                 "done_reason": "length"}
    backend, seen = _backend(["low"], [exhausted] if stream else exhausted)
    emitted = []
    try:
        result = await _agent().generate_response(
            backend, "model", "hello", "system", 64, 0.2,
            on_token=emitted.append if stream else None,
        )
        assert result == THINKING_EXHAUSTED_REPLY
        assert emitted == []
        assert [path for path, _ in seen] == ["/api/generate", "/api/show"]
        assert "think" not in seen[0][1]
    finally:
        await backend.aclose()


async def test_explicit_reasoning_does_not_trigger_default_retry():
    backend, seen = _backend([False], {"response": "", "thinking": "private chain",
                                         "done": True, "done_reason": "length"})
    try:
        with reasoning_scope("low"):
            await _agent().generate_response(backend, "model", "hello", "system", 64, 0.2)
        assert [path for path, _ in seen] == ["/api/generate"]
        assert "think" not in seen[0][1]
    finally:
        await backend.aclose()


@pytest.mark.parametrize("response", [
    {"response": THINKING_EXHAUSTED_REPLY, "done": True, "done_reason": "stop"},
    {"response": "", "thinking": "private chain", "done": True, "done_reason": "stop"},
    {"response": "", "done": True, "done_reason": "length"},
])
async def test_default_primary_does_not_retry_without_reasoning_exhaustion(response):
    backend, seen = _backend([False], response)
    try:
        result = await _agent().generate_response(backend, "model", "hello", "system", 64, 0.2)
        assert result == response["response"]
        assert [path for path, _ in seen] == ["/api/generate"]
    finally:
        await backend.aclose()


async def test_clean_stop_native_thinking_stays_private_in_stream():
    backend, seen = _backend([False], [{"response": "", "thinking": "private chain",
                                        "done": True, "done_reason": "stop"}])
    emitted = []
    try:
        result = await _agent().generate_response(
            backend, "model", "hello", "system", 64, 0.2, on_token=emitted.append)
        assert result == ""
        assert emitted == []
        assert [path for path, _ in seen] == ["/api/generate"]
    finally:
        await backend.aclose()


async def test_failed_native_generation_does_not_probe_or_retry():
    seen = []

    def fail(request):
        seen.append(request.url.path)
        return httpx.Response(503)

    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)
    backend.client = httpx.AsyncClient(
        transport=httpx.MockTransport(fail), base_url="http://127.0.0.1:11434")
    try:
        result = await _agent().generate_response(backend, "model", "hello", "system", 64, 0.2)
        assert result.startswith("⚠️")
        assert seen == ["/api/generate"]
    finally:
        await backend.aclose()


@pytest.mark.parametrize("route_change", ["metadata names a remote model", "endpoint changes"])
async def test_default_retry_keeps_the_original_local_route(route_change):
    requests = []
    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)

    def reply(request):
        requests.append(request.url.path)
        if request.url.path == "/api/show":
            metadata = {"thinking": {"values": [False]}}
            if route_change == "endpoint changes":
                backend.base_url = "http://localhost:11434"
            else:
                metadata["remote_model"] = "hosted"
            return httpx.Response(200, json=metadata)
        return httpx.Response(200, json={"response": "", "thinking": "internal",
                                          "done": True, "done_reason": "length"})

    await backend.client.aclose()
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(reply), base_url=backend.base_url)
    try:
        answer = await _agent().generate_response(backend, "model", "hi", "", 64, 0.2)
        assert answer == THINKING_EXHAUSTED_REPLY
        assert requests == ["/api/generate", "/api/show"]
    finally:
        await backend.aclose()


async def test_incomplete_native_stream_does_not_probe_or_retry():
    backend, seen = _backend([False], [{"thinking": "private chain", "done": False}])
    emitted = []
    try:
        result = await _agent().generate_response(
            backend, "model", "hello", "system", 64, 0.2, on_token=emitted.append)
        assert result == ""
        assert emitted == []
        assert [path for path, _ in seen] == ["/api/generate"]
    finally:
        await backend.aclose()


async def test_tool_turn_exhaustion_does_not_retry_primary_generate():
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.tool_rpc import ToolRPCServer

    backend, seen = _backend([False], {"message": {"content": "", "thinking": "private chain"},
                                        "done": True, "done_reason": "length"})
    server = ToolRPCServer()
    server.register_tool("unused", lambda args: pytest.fail("unexpected tool execution"),
                         input_schema={"type": "object", "properties": {}})
    agent = _agent()
    agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)
    agent.tool_event_sink = lambda event: None
    try:
        assert await agent.generate_response(
            backend, "model", "hello", "system", 64, 0.2) == THINKING_EXHAUSTED_REPLY
        assert [path for path, _ in seen] == ["/api/chat"]
        assert "think" not in seen[0][1]
    finally:
        await backend.aclose()


async def test_default_primary_retries_at_most_once_when_disable_is_ignored():
    exhausted = {"response": "", "thinking": "private chain", "done": True,
                 "done_reason": "length", "prompt_eval_count": 10, "eval_count": 64}
    backend, seen = _backend([False], exhausted)
    usage = []
    try:
        result = await _agent().generate_response(
            backend, "model", "hello", "system", 64, 0.2, usage_sink=usage.append)
        assert result == THINKING_EXHAUSTED_REPLY
        assert [path for path, _ in seen] == ["/api/generate", "/api/show", "/api/generate"]
        assert [body.get("think") for path, body in seen if path == "/api/generate"] == [None, False]
        assert [(row.input_tokens, row.output_tokens) for row in usage] == [(10, 64), (10, 64)]
    finally:
        await backend.aclose()


async def test_default_primary_does_not_retry_after_turn_deadline():
    exhausted = {"response": "", "thinking": "private chain", "done": True,
                 "done_reason": "length"}
    backend, seen = _backend([False], exhausted)
    try:
        result = await _agent().generate_response(
            backend, "model", "hello", "system", 64, 0.2, wall_seconds=0)
        assert result == THINKING_EXHAUSTED_REPLY
        assert [path for path, _ in seen] == ["/api/generate"]
    finally:
        await backend.aclose()


async def test_auxiliary_agent_generation_does_not_retry_primary_disable(monkeypatch):
    from agents.core.llm import data_handling

    exhausted = {"response": "", "thinking": "private chain", "done": True,
                 "done_reason": "length"}
    backend, seen = _backend([False], exhausted)
    monkeypatch.setattr(data_handling, "authorize", lambda *args, **kwargs: None)
    try:
        with data_handling.auxiliary_request_scope(SimpleNamespace(), backend, "model", role="review"):
            result = await _agent().generate_response(
                backend, "model", "hello", "system", 64, 0.2)
        assert result == THINKING_EXHAUSTED_REPLY
        assert [path for path, _ in seen] == ["/api/generate"]
        assert "think" not in seen[0][1]
    finally:
        await backend.aclose()


async def test_auxiliary_scope_does_not_inherit_primary_disable(monkeypatch):
    from agents.core.llm import data_handling

    backend, seen = _backend([False])
    router = SimpleNamespace()
    monkeypatch.setattr(data_handling, "authorize", lambda *args, **kwargs: None)
    try:
        with primary_ollama_no_think(backend, "model"):
            with data_handling.auxiliary_request_scope(router, backend, "model", role="review"):
                await backend.generate("model", "side call")
            await backend.generate("model", "primary")
        calls = [body for path, body in seen if path == "/api/generate"]
        assert "think" not in calls[0]
        assert calls[1]["think"] is False
    finally:
        await backend.aclose()


async def test_job_pin_never_probes_or_sends_native_disable():
    from agents.core.llm.reasoning_effort import ReasoningEffortRefused
    from agents.core.llm.request_context import job_reasoning_scope

    backend, seen = _backend([False])
    try:
        with job_reasoning_scope("none"), pytest.raises(ReasoningEffortRefused):
            await _agent().generate_response(backend, "model", "hello", "system", 64, 0.2)
        assert seen == []
    finally:
        await backend.aclose()


async def test_unpinned_job_nested_in_chat_does_not_take_chat_disable():
    from agents.core.llm.request_context import job_reasoning_scope

    backend, seen = _backend([False])
    try:
        with reasoning_scope("none"), job_reasoning_scope(None):
            await _agent().generate_response(backend, "model", "hello", "system", 64, 0.2)
        assert [path for path, _ in seen] == ["/api/generate"]
        assert "think" not in seen[0][1]
    finally:
        await backend.aclose()


@pytest.mark.parametrize("changed", ["client", "base_url"])
async def test_metadata_from_changed_server_does_not_enable_disable(changed):
    backend, seen = _backend([False])
    old_client = backend.client
    replacement_seen = []

    def replacement_answer(request):
        replacement_seen.append(json.loads(request.content))
        return httpx.Response(200, json={"response": "answer"})

    replacement = httpx.AsyncClient(
        transport=httpx.MockTransport(replacement_answer),
        base_url="http://127.0.0.1:11434")

    async def mutate_during_probe(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path == "/api/show":
            if changed == "client":
                backend.client = replacement
            else:
                backend.base_url = "http://localhost:11434"
            return httpx.Response(200, json={"thinking": {"values": [False]}})
        return httpx.Response(200, json={"response": "answer"})

    backend.client = httpx.AsyncClient(
        transport=httpx.MockTransport(mutate_during_probe), base_url="http://127.0.0.1:11434")
    probe_client = backend.client
    try:
        with reasoning_scope("none"):
            assert await _agent().generate_response(
                backend, "model", "hello", "system", 64, 0.2) == "answer"
        if changed == "client":
            assert len(seen) == 1
            assert len(replacement_seen) == 1
            assert "think" not in replacement_seen[0]
        else:
            body = [body for path, body in seen if path == "/api/generate"][0]
            assert "think" not in body
    finally:
        await probe_client.aclose()
        await replacement.aclose()
        await old_client.aclose()


async def test_existing_physical_guard_prevents_metadata_probe():
    from agents.core.llm.data_handling import physical_request_scope

    backend, seen = _backend([False])
    try:
        with reasoning_scope("none"), physical_request_scope(lambda: None):
            assert await _agent().generate_response(
                backend, "model", "hello", "system", 64, 0.2) == "answer"
        assert [path for path, _ in seen] == ["/api/generate"]
        assert "think" not in seen[0][1]
    finally:
        await backend.aclose()


async def test_cancelled_metadata_read_does_not_start_generation():
    entered = asyncio.Event()
    hold = asyncio.Event()
    seen = []

    async def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/api/show":
            entered.set()
            await hold.wait()
            return httpx.Response(200, json={"thinking": {"values": [False]}})
        return httpx.Response(200, json={"response": "answer"})

    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)
    backend.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:11434")

    async def turn():
        with reasoning_scope("none"):
            return await _agent().generate_response(backend, "model", "hi", "system", 64, 0.2)

    try:
        task = asyncio.create_task(turn())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert seen == ["/api/show"]
    finally:
        hold.set()
        await backend.aclose()
