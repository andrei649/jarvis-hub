"""Synthetic Nous Portal recommendation and entitlement behavior."""

import asyncio
import base64
import json
import time

import httpx
import pytest

from agents.core.llm import nous_models
from agents.core.llm.nous_auth import NousAuthError, NousCredentials


def _token(paid_access=None):
    claims = {"exp": int(time.time()) + 3600}
    if paid_access is not None:
        claims["paid_access"] = paid_access

    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.{part({'sig': 'test'})}"


def _credentials(*, paid_access=None, profile="default", portal="https://portal.nousresearch.com", base="https://inference-api.nousresearch.com/v1"):
    return NousCredentials(profile, _token(paid_access), base, portal, int(time.time()) + 3600)


def _recommendations(paid="anthropic/claude", free="google/gemini"):
    return {
        "paidRecommendedVisionModel": {"modelName": paid} if paid else None,
        "freeRecommendedVisionModel": {"modelName": free} if free else None,
    }


@pytest.fixture(autouse=True)
def _reset_cache():
    nous_models.clear_cache()
    yield
    nous_models.clear_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "paid,expected_model,expected_source",
    [
        (False, "google/gemini", "nous_recommended_free"),
        (True, "anthropic/claude", "nous_recommended_paid"),
        (None, "anthropic/claude", "nous_recommended_paid"),
    ],
)
async def test_jwt_entitlement_selects_tier_without_bearer_on_public_request(
    monkeypatch, tmp_path, paid, expected_model, expected_source
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=_recommendations())

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    result = await nous_models.recommend_vision(_credentials(paid_access=paid), cache_dir=tmp_path)
    assert result == nous_models.Recommendation(expected_model, expected_source)
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://portal.nousresearch.com/api/nous/recommended-models"
    assert "authorization" not in requests[0].headers
    assert "cookie" not in requests[0].headers


@pytest.mark.asyncio
async def test_free_tier_never_uses_paid_pick_even_when_free_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(
        lambda request: httpx.Response(200, json=_recommendations(free=None))
    ))
    result = await nous_models.recommend_vision(_credentials(paid_access=False), cache_dir=tmp_path)
    assert result == nous_models.Recommendation("google/gemini-3.6-flash", "nous_fallback")


@pytest.mark.asyncio
async def test_explicit_refresh_uses_account_entitlement_and_only_public_data_persists(monkeypatch, tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.path == "/api/oauth/account":
            return httpx.Response(200, json={"paid_service_access": {"allowed": False}, "email": "private@example.test"})
        return httpx.Response(200, json=_recommendations())

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    creds = _credentials(paid_access=True)
    result = await nous_models.recommend_vision(creds, force_refresh=True, cache_dir=tmp_path)
    assert result == nous_models.Recommendation("google/gemini", "nous_recommended_free")
    assert [call.url.path for call in calls] == ["/api/oauth/account", "/api/nous/recommended-models"]
    assert calls[0].headers["authorization"] == f"Bearer {creds.api_key}"
    assert "authorization" not in calls[1].headers
    disk = b"".join(path.read_bytes() for path in tmp_path.iterdir() if path.is_file())
    assert b"private@example.test" not in disk
    assert creds.api_key.encode() not in disk
    assert b"paid_service_access" not in disk


@pytest.mark.asyncio
@pytest.mark.parametrize("account", [
    {"paid_access": False},
    {"subscription": {"monthly_charge": 0}},
    {"paid_service_access": {"allowed": "false", "paid_access": "false"}},
    {"error": "synthetic failure", "paid_service_access": {"allowed": False}},
])
async def test_account_does_not_infer_tier_from_unrecognized_fields(monkeypatch, tmp_path, account):
    def respond(request):
        payload = account if request.url.path == "/api/oauth/account" else _recommendations()
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    result = await nous_models.recommend_vision(
        _credentials(paid_access=True), force_refresh=True, cache_dir=tmp_path
    )
    assert result == nous_models.Recommendation("anthropic/claude", "nous_recommended_paid")


@pytest.mark.asyncio
async def test_account_uses_nested_paid_access_when_allowed_is_not_bool(monkeypatch, tmp_path):
    def respond(request):
        payload = (
            {"paid_service_access": {"allowed": "false", "paid_access": False}}
            if request.url.path == "/api/oauth/account" else _recommendations()
        )
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    result = await nous_models.recommend_vision(
        _credentials(paid_access=True), force_refresh=True, cache_dir=tmp_path
    )
    assert result == nous_models.Recommendation("google/gemini", "nous_recommended_free")


@pytest.mark.asyncio
async def test_persistent_public_cache_survives_restart_and_stale_failure(monkeypatch, tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=_recommendations(paid="model/last-good"))
        raise httpx.ConnectError("synthetic offline")

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    creds = _credentials(paid_access=True)
    assert (await nous_models.recommend_vision(creds, cache_dir=tmp_path)).model == "model/last-good"
    nous_models.clear_cache()
    assert (await nous_models.recommend_vision(creds, cache_dir=tmp_path)).model == "model/last-good"
    assert len(calls) == 1
    result = await nous_models.recommend_vision(creds, force_refresh=True, cache_dir=tmp_path)
    assert result.model == "model/last-good"


@pytest.mark.asyncio
async def test_profile_and_portal_scoping_and_welcome_short_circuit(monkeypatch, tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=_recommendations(paid=f"model/{len(calls)}"))

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    one = _credentials(paid_access=True, profile="one")
    two = _credentials(paid_access=True, profile="two")
    welcome = _credentials(paid_access=True, base="https://welcome-api.nousresearch.com/v1")
    assert (await nous_models.recommend_vision(one, cache_dir=tmp_path)).model == "model/1"
    assert (await nous_models.recommend_vision(two, cache_dir=tmp_path)).model == "model/2"
    assert await nous_models.recommend_vision(welcome, cache_dir=tmp_path) == nous_models.Recommendation("nous/welcome", "nous_welcome")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_validation_after_client_hook_prevents_physical_request(monkeypatch, tmp_path):
    sent = []

    def factory(_backend, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: (sent.append(request), httpx.Response(200, json=_recommendations()))[1])

        async def mutate(_request):
            revoked[0] = True

        kwargs["event_hooks"] = {"request": [mutate]}
        return httpx.AsyncClient(**kwargs)

    revoked = [False]

    def validate():
        if revoked[0]:
            raise NousAuthError("reauth_required")

    with pytest.raises(NousAuthError, match="reauth_required"):
        await nous_models.recommend_vision(_credentials(), validate=validate, client_factory=factory, cache_dir=tmp_path)
    assert sent == []


@pytest.mark.asyncio
async def test_validation_and_cancellation_never_degrade_to_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(asyncio.CancelledError())
    ))
    with pytest.raises(asyncio.CancelledError):
        await nous_models.recommend_vision(_credentials(), cache_dir=tmp_path)


