"""H277: field-bound unsupported wording on real strict-local auxiliary wires."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agents.core import soul_edit
from agents.core.compaction_hold import SummaryStalled, SummaryUnusable
from agents.core.llm import data_handling
from agents.core.llm.auxiliary_recovery import rejects_output_cap, rejects_temperature
from agents.core.llm.base import is_degraded_reply
from agents.core.llm.egress import llm_async_client
from tests.test_h277_auxiliary_output_cap_recovery import CAPABILITY, CASES, DRAFT
from tests.test_h277_auxiliary_parameter_recovery import answer, invoke, route
from tests.test_h277_compression_temperature_recovery import completed, compress
from tests.test_h277_compression_temperature_recovery import route as compression_route
from tests.test_h277_soul_description_auxiliary import draft_route


def rejection(field: str, phrase: str) -> dict:
    return {"error": {"param": field, "message": phrase}}


@pytest.mark.parametrize("field,phrases", [
    ("temperature", ["temperature is not supported for this model",
                     "this model does not support temperature"]),
    ("max_tokens", ["max_tokens is not supported for this model",
                    "this model does not support max_tokens"]),
])
@pytest.mark.parametrize("task,answer_text,cap", CASES)
async def test_real_producers_repair_only_explicitly_unsupported_field(
    monkeypatch, task, answer_text, cap, field, phrases,
):
    checks = []
    original = data_handling.authorize

    def authorize(*args, **kwargs):
        checks.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(data_handling, "authorize", authorize)
    for phrase in phrases:
        sent = []

        def handler(request, sent=sent, phrase=phrase):
            sent.append((str(request.url), json.loads(request.content), len(checks)))
            return (httpx.Response(400, json=rejection(field, phrase))
                    if len(sent) == 1 else answer(answer_text))

        orch, router, backend = route(handler)
        try:
            result = await invoke(task, orch, router)
            expected = (CAPABILITY if task == "acquisition_capability" else
                        DRAFT if task == "acquisition_draft" else answer_text)
            assert result == expected
            assert len(sent) == 2
            first, second = sent
            assert first[0] == second[0] == "http://127.0.0.1:1234/v1/chat/completions"
            assert second[2] > first[2]
            assert first[1]["max_tokens"] == cap
            assert second[1] == {k: v for k, v in first[1].items() if k != field}
        finally:
            await backend.client.aclose()


@pytest.mark.parametrize("order", [("temperature", "max_tokens"),
                                    ("max_tokens", "temperature")])
async def test_new_wordings_chain_both_fields_and_unload_with_four_send_ceiling(order):
    errors = [rejection(order[0], f"this model does not support {order[0]}"),
              {"error": "Model unloaded by user or API request."},
              rejection(order[1], f"{order[1]} is not supported for this model")]
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json=errors[len(sent) - 1]) if len(sent) <= 3 else answer("ready")

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "ready"
        assert len(sent) == 4
        assert sent[1] == {k: v for k, v in sent[0].items() if k != order[0]}
        assert sent[2] == sent[1]
        assert sent[3] == {k: v for k, v in sent[0].items()
                           if k not in {"temperature", "max_tokens"}}
    finally:
        await backend.client.aclose()


async def test_new_cap_wording_is_not_learned_for_next_operation():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return (httpx.Response(400, json=rejection(
            "max_tokens", "max_tokens is not supported for this model"))
            if len(sent) == 1 else answer("ready"))

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "ready"
        assert await invoke("review", orch, router) == "ready"
        assert len(sent) == 3
        assert ["max_tokens" in body for body in sent] == [True, False, True]
    finally:
        await backend.client.aclose()


async def test_new_temperature_wording_learns_only_after_success_on_same_route():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return (httpx.Response(400, json=rejection(
            "temperature", "this model does not support temperature"))
            if len(sent) == 1 else answer("ready"))

    orch, router, backend = route(handler)
    try:
        assert await invoke("review", orch, router) == "ready"
        assert await invoke("review", orch, router) == "ready"
        assert len(sent) == 3
        assert ["temperature" in body for body in sent] == [True, False, False]
    finally:
        await backend.client.aclose()


async def test_new_cap_wording_rechecks_h513_and_stops_after_revocation(monkeypatch):
    seen = []
    permitted = True
    original = data_handling.authorize

    def authorize(*args, **kwargs):
        if not permitted:
            raise data_handling.DataHandlingRefused("revoked after first physical send")
        return original(*args, **kwargs)

    def handler(request):
        nonlocal permitted
        seen.append(json.loads(request.content))
        permitted = False
        return httpx.Response(400, json=rejection(
            "max_tokens", "this model does not support max_tokens"))

    monkeypatch.setattr(data_handling, "authorize", authorize)
    orch, router, backend = route(handler)
    try:
        with pytest.raises(data_handling.DataHandlingRefused, match="revoked after first"):
            await invoke("review", orch, router)
        assert len(seen) == 1
    finally:
        await backend.client.aclose()


async def test_strict_soul_accepts_cap_omission_only_after_new_typed_wording(draft_route):
    orch, backend, sent = draft_route

    def handler(request):
        sent.append(json.loads(request.content))
        return (httpx.Response(400, json=rejection(
            "max_tokens", "this model does not support max_tokens"))
            if len(sent) == 1 else answer("A local household assistant."))

    await backend.client.aclose()
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(handler))
    try:
        assert await soul_edit.draft_description(orch, "jarvis") == "A local household assistant."
        assert len(sent) == 2
        assert sent[1] == {k: v for k, v in sent[0].items() if k != "max_tokens"}
    finally:
        await backend.aclose()


@pytest.mark.parametrize("field", ["temperature", "max_tokens"])
async def test_compression_repairs_new_wording_only_before_stream_activity(field):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return (httpx.Response(400, json=rejection(
            field, f"this model does not support {field}"))
            if len(sent) == 1 else completed("private summary"))

    router, backend = compression_route(handler)
    try:
        assert await compress(router) == "private summary"
        assert len(sent) == 2
        assert sent[0]["stream"] is True
        assert sent[1] == {k: v for k, v in sent[0].items() if k != field}
    finally:
        await backend.aclose()


@pytest.mark.parametrize("field,check", [("temperature", rejects_temperature),
                                          ("max_tokens", rejects_output_cap)])
@pytest.mark.parametrize("status,body", [
    (400, {"error": {"param": "top_p", "message": "this model does not support {field}"}}),
    (400, {"error": {"param": "{field}", "message": "{field} must be between 0 and 2"}}),
    (400, {"error": {"message": "this model does not support another field"}}),
    (400, {"error": {"param": "{field}",
                     "message": "this model does not support {field} above 512"}}),
    (400, {"error": {"param": "{field}",
                     "message": "{field} is not supported at value 0.8"}}),
    (401, {"error": {"param": "{field}", "message": "this model does not support {field}"}}),
    (429, {"error": {"param": "{field}", "message": "this model does not support {field}"}}),
    (400, {"error": {"param": "{field}", "message": "this model does not support {field}" + "x" * 513}}),
    (400, {"error": {"param": "{field}", "message": "{field} is not supported",
                     "padding": "x" * 4096}}),
    (400, {"error": "this model does not support {field}"}),
])
def test_new_wording_is_field_and_status_bounded(field, check, status, body):
    payload = json.loads(json.dumps(body).replace("{field}", field))
    request = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
    response = httpx.Response(status, request=request, json=payload)
    error = httpx.HTTPStatusError("synthetic status", request=request, response=response)
    assert check(error) is False


async def test_mismatched_structured_param_never_causes_second_physical_send():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {
            "param": "top_p", "message": "this model does not support max_tokens"}})

    orch, router, backend = route(handler)
    try:
        assert is_degraded_reply(await invoke("review", orch, router))
        assert len(seen) == 1
    finally:
        await backend.client.aclose()


async def test_new_wording_after_stream_frame_never_replays():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"reasoning_content":"thought"}}]}\n\n'
            'data: [DONE]\n\n'))

    router, backend = compression_route(handler)
    original_stream = backend.generate_stream

    async def interrupted(*args, on_activity=None, **kwargs):
        def fail_after_frame():
            request = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
            response = httpx.Response(400, request=request, json=rejection(
                "max_tokens", "this model does not support max_tokens"))
            raise httpx.HTTPStatusError("synthetic status", request=request, response=response)

        return await original_stream(*args, on_activity=fail_after_frame, **kwargs)

    backend.generate_stream = interrupted
    try:
        with pytest.raises(SummaryUnusable):
            await compress(router)
        assert len(sent) == 1
    finally:
        await backend.aclose()


async def test_new_wording_cleanup_fault_never_replays():
    sent = []

    class FaultyBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(rejection("max_tokens", "max_tokens is not supported")).encode()

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


async def test_new_wording_retry_keeps_original_compression_idle_deadline():
    from agents.core.llm.auxiliary_text import generate_local_auxiliary

    sent = []

    async def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(400, json=rejection(
                "max_tokens", "this model does not support max_tokens"))
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
