"""Owner ChatGPT plan registration and model discovery, using only signed synthetic data."""
import asyncio
import base64
import hashlib
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from agents.core import chatgpt_connection as connection
from agents.core import managed_scope
from agents.core.http_client import PluginHTTPClient
from agents.core.llm import data_handling
from agents.core.llm.nous_credentials import NousAuthStore
from agents.core.secrets import SecretStore

CALLBACK = "http://127.0.0.1:54321/api/oauth/chatgpt/callback"
CLIENT = "oaiapp_synthetic"
BINDING = "synthetic-browser-binding"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
_native_store = connection._store


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64int(value):
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


@pytest.fixture
def provider(tmp_path, monkeypatch):
    store = NousAuthStore(tmp_path / "protected.sqlite3", cipher=SecretStore(tmp_path / "key-source"))
    monkeypatch.setattr(connection, "_store", lambda **kwargs: store)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()
    scenario = SimpleNamespace(calls=[], claims={}, token_fields={}, form=None, pause=None,
                               wrong_signature=False, catalog_code=200, headers={}, query={})
    def token():
        claims = {"iss": "https://auth.openai.com", "aud": [CLIENT], "sub": "owner-one",
                  "exp": int(time.time()) + 3600, "iat": int(time.time()),
                  "nonce": scenario.query["nonce"][0], **scenario.claims}
        parts = [b64(json.dumps(obj).encode()) for obj in ({"alg": "RS256", "kid": "one"}, claims)]
        signed = ".".join(parts).encode()
        signature = private.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        return ".".join([*parts, b64(b"invalid" if scenario.wrong_signature else signature)])

    async def reply(request):
        host, path = request.headers["host"], request.url.path
        scenario.calls.append((request.method, host, path))
        if host == "auth.openai.com" and path == "/api/accounts/oauth/token":
            form = parse_qs(request.content.decode())
            scenario.form = form
            assert "authorization" not in request.headers
            assert form["client_id"] == [CLIENT] and form["resource"] == ["https://api.openai.com/v1"]
            if form["grant_type"] == ["authorization_code"]:
                assert form["redirect_uri"] == [CALLBACK]
                verifier = form["code_verifier"][0].encode()
                assert b64(hashlib.sha256(verifier).digest()) == scenario.query["code_challenge"][0]
            if scenario.pause:
                started, release = scenario.pause
                started.set()
                await release.wait()
            data = {"access_token": "plan-access", "refresh_token": "plan-refresh", "token_type": "Bearer",
                    "id_token": token(), "scope": SCOPES, "expires_in": 3600, **scenario.token_fields}
        elif host == "auth.openai.com" and path == "/.well-known/jwks.json":
            assert "authorization" not in request.headers
            data = {"keys": [{"kty": "RSA", "kid": "one", "alg": "RS256", "use": "sig",
                              "n": b64int(public.n), "e": b64int(public.e)}]}
        elif host == "api.openai.com" and path == "/v1/models":
            scenario.headers = dict(request.headers)
            if scenario.catalog_code != 200:
                return httpx.Response(scenario.catalog_code, headers={"Location": "https://other.invalid/catalog"},
                                      json={"error": "private remote detail"})
            data = {"models": [{"slug": "second", "display_name": "Second", "visibility": "list", "extra": 1},
                               {"slug": "hidden", "display_name": "Hidden", "visibility": "hide"},
                               {"slug": "first", "display_name": "First", "visibility": "list"}]}
        else:
            pytest.fail(f"unexpected request to {host}{path}")
        return httpx.Response(200, json=data)

    monkeypatch.setattr(connection, "_http", lambda: PluginHTTPClient(
        "chatgpt-connection-test", resolver=lambda *args, **kw: (["93.184.216.34"], None),
        transport_factory=lambda target: httpx.MockTransport(reply)))
    def start():
        result = connection.start(CALLBACK, BINDING)
        parsed = urlsplit(result["url"])
        assert (parsed.scheme, parsed.netloc, parsed.path) == ("https", "auth.openai.com", "/api/accounts/authorize")
        scenario.query = parse_qs(parsed.query)
        assert scenario.query["state"] == [result["state"]] and scenario.query["code_challenge_method"] == ["S256"]
        return result["state"]
    scenario.start = start
    return scenario


