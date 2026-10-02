"""Task-specific local model selection in the real acquisition producers."""

import json
from contextlib import suppress
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.acquisition.llm_synth import draft_plan, generate_capability
from agents.core.llm import data_handling
from agents.core.llm.auxiliary_text import (
    AuxiliaryConfigError,
    prepare_local_auxiliary,
    resolve_auxiliary_model,
)
from agents.core.llm.egress import llm_async_client
from agents.core.llm.hybrid_router import HybridRouter
from agents.core.llm.job_selection import SelectionError, selection_scope
from agents.core.llm.providers import get_profile
from agents.core.llm.router import LLMRouter

FLAGS = {
    "capability": "JARVIS_AUX_ACQUISITION_CAPABILITY_MODEL",
    "draft": "JARVIS_AUX_ACQUISITION_DRAFT_MODEL",
}
PROMPT = {"goal": "create an item parser", "entrypoint": "run", "requirements": ["parse ids"]}
REFERENCES = [{"id": "source-1", "title": "API reference", "url": "https://example.invalid/api"}]
CAPABILITY = json.dumps({"name": "parser", "entrypoint": "run", "code": "def run(x): return x",
                         "test": "assert True"})
DRAFT = json.dumps([{"text": "Read source 1", "cites": ["source-1"]}])


class LocalBackend:
    profile = get_profile("lm-studio")
    base_url = "http://127.0.0.1:1234"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def generate(self, model, prompt, *, system, max_tokens, temperature):
        self.calls.append({"model": model, "prompt": prompt, "system": system,
                           "max_tokens": max_tokens, "temperature": temperature})
        return self.replies.pop(0)


def local_router(replies, *, model="active-local"):
    router = LLMRouter()
    backend = LocalBackend(replies)
    router._backend = backend
    router._backend_name = "lm-studio"
    router._detected_model = model
    router._local_model = model
    return router, backend


async def invoke(kind, router):
    if kind == "capability":
        return await generate_capability(PROMPT, router=router)
    return await draft_plan("parse API items", REFERENCES, router=router)


@pytest.mark.parametrize("kind,reply,want_tokens", [
    ("capability", CAPABILITY, 2048), ("draft", DRAFT, 1024),
])
async def test_each_acquisition_producer_uses_its_own_override_without_changing_active(
        monkeypatch, kind, reply, want_tokens):
    router, backend = local_router([reply])
    for task, flag in FLAGS.items():
        monkeypatch.setenv(flag, f"configured-{task}")

    assert await invoke(kind, router)
    assert backend.calls[0]["model"] == f"configured-{kind}"
    assert backend.calls[0]["max_tokens"] == want_tokens
    assert router.active_model == "active-local"


@pytest.mark.parametrize("kind,reply", [("capability", CAPABILITY), ("draft", DRAFT)])
async def test_empty_and_ascii_space_only_keep_exact_local_fallback(monkeypatch, kind, reply):
    router, backend = local_router([reply, reply], model=None)
    monkeypatch.delenv(FLAGS[kind], raising=False)
    await invoke(kind, router)
    monkeypatch.setenv(FLAGS[kind], "   ")
    await invoke(kind, router)
    assert [call["model"] for call in backend.calls] == ["local", "local"]


@pytest.mark.parametrize("kind,reply", [("capability", CAPABILITY), ("draft", DRAFT)])
async def test_router_without_optional_active_model_keeps_local_fallback(monkeypatch, kind, reply):
    monkeypatch.delenv(FLAGS[kind], raising=False)
    backend = LocalBackend([reply])
    router = SimpleNamespace(local_backend=backend)
    assert await invoke(kind, router)
    assert [call["model"] for call in backend.calls] == ["local"]


@pytest.mark.parametrize("kind,reply", [("capability", CAPABILITY), ("draft", DRAFT)])
async def test_printable_unicode_and_next_operation_read_current_override(monkeypatch, kind, reply):
    router, backend = local_router([reply, reply])
    monkeypatch.setenv(FLAGS[kind], " local-模型 ")
    await invoke(kind, router)
    monkeypatch.setenv(FLAGS[kind], "second-model")
    await invoke(kind, router)
    assert [call["model"] for call in backend.calls] == ["local-模型", "second-model"]


@pytest.mark.parametrize("kind", FLAGS)
@pytest.mark.parametrize("bad", ["bad\nmodel", "bad\u200bmodel", "x" * 257])
async def test_invalid_override_refuses_without_model_io_or_echo(monkeypatch, kind, bad):
    router, backend = local_router([CAPABILITY, DRAFT])
    monkeypatch.setenv(FLAGS[kind], bad)
    with pytest.raises(AuxiliaryConfigError) as exc:
        await invoke(kind, router)
    assert bad not in str(exc.value)
    assert backend.calls == []


@pytest.mark.parametrize("kind", FLAGS)
def test_resolver_rejects_non_string_override(kind):
    with pytest.raises(AuxiliaryConfigError, match="invalid auxiliary model override"):
        resolve_auxiliary_model(f"acquisition_{kind}", "active", env={FLAGS[kind]: 7})


