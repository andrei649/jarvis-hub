"""DeepInfra vision role and private, bounded catalog discovery."""

import asyncio

import httpx
import pytest

from agents.core.llm import vision_deepinfra
from agents.core.llm.vlm import VLMNotConfigured


def _env(**changes):
    return {
        "JARVIS_ROLE_VISION_PROVIDER": "deepinfra",
        "DEEPINFRA_API_KEY": "ambient-a",
        **changes,
    }


def _catalog(*items):
    return httpx.Response(200, json={"data": list(items)})


def _item(model, tags, metadata=True):
    return {"id": model, "metadata": {"tags": tags} if metadata else None}


def _transport(monkeypatch, handler):
    monkeypatch.setattr(vision_deepinfra, "_metadata_transport_factory",
                        lambda: httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _fresh_catalog_cache():
    vision_deepinfra.clear_cache()
    yield
    vision_deepinfra.clear_cache()


def test_explicit_model_is_pure_and_scoped(monkeypatch):
    _transport(monkeypatch, lambda request: pytest.fail("explicit model did network I/O"))
    env = _env(JARVIS_ROLE_VISION_MODEL="team/vision")
    config = vision_deepinfra.resolve_config(env)
    assert (config.backend, config.base_url, config.model, config.api_key, config.is_local) == (
        "deepinfra", "https://api.deepinfra.com/v1/openai", "team/vision", "ambient-a", False)
    assert vision_deepinfra.model_source(env) == "JARVIS_ROLE_VISION_MODEL"


@pytest.mark.asyncio
async def test_catalog_first_served_chat_vision_with_surface_and_legacy_filter(monkeypatch):
    seen = []

    def respond(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        return _catalog(
            _item("image-gen/first", ["image-gen", "vision"]),
            _item("embed/second", ["vision"]),
            _item("listed/stub", ["chat", "vision"], metadata=False),
            _item("chat/no-vision", ["chat"]),
            _item("org/first-vision", ["reasoning", "vision"]),
            _item("org/second-vision", ["chat", "vision"]),
        )

    _transport(monkeypatch, respond)
    env = _env(DEEPINFRA_API_KEY="catalog-secret-one")
    with pytest.raises(VLMNotConfigured):
        vision_deepinfra.resolve_config(env)
    config = await vision_deepinfra.prepare_config(env)
    assert config.model == "org/first-vision"
    assert vision_deepinfra.resolve_config(env).model == "org/first-vision"
    assert vision_deepinfra.model_source(env) == "deepinfra_catalog"
    assert seen == [("https://api.deepinfra.com/v1/openai/models?filter=true&sort_by=hermes",
                     "Bearer catalog-secret-one")]


@pytest.mark.asyncio
async def test_scoped_positive_cache_rotation_and_forced_refresh(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request.headers["authorization"])
        return _catalog(_item(f"org/model-{len(calls)}", ["chat", "vision"]))

    _transport(monkeypatch, respond)
    env = _env(DEEPINFRA_API_KEY="cache-key-one")
    assert (await vision_deepinfra.prepare_config(env)).model == "org/model-1"
    assert (await vision_deepinfra.prepare_config(env)).model == "org/model-1"
    assert (await vision_deepinfra.prepare_config(env, force_refresh=True)).model == "org/model-2"
    env["DEEPINFRA_API_KEY"] = "cache-key-two"
    with pytest.raises(VLMNotConfigured):
        vision_deepinfra.resolve_config(env)
    assert (await vision_deepinfra.prepare_config(env)).model == "org/model-3"
    assert calls == ["Bearer cache-key-one", "Bearer cache-key-one", "Bearer cache-key-two"]


@pytest.mark.asyncio
async def test_failed_forced_refresh_revokes_old_selection(monkeypatch):
    responses = [
        _catalog(_item("org/old-model", ["chat", "vision"])),
        httpx.Response(503, content=b"private server error"),
    ]
    _transport(monkeypatch, lambda request: responses.pop(0))
    env = _env(DEEPINFRA_API_KEY="refresh-key")
    assert (await vision_deepinfra.prepare_config(env)).model == "org/old-model"
    with pytest.raises(VLMNotConfigured):
        await vision_deepinfra.prepare_config(env, force_refresh=True)
    with pytest.raises(VLMNotConfigured) as refused:
        vision_deepinfra.resolve_config(env)
    assert refused.value.reason == "vlm_model_unset"


@pytest.mark.asyncio
async def test_older_inflight_fetch_cannot_replace_successful_refresh(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = [0]

    async def respond(request):
        calls[0] += 1
        if calls[0] == 1:
            entered.set()
            await release.wait()
            return _catalog(_item("org/stale", ["chat", "vision"]))
        return _catalog(_item("org/current", ["chat", "vision"]))

    _transport(monkeypatch, respond)
    env = _env(DEEPINFRA_API_KEY="race-refresh-success")
    old = asyncio.create_task(vision_deepinfra.prepare_config(env))
    await asyncio.wait_for(entered.wait(), 1)
    assert (await vision_deepinfra.prepare_config(env, force_refresh=True)).model == "org/current"
    release.set()
    with pytest.raises(VLMNotConfigured):
        await old
    assert vision_deepinfra.resolve_config(env).model == "org/current"


@pytest.mark.asyncio
async def test_older_inflight_fetch_cannot_replace_failed_refresh(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = [0]

    async def respond(request):
        calls[0] += 1
        if calls[0] == 1:
            entered.set()
            await release.wait()
            return _catalog(_item("org/stale", ["chat", "vision"]))
        return httpx.Response(503)

    _transport(monkeypatch, respond)
    env = _env(DEEPINFRA_API_KEY="race-refresh-failure")
    old = asyncio.create_task(vision_deepinfra.prepare_config(env))
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(VLMNotConfigured):
        await vision_deepinfra.prepare_config(env, force_refresh=True)
    release.set()
    with pytest.raises(VLMNotConfigured):
        await old
    with pytest.raises(VLMNotConfigured):
        vision_deepinfra.resolve_config(env)


@pytest.mark.asyncio
async def test_clear_cache_revokes_inflight_fetch(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def respond(request):
        entered.set()
        await release.wait()
        return _catalog(_item("org/stale", ["chat", "vision"]))

    _transport(monkeypatch, respond)
    env = _env(DEEPINFRA_API_KEY="race-clear")
    old = asyncio.create_task(vision_deepinfra.prepare_config(env))
    await asyncio.wait_for(entered.wait(), 1)
    vision_deepinfra.clear_cache()
    release.set()
    with pytest.raises(VLMNotConfigured):
        await old
    with pytest.raises(VLMNotConfigured):
        vision_deepinfra.resolve_config(env)


@pytest.mark.asyncio
async def test_pure_resolve_during_fetch_does_not_revoke_its_selection(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def respond(request):
        entered.set()
        await release.wait()
        return _catalog(_item("org/ready", ["chat", "vision"]))

    _transport(monkeypatch, respond)
    env = _env(DEEPINFRA_API_KEY="pending-pure-read")
    pending = asyncio.create_task(vision_deepinfra.prepare_config(env))
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(VLMNotConfigured) as refused:
        vision_deepinfra.resolve_config(env)
    assert refused.value.reason == "vlm_model_unset"
    release.set()
    assert (await pending).model == "org/ready"
    assert vision_deepinfra.resolve_config(env).model == "org/ready"


@pytest.mark.asyncio
async def test_catalog_cache_evicts_oldest_scope_at_32(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request.headers["authorization"])
        return _catalog(_item("org/ready", ["chat", "vision"]))

    _transport(monkeypatch, respond)
    for number in range(33):
        env = _env(DEEPINFRA_API_KEY=f"bounded-key-{number}")
        assert (await vision_deepinfra.prepare_config(env)).model == "org/ready"
    assert len(vision_deepinfra._cache) == 32
    await vision_deepinfra.prepare_config(_env(DEEPINFRA_API_KEY="bounded-key-0"))
    assert len(calls) == 34


@pytest.mark.asyncio
async def test_metadata_total_deadline_cancels_hanging_transport(monkeypatch):
    cancelled = []

    async def never_returns(request):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    _transport(monkeypatch, never_returns)
    monkeypatch.setattr(vision_deepinfra, "_METADATA_DEADLINE", 0.01, raising=False)
    with pytest.raises(VLMNotConfigured):
        await asyncio.wait_for(vision_deepinfra.prepare_config(
            _env(DEEPINFRA_API_KEY="deadline-key")), 0.3)
    assert cancelled == [True]


@pytest.mark.asyncio
async def test_catalog_selection_is_scoped_to_base_and_key(monkeypatch):
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return _catalog(_item(f"org/model-{len(seen)}", ["chat", "vision"]))

    _transport(monkeypatch, respond)
    env = _env(JARVIS_ROLE_VISION_KEY="dedicated-scope")
    assert (await vision_deepinfra.prepare_config(env)).model == "org/model-1"
    env["JARVIS_ROLE_VISION_BASE_URL"] = "https://private.example/v1"
    with pytest.raises(VLMNotConfigured):
        vision_deepinfra.resolve_config(env)
    assert (await vision_deepinfra.prepare_config(env)).model == "org/model-2"
    assert seen == [
        "https://api.deepinfra.com/v1/openai/models?filter=true&sort_by=hermes",
        "https://private.example/v1/models?filter=true&sort_by=hermes",
    ]


@pytest.mark.asyncio
async def test_valid_uppercase_host_still_matches_physical_request(monkeypatch):
    _transport(monkeypatch, lambda request: _catalog(
        _item("org/ready", ["chat", "vision"])))
    env = _env(JARVIS_ROLE_VISION_BASE_URL="https://API.DEEPINFRA.COM/v1/openai")
    assert (await vision_deepinfra.prepare_config(env)).model == "org/ready"


@pytest.mark.asyncio
async def test_negative_cache_expires_and_refresh_bypasses_it(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(vision_deepinfra.time, "monotonic", lambda: clock[0])
    calls = []

    def respond(request):
        calls.append(request)
        return _catalog(_item("org/ready", ["chat", "vision"])) if len(calls) > 1 else _catalog()

    _transport(monkeypatch, respond)
    env = _env(DEEPINFRA_API_KEY="negative-cache-key")
    with pytest.raises(VLMNotConfigured):
        await vision_deepinfra.prepare_config(env)
    with pytest.raises(VLMNotConfigured):
        await vision_deepinfra.prepare_config(env)
    assert len(calls) == 1
    clock[0] += 61
    assert (await vision_deepinfra.prepare_config(env)).model == "org/ready"


@pytest.mark.parametrize("field,value,reason", [
    ("JARVIS_ROLE_VISION_MODEL", "bad\nmodel", "vlm_model_invalid"),
    ("JARVIS_ROLE_VISION_MODEL", "x" * 513, "vlm_model_invalid"),
    ("JARVIS_ROLE_VISION_KEY", "bad\r\nheader: value", "vlm_key_invalid"),
])
def test_explicit_values_are_bounded_and_header_safe(field, value, reason):
    env = _env(JARVIS_ROLE_VISION_MODEL="good/model", JARVIS_ROLE_VISION_KEY="dedicated")
    env[field] = value
    with pytest.raises(VLMNotConfigured) as refused:
        vision_deepinfra.resolve_config(env)
    assert refused.value.reason == reason
    assert value not in str(refused.value)


@pytest.mark.parametrize("base", [
    "http://foreign.example/v1", "https://user:pass@foreign.example/v1",
    "https://foreign.example/v1?secret=yes", "https://foreign.example/v1#fragment",
    "ftp://foreign.example/v1", "https://foreign.example:bad/v1",
    "https://foreign.example/v1\nInjected: yes",
])
def test_bad_base_fails_closed(base):
    with pytest.raises(VLMNotConfigured) as refused:
        vision_deepinfra.resolve_config(_env(JARVIS_ROLE_VISION_MODEL="good/model",
                                              JARVIS_ROLE_VISION_BASE_URL=base,
                                              JARVIS_ROLE_VISION_KEY="dedicated"))
    assert refused.value.reason == "vlm_url_invalid"
    assert base not in str(refused.value)


def test_origin_scoping_and_precedence():
    env = _env(JARVIS_ROLE_VISION_MODEL="good/model",
               DEEPINFRA_BASE_URL="https://other.example/v1")
    with pytest.raises(VLMNotConfigured) as refused:
        vision_deepinfra.resolve_config(env)
    assert refused.value.reason == "vlm_key_unset"
    env["JARVIS_ROLE_VISION_BASE_URL"] = "https://api.deepinfra.com:443/v1/openai"
    assert vision_deepinfra.resolve_config(env).api_key == "ambient-a"
    env["JARVIS_ROLE_VISION_BASE_URL"] = "https://private.example/v1"
    env["JARVIS_ROLE_VISION_KEY"] = "role-key"
    assert vision_deepinfra.resolve_config(env).api_key == "role-key"
    assert vision_deepinfra.resolve_config(env).base_url == "https://private.example/v1"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://different.example/models"}),
    httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)),
    httpx.Response(200, content=b"not json"),
    httpx.Response(200, json={"data": {"id": "wrong"}}),
])
async def test_bad_catalog_responses_refuse_without_leak(monkeypatch, response):
    _transport(monkeypatch, lambda request: response)
    env = _env(DEEPINFRA_API_KEY="private-catalog-secret")
    with pytest.raises(VLMNotConfigured) as refused:
        await vision_deepinfra.prepare_config(env, force_refresh=True)
    assert refused.value.reason == "vlm_model_unset"
    assert "private-catalog-secret" not in str(refused.value)


@pytest.mark.asyncio
async def test_key_rotation_in_request_hook_refuses_before_transport(monkeypatch):
    env = _env(DEEPINFRA_API_KEY="rotation-old")
    sent = []
    _transport(monkeypatch, lambda request: sent.append(request) or _catalog(
        _item("org/ready", ["chat", "vision"])))
    original = httpx.AsyncClient

    class RotateClient(original):
        async def send(self, request, *args, **kwargs):
            env["DEEPINFRA_API_KEY"] = "rotation-new"
            return await super().send(request, *args, **kwargs)

    monkeypatch.setattr(vision_deepinfra.httpx, "AsyncClient", RotateClient)
    with pytest.raises(VLMNotConfigured):
        await vision_deepinfra.prepare_config(env, force_refresh=True)
    assert sent == []
    with pytest.raises(VLMNotConfigured):
        vision_deepinfra.resolve_config(env)


@pytest.mark.asyncio
async def test_key_rotation_after_response_cannot_publish_catalog(monkeypatch):
    env = _env(DEEPINFRA_API_KEY="late-old")

    def respond(request):
        env["DEEPINFRA_API_KEY"] = "late-new"
        return _catalog(_item("org/old-model", ["chat", "vision"]))

    _transport(monkeypatch, respond)
    with pytest.raises(VLMNotConfigured):
        await vision_deepinfra.prepare_config(env, force_refresh=True)
    with pytest.raises(VLMNotConfigured):
        vision_deepinfra.resolve_config(env)


@pytest.mark.asyncio
async def test_explicit_model_skips_catalog_even_in_prepare(monkeypatch):
    _transport(monkeypatch, lambda request: pytest.fail("unexpected metadata request"))
    config = await vision_deepinfra.prepare_config(_env(JARVIS_ROLE_VISION_MODEL="fixed/model"),
                                                    force_refresh=True)
    assert config.model == "fixed/model"


def test_unselected_provider_and_legacy_values_do_not_select_route():
    with pytest.raises(VLMNotConfigured) as refused:
        vision_deepinfra.resolve_config({"DEEPINFRA_API_KEY": "ambient-a",
                                          "JARVIS_VLM_MODEL": "legacy/model"})
    assert refused.value.reason == "vlm_disabled"
    with pytest.raises(VLMNotConfigured) as refused:
        vision_deepinfra.resolve_config(_env(DEEPINFRA_API_KEY="",
                                              JARVIS_VLM_KEY="legacy",
                                              JARVIS_VLM_MODEL="legacy/model"))
    assert refused.value.reason == "vlm_key_unset"
