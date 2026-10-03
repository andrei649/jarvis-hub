"""Temperature repair belongs to the real compression worker, never its parent."""

import asyncio
import json

import httpx
import pytest

from agents.core.compaction_hold import SummaryStalled, stream_summary
from agents.core.llm import data_handling
from agents.core.llm.auxiliary_recovery import (
    auxiliary_temperature_recovery_scope,
    may_repair_temperature,
)
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.egress import llm_async_client
from agents.core.llm.router import LLMRouter
from agents.core.orchestrator import Orchestrator

REJECTION = {"error": {"code": "unsupported_parameter", "param": "temperature"}}


def completed(text="private summary"):
    frame = {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}
    return httpx.Response(200, content=(f"data: {json.dumps(frame)}\n\ndata: [DONE]\n\n").encode())


def route(handler):
    backend = LMStudioBackend("http://127.0.0.1:1234", trust_env=False)
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, transport=httpx.MockTransport(handler))
    router = LLMRouter()
    router._backend = backend
    router._backend_name = "lm-studio"
    router._detected_model = "selected-local"
    router._local_model = "selected-local"
    return router, backend


async def compress(router):
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    settings = {"memory.compression_summary_max_tokens": 300,
                "memory.compression_summary_idle_seconds": 1}
    orch.get_setting = lambda name, default=None: settings.get(name, default)
    return await orch._compression_summarizer()("private history")


async def test_real_compression_worker_repairs_and_learns_with_fresh_egress(monkeypatch):
    sent, authorization = [], []
    original = data_handling.authorize

    def authorize(*args, **kwargs):
        authorization.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(data_handling, "authorize", authorize)

    def handler(request):
        sent.append((json.loads(request.content), len(authorization)))
        return httpx.Response(400, json=REJECTION) if len(sent) == 1 else completed()

    router, backend = route(handler)
    try:
        assert await compress(router) == "private summary"
        assert await compress(router) == "private summary"
        assert len(sent) == 3
        first, repaired, learned = (body for body, _ in sent)
        assert first["temperature"] == 0.2
        assert "temperature" not in repaired and learned == repaired
        assert {k: v for k, v in first.items() if k != "temperature"} == repaired
        assert repaired["model"] == "selected-local" and repaired["max_tokens"] == 300
        assert repaired["stream"] is True
        assert sent[1][1] > sent[0][1] and sent[2][1] > sent[1][1]
        assert not may_repair_temperature(backend, "selected-local")
    finally:
        await backend.aclose()


async def test_compression_retry_rechecks_current_policy(monkeypatch):
    sent, authorization, current = [], [], {"allowed": True}
    original = data_handling.authorize

    def authorize(*args, **kwargs):
        authorization.append(1)
        if not current["allowed"]:
            raise data_handling.DataHandlingRefused("revoked after first response")
        return original(*args, **kwargs)

    monkeypatch.setattr(data_handling, "authorize", authorize)

    def handler(request):
        sent.append(request)
        current["allowed"] = False
        return httpx.Response(400, json=REJECTION)

    router, backend = route(handler)
    try:
        with pytest.raises(data_handling.DataHandlingRefused, match="revoked after first response"):
            await compress(router)
        assert len(sent) == 1
        assert len(authorization) == 3
        assert not may_repair_temperature(backend, "selected-local")
    finally:
        await backend.aclose()


@pytest.mark.parametrize("stop", ["idle", "cancel"])
async def test_summary_worker_scope_is_revoked_before_cancellation_cleanup(stop):
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    permission = []

    class Backend:
        async def generate_stream(self, **_kwargs):
            permission.append(may_repair_temperature(self, "local"))
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                permission.append(may_repair_temperature(self, "local"))
                cancelled.set()
                await release.wait()
                return "late summary"

    backend = Backend()
    call = asyncio.create_task(stream_summary(
        backend, 0.03 if stop == "idle" else 10, model="local", prompt="history",
        system="system", max_tokens=30, temperature=0.2,
        call_scope=lambda: auxiliary_temperature_recovery_scope(backend, "local"),
    ))
    await entered.wait()
    assert not may_repair_temperature(backend, "local")
    if stop == "cancel":
        call.cancel()
    await cancelled.wait()
    release.set()
    with pytest.raises(SummaryStalled if stop == "idle" else asyncio.CancelledError):
        await call
    assert permission == [True, False]
    assert not may_repair_temperature(backend, "local")


async def test_stream_permission_is_not_inherited_by_an_unowned_child():
    permission = []

    class Backend:
        async def generate_stream(self, **_kwargs):
            permission.append(may_repair_temperature(self, "local"))

            async def child():
                permission.append(may_repair_temperature(self, "local"))

            await asyncio.create_task(child())
            return "summary"

    backend = Backend()
    assert await stream_summary(
        backend, 1, model="local", prompt="history", system="system", max_tokens=30,
        temperature=0.2,
        call_scope=lambda: auxiliary_temperature_recovery_scope(backend, "local"),
    ) == "summary"
    assert permission == [True, False]