@pytest.mark.parametrize("kind,reply", [("capability", CAPABILITY), ("draft", DRAFT)])
async def test_json_retry_keeps_prepared_backend_and_model_but_next_operation_refreshes(
        monkeypatch, kind, reply):
    router, original = local_router(["not JSON", reply])
    replacement = LocalBackend([reply])
    monkeypatch.setenv(FLAGS[kind], "frozen-model")
    authorize_calls = []
    real_authorize = data_handling.authorize

    def record(*args, **kwargs):
        authorize_calls.append((args[1], args[2], kwargs["route"]))
        return real_authorize(*args, **kwargs)

    monkeypatch.setattr(data_handling, "authorize", record)
    real_generate = original.generate

    async def mutate_after_first(model, prompt, *, system, max_tokens, temperature):
        result = await real_generate(model, prompt, system=system,
                                     max_tokens=max_tokens, temperature=temperature)
        if len(original.calls) == 1:
            monkeypatch.setenv(FLAGS[kind], "replacement-model")
            router._backend = replacement
            router._detected_model = "replacement-active"
        return result

    original.generate = mutate_after_first
    assert await invoke(kind, router)
    assert [call["model"] for call in original.calls] == ["frozen-model", "frozen-model"]
    assert [call["temperature"] for call in original.calls] == [0.2, 0.0]
    assert replacement.calls == []
    assert authorize_calls == [(original, "frozen-model", f"acquisition_{kind}")] * 2

    assert await invoke(kind, router)
    assert [call["model"] for call in replacement.calls] == ["replacement-model"]


@pytest.mark.parametrize("router_cls", [LLMRouter, HybridRouter])
@pytest.mark.parametrize("kind,reply", [("capability", CAPABILITY), ("draft", DRAFT)])
async def test_acquisition_keeps_existing_ignored_job_pin_on_real_local_accessor(
        monkeypatch, router_cls, kind, reply):
    router = router_cls.__new__(router_cls)
    backend = LocalBackend([reply])
    router._backend = backend
    router._backend_name = "lm-studio"
    router._detected_model = "active-local"
    router._local_model = "active-local"
    monkeypatch.setenv(FLAGS[kind], "configured-local")
    with selection_scope({"model": "job-pinned", "provider": "ollama"}):
        assert await invoke(kind, router)
    assert [call["model"] for call in backend.calls] == ["configured-local"]


@pytest.mark.parametrize("task", ["session_title", "query_rewrite", "review", "compression"])
async def test_prepared_existing_producers_still_exclude_pin_at_invocation(task):
    router, backend = local_router(["answer"])
    generate = prepare_local_auxiliary(router, task)
    with selection_scope({"model": "job-pinned"}), pytest.raises(SelectionError):
        await generate(system="s", prompt="p", max_tokens=24, temperature=0)
    assert backend.calls == []


@pytest.mark.parametrize("kind", FLAGS)
async def test_cloud_only_router_fails_closed_before_generation(kind):
    class CloudOnly:
        active_model = "cloud-model"

        @property
        def local_backend(self):
            raise RuntimeError("no local backend")

        @property
        def backend(self):
            pytest.fail("cloud backend was selected")

    with pytest.raises(RuntimeError, match="no local backend"):
        await invoke(kind, CloudOnly())


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(data_handling, "_scope_key", lambda: b"synthetic-acquisition-scope-key")
    return data_handling


def acknowledge(policy, router, allowed):
    row = policy.posture(router)["providers"][0]
    class Audit:
        def log(self, _event):
            pass
    policy.acknowledge(router, row["provider"], allowed, row["scope"], Audit())


@pytest.mark.parametrize("kind,reply", [("capability", CAPABILITY), ("draft", DRAFT)])
async def test_revocation_after_first_physical_attempt_blocks_json_retry(
        policy, kind, reply):
    router, backend = local_router(["not JSON", reply])
    backend.base_url = "https://acquisition.invalid"
    acknowledge(policy, router, True)
    sent = []

    def transport(request):
        sent.append(request)
        acknowledge(policy, router, False)
        return httpx.Response(200)

    client = llm_async_client("lm-studio", transport=httpx.MockTransport(transport))
    original = backend.generate

    async def generate(model, prompt, *, system, max_tokens, temperature):
        await client.post(backend.base_url + "/first")
        return await original(model, prompt, system=system,
                              max_tokens=max_tokens, temperature=temperature)

    backend.generate = generate
    try:
        with pytest.raises(policy.DataHandlingRefused):
            await invoke(kind, router)
        assert len(sent) == len(backend.calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("kind", FLAGS)
async def test_swallowed_physical_retry_denial_still_fails_operation(policy, kind):
    router, backend = local_router([])
    backend.base_url = "https://acquisition.invalid"
    acknowledge(policy, router, True)
    sent = []

    def transport(request):
        sent.append(request)
        acknowledge(policy, router, False)
        return httpx.Response(503)

    client = llm_async_client("lm-studio", transport=httpx.MockTransport(transport))
    calls = []

    async def generate(model, prompt, *, system, max_tokens, temperature):
        calls.append(model)
        await client.post(backend.base_url + "/first")
        with suppress(policy.DataHandlingRefused):
            await client.post(backend.base_url + "/retry")
        return CAPABILITY if kind == "capability" else DRAFT

    backend.generate = generate
    try:
        with pytest.raises(policy.DataHandlingRefused):
            await invoke(kind, router)
        assert len(sent) == len(calls) == 1
    finally:
        await client.aclose()
