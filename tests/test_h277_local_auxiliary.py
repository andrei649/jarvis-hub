"""H277: task-specific local models through actual auxiliary producers."""

import asyncio
from contextlib import suppress
from types import SimpleNamespace

import httpx
import pytest

from agents.core.llm import data_handling
from agents.core.llm.auxiliary_text import AuxiliaryConfigError, resolve_auxiliary_model
from agents.core.llm.egress import llm_async_client
from agents.core.llm.job_selection import SelectionError, selection_scope
from agents.core.llm.model_config import DEFAULT_LOCAL_MODEL
from agents.core.llm.providers import get_profile
from agents.core.orchestrator import Orchestrator

TASKS = {
    "session_title": "JARVIS_AUX_SESSION_TITLE_MODEL",
    "query_rewrite": "JARVIS_AUX_QUERY_REWRITE_MODEL",
    "review": "JARVIS_AUX_REVIEW_MODEL",
    "compression": "JARVIS_AUX_COMPRESSION_MODEL",
}


@pytest.fixture
def producer(monkeypatch):
    for name in TASKS.values():
        monkeypatch.delenv(name, raising=False)
    calls = []

    async def generate(**kwargs):
        calls.append(("generate", kwargs))
        return "local answer"

    async def generate_stream(**kwargs):
        calls.append(("stream", kwargs))
        await kwargs["on_token"]("local answer")
        return "local answer"

    backend = SimpleNamespace(
        profile=get_profile("lm-studio"), base_url="http://127.0.0.1:1234",
        generate=generate, generate_stream=generate_stream,
    )
    router = SimpleNamespace(local_backend=backend, active_model="active-local",
                             _backend=backend, _local_model="active-local")
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    orch.get_setting = lambda _key, default=None: default

    async def invoke(task):
        if task == "session_title":
            return await orch._session_titler()(system="title system", prompt="private prompt")
        if task == "query_rewrite":
            return await orch._query_rewriter()(system="rewrite system", prompt="private prompt")
        if task == "review":
            return await orch._review_llm("private prompt")
        return await orch._compression_summarizer()("private prompt")

    return SimpleNamespace(orch=orch, router=router, backend=backend,
                           calls=calls, invoke=invoke)


@pytest.mark.parametrize("task", TASKS)
async def test_each_producer_uses_its_own_model_without_changing_active(producer, monkeypatch, task):
    for other, name in TASKS.items():
        monkeypatch.setenv(name, f"configured-{other}")
    assert await producer.invoke(task) == "local answer"
    assert producer.calls[0][1]["model"] == f"configured-{task}"
    assert producer.router.active_model == "active-local"
    assert producer.calls[0][0] == ("stream" if task == "compression" else "generate")


async def test_unset_title_model_never_inherits_a_large_active_chat_model(producer):
    producer.router.active_model = "large-chat-70b"
    assert await producer.invoke("session_title") == "local answer"
    assert producer.calls == [("generate", {
        "model": DEFAULT_LOCAL_MODEL, "system": "title system",
        "prompt": "private prompt\n/no_think", "max_tokens": 24, "temperature": 0,
    })]
    assert producer.router.active_model == "large-chat-70b"


async def test_default_title_does_not_read_the_active_chat_model(producer):
    class Router:
        local_backend = producer.backend
        _backend = producer.backend

        @property
        def active_model(self):
            pytest.fail("a default title must not inspect the active chat model")

    producer.orch.llm_router = Router()
    assert await producer.invoke("session_title") == "local answer"
    assert producer.calls[-1][1]["model"] == DEFAULT_LOCAL_MODEL


def test_title_override_is_deliberate_while_other_tasks_keep_active_fallback():
    env = {TASKS["session_title"]: ""}
    assert resolve_auxiliary_model("session_title", "large-chat-70b", env=env) == DEFAULT_LOCAL_MODEL
    assert resolve_auxiliary_model("session_title", "large-chat-70b",
                                   env={TASKS["session_title"]: "owner-title-model"}) == "owner-title-model"
    for task in TASKS.keys() - {"session_title"}:
        assert resolve_auxiliary_model(task, "large-chat-70b", env={}) == "large-chat-70b"


