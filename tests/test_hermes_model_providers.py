"""Adopt lane, slice 2 — model providers Nerva runs from Hermes's vendored profiles.

No live network: every request goes to an ``httpx.MockTransport`` behind Nerva's own
ledgered model client (``egress.llm_async_client``) and the bridge's host pin.

Guide: docs/hermes/ADOPT_LANE.md ("Model providers").
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agents.core.llm import egress as llm_egress
from agents.core.llm import hermes_profiles as hp
from agents.core.llm.hermes_provider_table import (
    ADOPTED_MODEL_PROVIDER_IDS,
    ADOPTED_MODEL_PROVIDER_KEYS,
    ADOPTED_MODEL_PROVIDERS,
)
from agents.core.llm.provider_request import ProfileRequestRefused
from agents.core.llm.providers import BUILTIN_PROVIDER_IDS, DEFAULT_REGISTRY
from agents.core.llm.reasoning_effort import ReasoningEffortRefused

#: A representative model and effort per adopted provider (effort None: the model takes none).
CASES = {
    "ai-gateway": ("openai/gpt-5.5", "high"),
    "alibaba": ("qwen3.6-plus", None),
    "alibaba-cn": ("glm-5", None),
    "alibaba-token-plan": ("qwen3.6-plus", None),
    "alibaba-token-plan-cn": ("qwen3.6-plus", None),
    "alibaba-coding-plan": ("qwen3.7-coder", None),
    "alibaba-coding-plan-cn": ("kimi-k2.6", None),
    "arcee": ("trinity-large", None),
    "deepseek": ("deepseek-v4-pro", "high"),
    "commandcode": ("deepseek/deepseek-v4-flash", "medium"),
    "fireworks": ("accounts/fireworks/models/kimi-k2p6", "high"),
    "gmi": ("zai-org/GLM-5.1-FP8", None),
    "huggingface": ("Qwen/Qwen3.5-72B-Instruct", None),
    "kilocode": ("google/gemini-3.6-flash", None),
    "kimi-coding": ("kimi-k2.6", "high"),
    "kimi-coding-cn": ("k3", "max"),
    "nebius-token-factory": ("deepseek-ai/DeepSeek-V4-Pro", "low"),
    "novita": ("deepseek/deepseek-v3-0324", None),
    "nvidia": ("nvidia/llama-3.3-70b-instruct", None),
    "ollama-cloud": ("deepseek-v4-pro", "max"),
    "stepfun": ("step-3.5-flash", None),
    "upstage": ("solar-pro3", "medium"),
    "xiaomi": ("mimo-v2.5-pro", None),
    "zai": ("glm-5.2", "high"),
}
_BASE_BODY = {"model", "messages", "max_tokens", "temperature", "stream"}


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in ADOPTED_MODEL_PROVIDER_KEYS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def ledger(monkeypatch):
    rows: list[dict] = []

    def record(plugin, host, method, *, allowed, local, reason=""):
        rows.append({"plugin": plugin, "host": host, "allowed": allowed, "reason": reason})

    monkeypatch.setattr(llm_egress.EGRESS_MONITOR, "record", record)
    return rows


class Wire:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    def body(self) -> dict:
        return json.loads(self.requests[-1].content)


def _settings(effort: str | None, reasoning: bool = True):
    values = {"compatible_reasoning_enabled": reasoning, "reasoning_effort": effort or ""}
    return lambda name, default=None: values.get(name, default)


def _backend(provider_id, monkeypatch, wire, effort, reasoning=True):
    key_name = {row[0]: row[2] for row in ADOPTED_MODEL_PROVIDERS}[provider_id][0]
    monkeypatch.setenv(key_name, f"key-for-{provider_id}")
    return hp.build_backend(provider_id, settings=_settings(effort, reasoning), transport=wire.transport)


# ── the table and the registry ───────────────────────────────────────────────

def test_the_table_matches_the_vendored_profiles():
    for provider_id, _directory, keys, _display in ADOPTED_MODEL_PROVIDERS:
        upstream = hp.upstream_profile(provider_id)
        assert upstream.name == provider_id
        assert upstream.api_mode == "chat_completions" and upstream.auth_type == "api_key"
        assert keys == tuple(n for n in upstream.env_vars if not n.endswith("_BASE_URL")), provider_id
    assert set(CASES) == set(ADOPTED_MODEL_PROVIDER_IDS)


def test_adopted_providers_join_the_registry_beside_the_native_ones():
    ids = [p.id for p in DEFAULT_REGISTRY.list()]
    assert ids[:len(BUILTIN_PROVIDER_IDS)] == list(BUILTIN_PROVIDER_IDS)
    assert set(ADOPTED_MODEL_PROVIDER_IDS).isdisjoint(BUILTIN_PROVIDER_IDS)
    for provider_id in ADOPTED_MODEL_PROVIDER_IDS:
        profile = DEFAULT_REGISTRY.get(provider_id)
        assert hp.is_adopted_profile(profile)
        assert profile.backend_kind == "openai-compatible" and profile.api_mode == "chat_completions"
        assert profile.default_base_url == hp.upstream_profile(provider_id).base_url.rstrip("/")
        assert profile.data_policy == "unknown"
        assert profile.status(environ={})["configured"] is False


def test_each_provider_is_off_until_its_own_key_is_set(monkeypatch):
    assert hp.build_backend("zai", settings=_settings(None)) is None
    monkeypatch.setenv("DEEPSEEK_API_KEY", "a-deepseek-key")  # another provider's key
    assert hp.build_backend("zai", settings=_settings(None)) is None
    assert DEFAULT_REGISTRY.get("zai").auth_key() == ""
    monkeypatch.setenv("Z_AI_API_KEY", "the-zai-key")
    assert DEFAULT_REGISTRY.get("zai").auth_key() == "the-zai-key"
    assert hp.build_backend("zai", settings=_settings(None)) is not None


def test_keys_are_managed_and_selectable_in_settings():
    from agents.core import code_env, settings_db

    assert ADOPTED_MODEL_PROVIDER_KEYS <= code_env._MANAGED_NAMES
    row = next(r for r in settings_db.DEFAULTS if r["key"] == "compatible_provider")
    assert set(ADOPTED_MODEL_PROVIDER_IDS) <= set(row["opts"])


# ── the request Nerva sends equals what the Hermes profile asks for ──────────

@pytest.mark.parametrize("provider_id", sorted(CASES))
def test_the_request_matches_the_hermes_profile(provider_id, monkeypatch):
    model, effort = CASES[provider_id]
    wire = Wire()
    backend = _backend(provider_id, monkeypatch, wire, effort)
    assert asyncio.run(backend.generate(model, "hello")) == "ok"
    request = wire.requests[-1]
    upstream = hp.upstream_profile(provider_id)
    assert str(request.url) == upstream.base_url.rstrip("/") + "/chat/completions"
    assert request.headers["authorization"] == f"Bearer key-for-{provider_id}"
    config = {"enabled": True, "effort": effort} if effort else {"enabled": False}
    if effort:
        assert effort in hp.derived_efforts(provider_id, backend.profile.default_base_url, model)
    else:
        assert hp.derived_efforts(provider_id, backend.profile.default_base_url, model) == ()
    extra, top = upstream.build_api_kwargs_extras(
        reasoning_config=config, model=model, base_url=upstream.base_url, supports_reasoning=True)
    expected = {**upstream.build_extra_body(), **extra, **top}
    body = wire.body()
    assert {k: body[k] for k in set(body) - _BASE_BODY} == expected
    if upstream.fixed_temperature is not None:
        assert "temperature" not in body
    for value in request.headers.values():
        assert "hermes" not in value.lower()


def test_reasoning_off_is_sent_the_vendors_way(monkeypatch):
    wire = Wire()
    backend = _backend("deepseek", monkeypatch, wire, "none")
    asyncio.run(backend.generate("deepseek-v4-pro", "hi"))
    assert wire.body()["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in wire.body()


def test_no_effort_chosen_sends_no_reasoning_field(monkeypatch):
    # Hermes's Upstage profile turns reasoning on at "medium" when nothing is chosen;
    # in Nerva an unset effort stays unset.
    wire = Wire()
    backend = _backend("upstage", monkeypatch, wire, None)
    asyncio.run(backend.generate("solar-pro3", "hi"))
    assert "reasoning_effort" not in wire.body()
    wire = Wire()
    backend = _backend("deepseek", monkeypatch, wire, "high", reasoning=False)
    asyncio.run(backend.generate("deepseek-v4-pro", "hi"))
    assert not {"thinking", "reasoning_effort"} & set(wire.body())


def test_an_effort_between_levels_is_clamped_weaker_by_nerva_first(monkeypatch):
    wire = Wire()
    backend = _backend("ollama-cloud", monkeypatch, wire, "xhigh")  # Hermes would send "max"
    asyncio.run(backend.generate("deepseek-v4-pro", "hi"))
    assert wire.body()["reasoning_effort"] == "high"


def test_an_effort_below_the_vendors_floor_is_refused(monkeypatch):
    wire = Wire()
    backend = _backend("zai", monkeypatch, wire, "low")  # GLM-5.2 takes high and max only
    with pytest.raises(ReasoningEffortRefused):
        asyncio.run(backend.generate("glm-5.2", "hi"))
    assert wire.requests == []


def test_a_profile_that_cannot_turn_reasoning_off_is_refused(monkeypatch):
    wire = Wire()
    backend = _backend("zai", monkeypatch, wire, "none")  # GLM-5.3 answers "off" with "low"
    with pytest.raises(ProfileRequestRefused):
        asyncio.run(backend.generate("glm-5.3", "hi"))
    assert wire.requests == []


@pytest.mark.parametrize(("requested", "config", "ok"), [
    ({"thinking": {"type": "enabled"}, "reasoning_effort": "high"}, {"enabled": True, "effort": "high"}, True),
    ({"reasoning_effort": "medium"}, {"enabled": True, "effort": "high"}, True),
    ({"reasoning": {"enabled": True, "effort": "low"}}, {"enabled": True, "effort": "low"}, True),
    ({"thinking": {"type": "disabled"}}, {"enabled": False}, True),
    ({"reasoning_effort": "none"}, {"enabled": False}, True),
    ({"reasoning_effort": "max"}, {"enabled": True, "effort": "high"}, False),
    ({"reasoning": {"effort": "xhigh"}}, {"enabled": True, "effort": "high"}, False),
    ({"thinking": {"type": "enabled", "budget_tokens": 99999}}, {"enabled": True, "effort": "low"}, False),
    ({"thinking": {"type": "enabled"}}, {"enabled": False}, False),
    ({"reasoning_effort": "low"}, {"enabled": False}, False),
    ({"reasoning_effort": "low"}, None, False),
    ({"reasoning_effort": "none"}, {"enabled": True, "effort": "high"}, False),
])
def test_the_reasoning_check_only_lets_a_restatement_through(requested, config, ok):
    if ok:
        hp.check_reasoning(requested, config)
    else:
        with pytest.raises(ProfileRequestRefused):
            hp.check_reasoning(requested, config)


def test_attribution_headers_naming_hermes_are_dropped(monkeypatch):
    upstream = hp.upstream_profile("fireworks")
    assert "X-Title" in upstream.default_headers
    assert dict(DEFAULT_REGISTRY.get("fireworks").default_headers) == {}
    assert dict(DEFAULT_REGISTRY.get("kimi-coding").default_headers) == {}


# ── egress: the profile's host and nothing else ──────────────────────────────

@pytest.mark.parametrize("url", [
    "https://evil.example/v1/chat/completions",
    "https://192.168.1.10/v1/chat/completions",
    "https://127.0.0.1/v1/chat/completions",
    "http://api.z.ai/api/paas/v4/chat/completions",
    "https://api.z.ai:8443/api/paas/v4/chat/completions",
    "https://api.z.ai.attacker.test/api/paas/v4/chat/completions",
])
def test_any_other_destination_is_refused_before_the_transport(url, ledger):
    wire = Wire()
    client = hp.adopted_client(DEFAULT_REGISTRY.get("zai"), transport=wire.transport)

    async def go():
        async with client:
            await client.post(url, json={}, headers={"Authorization": "Bearer secret"})

    with pytest.raises(hp.AdoptedDestinationRefused):
        asyncio.run(go())
    assert wire.requests == []
    assert ledger and ledger[-1]["allowed"] is False and ledger[-1]["plugin"] == "llm:zai"
    assert "secret" not in json.dumps(ledger)


def test_the_profile_host_resolving_local_is_refused(monkeypatch, ledger):
    from agents.core import http_client

    monkeypatch.setattr(http_client, "host_is_local", lambda host: True)
    wire = Wire()
    client = hp.adopted_client(DEFAULT_REGISTRY.get("deepseek"), transport=wire.transport)

    async def go():
        async with client:
            await client.post("/chat/completions", json={})

    with pytest.raises(hp.AdoptedDestinationRefused):
        asyncio.run(go())
    assert wire.requests == []


def test_the_profile_host_is_sent_and_ledgered(monkeypatch, ledger):
    wire = Wire()
    backend = _backend("nvidia", monkeypatch, wire, None)
    asyncio.run(backend.generate("nvidia/llama-3.3-70b-instruct", "hi"))
    assert [r["host"] for r in ledger if r["allowed"]] == ["integrate.api.nvidia.com"]
    assert ledger[-1]["plugin"] == "llm:nvidia"


def test_a_backend_without_the_pin_or_on_another_base_is_refused(monkeypatch):
    from agents.core.llm.openrouter import OpenRouterBackend

    profile = DEFAULT_REGISTRY.get("zai")
    bare = llm_egress.llm_async_client("zai", base_url=profile.default_base_url)
    with pytest.raises(ValueError):
        OpenRouterBackend("k", base_url=profile.default_base_url, profile=profile, client=bare)
    with pytest.raises(ValueError):
        OpenRouterBackend("k", base_url="https://evil.example/v1", profile=profile)
    built = OpenRouterBackend("k", base_url=profile.default_base_url, profile=profile)
    assert getattr(built.client.event_hooks["request"][0], "_nerva_adopted_pin", None) == "zai"


def test_backend_factory_construction_gets_the_pin_too(monkeypatch):
    from agents.core.llm.backend_factory import construct_backend

    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    backend = construct_backend("nvidia", model="nvidia/llama-3.3-70b-instruct")
    assert getattr(backend.client.event_hooks["request"][0], "_nerva_adopted_pin", None) == "nvidia"


def test_vendored_profiles_open_no_connection():
    # ``fetch_models`` builds an inert request and the compat opener refuses it.
    assert hp.upstream_profile("kimi-coding").fetch_models(api_key="k") is None
    assert hp.upstream_profile("commandcode").fetch_models() is None
    from agents.vendor.hermes.providers import base
    from agents.vendor.hermes_compat import locks, urllib_refused

    assert base.threading is locks
    assert not hasattr(urllib_refused.request, "urlopen")


@pytest.mark.asyncio
async def test_the_router_puts_an_adopted_provider_on_the_compatible_slot(monkeypatch):
    from agents.core.llm.hybrid_router import HybridRouter
    from agents.core.llm.router import LLMRouter

    settings = {"compatible_provider": "deepseek", "compatible_model": "deepseek-v4-pro",
                "cloud_fallback": "on-demand"}
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "foreign-key")
    monkeypatch.setattr(LLMRouter, "detect", lambda *_: asyncio.sleep(0))
    monkeypatch.setattr(HybridRouter, "_check", lambda *_: asyncio.sleep(0, result=False))
    monkeypatch.setattr(HybridRouter, "_admin_setting",
                        staticmethod(lambda key, default: settings.get(key, default)))
    router = HybridRouter()
    await router.detect()
    try:
        backend, model, route = router.select_backend("jarvis", "Hello")
        assert (backend.profile.id, backend.api_key, backend.base_url, model, route) == (
            "deepseek", "deepseek-key", "https://api.deepseek.com/v1", "deepseek-v4-pro",
            "cloud-compatible")
        assert getattr(backend.client.event_hooks["request"][0], "_nerva_adopted_pin", None) == "deepseek"
    finally:
        await router.aclose()


@pytest.mark.asyncio
async def test_the_router_leaves_an_adopted_provider_off_without_its_key(monkeypatch):
    from agents.core.llm.hybrid_router import HybridRouter
    from agents.core.llm.router import LLMRouter

    settings = {"compatible_provider": "deepseek", "compatible_model": "deepseek-v4-pro"}
    monkeypatch.setenv("OPENROUTER_API_KEY", "foreign-key")
    monkeypatch.setattr(LLMRouter, "detect", lambda *_: asyncio.sleep(0))
    monkeypatch.setattr(HybridRouter, "_check", lambda *_: asyncio.sleep(0, result=False))
    monkeypatch.setattr(HybridRouter, "_admin_setting",
                        staticmethod(lambda key, default: settings.get(key, default)))
    router = HybridRouter()
    await router.detect()
    try:
        assert router._compatible_backend is None
    finally:
        await router.aclose()
