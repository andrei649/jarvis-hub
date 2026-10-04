"""H277: typed, operation-only local auxiliary output-cap recovery."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agents.core import soul_edit
from agents.core.compaction_hold import SummaryStalled, SummaryUnusable
from agents.core.llm import data_handling
from agents.core.llm.base import is_degraded_reply
from agents.core.llm.egress import llm_async_client
from tests.test_h277_auxiliary_parameter_recovery import (
    CAPABILITY,
    CASES,
    DRAFT,
    answer,
    invoke,
    route,
)
from tests.test_h277_compression_temperature_recovery import (
    completed,
    compress,
)
from tests.test_h277_compression_temperature_recovery import (
    route as compression_route,
)
from tests.test_h277_soul_description_auxiliary import draft_route

CAP = {"error": {"code": "unsupported_parameter", "param": "max_tokens",
                 "message": "Unsupported parameter: max_tokens"}}
TEMP = {"error": {"code": "unsupported_parameter", "param": "temperature",
                  "message": "Unsupported parameter: temperature"}}
UNLOADED = {"error": "Model unloaded by user or API request."}


def _same_except(first, second, *removed):
    assert second == {key: value for key, value in first.items() if key not in removed}


@pytest.mark.parametrize("task,answer_text,cap", CASES)
async def test_real_auxiliary_producer_removes_only_rejected_cap(
    monkeypatch, task, answer_text, cap,
):
    sent = []
    checks = []
    original = data_handling.authorize

    def authorize(*args, **kwargs):
        checks.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(data_handling, "authorize", authorize)

    def handler(request):
        sent.append((str(request.url), json.loads(request.content), len(checks)))
        return httpx.Response(400, json=CAP) if len(sent) == 1 else answer(answer_text)

    orch, router, backend = route(handler)
    try:
        expected = (CAPABILITY if task == "acquisition_capability" else
                    DRAFT if task == "acquisition_draft" else answer_text)
        assert await invoke(task, orch, router) == expected
        assert len(sent) == 2
        assert [url for url, _, _ in sent] == [
            "http://127.0.0.1:1234/v1/chat/completions"] * 2
        assert sent[0][2] >= 2 and sent[1][2] > sent[0][2]
        first, second = sent[0][1], sent[1][1]
        assert first["max_tokens"] == cap
        _same_except(first, second, "max_tokens")
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("order", [(TEMP, CAP), (CAP, TEMP)])
async def test_temperature_and_cap_chain_in_either_order(order):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=order[len(sent) - 1]) if len(sent) < 3 else answer("recovered")

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "recovered"
        assert len(sent) == 3
        assert sent[0]["max_tokens"] == 512 and sent[0]["temperature"] == 0.2
        assert sent[2] == {key: value for key, value in sent[0].items()
                           if key not in {"temperature", "max_tokens"}}
        removed = "temperature" if order[0] == TEMP else "max_tokens"
        _same_except(sent[0], sent[1], removed)
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("order", [(UNLOADED, TEMP, CAP), (CAP, UNLOADED, TEMP)])
async def test_unload_and_both_typed_fields_have_four_send_ceiling(order):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=order[len(sent) - 1]) if len(sent) < 4 else answer("ready")

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "ready"
        assert len(sent) == 4
        assert all(body["messages"] == sent[0]["messages"] and
                   body["model"] == sent[0]["model"] for body in sent)
        assert "temperature" not in sent[-1] and "max_tokens" not in sent[-1]
        assert sent[1] == (sent[0] if order[0] == UNLOADED else
                           {key: value for key, value in sent[0].items() if key != "max_tokens"})
    finally:
        await backend.client.aclose()


async def test_cap_omission_is_never_learned_for_next_auxiliary_operation():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=CAP) if len(sent) == 1 else answer("ready")

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "ready"
        assert await invoke("review", orch, router) == "ready"
        assert len(sent) == 3
        assert ["max_tokens" in body for body in sent] == [True, False, True]
        assert all(body["messages"] == sent[0]["messages"] for body in sent)
    finally:
        await backend.client.aclose()


@pytest.mark.parametrize("status,body", [
    (401, CAP),
    (429, CAP),
    (400, {"error": {"code": "unsupported_parameter", "param": "top_p",
                     "message": "Unsupported parameter: max_tokens"}}),
    (400, {"error": {"message": "context overflow with max_tokens=512"}}),
    (400, {"error": {"message": "max_tokens has an invalid value"}}),
    (400, {"error": {"code": "unsupported_parameter", "message": "unsupported input"}}),
    (400, {"error": "Unsupported parameter: max_tokens"}),
    (400, {"error": {"message": "Unsupported parameter: max_tokens" + "x" * 513}}),
    (400, {"error": {"message": "Unsupported parameter: max_tokens"},
           "padding": "x" * 4096}),
])
async def test_unrelated_unstructured_or_unbounded_error_never_replays(status, body):
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


async def test_bounded_message_without_code_can_identify_cap():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {"message": "Unknown parameter: max_tokens"}})
        return answer("ready")

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "ready"
        assert len(sent) == 2 and "max_tokens" not in sent[1]
    finally:
        await backend.client.aclose()


async def test_absent_auto_cap_does_not_replay_unchanged_request():
    from agents.core.llm.auxiliary_text import generate_local_auxiliary

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=CAP)

    _orch, router, backend = route(handler)
    try:
        result = await generate_local_auxiliary(
            router, "review", system="system", prompt="private", max_tokens=0, temperature=0.2)
        assert is_degraded_reply(result)
        assert len(sent) == 1 and "max_tokens" not in sent[0]
    finally:
        await backend.client.aclose()


async def test_ordinary_generation_and_tool_turn_cannot_repair_cap():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=CAP)

    _orch, _router, backend = route(handler)
    try:
        assert is_degraded_reply(await backend.generate("selected-local", "ordinary"))
        tool = await backend.generate_tool_turn(
            "selected-local", [{"role": "user", "content": "ordinary"}], [])
        assert is_degraded_reply(tool.content)
        assert len(sent) == 2 and all(body["max_tokens"] == 1024 for body in sent)
    finally:
        await backend.client.aclose()


async def test_cap_retry_rechecks_physical_h513_authorization(monkeypatch):
    sent = []
    original = data_handling.authorize
    allowed = True

    def authorize(*args, **kwargs):
        if not allowed:
            raise data_handling.DataHandlingRefused("revoked after first send")
        return original(*args, **kwargs)

    def handler(request):
        nonlocal allowed
        sent.append(json.loads(request.content))
        allowed = False
        return httpx.Response(400, json=CAP)

    monkeypatch.setattr(data_handling, "authorize", authorize)
    orch, router, backend = route(handler)
    try:
        with pytest.raises(data_handling.DataHandlingRefused, match="revoked after first send"):
            await invoke("query_rewrite", orch, router)
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_cap_retry_refuses_changed_client_route():
    first_sent, second_sent = [], []
    second_client = None

    def handler(request):
        first_sent.append(json.loads(request.content))
        backend.client = second_client
        return httpx.Response(400, json=CAP)

    orch, router, backend = route(handler)
    original_client = backend.client
    second_client = llm_async_client(
        "lm-studio", base_url=backend.base_url,
        transport=httpx.MockTransport(lambda request: (
            second_sent.append(request) or answer("wrong route"))))
    try:
        assert is_degraded_reply(await invoke("review", orch, router))
        assert len(first_sent) == 1 and second_sent == []
    finally:
        await original_client.aclose()
        await second_client.aclose()


async def test_soul_description_accepts_only_typed_cap_omission(draft_route):
    orch, backend, sent = draft_route

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=CAP) if len(sent) == 1 else answer("A local household assistant.")

    await backend.client.aclose()
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(handler))
    try:
        assert await soul_edit.draft_description(orch, "jarvis") == "A local household assistant."
        assert len(sent) == 2
        _same_except(sent[0], sent[1], "max_tokens")
    finally:
        await backend.aclose()


async def test_soul_description_rejects_missing_cap_on_first_send(draft_route):
    orch, backend, sent = draft_route

    async def remove_cap(request):
        body = json.loads(request.content)
        body.pop("max_tokens", None)
        request._content = json.dumps(body).encode()

    backend.client.event_hooks["request"].insert(0, remove_cap)
    try:
        with pytest.raises(soul_edit.SoulEditError):
            await soul_edit.draft_description(orch, "jarvis")
        assert sent == []
    finally:
        await backend.aclose()


async def test_soul_description_rechecks_prompt_on_repaired_send(draft_route):
    orch, backend, sent = draft_route

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=CAP) if len(sent) == 1 else answer("wrong")

    await backend.client.aclose()
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(handler))
    hooks = backend.client.event_hooks["request"]
    count = 0

    async def mutate_second(request):
        nonlocal count
        count += 1
        if count == 2:
            body = json.loads(request.content)
            body["messages"][-1]["content"] = "injected prompt"
            request._content = json.dumps(body).encode()

    hooks.insert(0, mutate_second)
    try:
        with pytest.raises(soul_edit.SoulEditError):
            await soul_edit.draft_description(orch, "jarvis")
        assert len(sent) == 1
    finally:
        await backend.aclose()


async def test_real_compression_worker_recovers_before_any_frame(monkeypatch):
    sent, checks = [], []
    original = data_handling.authorize

    def authorize(*args, **kwargs):
        checks.append(1)
        return original(*args, **kwargs)

    def handler(request):
        sent.append((str(request.url), json.loads(request.content), len(checks)))
        return httpx.Response(400, json=CAP) if len(sent) == 1 else completed("private summary")

    monkeypatch.setattr(data_handling, "authorize", authorize)
    router, backend = compression_route(handler)
    try:
        assert await compress(router) == "private summary"
        assert len(sent) == 2
        assert sent[0][0] == sent[1][0] == "http://127.0.0.1:1234/v1/chat/completions"
        assert sent[1][2] > sent[0][2]
        _same_except(sent[0][1], sent[1][1], "max_tokens")
    finally:
        await backend.aclose()


async def test_compression_cap_rejection_after_frame_never_replays():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"reasoning_content":"thought"}}]}\n\n'
            'data: [DONE]\n\n'))

    router, backend = compression_route(handler)
    original_stream = backend.generate_stream

    async def interrupted_stream(*args, on_activity=None, **kwargs):
        def fail_after_frame():
            request = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
            response = httpx.Response(400, json=CAP, request=request)
            raise httpx.HTTPStatusError("rejected", request=request, response=response)

        return await original_stream(*args, on_activity=fail_after_frame, **kwargs)

    backend.generate_stream = interrupted_stream
    try:
        with pytest.raises(SummaryUnusable):
            await compress(router)
        assert len(sent) == 1
    finally:
        await backend.aclose()


async def test_stream_cap_rejection_cleanup_failure_never_replays():
    sent = []

    class FaultyBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(CAP).encode()

        async def aclose(self):
            raise RuntimeError("cleanup failed")

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, stream=FaultyBody(),
                              headers={"content-type": "application/json"})

    router, backend = compression_route(handler)
    try:
        with pytest.raises(SummaryUnusable):
            await compress(router)
        assert len(sent) == 1
    finally:
        await backend.aclose()


async def test_stream_cap_rejection_cancellation_never_replays():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        raise asyncio.CancelledError()

    router, backend = compression_route(handler)
    try:
        with pytest.raises(asyncio.CancelledError):
            await compress(router)
        assert len(sent) == 1
    finally:
        await backend.aclose()


async def test_transport_error_text_cannot_trigger_cap_replay():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        raise httpx.ConnectError("Unsupported parameter: max_tokens")

    orch, router, backend = route(handler)
    try:
        assert is_degraded_reply(await invoke("review", orch, router))
        assert len(sent) == 1
    finally:
        await backend.client.aclose()


async def test_cap_retry_does_not_extend_compression_idle_deadline():
    from agents.core.llm.auxiliary_text import generate_local_auxiliary

    sent = []

    async def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(400, json=CAP)
        await asyncio.sleep(0.2)
        return completed("too late")

    router, backend = compression_route(handler)
    try:
        with pytest.raises(SummaryStalled):
            await generate_local_auxiliary(
                router, "compression", system="system", prompt="private history",
                max_tokens=300, temperature=0.2, summary_idle=0.04)
        assert len(sent) == 2
    finally:
        await backend.aclose()
