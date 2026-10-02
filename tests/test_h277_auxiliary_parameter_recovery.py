"""H277 typed local parameter recovery through actual auxiliary producers."""

import json
from contextvars import copy_context

import httpx
import pytest

from agents.core.acquisition.llm_synth import draft_plan, generate_capability
from agents.core.llm import data_handling
from agents.core.llm.auxiliary_recovery import (
    auxiliary_temperature_recovery_scope,
    may_repair_temperature,
)
from agents.core.llm.base import LMStudioBackend, is_degraded_reply
from agents.core.llm.egress import llm_async_client
from agents.core.llm.router import LLMRouter
from agents.core.orchestrator import Orchestrator

CAPABILITY = {"name": "parser", "entrypoint": "run", "code": "def run(x): return x",
              "test": "assert True"}
DRAFT = [{"text": "Read source 1", "cites": ["source-1"]}]
PROMPT = {"goal": "create parser", "entrypoint": "run", "requirements": ["parse ids"]}
REFERENCES = [{"id": "source-1", "title": "API reference", "url": "https://example.invalid/api"}]
CASES = [
    ("session_title", "short title", 24),
    ("query_rewrite", "better query", 96),
    ("review", '{"actions": []}', 512),
    ("acquisition_capability", json.dumps(CAPABILITY), 2048),
    ("acquisition_draft", json.dumps(DRAFT), 1024),
]
REJECTION = {"error": {"code": "unsupported_parameter", "param": "temperature",
                       "message": "Unsupported parameter: temperature"}}
UNLOADED = {"error": "Model unloaded by user or API request."}


def answer(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text},
                                                   "finish_reason": "stop"}]})


def route(handler):
    backend = LMStudioBackend("http://127.0.0.1:1234")
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, transport=httpx.MockTransport(handler))
    router = LLMRouter()
    router._backend = backend
    router._backend_name = "lm-studio"
    router._detected_model = "selected-local"
    router._local_model = "selected-local"
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    orch.get_setting = lambda _key, default=None: default
    return orch, router, backend


async def invoke(task, orch, router):
    if task == "session_title":
        return await orch._session_titler()(system="title system", prompt="private prompt")
    if task == "query_rewrite":
        return await orch._query_rewriter()(system="rewrite system", prompt="private prompt")
    if task == "review":
        return await orch._review_llm("private prompt")
    if task == "acquisition_capability":
        return await generate_capability(PROMPT, router=router)
    return await draft_plan("parse API items", REFERENCES, router=router)


@pytest.mark.parametrize("task,answer_text,max_tokens", CASES)
async def test_real_producer_repairs_typed_temperature_rejection_once(task, answer_text, max_tokens):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(400, json=REJECTION)
        return answer(answer_text)

    orch, router, backend = route(handler)
    try:
        result = await invoke(task, orch, router)
        assert result == (CAPABILITY if task == "acquisition_capability" else
                          DRAFT if task == "acquisition_draft" else answer_text)
        assert len(sent) == 2
        assert sent[0]["temperature"] == (0 if task in {"session_title", "query_rewrite"} else 0.2)
        assert "temperature" not in sent[1]
        assert [body["max_tokens"] for body in sent] == [max_tokens, max_tokens]
        assert [body["model"] for body in sent] == ["selected-local", "selected-local"]
        assert sent[0]["messages"] == sent[1]["messages"]
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("first,second", [(UNLOADED, REJECTION), (REJECTION, UNLOADED)])
async def test_both_repair_orders_keep_same_operation_and_three_send_cap(first, second):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) < 3:
            return httpx.Response(400, json=first if len(sent) == 1 else second)
        return answer("recovered")

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "recovered"
        assert len(sent) == 3
        assert all(body["model"] == "selected-local" and body["max_tokens"] == 512
                   for body in sent)
        assert all(body["messages"] == sent[0]["messages"] for body in sent)
        if first == UNLOADED:
            assert "temperature" in sent[1]
        else:
            assert "temperature" not in sent[1]
        assert "temperature" not in sent[2]
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("body", [
    REJECTION,
    UNLOADED,
])
async def test_same_rejection_twice_never_loops(body):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=body)

    orch, router, backend = route(handler)
    try:
        assert is_degraded_reply(await invoke("review", orch, router))
        assert len(sent) == 2
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("status,body", [
    (401, REJECTION), (402, REJECTION), (429, REJECTION), (500, REJECTION),
    (400, {"error": {"code": "unsupported_parameter", "param": "top_p",
                     "message": "unsupported temperature and top_p"}}),
    (400, {"error": {"message": "temperature has an invalid value"}}),
    (400, {"error": "Unsupported parameter: temperature"}),
    (400, {"error": {"message": "unsupported temperature" + "x" * 513}}),
    (400, {"error": {"message": "unsupported temperature"}, "padding": "x" * 4096}),
    (400, {"error": {"message": "Unknown model; temperature is supported"}}),
    (400, {"error": {"message": "unknown temperature_sensor"}}),
])
async def test_unrelated_or_unbounded_failures_do_not_repair(status, body):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(status, json=body)

    orch, router, backend = route(handler)
    try:
        assert is_degraded_reply(await invoke("review", orch, router))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_bounded_message_without_code_identifies_temperature():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {"message": "Unknown parameter: temperature"}})
        return answer("recovered")

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "recovered"
        assert len(sent) == 2 and "temperature" not in sent[1]
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("task,variable", [
    ("session_title", "JARVIS_AUX_SESSION_TITLE_MODEL"),
    ("query_rewrite", "JARVIS_AUX_QUERY_REWRITE_MODEL"),
])
async def test_qwen_no_think_prompt_is_identical_on_repair(monkeypatch, task, variable):
    monkeypatch.setenv(variable, "local-qwen3")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=REJECTION) if len(sent) == 1 else answer("recovered")

    orch, router, backend = route(handler)
    try:
        assert await invoke(task, orch, router) == "recovered"
        assert len(sent) == 2
        assert sent[0]["messages"] == sent[1]["messages"]
        assert sent[0]["messages"][-1]["content"].endswith("/no_think")
        assert [body["model"] for body in sent] == ["local-qwen3", "local-qwen3"]
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("response", [
    httpx.Response(400, text="not JSON: unsupported parameter temperature"),
    httpx.ConnectError("unsupported parameter temperature"),
])
async def test_unstructured_response_or_exception_string_does_not_repair(response):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if isinstance(response, BaseException):
            raise response
        return response

    orch, router, backend = route(handler)
    try:
        assert is_degraded_reply(await invoke("review", orch, router))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_ordinary_generate_and_tool_turn_have_no_parameter_repair():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=REJECTION)

    _, _, backend = route(handler)
    try:
        assert is_degraded_reply(await backend.generate("selected-local", "ordinary"))
        with auxiliary_temperature_recovery_scope(backend, "selected-local"):
            tool = await backend.generate_tool_turn(
                "selected-local", [{"role": "user", "content": "ordinary"}], [])
        assert is_degraded_reply(tool.content)
        assert len(sent) == 2 and all("temperature" in body for body in sent)
    finally:
        await backend.client.aclose()