async def connect(s):
    return await connection.complete(s.start(), BINDING, code="owner-code", client_id=CLIENT, error=None)


def test_settings_status_leaves_pristine_profile_untouched(tmp_path, monkeypatch):
    profile = tmp_path / "never-connected"
    monkeypatch.setenv("JARVIS_HOME", str(profile))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.setattr(connection, "_http", lambda: pytest.fail("status made a network request"))
    assert connection.status() == {"connected": False}
    assert not profile.exists()


@pytest.mark.asyncio
async def test_malformed_token_type_is_a_public_provider_error(provider):
    provider.token_fields["token_type"] = ["Bearer"]
    with pytest.raises(connection.ConnectionError, match="invalid_token_response") as failure:
        await connect(provider)
    assert failure.value.status == 502
    assert connection.status() == {"connected": False}


@pytest.mark.asyncio
async def test_register_catalog_reauthorize_and_forget(provider):
    s = provider
    assert connection.status() == {"connected": False}
    state = s.start()
    host_id = s.query["ext_agent_host_id"]
    assert s.query["client_id"] == ["dynamic_agent_client"] and s.query["agent_name_hint"] == ["Nerva"]
    assert set(s.query["scope"][0].split()) == set(SCOPES.split())
    assert await connection.complete(state, BINDING, code="first", client_id=CLIENT) == {"connected": True}
    assert connection.status() == {"connected": True}
    assert await connection.models() == {"models": [{"slug": "second", "display_name": "Second"},
                                                   {"slug": "first", "display_name": "First"}]}
    assert s.headers["authorization"] == "Bearer plan-access"
    with pytest.raises(connection.ConnectionError):
        await connection.complete(state, BINDING, code="replay", client_id=CLIENT)
    state = s.start()
    assert s.query["client_id"] == [CLIENT] and "agent_name_hint" not in s.query
    assert "id_token_hint" not in s.query
    assert await connection.complete(state, BINDING, code="again") == {"connected": True}
    state = s.start()
    assert connection.disconnect() == {"connected": False}
    with pytest.raises(connection.ConnectionError):
        await connection.complete(state, BINDING, code="late")
    with pytest.raises(connection.ConnectionError):
        await connection.models()
    s.start()
    assert s.query["ext_agent_host_id"] == host_id and s.query["client_id"] == ["dynamic_agent_client"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("iss", "https://elsewhere.invalid"), ("aud", "other-client"),
                                         ("nonce", "other-flow"), ("exp", 123), ("iat", 2**40),
                                         ("sub", ""), ("signature", False), ("scope", "openid profile")])
async def test_reject_unverified_identity_or_plan_permission(provider, field, value):
    if field == "signature":
        provider.wrong_signature = True
    elif field == "scope":
        provider.token_fields[field] = value
    else:
        provider.claims[field] = value
    with pytest.raises(connection.ConnectionError):
        await connect(provider)
    assert connection.status() == {"connected": False}
    assert all(call[2] != "/v1/models" for call in provider.calls)
    provider.start()
    assert provider.query["client_id"] == [CLIENT if field == "scope" else "dynamic_agent_client"]


@pytest.mark.asyncio
async def test_returning_subject_or_client_mismatch_preserves_active_account(provider):
    await connect(provider)
    state = provider.start()
    before = list(provider.calls)
    with pytest.raises(connection.ConnectionError):
        await connection.complete(state, BINDING, code="again", client_id="oaiapp_other")
    assert provider.calls == before
    provider.claims["sub"] = "other-owner"
    with pytest.raises(connection.ConnectionError):
        await connection.complete(provider.start(), BINDING, code="again")
    assert connection.status() == {"connected": True}


