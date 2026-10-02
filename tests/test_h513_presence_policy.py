"""H513 optional presence explanation binding; no production caller or network."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.commands import Principal
from agents.core.house.presence import LocalPresenceExplainer, PresenceInference
from agents.core.llm import data_handling as dh
from agents.core.llm.providers import get_profile
from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
from tests.test_h30_presence import _present_evidence, _store


@pytest.fixture
def presence(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-presence-key")
    requests, audits = [], []
    async def generate(model, prompt, **kwargs):
        requests.append((model, json.loads(prompt), kwargs))
        return "x" * 1_100
    backend = SimpleNamespace(profile=get_profile("lm-studio"), base_url="http://127.0.0.1:1234",
                              generate=generate)
    router = SimpleNamespace(local_backend=backend, active_model="synthetic-presence",
                             _backend=backend, _local_model="synthetic-presence")
    engine = PresenceInference(_store(tmp_path), clock=lambda: 1_000.0)
    decision = engine.infer("Alice Example", _present_evidence()).decision
    return SimpleNamespace(backend=backend, router=router, requests=requests, decision=decision,
                          audit=SimpleNamespace(log=audits.append), audits=audits, engine=engine)


@pytest.mark.asyncio
async def test_offloopback_copied_owner_context_is_refused_before_io(presence):
    presence.backend.base_url = "https://synthetic.invalid/v1"
    explainer = LocalPresenceExplainer.from_router(presence.router)
    token = bind_turn_principal(Principal(channel="web", admin=True))
    try:
        with pytest.raises(dh.DataHandlingRefused, match="acknowledg"):
            await asyncio.create_task(explainer.explain(presence.decision))
        assert presence.requests == []
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", [False, True])
async def test_loopback_or_audited_scope_preserves_limits_and_sanitization(presence, remote):
    if remote:
        presence.backend.base_url = "https://synthetic.invalid/v1"
        row = dh.posture(presence.router)["providers"][0]
        dh.acknowledge(presence.router, row["provider"], True, row["scope"], presence.audit)
        assert len(presence.audits) == 1
    explainer = LocalPresenceExplainer.from_router(presence.router)
    assert await explainer.explain(presence.decision) == "x" * 1_000
    model, payload, options = presence.requests[0]
    assert model == "synthetic-presence"
    assert "occupant_id" not in payload and "Alice Example" not in str(payload)
    assert options["max_tokens"] == 128 and options["temperature"] == 0.0
    assert payload["status"] == presence.decision.status


@pytest.mark.asyncio
async def test_explicit_strict_local_explanation_refuses_remote_even_with_consent(presence):
    presence.backend.base_url = "https://synthetic.invalid/v1"
    row = dh.posture(presence.router)["providers"][0]
    dh.acknowledge(presence.router, row["provider"], True, row["scope"], presence.audit)

    with pytest.raises(dh.DataHandlingRefused, match="local"):
        await LocalPresenceExplainer.from_router(presence.router).explain(
            presence.decision, strict_local=True,
        )
    assert presence.requests == []


@pytest.mark.asyncio
async def test_strict_local_explanation_checks_final_physical_request(presence):
    from agents.core.llm.egress import llm_async_client

    sent = []
    client = llm_async_client("lm-studio", transport=httpx.MockTransport(
        lambda request: (sent.append(request), httpx.Response(200))[1]
    ))

    async def generate(model, prompt, **kwargs):
        await client.post("https://synthetic.invalid/v1/chat/completions", json={"prompt": prompt})
        return "should not arrive"

    presence.backend.generate = generate
    try:
        with pytest.raises(dh.DataHandlingRefused, match="local"):
            await LocalPresenceExplainer.from_router(presence.router).explain(
                presence.decision, strict_local=True,
            )
        assert sent == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_strict_local_explanation_rejects_late_backend_rebind(presence):
    from agents.core.llm.egress import llm_async_client

    sent = []
    client = llm_async_client("lm-studio", transport=httpx.MockTransport(
        lambda request: (sent.append(request), httpx.Response(200))[1]
    ))

    async def generate(model, prompt, **kwargs):
        presence.backend.base_url = "https://synthetic.invalid/v1"
        try:
            await client.post("http://127.0.0.1:1234/v1/chat/completions", json={"prompt": prompt})
        except dh.DataHandlingRefused:
            return "adapter swallowed the refusal"
        return "unexpected success"

    presence.backend.generate = generate
    try:
        with pytest.raises(dh.DataHandlingRefused):
            await LocalPresenceExplainer.from_router(presence.router).explain(
                presence.decision, strict_local=True,
            )
        assert sent == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unbound_constructor_fails_closed(presence):
    explainer = LocalPresenceExplainer(presence.backend, "synthetic-presence")
    with pytest.raises(dh.DataHandlingRefused, match="binding"):
        await explainer.explain(presence.decision)
    assert presence.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["changed", "unrelated", "unavailable"])
async def test_router_backend_change_invalidates_saved_binding(presence, binding):
    explainer = LocalPresenceExplainer.from_router(presence.router)
    other = SimpleNamespace(profile=get_profile("lm-studio"), base_url="http://127.0.0.1:5678")
    if binding == "changed":
        presence.router.local_backend = other
    elif binding == "unrelated":
        explainer = LocalPresenceExplainer(presence.backend, "synthetic-presence",
                                           router=SimpleNamespace(local_backend=other))
    else:
        class UnavailableRouter:
            @property
            def local_backend(self):
                raise RuntimeError("no local backend")
        explainer = LocalPresenceExplainer(presence.backend, "synthetic-presence", router=UnavailableRouter())
    with pytest.raises(dh.DataHandlingRefused, match="binding"):
        await explainer.explain(presence.decision)
    assert presence.requests == []


@pytest.mark.asyncio
async def test_presence_inference_is_independent_of_refused_explanation(presence):
    presence.backend.base_url = "https://synthetic.invalid/v1"
    before = presence.decision.to_dict()
    with pytest.raises(dh.DataHandlingRefused):
        await LocalPresenceExplainer.from_router(presence.router).explain(presence.decision)
    assert presence.engine.current_presence("Alice Example").to_dict() == before
    assert presence.requests == []


@pytest.mark.asyncio
async def test_revocation_between_physical_requests_prevents_retry(presence):
    from agents.core.llm.egress import llm_async_client

    presence.backend.base_url = "https://synthetic.invalid/v1"
    row = dh.posture(presence.router)["providers"][0]
    dh.acknowledge(presence.router, row["provider"], True, row["scope"], presence.audit)
    sent = []
    async def transport(request):
        sent.append(request)
        await asyncio.sleep(0)
        dh.acknowledge(presence.router, row["provider"], False, row["scope"], presence.audit)
        return httpx.Response(401)
    client = llm_async_client("lm-studio", transport=httpx.MockTransport(transport))
    async def generate(model, prompt, **kwargs):
        await client.post(presence.backend.base_url + "/first", json={"prompt": prompt})
        try:
            await client.post(presence.backend.base_url + "/retry", json={"prompt": prompt})
        except Exception:
            return "adapter swallowed refusal"
        return "unexpected retry"
    presence.backend.generate = generate
    try:
        with pytest.raises(dh.DataHandlingRefused, match="acknowledg"):
            await LocalPresenceExplainer.from_router(presence.router).explain(presence.decision)
        assert len(sent) == 1
    finally:
        await client.aclose()