@pytest.mark.parametrize("task", TASKS)
async def test_unset_and_space_only_use_each_tasks_default_selection(producer, monkeypatch, task):
    assert await producer.invoke(task) == "local answer"
    assert producer.calls[-1][1]["model"] == (DEFAULT_LOCAL_MODEL if task == "session_title" else "active-local")
    monkeypatch.setenv(TASKS[task], "   ")
    producer.router.active_model = None
    await producer.invoke(task)
    expected = "google/gemma-4-31b-a4b" if task == "review" else DEFAULT_LOCAL_MODEL
    assert producer.calls[-1][1]["model"] == expected


@pytest.mark.parametrize("task", TASKS)
async def test_override_is_read_for_each_invocation(producer, monkeypatch, task):
    generate = (producer.orch._session_titler() if task == "session_title" else
                producer.orch._query_rewriter() if task == "query_rewrite" else None)
    async def invoke():
        return await (generate(system="s", prompt="p") if generate else producer.invoke(task))

    monkeypatch.setenv(TASKS[task], "first-model")
    await invoke()
    monkeypatch.setenv(TASKS[task], "second-model")
    await invoke()
    assert [call[1]["model"] for call in producer.calls] == ["first-model", "second-model"]


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("bad", ["bad\nmodel", "bad\u200bmodel", "x" * 257])
async def test_invalid_override_is_sanitized_and_never_dispatches(producer, monkeypatch, task, bad):
    monkeypatch.setenv(TASKS[task], bad)
    with pytest.raises(AuxiliaryConfigError) as exc:
        await producer.invoke(task)
    assert bad not in str(exc.value)
    assert producer.calls == []


@pytest.mark.parametrize("bad", [None, 5, b"model", ["model"]])
def test_resolver_rejects_invalid_mapping_types_without_echoing(bad):
    with pytest.raises(AuxiliaryConfigError, match="invalid auxiliary model override") as exc:
        resolve_auxiliary_model("review", "active", env={TASKS["review"]: bad})
    assert repr(bad) not in str(exc.value)


@pytest.mark.parametrize("task", ["unknown", 8, None])
def test_resolver_refuses_unknown_tasks(task):
    with pytest.raises(AuxiliaryConfigError, match="unknown auxiliary task"):
        resolve_auxiliary_model(task, "active", env={})


def test_resolver_trims_ascii_spaces_only_and_preserves_opaque_model_id():
    assert resolve_auxiliary_model("review", "active", env={TASKS["review"]: ""}) == "active"
    assert resolve_auxiliary_model("review", None, env={TASKS["review"]: "  named / model:7!  "}) == "named / model:7!"
    assert resolve_auxiliary_model("review", None, env={TASKS["review"]: " local-模型 "}) == "local-模型"
    assert resolve_auxiliary_model("review", "active", env={TASKS["review"]: "x" * 256}) == "x" * 256


@pytest.mark.parametrize("bad", ["bad\x00model", "bad\ud800model", "bad\u00a0model"])
def test_resolver_refuses_nonprintable_model_id(bad):
    with pytest.raises(AuxiliaryConfigError, match="invalid auxiliary model override"):
        resolve_auxiliary_model("review", "active", env={TASKS["review"]: bad})


@pytest.mark.parametrize("task", TASKS)
async def test_printable_unicode_override_reaches_real_producer(producer, monkeypatch, task):
    monkeypatch.setenv(TASKS[task], "local-模型")
    await producer.invoke(task)
    assert producer.calls[-1][1]["model"] == "local-模型"


@pytest.mark.parametrize("task", TASKS)
async def test_job_pin_is_rejected_before_backend_or_model_lookup(producer, monkeypatch, task):
    class NoBackend:
        active_model = "active"
        @property
        def local_backend(self):
            pytest.fail("job pin selected a backend")

    producer.orch.llm_router = NoBackend()
    monkeypatch.setenv(TASKS[task], "bad\nmodel")
    with selection_scope({"model": "pinned"}), pytest.raises(SelectionError):
        await producer.invoke(task)


