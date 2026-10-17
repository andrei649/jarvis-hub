"""Unit tests of ``agents.core.workspace.llm`` against a stub hub (spec §5, Appendix A).

The stub router and backends behave like the real ones in the ways that matter here:
backends never raise on failure but return (and stream) fixed degraded strings, they
call ``on_token`` through ``base._emit`` (so an ``async def`` callback is required),
and a backend's HTTP request passes the data-handling physical-request check. The
real router runs against a real model server in ``test_workspace_llm_integration``.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import agents.web as web
from agents.core.llm import base, data_handling
from agents.core.llm.base import THINKING_EXHAUSTED_REPLY
from agents.core.llm.data_handling import DataHandlingRefused
from agents.core.llm.hybrid_router import LocalBackendUnavailableError, ModelNotApprovedError
from agents.core.llm.job_selection import SelectionError
from agents.core.security.guardrails import GuardrailsEngine
from agents.core.security.types import RedactionMode
from agents.core.workspace import llm
from agents.core.workspace.errors import WorkspaceError, error_response
from tests.support.workspace_fixtures import FakeEngine, ws  # noqa: F401  (ws is a fixture)

UNREACHABLE = ("⚠️ I can't reach the local LM Studio model right now. Start LM Studio "
               "(http://127.0.0.1:1234) and try again — Jarvis runs local-first, so it needs "
               "a local model server running.")
LONG_ANSWER = ("Concediul de odihnă anual este de 21 de zile lucrătoare, conform politicii "
               "interne [1]. Cererea se depune cu cel puțin 10 zile înainte.")
LOCAL = {"provider": "lm-studio", "policy": "local", "warning": ""}


class StubBackend:
    """Streams *pieces* (default: *reply* word by word) the way real backends do."""

    def __init__(self, reply: str = LONG_ANSWER, *, pieces: list[str] | None = None,
                 delay: float = 0.0, error: BaseException | None = None,
                 sends_request: bool = False) -> None:
        self.reply = reply
        self.pieces = pieces if pieces is not None else [w + " " for w in reply.split(" ")]
        if pieces is None and self.pieces:
            self.pieces[-1] = self.pieces[-1].rstrip(" ")
        self.delay = delay
        self.error = error
        self.sends_request = sends_request
        self.calls: list[dict] = []

    async def generate_stream(self, model: str, prompt: str, system: str = "",
                              max_tokens: int = 1024, temperature: float = 0.7,
                              on_token: Any = None) -> str:
        self.calls.append({"model": model, "prompt": prompt, "system": system,
                           "max_tokens": max_tokens, "temperature": temperature,
                           "on_token": on_token})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        if self.sends_request:
            try:
                await data_handling.check_physical_request(
                    httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
            except Exception:
                # Like LMStudioBackend: the refusal becomes a degraded reply.
                if on_token:
                    await base._emit(on_token, UNREACHABLE)
                return UNREACHABLE
        for piece in self.pieces:
            if on_token:
                await base._emit(on_token, piece)
        return self.reply


class StubRouter:
    """The parts of ``HybridRouter`` the workspace uses, recording every call."""

    def __init__(self, backend: StubBackend | None = None, *, local: bool = True,
                 model: str = "local-model", selection: tuple | None = None,
                 select_error: BaseException | None = None, handling: dict | None = None,
                 handling_error: BaseException | None = None,
                 recheck_error: BaseException | None = None) -> None:
        self.backend = backend or StubBackend()
        self.local = local
        self.model = model
        self.selection = selection
        self.select_error = select_error
        self.handling = handling if handling is not None else dict(LOCAL)
        self.handling_error = handling_error
        self.recheck_error = recheck_error
        self.selected: list[tuple[str, str]] = []
        self.previewed: list[tuple[str, str]] = []
        self.checks: list[tuple] = []

    @property
    def local_backend(self) -> StubBackend:
        if not self.local:
            raise RuntimeError("No local LLM backend available (strict-local path).")
        return self.backend

    def get_model(self, agent_id: str) -> str:
        assert agent_id == "workspace"
        return self.model

    def _choose(self, log: list, agent_id: str, prompt: str) -> tuple:
        log.append((agent_id, prompt))
        if self.select_error is not None:
            raise self.select_error
        assert self.selection is not None, "the router chose a route it was not given"
        return self.selection

    def select_backend(self, agent_id: str, prompt: str) -> tuple:
        return self._choose(self.selected, agent_id, prompt)

    def preview_backend(self, agent_id: str, prompt: str) -> tuple:
        return self._choose(self.previewed, agent_id, prompt)

    def check_data_handling(self, backend: Any, model: str, route: str = "", *,
                            actual_use: bool = True) -> dict:
        self.checks.append((backend, model, route, actual_use))
        if route == "" and self.recheck_error is not None:
            raise self.recheck_error
        if self.handling_error is not None:
            raise self.handling_error
        return self.handling


@pytest.fixture
def hub(monkeypatch):
    """Install a stub orchestrator for ``get_orch()``; the real engine is used."""
    monkeypatch.delenv("NERVA_WORKSPACE_MAX_CONCURRENT_LLM", raising=False)
    llm.set_engine_for_tests(None)

    def install(router: StubRouter | None, security: Any = None) -> StubRouter | None:
        orch = None if router is None else SimpleNamespace(llm_router=router, security=security)
        monkeypatch.setattr(web, "orch", orch)
        return router

    yield install
    llm.set_engine_for_tests(None)


async def _complete(policy: str = "local_only", **kwargs: Any) -> llm.LLMResult:
    params = {"system": "Ești asistentul.", "prompt": "Câte zile de concediu?",
              "policy": policy, **kwargs}
    return await llm.complete(**params)


def _collector() -> tuple[list[str], Any]:
    tokens: list[str] = []

    async def on_token(text: str) -> None:
        tokens.append(text)

    return tokens, on_token


# ── errors and small helpers ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("error,code,status", [
    (llm.LLMUnavailable("no_local_model"), "model_unavailable", 503),
    (llm.ModelPolicyBlocked("provider_may_train"), "model_policy_blocked", 409),
    (llm.ModelBusy(), "model_busy", 503),
    (llm.ModelTimeout(), "model_timeout", 504),
    (llm.ModelTimeout(12.5), "model_timeout", 504),
    (llm.ContentBlocked(), "content_blocked", 422),
])
def test_error_classes_carry_their_code_and_status(error, code, status):
    assert isinstance(error, WorkspaceError)
    assert (error.code, error.status) == (code, status)
    body = error_response(error)
    assert body.status_code == status


def test_reasons_are_extras_and_busy_says_when_to_retry():
    assert llm.LLMUnavailable("no_local_model").extra == {"reason": "no_local_model"}
    assert llm.ModelPolicyBlocked("provider_may_train").extra == {"reason": "provider_may_train"}
    busy = error_response(llm.ModelBusy())
    assert busy.headers["Retry-After"] == str(llm.BUSY_RETRY_AFTER_SECONDS)


@pytest.mark.parametrize("policy,expected", [
    ("allow_cloud", "allow_cloud"), ("local_only", "local_only"), ("", "local_only"),
    (None, "local_only"), ("ALLOW_CLOUD", "local_only"),
])
def test_unknown_policies_fail_closed_to_local(policy, expected):
    assert llm.normalize_policy(policy) == expected


@pytest.mark.parametrize("data_policy,route,expected", [
    ("local", "local", "local"), ("unknown", "local", "unknown"),
    ("unknown", "ollama-howard", "unknown"), ("no-training", "claude", "cloud"),
    ("unknown", "cloud-flash", "cloud"), ("local", "cloud-compatible", "local"),
])
def test_locality_is_local_only_on_the_data_policys_word(data_policy, route, expected):
    assert llm.route_locality(data_policy, route) == expected


def test_set_engine_for_tests_none_restores_the_hub_engine():
    fake = FakeEngine()
    llm.set_engine_for_tests(fake)
    assert llm._engine() is fake
    llm.set_engine_for_tests(None)
    assert isinstance(llm._engine(), llm.HubEngine)


def test_the_fixture_engine_returns_this_modules_result_type(ws):
    result = asyncio.run(llm.complete(system="s", prompt="p", policy="local_only"))
    assert isinstance(result, llm.LLMResult)


def test_the_gate_feed_is_a_coroutine_function_as_base_emit_requires():
    gate = llm.TokenGate(lambda text: None)
    assert inspect.iscoroutinefunction(gate.feed)


# ── algorithm steps 1–2: hub and route ───────────────────────────────────────────────

async def test_no_orchestrator_means_hub_not_ready(hub):
    hub(None)
    with pytest.raises(llm.LLMUnavailable) as caught:
        await _complete()
    assert caught.value.extra["reason"] == "hub_not_ready"


async def test_an_orchestrator_without_a_router_is_not_ready(hub, monkeypatch):
    monkeypatch.setattr(web, "orch", SimpleNamespace(llm_router=None, security=None))
    with pytest.raises(llm.LLMUnavailable) as caught:
        await _complete()
    assert caught.value.extra["reason"] == "hub_not_ready"


async def test_local_only_uses_the_local_backend_and_never_selects(hub):
    router = hub(StubRouter(model="qwen-local"))
    tokens, on_token = _collector()
    result = await _complete(on_token=on_token, max_tokens=900, temperature=0.1)
    assert router.selected == [] and router.previewed == []
    assert (result.model, result.route, result.locality) == ("qwen-local", "local", "local")
    assert result.text == LONG_ANSWER
    assert "".join(tokens) == LONG_ANSWER
    call = router.backend.calls[0]
    assert call["model"] == "qwen-local" and call["system"] == "Ești asistentul."
    assert (call["max_tokens"], call["temperature"]) == (900, 0.1)
    assert router.checks[0] == (router.backend, "qwen-local", "local", True)


async def test_local_only_without_a_local_server_is_no_local_model(hub):
    router = hub(StubRouter(local=False, selection=("cloud", "gemini", "cloud-flash")))
    with pytest.raises(llm.LLMUnavailable) as caught:
        await _complete()
    assert caught.value.extra["reason"] == "no_local_model"
    assert router.selected == []


async def test_allow_cloud_lets_the_router_choose(hub):
    cloud = StubBackend("Răspuns din cloud, suficient de lung pentru a trece de pragul de 64.")
    router = hub(StubRouter(selection=(cloud, "claude-x", "claude"),
                            handling={"provider": "anthropic", "policy": "no-training"}))
    result = await _complete("allow_cloud")
    assert router.selected == [("workspace", "Câte zile de concediu?")]
    assert (result.model, result.route, result.locality) == ("claude-x", "claude", "cloud")
    assert cloud.calls and not router.backend.calls


@pytest.mark.parametrize("error,reason", [
    (RuntimeError("No LLM backend available"), "no_model"),
    (LocalBackendUnavailableError("explicit DeepInfra main route is unavailable"), "no_model"),
    (SelectionError("pin cannot be honored"), "no_model"),
    (ModelNotApprovedError("unapproved"), "model_not_approved"),
])
async def test_selection_failures_are_model_unavailable(hub, error, reason):
    hub(StubRouter(select_error=error))
    with pytest.raises(llm.LLMUnavailable) as caught:
        await _complete("allow_cloud")
    assert caught.value.extra["reason"] == reason


# ── step 3–4: data handling and locality ─────────────────────────────────────────────

@pytest.mark.parametrize("error", [DataHandlingRefused("unattended"),
                                   ValueError("routed backend provider is unknown")])
async def test_refused_or_unknown_data_handling_blocks(hub, error):
    router = hub(StubRouter(handling_error=error))
    with pytest.raises(llm.ModelPolicyBlocked) as caught:
        await _complete()
    assert caught.value.extra["reason"] == "data_policy_unacknowledged"
    assert router.backend.calls == []


@pytest.mark.parametrize("data_policy", ["unknown", "trains-on-inputs"])
async def test_allow_cloud_refuses_a_provider_that_may_train(hub, data_policy):
    cloud = StubBackend()
    hub(StubRouter(selection=(cloud, "gemini-2.5-flash", "cloud-flash"),
                   handling={"provider": "gemini", "policy": data_policy}))
    with pytest.raises(llm.ModelPolicyBlocked) as caught:
        await _complete("allow_cloud")
    assert caught.value.extra["reason"] == "provider_may_train"
    assert cloud.calls == []


async def test_local_only_accepts_an_acknowledged_remote_local_server_as_unknown(hub):
    hub(StubRouter(handling={"provider": "lm-studio", "policy": "unknown"}))
    result = await _complete()
    assert result.locality == "unknown"


# ── steps 5–6: guardrails, scope, deadline ───────────────────────────────────────────

async def test_guardrails_in_block_mode_turn_into_content_blocked(hub):
    router = hub(StubRouter(), security=GuardrailsEngine(mode=RedactionMode.BLOCK))
    with pytest.raises(llm.ContentBlocked):
        await _complete(prompt="Scrie-i Anei la ana.popescu@example.com")
    assert router.backend.calls == []


async def test_guardrails_in_warn_mode_stream_normally(hub):
    hub(StubRouter(), security=GuardrailsEngine(mode=RedactionMode.WARN))
    tokens, on_token = _collector()
    result = await _complete(on_token=on_token)
    assert result.text == LONG_ANSWER and "".join(tokens) == LONG_ANSWER


async def test_guardrails_in_redact_mode_deliver_the_answer_in_one_piece(hub):
    hub(StubRouter(), security=GuardrailsEngine(mode=RedactionMode.REDACT))
    tokens, on_token = _collector()
    await _complete(on_token=on_token)
    assert tokens == [LONG_ANSWER]


async def test_a_refusal_inside_the_physical_scope_is_re_raised(hub):
    router = hub(StubRouter(backend=StubBackend(sends_request=True),
                            recheck_error=DataHandlingRefused("consent revoked")))
    tokens, on_token = _collector()
    with pytest.raises(llm.ModelPolicyBlocked) as caught:
        await _complete(on_token=on_token)
    assert caught.value.extra["reason"] == "data_policy_unacknowledged"
    assert tokens == []
    assert router.checks[-1] == (router.backend, "local-model", "", True)


async def test_the_answer_deadline_is_model_timeout(hub):
    hub(StubRouter(backend=StubBackend(delay=1.0)))
    with pytest.raises(llm.ModelTimeout) as caught:
        await _complete(timeout_seconds=0.05)
    assert caught.value.status == 504


@pytest.mark.parametrize("error,reason", [
    (RuntimeError("guardrails policy is not bound"), "backend_error"),
    (ModelNotApprovedError("unapproved"), "model_not_approved"),
])
async def test_backend_exceptions_are_model_unavailable(hub, error, reason):
    hub(StubRouter(backend=StubBackend(error=error)))
    with pytest.raises(llm.LLMUnavailable) as caught:
        await _complete()
    assert caught.value.extra["reason"] == reason


# ── steps 7–8: failure replies and the hold-back ─────────────────────────────────────

async def test_a_degraded_reply_is_model_error_and_is_never_streamed(hub):
    hub(StubRouter(backend=StubBackend(UNREACHABLE)))
    tokens, on_token = _collector()
    with pytest.raises(llm.LLMUnavailable) as caught:
        await _complete(on_token=on_token)
    assert caught.value.extra["reason"] == "model_error"
    assert caught.value.extra["model"] == "local-model"
    assert tokens == []


async def test_a_degraded_reply_sent_in_one_piece_is_not_streamed_either(hub):
    hub(StubRouter(backend=StubBackend(UNREACHABLE, pieces=[UNREACHABLE])))
    tokens, on_token = _collector()
    with pytest.raises(llm.LLMUnavailable):
        await _complete(on_token=on_token)
    assert tokens == []


async def test_a_failure_after_a_partial_answer_is_not_streamed(hub):
    pieces = [LONG_ANSWER[:70], LONG_ANSWER[70:90], UNREACHABLE]
    hub(StubRouter(backend=StubBackend(UNREACHABLE, pieces=pieces)))
    tokens, on_token = _collector()
    with pytest.raises(llm.LLMUnavailable):
        await _complete(on_token=on_token)
    assert "".join(tokens) == LONG_ANSWER[:90]
    assert all("⚠️" not in token for token in tokens)


async def test_thinking_exhausted_has_its_own_reason(hub):
    hub(StubRouter(backend=StubBackend(THINKING_EXHAUSTED_REPLY)))
    with pytest.raises(llm.LLMUnavailable) as caught:
        await _complete()
    assert caught.value.extra["reason"] == "thinking_exhausted"


@pytest.mark.parametrize("reply", ["", "   \n "])
async def test_an_empty_answer_is_model_unavailable(hub, reply):
    hub(StubRouter(backend=StubBackend(reply, pieces=[reply])))
    tokens, on_token = _collector()
    with pytest.raises(llm.LLMUnavailable) as caught:
        await _complete(on_token=on_token)
    assert caught.value.extra["reason"] == "empty_answer"
    assert tokens == []


async def test_a_short_answer_is_held_until_the_end(hub):
    hub(StubRouter(backend=StubBackend("Da, 21 de zile [1].")))
    tokens, on_token = _collector()
    await _complete(on_token=on_token)
    assert tokens == ["Da, 21 de zile [1]."]


async def test_a_long_answer_is_released_after_sixty_four_characters(hub):
    hub(StubRouter())
    tokens, on_token = _collector()
    await _complete(on_token=on_token)
    assert len(tokens[0]) >= llm.HOLD_BACK_CHARS
    assert len(tokens) > 2
    assert "".join(tokens) == LONG_ANSWER


async def test_a_plain_function_works_as_the_sink(hub):
    hub(StubRouter())
    tokens: list[str] = []
    await _complete(on_token=tokens.append)
    assert "".join(tokens) == LONG_ANSWER


async def test_latency_is_measured_around_the_generation(hub):
    hub(StubRouter(backend=StubBackend(delay=0.05)))
    result = await _complete()
    assert result.latency_ms >= 40


# ── the concurrency limit ────────────────────────────────────────────────────────────

async def test_a_call_waiting_past_the_acquire_window_is_model_busy(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_MAX_CONCURRENT_LLM", "1")
    monkeypatch.setattr(llm, "ACQUIRE_TIMEOUT_SECONDS", 0.05)
    ws.use_engine(FakeEngine(delay=0.3))
    first = asyncio.create_task(llm.complete(system="s", prompt="p", policy="local_only"))
    await asyncio.sleep(0.02)
    with pytest.raises(llm.ModelBusy):
        await llm.complete(system="s", prompt="p", policy="local_only")
    assert isinstance(await first, llm.LLMResult)
    await llm.complete(system="s", prompt="p", policy="local_only")  # the slot came back


async def test_two_slots_admit_two_calls_at_once(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_MAX_CONCURRENT_LLM", "2")
    monkeypatch.setattr(llm, "ACQUIRE_TIMEOUT_SECONDS", 0.05)
    ws.use_engine(FakeEngine(delay=0.15))
    results = await asyncio.gather(*(llm.complete(system="s", prompt="p", policy="local_only")
                                     for _ in range(2)))
    assert len(results) == 2


async def test_a_failed_or_cancelled_call_gives_its_slot_back(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_MAX_CONCURRENT_LLM", "1")
    monkeypatch.setattr(llm, "ACQUIRE_TIMEOUT_SECONDS", 0.05)
    ws.use_engine(FakeEngine(fail=llm.LLMUnavailable("no_local_model")))
    with pytest.raises(llm.LLMUnavailable):
        await llm.complete(system="s", prompt="p", policy="local_only")
    ws.use_engine(FakeEngine(delay=5))
    task = asyncio.create_task(llm.complete(system="s", prompt="p", policy="local_only"))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    ws.use_engine(FakeEngine())
    assert isinstance(await llm.complete(system="s", prompt="p", policy="local_only"),
                      llm.LLMResult)


async def test_the_engine_sees_the_normalized_policy_and_the_gate(ws):
    engine = ws.use_engine(FakeEngine())
    tokens, on_token = _collector()
    await llm.complete(system="s", prompt="p", policy="anything", on_token=on_token,
                       timeout_seconds=12)
    call = engine.calls[0]
    assert call["policy"] == "local_only" and call["streamed"] is True
    assert call["timeout_seconds"] == 12


# ── posture ──────────────────────────────────────────────────────────────────────────

async def test_posture_without_a_hub_is_hub_not_ready(hub):
    hub(None)
    posture = await llm.posture("local_only")
    assert posture == {"available": False, "backend": "", "model": "", "route": "",
                       "locality": "unknown", "policy": "local_only",
                       "reason": "hub_not_ready", "guardrails_mode": "off"}


async def test_posture_of_a_local_model_reads_the_guardrails_mode(hub):
    router = hub(StubRouter(model="qwen-local"),
                 security=GuardrailsEngine(mode=RedactionMode.REDACT))
    posture = await llm.posture("local_only")
    assert posture == {"available": True, "backend": "lm-studio", "model": "qwen-local",
                       "route": "local", "locality": "local", "policy": "local_only",
                       "reason": "", "guardrails_mode": "redact"}
    assert router.checks == [(router.backend, "qwen-local", "local", False)]
    assert router.backend.calls == []


async def test_posture_without_a_local_server(hub):
    hub(StubRouter(local=False))
    posture = await llm.posture("local_only")
    assert (posture["available"], posture["reason"]) == (False, "no_local_model")


async def test_posture_under_allow_cloud_previews_without_dispatching(hub):
    cloud = StubBackend()
    router = hub(StubRouter(selection=(cloud, "gemini-2.5-flash", "cloud-flash"),
                            handling_error=DataHandlingRefused("unattended")))
    posture = await llm.posture("allow_cloud")
    assert router.previewed == [("workspace", "x")] and router.selected == []
    assert posture["available"] is False
    assert posture["reason"] == "data_policy_unacknowledged"
    assert (posture["route"], posture["locality"]) == ("cloud-flash", "cloud")


async def test_posture_flags_a_provider_that_may_train(hub):
    hub(StubRouter(selection=(StubBackend(), "gemini", "cloud-flash"),
                   handling={"provider": "gemini", "policy": "unknown"}))
    posture = await llm.posture("allow_cloud")
    assert (posture["available"], posture["reason"]) == (False, "provider_may_train")


async def test_posture_survives_an_unreadable_guardrails_engine(hub):
    class Broken:
        def stats(self) -> dict:
            raise RuntimeError("counters gone")

        def bind(self, backend: Any) -> Any:
            return backend

    hub(StubRouter(), security=Broken())
    assert (await llm.posture("local_only"))["guardrails_mode"] == "unknown"


async def test_posture_delegates_to_an_installed_engine(ws):
    engine = ws.use_engine(FakeEngine(model="m1"))
    posture = await llm.posture("allow_cloud")
    assert engine.posture_calls == ["allow_cloud"]
    assert posture["model"] == "m1" and posture["available"] is True
