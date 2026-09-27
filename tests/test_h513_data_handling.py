"""H513 routed data handling: synthetic backends, no provider requests."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.commands import Principal
from agents.core.llm.providers import get_profile
from agents.core.turn_notices import open_turn_notices, reset_turn_notices


@pytest.fixture
def dh(tmp_path, monkeypatch):
    from agents.core.llm import data_handling
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(data_handling, "_scope_key", lambda: b"synthetic-h513-local-key")
    return data_handling


def router(provider="openai-compatible", *, policy="unknown", url="https://example.invalid/v1"):
    backend = SimpleNamespace(profile=replace(get_profile(provider), data_policy=policy),
                              base_url=url, api_key="synthetic-key")
    return SimpleNamespace(_compatible_backend=backend, _compatible_model="synthetic-model",
                           _backend=None, _ollama_backend=None, _gemini_backend=None, _claude_backend=None)


class Audit:
    def __init__(self, fail=False):
        self.fail, self.rows = fail, []

    def log(self, event):
        if self.fail:
            raise OSError("synthetic disk full")
        self.rows.append(event)


def allow(dh, r, audit=None):
    row = dh.posture(r)["providers"][0]
    return dh.acknowledge(r, row["provider"], True, row["scope"], audit or Audit())


def test_unknown_internal_is_refused_without_dispatch(dh):
    r = router()
    called = []
    with pytest.raises(dh.DataHandlingRefused, match="acknowledg"):
        dh.authorize(r, r._compatible_backend, "synthetic-model", "cloud-compatible", principal=Principal())
        called.append("provider request")
    assert called == []
    assert dh.posture(r)["providers"][0]["last_used"] is None


@pytest.mark.parametrize("channel", ["builder", "workflow", "internal"])
def test_owner_internal_channels_still_require_consent(dh, channel):
    r = router()
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(r, r._compatible_backend, "synthetic-model", "cloud-compatible",
                     principal=Principal(channel=channel, admin=True))


def test_interactive_warning_remains_after_durable_ack(dh):
    r = router()
    audit = Audit()
    row = allow(dh, r, audit)
    assert row["acknowledged"] is True
    assert audit.rows[0].action_taken == "model_training_consent"
    notices, token = open_turn_notices()
    try:
        used = dh.authorize(r, r._compatible_backend, "synthetic-model", "cloud-compatible",
                            principal=Principal(channel="web", admin=True))
    finally:
        reset_turn_notices(token)
    assert used["policy"] == "unknown" and used["warning"]
    assert "unknown" in notices[0]["text"]
    assert dh.posture(r)["providers"][0]["last_used"] is not None
    # Fresh read of durable consent, not an in-memory permission cache.
    assert dh.authorize(r, r._compatible_backend, "synthetic-model", "cloud-compatible",
                        principal=Principal())["acknowledged"] is True


@pytest.mark.parametrize("change", ["endpoint", "credential", "declaration"])
def test_configuration_changes_invalidate_ack_and_stale_form(dh, change):
    r = router()
    old = allow(dh, r)
    if change == "endpoint":
        r._compatible_backend.base_url = "https://different.invalid/v1"
    elif change == "credential":
        r._compatible_backend.api_key = "different-synthetic-key"
    else:
        r._compatible_backend.profile = replace(r._compatible_backend.profile, data_policy="trains-on-inputs")
    with pytest.raises(dh.StaleAcknowledgment):
        dh.acknowledge(r, old["provider"], True, old["scope"], Audit())
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(r, r._compatible_backend, "synthetic-model", "cloud-compatible", principal=Principal())


def test_revoke_after_selection_before_dispatch_refuses(dh):
    r = router()
    chosen = r._compatible_backend, "synthetic-model", "cloud-compatible"
    row = allow(dh, r)
    dh.acknowledge(r, row["provider"], False, row["scope"], Audit())
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(r, *chosen, principal=Principal())


def test_audit_failure_cannot_grant(dh):
    r = router()
    row = dh.posture(r)["providers"][0]
    with pytest.raises(dh.ConsentUnavailable):
        dh.acknowledge(r, row["provider"], True, row["scope"], Audit(fail=True))
    assert dh.posture(r)["providers"][0]["acknowledged"] is False


@pytest.mark.parametrize("raw", [True, ["openai-compatible"], {"openai-compatible": True}, {"any": "a" * 64}])
def test_corrupt_storage_never_grants(dh, raw):
    settings_db.put_category("security", {"data_training_ack": raw})
    r = router()
    assert dh.posture(r)["settings_readable"] is False
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(r, r._compatible_backend, "synthetic-model", "cloud-compatible", principal=Principal())


def test_unreadable_settings_fails_closed(dh, monkeypatch):
    r = router()
    allow(dh, r)
    def unreadable(*args):
        raise settings_db.SettingsUnreadable("synthetic corrupt store")
    monkeypatch.setattr(settings_db, "read_setting", unreadable)
    assert dh.posture(r)["settings_readable"] is False
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(r, r._compatible_backend, "synthetic-model", "cloud-compatible", principal=Principal())


def test_actual_cloned_profile_and_remote_local_endpoint(dh):
    r = router(policy="trains-on-inputs")
    resolved = dh.resolve(r, r._compatible_backend, "synthetic-model", "cloud-compatible")
    assert resolved.policy == "trains-on-inputs"
    local = router("lm-studio", policy="local", url="http://127.0.0.1:1234")
    assert dh.resolve(local, local._compatible_backend, "m", "cloud-compatible").policy == "local"
    local._compatible_backend.base_url = "http://192.0.2.10:1234"
    assert dh.resolve(local, local._compatible_backend, "m", "local").policy == "unknown"


def test_generic_settings_cannot_grant_and_reset_does_not_reintroduce_ack(dh):
    assert settings_db.route_only_problems("security", ["data_training_ack"])
    exported = settings_db.export_settings()
    assert "data_training_ack" not in exported.get("settings", {}).get("security", {})
    planned = settings_db.plan_reset("security")
    assert "data_training_ack" not in planned.get("security", {})


def test_metadata_probes_do_not_warn_or_count(dh):
    r = router()
    notices, token = open_turn_notices()
    try:
        dh.resolve(r, r._compatible_backend, "synthetic-model", "cloud-compatible")
        dh.posture(r)
    finally:
        reset_turn_notices(token)
    assert notices == []
    assert dh.posture(r)["providers"][0]["last_used"] is None


@pytest.fixture
def api(dh, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    r, audit = router(), Audit()
    monkeypatch.setattr(web, "ADMIN_TOKEN", "h513-admin")
    orch = SimpleNamespace(llm_router=r, audit=audit)
    monkeypatch.setattr(web, "orch", orch)
    return TestClient(web.app), r, audit


def test_admin_ack_route_strict_and_audited(api, dh):
    client, r, audit = api
    row = dh.posture(r)["providers"][0]
    body = {"provider": row["provider"], "scope": row["scope"], "acknowledged": True}
    headers = {"X-Admin-Token": "h513-admin"}
    injected = {row["provider"]: row["scope"]}
    generic = client.put("/api/admin/settings/security", json={"values": {"data_training_ack": injected}}, headers=headers)
    assert generic.status_code == 422
    changes, errors = settings_db.plan_import({"settings": {"security": {"data_training_ack": injected}}})
    assert errors and not changes
    assert settings_db.get_value("security", "data_training_ack") == {}
    assert client.post("/api/security/data-handling/ack", json=body).status_code in (401, 403)
    response = client.post("/api/security/data-handling/ack", json=body, headers={"X-Admin-Token": "h513-admin"})
    assert response.status_code == 200
    assert response.json()["acknowledged"] is True
    assert audit.rows and dh.posture(r)["providers"][0]["acknowledged"]
    for invalid in ({**body, "acknowledged": "true"}, {**body, "provider": 1},
                    {**body, "scope": ""}, {**body, "extra": True}):
        assert client.post("/api/security/data-handling/ack", json=invalid,
                           headers={"X-Admin-Token": "h513-admin"}).status_code == 422
    response = client.post("/api/security/data-handling/ack", json={**body, "scope": "0" * 64},
                           headers={"X-Admin-Token": "h513-admin"})
    assert response.status_code == 409
    audit.fail = True
    assert client.post("/api/security/data-handling/ack", json={**body, "acknowledged": False},
                       headers={"X-Admin-Token": "h513-admin"}).status_code == 503


@pytest.mark.asyncio
async def test_agent_dispatch_rechecks_revocation_and_keeps_backend_identity(dh, monkeypatch):
    from agents.core.agent import Agent
    from agents.core.llm.hybrid_router import HybridRouter
    r = router()
    h = HybridRouter.__new__(HybridRouter)
    h.__dict__.update(r.__dict__)
    selected = (h._compatible_backend, "synthetic-model", "cloud-compatible")
    monkeypatch.setattr(h, "_select_backend_inner", lambda *args: selected)
    monkeypatch.setattr(h, "_enforce_approved_models", lambda *args: None)
    assert h.select_backend("athena", "x")[0] is selected[0]
    old = allow(dh, h)
    dh.acknowledge(h, old["provider"], False, old["scope"], Audit())
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return "synthetic answer"
    selected[0].generate = generate
    agent = Agent.__new__(Agent)
    agent.id, agent.llm_router, agent.tool_runtime = "athena", h, None
    with pytest.raises(dh.DataHandlingRefused):
        await agent._generate_response(selected[0], selected[1], "private prompt", "", 16, 0.2)
    assert calls == []
    allow(dh, h)
    assert await agent._generate_response(selected[0], selected[1], "private prompt", "", 16, 0.2) == "synthetic answer"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_revocation_by_tool_blocks_next_model_round(dh):
    import httpx

    from agents.core.agent import Agent
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.egress import llm_async_client
    from agents.core.llm.hybrid_router import HybridRouter
    from agents.core.llm.tool_protocol import ToolCall, ToolTurn
    from agents.core.tool_rpc import ToolRPCServer
    r = router()
    h = HybridRouter.__new__(HybridRouter)
    h.__dict__.update(r.__dict__)
    row = allow(dh, h)
    calls, tool_calls, independent = [], [], []
    async def generate_tool_turn(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ToolTurn(tool_calls=(ToolCall("revoke-1", "revoke"),), finish_reason="tool_calls")
        return ToolTurn(content="should never reach this round")
    backend = h._compatible_backend
    backend.supports_tools, backend.generate_tool_turn = True, generate_tool_turn
    server = ToolRPCServer()
    async def revoke(args):
        tool_calls.append("revoked")
        dh.acknowledge(h, row["provider"], False, row["scope"], Audit())
        # ToolRPC work is not part of the primary model's physical request scope.
        def transport(request):
            independent.append(request)
            return httpx.Response(200)
        async with llm_async_client("gemini", transport=httpx.MockTransport(transport)) as client:
            await client.post("https://independent.invalid/local-role-probe")
        return {"revoked": True}
    server.register_tool("revoke", revoke)
    agent = Agent.__new__(Agent)
    agent.id, agent.llm_router = "athena", h
    agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)
    agent.tool_event_sink = lambda event: None
    with pytest.raises(dh.DataHandlingRefused):
        await agent._generate_response(backend, "synthetic-model", "use revoke", "", 32, 0.2)
    assert tool_calls == ["revoked"]
    assert len(calls) == 1
    assert len(independent) == 1


@pytest.mark.asyncio
async def test_runtime_pre_request_hook_failure_never_dispatches(dh):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.tool_protocol import ToolTurn
    from agents.core.tool_rpc import ToolRPCServer
    calls = []
    async def generate_tool_turn(**kwargs):
        calls.append(kwargs)
        return ToolTurn(content="not called")
    server = ToolRPCServer()
    async def echo(args):
        return args
    server.register_tool("echo", echo)
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    backend = SimpleNamespace(supports_tools=True, generate_tool_turn=generate_tool_turn)
    async def unavailable():
        raise OSError("policy reader unavailable")
    with pytest.raises(OSError, match="policy reader unavailable"):
        await runtime.run(agent_id="athena", backend=backend, model="m", prompt="x",
                          before_model_call=unavailable)
    assert calls == []


def test_unregistered_profile_cannot_corrupt_existing_consent(dh):
    r = router()
    allow(dh, r)
    before = settings_db.get_value("security", "data_training_ack")
    r._compatible_backend.profile = replace(r._compatible_backend.profile, id="unregistered-synthetic")
    row = dh.posture(r)["providers"][0]
    audit = Audit()
    with pytest.raises(ValueError, match="registered"):
        dh.acknowledge(r, row["provider"], True, row["scope"], audit)
    assert audit.rows == []
    assert settings_db.get_value("security", "data_training_ack") == before
    assert dh.posture(r)["settings_readable"] is True


def test_duplicate_provider_accounts_are_not_actionable(dh):
    r = router()
    r._backend = SimpleNamespace(profile=r._compatible_backend.profile,
                                base_url="https://other-account.invalid", api_key="different-key")
    rows = dh.posture(r)["providers"]
    assert len(rows) == 2
    assert all(row["can_acknowledge"] is False and row["acknowledgment_unavailable"] for row in rows)
    with pytest.raises(ValueError, match="one configured"):
        dh.acknowledge(r, rows[0]["provider"], True, rows[0]["scope"], Audit())


def test_actual_endpoint_override_and_key_pool_changes_invalidate_scope(dh):
    r = router()
    original = dh.resolve(r, r._compatible_backend, "m")
    r._compatible_backend.endpoint = "https://override.invalid/responses"
    overridden = dh.resolve(r, r._compatible_backend, "m")
    assert overridden.scope != original.scope
    r._compatible_backend.auth_pool = SimpleNamespace(_profiles=[SimpleNamespace(api_key="account-one")])
    pooled = dh.resolve(r, r._compatible_backend, "m")
    r._compatible_backend.auth_pool._profiles.append(SimpleNamespace(api_key="account-two"))
    assert dh.resolve(r, r._compatible_backend, "m").scope != pooled.scope


def test_openrouter_live_routing_policy_invalidates_permission(dh):
    r = router("openrouter")
    routing = {"data_collection": "deny"}
    r._compatible_backend._current_block = lambda: routing.copy()
    row = allow(dh, r)
    routing["data_collection"] = "allow"
    actual = dh.resolve(r, r._compatible_backend, "m")
    assert actual.policy == "trains-on-inputs" and actual.scope != row["scope"]
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(r, r._compatible_backend, "m", principal=Principal())


def test_consent_survives_router_recreation(dh):
    original = allow(dh, router())
    fresh = dh.posture(router())["providers"][0]
    assert fresh["scope"] == original["scope"] and fresh["acknowledged"]
    assert fresh["last_used"] is None


def test_changed_effective_model_tier_requires_fresh_ack(dh):
    r = router()
    r._compatible_backend.profile = replace(r._compatible_backend.profile,
                                            data_policy_models=(("training-model", "trains-on-inputs", "declared training tier"),))
    original = allow(dh, r)
    changed = dh.resolve(r, r._compatible_backend, "training-model")
    assert changed.policy == "trains-on-inputs" and changed.scope != original["scope"]
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(r, r._compatible_backend, "training-model", principal=Principal())


@pytest.mark.asyncio
async def test_proven_local_generation_survives_scope_key_failure(dh, monkeypatch):
    from agents.core.agent import Agent
    from agents.core.llm.hybrid_router import HybridRouter
    def unavailable():
        raise OSError("synthetic secret store unavailable")
    monkeypatch.setattr(dh, "_scope_key", unavailable)
    r = router("lm-studio", policy="local", url="http://127.0.0.1:1234")
    h = HybridRouter.__new__(HybridRouter)
    h.__dict__.update(r.__dict__)
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return "local answer"
    h._compatible_backend.generate = generate
    agent = Agent.__new__(Agent)
    agent.id, agent.llm_router, agent.tool_runtime = "athena", h, None
    assert await agent._generate_response(h._compatible_backend, "m", "x", "", 32, 0.2) == "local answer"
    assert len(calls) == 1
    remote = router()
    assert dh.posture(remote)["providers"][0]["can_acknowledge"] is False
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(remote, remote._compatible_backend, "m", principal=Principal())


@pytest.mark.asyncio
async def test_revoked_before_background_cache_dispatch_sends_no_material(dh):
    from agents.core.llm.auth_rotation import AuthLease
    from agents.core.llm.hybrid_router import HybridRouter
    from agents.core.orchestrator import Orchestrator
    r = router("gemini")
    h = HybridRouter.__new__(HybridRouter)
    h.__dict__.update(r.__dict__)
    h._gemini_backend, h._compatible_backend = h._compatible_backend, None
    h._gemini_model = "synthetic-model"
    row = allow(dh, h)
    dh.acknowledge(h, row["provider"], False, row["scope"], Audit())
    calls = []
    async def create_or_extend(**kwargs):
        calls.append(kwargs)
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = h
    orch.context_cache = SimpleNamespace(create_or_extend=create_or_extend)
    with pytest.raises(dh.DataHandlingRefused):
        await orch._async_create_cache("s", "private system", ("private history",),
                                       "synthetic-model", "p", AuthLease("fake", "synthetic-key"))
    assert calls == []


def test_config_reload_during_audit_rolls_back_grant(dh):
    r = router()
    row = dh.posture(r)["providers"][0]
    observed = []
    class ReloadAudit:
        def log(self, event):
            observed.append(settings_db.get_value("security", "data_training_ack"))
            r._compatible_backend.api_key = "new-synthetic-account"
    with pytest.raises(dh.ConsentUnavailable):
        dh.acknowledge(r, row["provider"], True, row["scope"], ReloadAudit())
    assert observed == [{}]  # required audit ran before any grant
    assert settings_db.get_value("security", "data_training_ack") == {}


def test_posture_projection_exposes_warning_and_actionability(api, dh, monkeypatch):
    from agents.core.routers import security
    client, r, _ = api
    orch = security.get_orch()
    orch.get_setting = lambda key, default=None: default
    monkeypatch.setattr(security, "_host_posture", lambda: {})
    response = client.get("/api/security/posture", headers={"X-Admin-Token": "h513-admin"})
    assert response.status_code == 200
    row = response.json()["data_handling"]["providers"][0]
    assert row["policy"] == "unknown" and row["warning"] and row["can_acknowledge"]
    assert "synthetic-key" not in response.text and "example.invalid" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", [False, True])
async def test_cache_lock_wait_rechecks_consent_before_http(dh, extension):
    import asyncio

    import httpx

    from agents.core.llm.auth_rotation import AuthLease
    from agents.core.llm.gemini_cache import ContextCache, _digest_parts
    r = router("gemini")
    row = allow(dh, r)
    lease = AuthLease("synthetic", "synthetic-key")
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"name": "cachedContents/synthetic"})
    cache = ContextCache(lambda: None)
    await cache._client.aclose()
    cache._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    if extension:
        cache._cache_map["s"] = {"cache_name": "cachedContents/synthetic", "model": "synthetic-model",
                                 "system_digest": _digest_parts(("system",)), "prefix_count": 1,
                                 "prefix_digest": _digest_parts(("history",)), "policy_fingerprint": "p",
                                 "profile_id": lease.profile_id}
    lock = cache._session_locks.setdefault("s", asyncio.Lock())
    await lock.acquire()
    async def before_request():
        dh.authorize(r, r._compatible_backend, "synthetic-model", principal=Principal())
    task = asyncio.create_task(cache.create_or_extend(session_id="s", system_instruction="system",
                                                      history=("history",), model="synthetic-model",
                                                      policy_fingerprint="p", lease=lease,
                                                      before_request=before_request))
    try:
        await asyncio.sleep(0)
        assert not task.done()
        dh.acknowledge(r, row["provider"], False, row["scope"], Audit())
        lock.release()
        with pytest.raises(dh.DataHandlingRefused):
            await task
        assert requests == []
    finally:
        if lock.locked():
            lock.release()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await cache.close()


@pytest.mark.asyncio
async def test_stream_refusal_names_acknowledgment_and_is_failed_turn(dh):
    from agents.core.agent import Agent
    from agents.core.orchestrator import is_failed_turn_reply
    from tests.test_agent_runtime_v2 import _LegacyDualBackend, _streamed_orchestrator_for
    backend = _LegacyDualBackend("should never generate")
    agent = Agent("jarvis", {"name": "Jarvis"})
    orch, _, _, _ = _streamed_orchestrator_for(agent, backend)
    backend.profile = replace(get_profile("openai-compatible"), data_policy="unknown")
    backend.base_url = "https://synthetic.invalid"
    answer = await orch.handle_input_stream("private prompt", channel="internal", session_id="s")
    assert "acknowledg" in answer
    assert is_failed_turn_reply("jarvis", answer)
    assert backend.generate_calls == backend.stream_calls == 0


def test_unbound_inbound_origin_is_unattended(dh):
    r = router()
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(r, r._compatible_backend, "m", principal=Principal(), origin="inbound")
    # An authenticated channel user still has an interactive inbound turn.
    assert dh.authorize(r, r._compatible_backend, "m",
                        principal=Principal(channel="telegram", sender="owner", admin=True),
                        origin="inbound")["warning"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["credential-retry", "cache-fallback", "stream-cache-fallback"])
async def test_revoke_during_first_gemini_physical_attempt_blocks_retry(dh, kind):
    import httpx

    from agents.core.agent import Agent
    from agents.core.llm.auth_rotation import AuthProfilePool
    from agents.core.llm.egress import llm_async_client
    from agents.core.llm.gemini import GeminiBackend
    from agents.core.llm.gemini_context import GeminiRequestBinding
    from agents.core.llm.hybrid_router import HybridRouter
    pool = AuthProfilePool(["synthetic-one", "synthetic-two"], provider="gemini")
    backend = GeminiBackend("", auth_pool=pool)
    await backend.client.aclose()
    h = HybridRouter.__new__(HybridRouter)
    h._gemini_backend, h._gemini_model = backend, "gemini-2.5-flash"
    row = allow(dh, h)
    requests = []
    async def transport(request):
        requests.append(request)
        # Revoke while the first request is in flight; retry must reread consent.
        dh.acknowledge(h, row["provider"], False, row["scope"], Audit())
        return httpx.Response(401 if kind == "credential-retry" else 404)
    backend.client = llm_async_client("gemini", transport=httpx.MockTransport(transport))
    agent = Agent.__new__(Agent)
    agent.id, agent.llm_router, agent.tool_runtime = "athena", h, None
    if kind == "credential-retry":
        from agents.core.agent_runtime import AgentToolRuntime
        from agents.core.tool_rpc import ToolRPCServer
        server = ToolRPCServer()
        async def echo(args):
            return args
        server.register_tool("echo", echo)
        agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)
        agent.tool_event_sink = lambda event: None
    kwargs = {} if kind != "stream-cache-fallback" else {"on_token": lambda text: None}
    binding = GeminiRequestBinding(lease=pool.lease(), cache_name="cachedContents/synthetic")
    try:
        with backend.request_scope(binding), pytest.raises(dh.DataHandlingRefused):
            await agent._generate_response(backend, "gemini-2.5-flash", "private", "", 32, 0.2, **kwargs)
        assert len(requests) == 1
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_physical_request_scope_is_concurrent_and_does_not_leak(dh):
    import asyncio

    import httpx

    from agents.core.llm.egress import llm_async_client
    seen, checked = [], []
    async def transport(request):
        seen.append(request.url.path)
        return httpx.Response(200)
    client = llm_async_client("gemini", transport=httpx.MockTransport(transport))
    async def run(name, denied):
        def check():
            checked.append(name)
            if denied:
                raise dh.DataHandlingRefused("revoked synthetic turn")
        with dh.physical_request_scope(check):
            await asyncio.sleep(0)
            await client.post(f"https://example.invalid/{name}")
    try:
        result = await asyncio.gather(run("blocked", True), run("allowed", False), return_exceptions=True)
        assert isinstance(result[0], dh.DataHandlingRefused)
        assert seen == ["/allowed"] and set(checked) == {"blocked", "allowed"}
        await client.post("https://example.invalid/direct")
        assert seen == ["/allowed", "/direct"]
        assert len(checked) == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_swallowed_physical_guard_error_is_rethrown_without_dispatch(dh):
    from contextlib import suppress

    import httpx

    from agents.core.llm.egress import llm_async_client
    sent = []
    def transport(request):
        sent.append(request)
        return httpx.Response(200)
    def unavailable():
        raise OSError("synthetic guard store unreadable")
    client = llm_async_client("gemini", transport=httpx.MockTransport(transport))
    try:
        with pytest.raises(OSError, match="guard store unreadable"), dh.physical_request_scope(unavailable), suppress(Exception):
            # Adapter-style degradation cannot clear the remembered denial.
            await client.post("https://example.invalid/prompt")
        assert sent == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_inherited_scope_cannot_send_after_routed_lifetime_closes(dh):
    import asyncio

    import httpx

    from agents.core.llm.egress import llm_async_client
    sent = []
    def transport(request):
        sent.append(request)
        return httpx.Response(200)
    client = llm_async_client("gemini", transport=httpx.MockTransport(transport))
    release = asyncio.Event()
    async def delayed():
        await release.wait()
        await client.post("https://example.invalid/late-retry")
    try:
        with dh.physical_request_scope(lambda: None):
            task = asyncio.create_task(delayed())
        release.set()
        with pytest.raises(dh.DataHandlingRefused, match="scope is closed"):
            await task
        assert sent == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_async_physical_guard_is_awaited_again_before_retry(dh):
    import asyncio

    import httpx

    from agents.core.llm.egress import llm_async_client
    permitted, checked, sent = True, [], []
    async def check():
        await asyncio.sleep(0)
        checked.append(permitted)
        if not permitted:
            raise dh.DataHandlingRefused("async consent revoked")
    async def transport(request):
        nonlocal permitted
        sent.append(request)
        await asyncio.sleep(0)
        permitted = False
        return httpx.Response(401)
    client = llm_async_client("gemini", transport=httpx.MockTransport(transport))
    try:
        with pytest.raises(dh.DataHandlingRefused, match="async consent revoked"), dh.physical_request_scope(check):
            await client.post("https://example.invalid/first")
            await client.post("https://example.invalid/retry")
        assert checked == [True, False]
        assert len(sent) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("router_state", ["missing", "none"])
async def test_direct_agent_generation_preserves_optional_router_contract(router_state):
    from agents.core.agent import Agent

    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return "direct answer"
    agent = Agent.__new__(Agent)
    agent.id, agent.tool_runtime = "jarvis", None
    if router_state == "none":
        agent.llm_router = None
    backend = SimpleNamespace(generate=generate)
    assert await agent._generate_response(backend, "m", "p", "", 16, .2) == "direct answer"
    assert len(calls) == 1


@pytest.mark.parametrize("reply,failed", [
    ('["a.py"]', False), ("[1] first", False), ("[docs](https://x.test)", False),
    ("⚠️ careful: that deletes files", False), ("[Gemini error: request failed]", True),
    ("[jarvis timeout: stopped]", True), ("[data handling error: acknowledgment required]", True),
])
def test_failed_turn_classifier_distinguishes_answers_from_failure_markers(reply, failed):
    from agents.core.orchestrator import is_failed_turn_reply

    assert is_failed_turn_reply("jarvis", reply) is failed