@pytest.mark.parametrize("task", TASKS)
async def test_cloud_only_router_never_generates(producer, task):
    class CloudOnly:
        active_model = "cloud-model"

        @property
        def local_backend(self):
            raise RuntimeError("no local backend")

        @property
        def backend(self):
            pytest.fail("auxiliary generation tried the cloud backend")

    producer.orch.llm_router = CloudOnly()
    with pytest.raises(RuntimeError, match="no local backend"):
        await producer.invoke(task)
    assert producer.calls == []


@pytest.mark.parametrize("task", TASKS)
async def test_qwen_suffix_depends_on_selected_model_and_task(producer, monkeypatch, task):
    monkeypatch.setenv(TASKS[task], "Qwen3-selected")
    await producer.invoke(task)
    assert producer.calls[-1][1]["prompt"].endswith("\n/no_think") is (task in {"session_title", "query_rewrite"})
    monkeypatch.setenv(TASKS[task], "other-selected")
    producer.router.active_model = "qwen3-active"
    await producer.invoke(task)
    assert producer.calls[-1][1]["prompt"].endswith("\n/no_think") is False


async def test_concurrent_tasks_capture_independent_models_and_physical_guards(producer, monkeypatch):
    for task, name in TASKS.items():
        monkeypatch.setenv(name, f"parallel-{task}")
    arrived = asyncio.Event()
    release = asyncio.Event()
    entered = []
    seen = []
    original = data_handling.authorize

    def record(*args, **kwargs):
        seen.append((args[2], kwargs["route"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(data_handling, "authorize", record)
    sent = []
    client = llm_async_client("lm-studio", transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200)))

    async def generate(**kwargs):
        entered.append(kwargs["model"])
        if len(entered) == 2:
            arrived.set()
        await release.wait()
        await client.post("http://127.0.0.1:1234/send")
        return "local answer"

    producer.backend.generate = generate
    try:
        tasks = [asyncio.create_task(producer.invoke(task)) for task in ("session_title", "review")]
        await arrived.wait()
        assert set(entered) == {"parallel-session_title", "parallel-review"}
        release.set()
        assert await asyncio.gather(*tasks) == ["local answer", "local answer"]
        assert len(sent) == 2
        assert {(model, role) for model, role in seen} == {
            ("parallel-session_title", "session_title"), ("parallel-review", "review")}
        assert len(seen) == 4  # each preflight and physical send
    finally:
        await client.aclose()


async def test_policy_change_before_actual_send_refuses_request(producer, monkeypatch):
    monkeypatch.setenv(TASKS["review"], "review-specific")
    sent = []
    client = llm_async_client("lm-studio", transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200)))

    async def generate(**kwargs):
        assert kwargs["model"] == "review-specific"
        producer.backend.base_url = "https://changed.invalid"
        await client.post("http://127.0.0.1:1234/send")
        return "local answer"

    producer.backend.generate = generate
    try:
        with pytest.raises(data_handling.DataHandlingRefused):
            await producer.invoke("review")
        assert sent == []
    finally:
        await client.aclose()


async def test_compression_child_cannot_send_after_cancelled_scope(producer, monkeypatch):
    monkeypatch.setenv(TASKS["compression"], "compression-specific")
    started = asyncio.Event()
    release = asyncio.Event()
    late = None
    sent = []
    client = llm_async_client("lm-studio", transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200)))

    async def stream(**kwargs):
        nonlocal late
        async def send_late():
            await release.wait()
            await client.post("http://127.0.0.1:1234/late")
        late = asyncio.create_task(send_late())
        started.set()
        await asyncio.Event().wait()

    producer.backend.generate_stream = stream
    try:
        outer = asyncio.create_task(producer.invoke("compression"))
        await started.wait()
        outer.cancel()
        with suppress(asyncio.CancelledError):
            await outer
        release.set()
        with pytest.raises(data_handling.DataHandlingRefused, match="scope is closed"):
            await late
        assert sent == []
    finally:
        await client.aclose()
