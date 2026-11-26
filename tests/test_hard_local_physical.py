"""Synthetic, offline proofs of the hard-local inference boundary."""

import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.agent import Agent
from agents.core.llm.base import OllamaBackend
from agents.core.llm.data_handling import DataHandlingRefused
from agents.core.llm.egress import llm_async_client
from agents.core.llm.hybrid_router import HybridRouter
from agents.core.llm.moa import MoACommitteeBackend, MoAPreset
from agents.core.llm.physical_local import physical_local_scope
from agents.core.turn_usage import model_calls_from_snapshot, model_usage_scope, turn_usage_scope


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("generate", "/api/generate"),
    ("generate_stream", "/api/generate"),
    ("generate_tool_turn", "/api/chat"),
])
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_hard_local_ollama_uses_physical_selector_and_measured_receipt(method, path, scheme):
    seen = []

    def answer(request):
        seen.append(request)
        if path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": "safe"}, "done": True,
                                             "prompt_eval_count": 2, "eval_count": 1})
        if method == "generate_stream":
            return httpx.Response(200, text=json.dumps({"response": "safe", "done": True,
                                                         "prompt_eval_count": 2, "eval_count": 1}) + "\n")
        return httpx.Response(200, json={"response": "safe", "done": True,
                                         "prompt_eval_count": 2, "eval_count": 1})

    backend = OllamaBackend(base_url=f"{scheme}://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client("ollama", base_url=backend.base_url,
                                      transport=httpx.MockTransport(answer), trust_env=False)
    try:
        with turn_usage_scope() as usage, model_usage_scope(model="test:latest", route="local"), physical_local_scope():
            if method == "generate_tool_turn":
                result = await backend.generate_tool_turn("test:latest", [{"role": "user", "content": "synthetic"}], [])
            else:
                result = await getattr(backend, method)("test:latest", "synthetic")
        assert (result.content if method == "generate_tool_turn" else result) == "safe"
        assert len(seen) == 1 and seen[0].url.path == path
        assert seen[0].read().decode()  # real body, no cloud transport
        assert json.loads(seen[0].content)["model"] == "test:latest:local"
        assert model_calls_from_snapshot(usage.snapshot()) == [
            {"provider": "ollama", "model": "test:latest:local"}]
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_hard_local_refuses_lan_before_dispatch():
    seen = []
    backend = OllamaBackend(base_url="http://192.168.1.7:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client("ollama", base_url=backend.base_url,
                                      transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200)),
                                      trust_env=False)
    try:
        with pytest.raises(DataHandlingRefused), physical_local_scope():
                await backend.generate("test:latest", "synthetic private excerpt")
        assert seen == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_hard_local_rechecks_final_ollama_body_before_dispatch():
    seen = []

    async def alter(request):
        body = json.loads(request.content)
        body["model"] = "test:latest"
        request._content = json.dumps(body).encode()

    backend = OllamaBackend(base_url="http://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client(
        "ollama", base_url=backend.base_url,
        event_hooks={"request": [alter]},
        transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200)),
        trust_env=False)
    try:
        with pytest.raises(DataHandlingRefused), physical_local_scope():
            await backend.generate("test:latest", "synthetic private excerpt")
        assert seen == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_hard_local_ollama_generation_requires_trusted_selector():
    seen = []
    client = llm_async_client(
        "ollama", base_url="http://127.0.0.1:11434",
        transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200)),
        trust_env=False)
    try:
        with pytest.raises(DataHandlingRefused), physical_local_scope():
            await client.post("/api/generate", json={"model": "test:latest",
                                                     "prompt": "synthetic private excerpt"})
        assert seen == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_strict_scope_ollama_warm_up_pins_selector():
    seen = []

    def answer(request):
        seen.append(request)
        return httpx.Response(200, json={"done": True})

    backend = OllamaBackend(base_url="http://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client("ollama", base_url=backend.base_url,
                                      transport=httpx.MockTransport(answer), trust_env=False)
    try:
        with physical_local_scope():
            assert await backend.warm_up("test:latest")
        assert len(seen) == 1
        assert json.loads(seen[0].content)["model"] == "test:latest:local"
        assert json.loads(seen[0].content)["prompt"] == ""
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_hard_local_refuses_redirect_to_lan_before_second_dispatch():
    seen = []

    def answer(request):
        seen.append(request)
        return httpx.Response(307, headers={"location": "http://192.168.1.7:11434/api/generate"})

    backend = OllamaBackend(base_url="http://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client("ollama", base_url=backend.base_url,
                                      transport=httpx.MockTransport(answer), follow_redirects=True,
                                      trust_env=False)
    try:
        with pytest.raises(DataHandlingRefused), physical_local_scope():
            await backend.generate("test:latest", "synthetic private excerpt")
        assert len(seen) == 1
        assert seen[0].url.host == "127.0.0.1"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_hard_local_refuses_proxy_selected_for_loopback():
    backend = OllamaBackend(base_url="http://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client("ollama", base_url=backend.base_url,
                                      proxy="http://127.0.0.1:8765", trust_env=False)
    try:
        with pytest.raises(DataHandlingRefused), physical_local_scope():
            await backend.generate("test:latest", "synthetic private excerpt")
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_id,strict", [("frigga", False), ("jarvis", True)])
@pytest.mark.parametrize("stream", [False, True])
async def test_agent_synthetic_excerpt_uses_local_wire_and_receipt(monkeypatch, agent_id, strict, stream):
    monkeypatch.setenv("JARVIS_STRICT_LOCAL", "1" if strict else "0")
    seen = []

    def answer(request):
        seen.append(request)
        payload = {"response": "safe", "done": True, "prompt_eval_count": 2, "eval_count": 1}
        return (httpx.Response(200, text=json.dumps(payload) + "\n") if stream
                else httpx.Response(200, json=payload))

    backend = OllamaBackend(base_url="http://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client("ollama", base_url=backend.base_url,
                                      transport=httpx.MockTransport(answer), trust_env=False)
    agent = object.__new__(Agent)
    agent.id = agent_id
    agent.tool_runtime = None
    agent.llm_router = None
    agent._checkpoint_manager = None
    try:
        with turn_usage_scope() as usage, model_usage_scope(model="test:latest", route="local",
                                                             agent_id=agent_id):
            result = await agent.generate_response(
                backend, "test:latest", "synthetic private excerpt", "synthetic system", 16, 0,
                on_token=(lambda _piece: None) if stream else None, clock_snapshot=None)
        assert result == "safe"
        assert len(seen) == 1
        assert json.loads(seen[0].content)["prompt"] == "synthetic private excerpt"
        assert json.loads(seen[0].content)["model"] == "test:latest:local"
        assert model_calls_from_snapshot(usage.snapshot()) == [
            {"provider": "ollama", "model": "test:latest:local"}]
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_strict_local_synthesis_routes_ordinary_contributors_to_native_wire(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_LOCAL", "1")
    seen = []

    def answer(request):
        seen.append(request)
        return httpx.Response(200, json={"response": "fused", "done": True})

    backend = OllamaBackend(base_url="http://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client("ollama", base_url=backend.base_url,
                                      transport=httpx.MockTransport(answer), trust_env=False)
    router = HybridRouter(gemini_api_key="inert")
    router._local_available = router._cloud_available = True
    router._backend, router._backend_name = backend, "ollama"
    router._gemini_backend = object()
    router.set_cloud_fallback_mode("always")
    router.check_data_handling = lambda *_args, **_kwargs: None
    agent = object.__new__(Agent)
    agent.id, agent.config, agent.llm_router = "jarvis", {"model": "test:latest"}, router
    agent.guardrails = agent.tool_runtime = None
    agent.system_prompt = lambda: "synthetic system"
    agent._gen_params = lambda _route: (16, 0)
    try:
        assert await agent.synthesize({"stark": "synthetic observation"}, None) == "fused"
        assert len(seen) == 1
        assert json.loads(seen[0].content)["model"] == router._local_model + ":local"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_direct_frigga_moa_pins_every_member_to_physical_local(stream):
    seen = []

    def answer(request):
        seen.append(request)
        body = json.loads(request.content)
        result = {"response": "safe", "done": True, "prompt_eval_count": 2, "eval_count": 1}
        return (httpx.Response(200, text=json.dumps(result) + "\n") if body["stream"]
                else httpx.Response(200, json=result))

    async def resident(*_args):
        return None

    backend = OllamaBackend(base_url="http://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client("ollama", base_url=backend.base_url,
                                      transport=httpx.MockTransport(answer), trust_env=False)
    committee = MoACommitteeBackend(
        router=SimpleNamespace(ensure_resident=resident), agent_id="frigga",
        preset=MoAPreset("test", ("local", "local"), "local"),
        proposer_bindings=[("first", backend, "test:latest", "local"),
                           ("second", backend, "test:latest", "local")],
        aggregator_binding=("final", backend, "test:latest", "local"))
    committee._authorize_all_members = lambda: None
    try:
        with turn_usage_scope() as usage:
            method = committee.generate_stream if stream else committee.generate
            result = await method("moa:test", "synthetic private excerpt", max_tokens=16)
        assert result == "safe"
        assert len(seen) == 3
        assert all(request.url.host == "127.0.0.1" for request in seen)
        assert all(json.loads(request.content)["model"] == "test:latest:local"
                   for request in seen)
        assert model_calls_from_snapshot(usage.snapshot()) == [
            {"provider": "ollama", "model": "test:latest:local"}]
    finally:
        await backend.aclose()