async def test_repair_uses_copy_and_leaves_caller_payload_unchanged():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=REJECTION) if len(sent) == 1 else answer("recovered")

    _, _, backend = route(handler)
    original = {"model": "selected-local", "messages": [{"role": "user", "content": "prompt"}],
                "temperature": 0.2, "stream": False, "max_tokens": 512}
    try:
        with auxiliary_temperature_recovery_scope(backend, "selected-local"):
            response = await backend._post_chat(original)
        assert response.status_code == 200
        assert original["temperature"] == 0.2
        assert sent[0] == original
        assert sent[1] == {key: value for key, value in original.items() if key != "temperature"}
    finally:
        await backend.client.aclose()


async def test_stream_stays_outside_parameter_recovery():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=REJECTION)

    _, _, backend = route(handler)
    try:
        assert is_degraded_reply(await backend.generate_stream("selected-local", "ordinary stream"))
        assert len(sent) == 1 and sent[0]["temperature"] == 0.7
    finally:
        await backend.client.aclose()


def test_scope_is_exact_nested_and_closed_even_in_inherited_reference():
    one, two = object(), object()
    assert not may_repair_temperature(one, "m")
    with auxiliary_temperature_recovery_scope(one, "m"):
        inherited = copy_context()
        assert may_repair_temperature(one, "m")
        assert not may_repair_temperature(two, "m")
        assert not may_repair_temperature(one, "other")
        with auxiliary_temperature_recovery_scope(two, "other"):
            assert may_repair_temperature(two, "other")
            assert not may_repair_temperature(one, "m")
        assert may_repair_temperature(one, "m")
    assert not may_repair_temperature(one, "m")
    assert not inherited.run(may_repair_temperature, one, "m")


async def test_scope_identity_controls_actual_backend_retry():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=REJECTION)

    _, _, backend = route(handler)
    try:
        with auxiliary_temperature_recovery_scope(object(), "selected-local"):
            assert is_degraded_reply(await backend.generate("selected-local", "not selected backend"))
        with auxiliary_temperature_recovery_scope(backend, "other-model"):
            assert is_degraded_reply(await backend.generate("selected-local", "not selected model"))
        assert len(sent) == 2
        assert all(body["temperature"] == 0.7 for body in sent)
    finally:
        await backend.client.aclose()


async def test_successful_repair_does_not_cache_provider_capability():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) in (1, 3):
            return httpx.Response(400, json=REJECTION)
        return answer("recovered")

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "recovered"
        assert await invoke("review", orch, router) == "recovered"
        assert len(sent) == 4
        assert ["temperature" in body for body in sent] == [True, False, True, False]
    finally:
        await backend.client.aclose()


async def test_physical_guard_rechecks_before_temperature_retry(monkeypatch):
    sent = []
    original = data_handling.authorize
    authorized = True

    def authorize(*args, **kwargs):
        if not authorized:
            raise data_handling.DataHandlingRefused("synthetic revocation")
        return original(*args, **kwargs)

    def handler(request):
        nonlocal authorized
        sent.append(json.loads(request.content))
        authorized = False
        return httpx.Response(400, json=REJECTION)

    monkeypatch.setattr(data_handling, "authorize", authorize)
    orch, router, backend = route(handler)
    try:
        with pytest.raises(data_handling.DataHandlingRefused, match="synthetic revocation"):
            await invoke("review", orch, router)
        assert len(sent) == 1
    finally:
        await backend.client.aclose()