@pytest.mark.asyncio
async def test_invalid_profile_or_portal_cannot_issue_request(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(
        lambda request: (sent.append(request), httpx.Response(200, json=_recommendations()))[1]
    ))
    with pytest.raises(NousAuthError, match="invalid_configuration"):
        await nous_models.recommend_vision(_credentials(profile="../other"), cache_dir=tmp_path)
    with pytest.raises(NousAuthError, match="invalid_configuration"):
        await nous_models.recommend_vision(_credentials(portal="http://other.example"), cache_dir=tmp_path)
    assert sent == []


@pytest.mark.asyncio
async def test_slow_stale_fetch_cannot_replace_newer_recommendation(monkeypatch, tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def respond(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            return httpx.Response(200, json=_recommendations(paid="model/old"))
        return httpx.Response(200, json=_recommendations(paid="model/new"))

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    creds = _credentials(paid_access=True)
    old = asyncio.create_task(nous_models.recommend_vision(creds, cache_dir=tmp_path))
    await started.wait()
    newer = await nous_models.recommend_vision(creds, cache_dir=tmp_path)
    release.set()
    older = await old
    assert newer.model == older.model == "model/new"
    nous_models.clear_cache()
    assert (await nous_models.recommend_vision(creds, cache_dir=tmp_path)).model == "model/new"
    assert calls == 2


@pytest.mark.asyncio
async def test_older_account_refresh_cannot_replace_newer_entitlement_or_model(monkeypatch, tmp_path):
    first_account_started = asyncio.Event()
    release_first = asyncio.Event()
    account_calls = 0
    recommendation_calls = 0

    async def respond(request):
        nonlocal account_calls, recommendation_calls
        if request.url.path == "/api/oauth/account":
            account_calls += 1
            if account_calls == 1:
                first_account_started.set()
                await release_first.wait()
                return httpx.Response(200, json={"paid_service_access": {"allowed": True}})
            return httpx.Response(200, json={"paid_service_access": {"allowed": False}})
        recommendation_calls += 1
        model = "model/new" if recommendation_calls == 1 else "model/old"
        return httpx.Response(200, json=_recommendations(paid=model, free="model/free"))

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    creds = _credentials(paid_access=True)
    older = asyncio.create_task(nous_models.recommend_vision(creds, force_refresh=True, cache_dir=tmp_path))
    await first_account_started.wait()
    newer = await nous_models.recommend_vision(creds, force_refresh=True, cache_dir=tmp_path)
    release_first.set()
    old_result = await older
    assert newer == old_result == nous_models.Recommendation("model/free", "nous_recommended_free")
    assert (await nous_models.recommend_vision(creds, cache_dir=tmp_path)).model == "model/free"
    assert recommendation_calls <= 2


@pytest.mark.asyncio
async def test_process_cache_evicts_old_profiles(monkeypatch, tmp_path):
    calls = 0

    def respond(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_recommendations(paid="model/shared"))

    monkeypatch.setattr(nous_models, "_transport_factory", lambda: httpx.MockTransport(respond))
    for number in range(33):
        await nous_models.recommend_vision(
            _credentials(paid_access=True, profile=f"profile-{number}"), cache_dir=tmp_path
        )
    assert calls == 33
    for path in tmp_path.iterdir():
        path.unlink()
    await nous_models.recommend_vision(_credentials(paid_access=True, profile="profile-0"), cache_dir=tmp_path)
    assert calls == 34


def test_wire_mode_requires_explicit_native_for_anthropic():
    assert nous_models.wire_mode("anthropic/claude") == "chat_completions"
    assert nous_models.wire_mode("anthropic/claude", "native") == "anthropic_messages"
    assert nous_models.wire_mode("anthropic/claude", "auto") == "chat_completions"
    assert nous_models.wire_mode("anthropic/claude", "bad") == "chat_completions"
    assert nous_models.wire_mode("google/gemini", "native") == "chat_completions"