@pytest.mark.asyncio
async def test_callback_refusal_expiry_and_binding_before_any_dispatch(provider, monkeypatch):
    for uri in ("https://127.0.0.1:1234/api/oauth/chatgpt/callback", "http://localhost:1234/api/oauth/chatgpt/callback",
                CALLBACK + "?x=1", CALLBACK.replace("callback", "other")):
        with pytest.raises(connection.ConnectionError):
            connection.start(uri, BINDING)
    state = provider.start()
    with pytest.raises(connection.ConnectionError):
        await connection.complete(state, "another-browser", code="x", client_id=CLIENT)
    with pytest.raises(connection.ConnectionError):
        await connection.complete(state, BINDING, error="access_denied")
    with pytest.raises(connection.ConnectionError):
        await connection.complete(state, BINDING, code="x", client_id=CLIENT)
    with pytest.raises(connection.ConnectionError):
        await connection.complete(provider.start(), BINDING, code="x", client_id="dynamic_agent_client")
    state = provider.start()
    now = time.time()
    monkeypatch.setattr(connection, "_now", lambda: now + 601)
    with pytest.raises(connection.ConnectionError):
        await connection.complete(state, BINDING, code="x", client_id=CLIENT)
    assert provider.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["complete", "refresh"])
async def test_disconnect_wins_over_inflight_work(provider, phase):
    if phase == "refresh":
        provider.token_fields["expires_in"] = 1
        await connect(provider)
    provider.pause = (asyncio.Event(), asyncio.Event())
    operation = asyncio.create_task(connect(provider) if phase == "complete" else connection.models())
    await asyncio.wait_for(provider.pause[0].wait(), 3)
    if phase == "refresh":
        with pytest.raises(connection.ConnectionError):
            await connection.models()
    connection.disconnect()
    provider.pause[1].set()
    with pytest.raises(connection.ConnectionError):
        await operation
    assert connection.status() == {"connected": False}
    assert all(call[2] != "/v1/models" for call in provider.calls)


@pytest.mark.asyncio
async def test_rotation_and_redirection(provider):
    provider.token_fields["expires_in"] = 1
    await connect(provider)
    provider.token_fields.update(access_token="new-access", refresh_token="new-refresh", expires_in=3600)
    await connection.models()
    assert provider.form["refresh_token"] == ["plan-refresh"]
    assert "scope" not in provider.form and provider.headers["authorization"] == "Bearer new-access"
    count = len(provider.calls)
    provider.catalog_code = 307
    with pytest.raises(connection.ConnectionError) as error:
        await connection.models()
    assert len(provider.calls) == count + 1 and "private" not in str(error.value)


@pytest.mark.asyncio
async def test_managed_configuration_changed_while_exchange_inflight(provider, monkeypatch):
    provider.pause = (asyncio.Event(), asyncio.Event())
    operation = asyncio.create_task(connect(provider))
    await asyncio.wait_for(provider.pause[0].wait(), 3)
    monkeypatch.setenv("NERVA_MANAGED", "synthetic-managed-policy")
    managed_scope.invalidate()
    provider.pause[1].set()
    with pytest.raises(connection.ConnectionError, match="managed_configuration"):
        await operation
    assert connection.status() == {"connected": False}


@pytest.mark.asyncio
async def test_routed_physical_guard_and_website_policy_block_catalog(provider, monkeypatch):
    await connect(provider)
    before = list(provider.calls)
    def refuse(request):
        raise data_handling.DataHandlingRefused("private policy information")
    with (pytest.raises(data_handling.DataHandlingRefused),
          data_handling.physical_request_scope(None, request_check=refuse),
          pytest.raises(connection.ConnectionError, match="egress_refused")):
        await connection.models()
    from agents.core.security import website_policy
    monkeypatch.setattr(website_policy, "website_refusal", lambda url: "website_blocked")
    with pytest.raises(connection.ConnectionError, match="egress_refused"):
        await connection.models()
    assert before == provider.calls


@pytest.mark.asyncio
async def test_fixed_offer_limit_and_restart_protected_native_store(tmp_path, provider, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "isolated-profile"))
    monkeypatch.setattr(connection, "_store", _native_store)
    await connect(provider)
    for _ in range(connection.MAX_PENDING):
        provider.start()
    with pytest.raises(connection.ConnectionError, match="too_many_attempts"):
        provider.start()
    database = _native_store().path
    persisted = database.read_bytes()
    assert all(value not in persisted for value in (b"owner-one", b"plan-access", b"plan-refresh", CLIENT.encode()))
    record = _native_store().read()
    assert record["subject"] == "owner-one" and record["tokens"]["refresh"] == "plan-refresh"
    assert _native_store()._get_cipher().backend == "fernet"
    connection.disconnect()
    assert set(_native_store().read()) == {"host", "generation"}
