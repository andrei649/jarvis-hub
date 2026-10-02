"""Synthetic Nous Portal device and refresh exchanges; no provider traffic."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.parse import parse_qs

import httpx
import pytest

from agents.core.llm import nous_auth
from agents.core.llm.nous_auth import NousAuthError, NousAuthService
from agents.core.llm.nous_credentials import NousAuthStore


def _jwt(exp: int | None, scope: str | None = "inference:invoke") -> str:
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    payload = {}
    if exp is not None:
        payload["exp"] = exp
    if scope is not None:
        payload["scope"] = scope
    return f"{part({'alg': 'HS256'})}.{part(payload)}.sig"


class _Store:
    def __init__(self):
        self.rows = {}
        self.lock = threading.RLock()

    def read(self, profile="default"):
        with self.lock:
            return dict(self.rows.get(profile, {}))

    @contextmanager
    def transaction(self, profile="default"):
        with self.lock:
            state = dict(self.rows.get(profile, {}))
            yield state
            if state:
                self.rows[profile] = state
            else:
                self.rows.pop(profile, None)


def _service(store, handler, now, **env):
    settings = {"JARVIS_NOUS_CLIENT_ID": "nerva-test-public-client", **env}
    def factory(_backend, **kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    return NousAuthService(store, env=settings, client_factory=factory, clock=lambda: now[0])


def _login_handler(request):
    assert request.method == "POST"
    assert request.url == "https://portal.nousresearch.com/api/oauth/device/code"
    assert parse_qs(request.content.decode()) == {"client_id": ["nerva-test-public-client"], "scope": ["inference:invoke"]}
    assert "authorization" not in request.headers and "cookie" not in request.headers
    return httpx.Response(200, json={
        "device_code": "private-device-code", "user_code": "VISIBLE-CODE",
        "verification_uri": "https://portal.nousresearch.com/device",
        "verification_uri_complete": "https://portal.nousresearch.com/device?user_code=VISIBLE-CODE",
        "expires_in": 600, "interval": 5,
    })


def test_device_flow_is_secret_free_rate_limited_and_keeps_previous_credentials():
    now = [1_800_000_000]
    store = _Store()
    old = _jwt(now[0] + 3600)
    store.rows["default"] = {"access_token": old, "refresh_token": "old-refresh", "scope": "inference:invoke",
                             "portal_base_url": "https://portal.nousresearch.com", "client_id": "nerva-test-public-client"}
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/device/code"):
            return _login_handler(request)
        assert parse_qs(request.content.decode()) == {
            "grant_type": ["urn:ietf:params:oauth:grant-type:device_code"],
            "client_id": ["nerva-test-public-client"], "device_code": ["private-device-code"],
        }
        return httpx.Response(400, json={"error": "slow_down", "error_description": "secret-text"})

    service = _service(store, handle, now)
    started = service.start_login()
    assert set(started) == {"login_id", "user_code", "verification_uri", "verification_uri_complete", "expires_in", "interval"}
    assert "private-device-code" not in repr(started)
    assert store.read()["pending"]["device_code"] == "private-device-code"
    assert service.poll_login("default", started["login_id"]) == {"state": "pending", "retry_after": 5}
    assert len(calls) == 1
    now[0] += 5
    assert service.poll_login("default", started["login_id"]) == {"state": "pending", "retry_after": 10}
    assert service.poll_login("default", started["login_id"]) == {"state": "pending", "retry_after": 10}
    assert len(calls) == 2
    assert store.read()["access_token"] == old
    now[0] += 601
    assert service.poll_login("default", started["login_id"]) == {"state": "expired"}
    assert "pending" not in store.read()


def test_poll_success_replaces_tokens_only_after_valid_inference_jwt():
    now = [1_800_000_000]
    store = _Store()
    access = _jwt(now[0] + 3600)
    def handle(request):
        if request.url.path.endswith("/device/code"):
            return _login_handler(request)
        return httpx.Response(200, json={"access_token": access, "refresh_token": "rotated", "scope": "inference:invoke", "expires_in": 3600})
    service = _service(store, handle, now)
    login = service.start_login()
    now[0] += 5
    assert service.poll_login("default", login["login_id"]) == {"state": "complete"}
    assert store.read()["access_token"] == access
    assert store.read()["refresh_token"] == "rotated"
    assert service.status() == {"profile": "default", "authenticated": True, "usable": True, "has_refresh_token": True}
    assert service.logout() == {"profile": "default", "authenticated": False, "usable": False, "has_refresh_token": False}
    assert store.read() == {}


def test_refresh_header_only_peer_adoption_and_terminal_quarantine():
    now = [1_800_000_000]
    store = _Store()
    stale = _jwt(now[0] - 1)
    fresh = _jwt(now[0] + 3600)
    store.rows["default"] = {"access_token": stale, "refresh_token": "private-refresh", "scope": "inference:invoke",
                             "portal_base_url": "https://portal.nousresearch.com", "client_id": "nerva-test-public-client"}
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers["x-nous-refresh-token"] == "private-refresh"
        assert "private-refresh" not in request.content.decode()
        assert parse_qs(request.content.decode()) == {"grant_type": ["refresh_token"], "client_id": ["nerva-test-public-client"]}
        return httpx.Response(200, json={"access_token": fresh, "refresh_token": "new-refresh", "expires_in": 3600})
    service = _service(store, handle, now)
    credentials = service.prepare_credentials()
    assert credentials.api_key == fresh
    assert "private-refresh" not in repr(credentials) and fresh not in repr(credentials)
    assert store.read()["refresh_token"] == "new-refresh"
    assert service.prepare_credentials(force_refresh=True, stale_access_token=stale).api_key == fresh
    assert len(calls) == 1

    store.rows["default"] = {"access_token": stale, "refresh_token": "dead-refresh", "scope": "inference:invoke",
                             "portal_base_url": "https://portal.nousresearch.com", "client_id": "nerva-test-public-client"}
    def rejected(request):
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "private-refresh-secret"})
    service = _service(store, rejected, now)
    with pytest.raises(NousAuthError) as exc:
        service.prepare_credentials()
    assert exc.value.reason == "reauth_required"
    assert "private" not in str(exc.value)
    assert "refresh_token" not in store.read() and "access_token" not in store.read()
    assert store.read()["quarantine_reason"] == "reauth_required"


def test_transient_refresh_and_hostile_urls_do_not_disclose_or_redirect():
    now = [1_800_000_000]
    store = _Store()
    stale = _jwt(now[0] - 1)
    store.rows["default"] = {"access_token": stale, "refresh_token": "keep-me", "scope": "inference:invoke",
                             "portal_base_url": "https://portal.nousresearch.com", "client_id": "nerva-test-public-client",
                             "inference_base_url": "https://attacker.example/steal"}
    urls = []
    def denied(request):
        urls.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://attacker.example/steal"})
    service = _service(store, denied, now)
    with pytest.raises(NousAuthError) as exc:
        service.prepare_credentials()
    assert exc.value.reason == "temporarily_unavailable"
    assert urls == ["https://portal.nousresearch.com/api/oauth/token"]
    assert store.read()["refresh_token"] == "keep-me"

    def hostile(request):
        payload = _login_handler(request).json()
        payload["verification_uri_complete"] = "https://attacker.example/device?token=private-device-code"
        return httpx.Response(200, json=payload)
    with pytest.raises(NousAuthError) as exc:
        _service(_Store(), hostile, now).start_login()
    assert exc.value.reason == "invalid_response"


@pytest.mark.parametrize("malformed_error", [[], {"private": "diagnostic"}])
@pytest.mark.parametrize("status", [200, 400, 401, 503])
def test_malformed_refresh_error_preserves_rotation_or_classifies_http_status(malformed_error, status):
    now = [1_800_000_000]
    store = _Store()
    stale, fresh = _jwt(now[0] - 1), _jwt(now[0] + 3600)
    store.rows["default"] = {
        "access_token": stale, "refresh_token": "old-grant", "scope": "inference:invoke",
        "portal_base_url": "https://portal.nousresearch.com", "client_id": "nerva-test-public-client",
    }
    payload = {"error": malformed_error}
    if status == 200:
        payload.update(access_token=fresh, refresh_token="new-grant", expires_in=3600)
    service = _service(store, lambda request: httpx.Response(status, json=payload), now)
    if status == 200:
        assert service.prepare_credentials().api_key == fresh
        assert store.read()["refresh_token"] == "new-grant"
    else:
        with pytest.raises(NousAuthError) as exc:
            service.prepare_credentials()
        assert exc.value.reason == ("reauth_required" if status == 401 else "temporarily_unavailable")
        if status == 401:
            assert "refresh_token" not in store.read()
        else:
            assert store.read()["refresh_token"] == "old-grant"
            assert store.read()["access_token"] == stale


@pytest.mark.parametrize("malformed_error", [[], {"private": "diagnostic"}])
def test_malformed_poll_error_keeps_pending_login_and_rate_limit(malformed_error):
    now = [1_800_000_000]
    store = _Store()
    def handle(request):
        if request.url.path.endswith("/device/code"):
            return _login_handler(request)
        return httpx.Response(503, json={"error": malformed_error})
    service = _service(store, handle, now)
    login = service.start_login()
    now[0] += 5
    assert service.poll_login("default", login["login_id"]) == {"state": "pending", "retry_after": 5}
    assert store.read()["pending"]["next_poll_at"] == now[0] + 5


@pytest.mark.parametrize("claims", [b"[]", b"[" * 1100 + b"0" + b"]" * 1100], ids=["list", "nested-list"])
def test_malformed_jwt_claims_still_persist_rotated_refresh_grant(claims):
    now = [1_800_000_000]
    store = _Store()
    stale = _jwt(now[0] - 1)
    header = stale.split(".")[0]
    broken = f"{header}.{base64.urlsafe_b64encode(claims).rstrip(b'=').decode()}.sig"
    store.rows["default"] = {
        "access_token": stale, "refresh_token": "old-grant", "scope": "inference:invoke",
        "portal_base_url": "https://portal.nousresearch.com", "client_id": "nerva-test-public-client",
    }
    service = _service(store, lambda request: httpx.Response(200, json={
        "access_token": broken, "refresh_token": "rotated-grant", "expires_in": 3600,
    }), now)
    with pytest.raises(NousAuthError) as exc:
        service.prepare_credentials()
    assert exc.value.reason == "unusable_token"
    assert store.read()["access_token"] == broken
    assert store.read()["refresh_token"] == "rotated-grant"


def test_missing_client_id_prevents_network_and_missing_inference_scope_never_usable():
    now = [1_800_000_000]
    store = _Store()
    called = []
    service = _service(store, lambda request: called.append(request), now, JARVIS_NOUS_CLIENT_ID="")
    with pytest.raises(NousAuthError) as exc:
        service.start_login()
    assert exc.value.reason == "client_id_required" and called == []

    store.rows["default"] = {"access_token": _jwt(now[0] + 3600, "profile:read"), "scope": "profile:read",
                             "portal_base_url": "https://portal.nousresearch.com", "client_id": "nerva-test-public-client"}
    service = _service(store, lambda request: called.append(request), now)
    with pytest.raises(NousAuthError) as exc:
        service.prepare_credentials()
    assert exc.value.reason == "reauth_required" and called == []


def test_two_service_instances_adopt_one_rotated_refresh_under_encrypted_store(tmp_path):
    now = [1_800_000_000]
    path = tmp_path / "nous.sqlite3"
    store_a, store_b = NousAuthStore(path), NousAuthStore(path)
    stale, fresh = _jwt(now[0] - 1), _jwt(now[0] + 3600)
    with store_a.transaction() as state:
        state.update(access_token=stale, refresh_token="secret-rotating-grant", scope="inference:invoke",
                     portal_base_url="https://portal.nousresearch.com", client_id="nerva-test-public-client")
    entered, release = threading.Event(), threading.Event()
    calls = []
    def exchange(request):
        calls.append(request)
        entered.set()
        assert release.wait(timeout=3)
        return httpx.Response(200, json={"access_token": fresh, "refresh_token": "new-grant", "scope": "inference:invoke"})
    first = _service(store_a, exchange, now)
    second = _service(store_b, exchange, now)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first.prepare_credentials, force_refresh=True, stale_access_token=stale)
        assert entered.wait(timeout=3)
        b = pool.submit(second.prepare_credentials, force_refresh=True, stale_access_token=stale)
        release.set()
        assert a.result(timeout=5).api_key == fresh
        assert b.result(timeout=5).api_key == fresh
    assert len(calls) == 1
    assert store_b.read()["refresh_token"] == "new-grant"
    assert b"secret-rotating-grant" not in path.read_bytes()


def test_client_id_change_before_physical_send_blocks_device_request():
    now = [1_800_000_000]
    env = {"JARVIS_NOUS_CLIENT_ID": "original-client"}
    calls = []
    def factory(_backend, **kwargs):
        env["JARVIS_NOUS_CLIENT_ID"] = "new-client"
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request)), **kwargs)
    service = NousAuthService(_Store(), env=env, client_factory=factory, clock=lambda: now[0])
    with pytest.raises(NousAuthError) as exc:
        service.start_login()
    assert exc.value.reason == "invalid_configuration"
    assert calls == []


def test_late_hook_mutation_is_refused_at_physical_transport():
    now = [1_800_000_000]
    physical = []
    def factory(_backend, **kwargs):
        async def late_hook(request):
            request.headers["x-nous-refresh-token"] = "late-secret"
        hooks = kwargs.pop("event_hooks", {"request": []})
        hooks["request"].append(late_hook)
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: physical.append(request)),
                                 event_hooks=hooks, **kwargs)
    service = NousAuthService(_Store(), env={"JARVIS_NOUS_CLIENT_ID": "public-client"},
                              client_factory=factory, clock=lambda: now[0])
    with pytest.raises(NousAuthError) as exc:
        service.start_login()
    assert exc.value.reason == "invalid_configuration"
    assert physical == []


def test_total_deadline_covers_slow_response_body(monkeypatch):
    now = [1_800_000_000]
    monkeypatch.setattr(nous_auth, "_REQUEST_DEADLINE_SECONDS", 0.05)
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.2)
            yield b'{}'
    def factory(_backend, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=SlowBody())), **kwargs)
    service = NousAuthService(_Store(), env={"JARVIS_NOUS_CLIENT_ID": "public-client"},
                              client_factory=factory, clock=lambda: now[0])
    with pytest.raises(NousAuthError) as exc:
        service.start_login()
    assert exc.value.reason == "temporarily_unavailable"


def test_issuer_change_refuses_poll_and_refresh_without_sending_credentials():
    now = [1_800_000_000]
    env = {"JARVIS_NOUS_CLIENT_ID": "nerva-test-public-client"}
    sent = []
    def factory(_backend, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: sent.append(request) or _login_handler(request)), **kwargs)
    store = _Store()
    service = NousAuthService(store, env=env, client_factory=factory, clock=lambda: now[0])
    login = service.start_login()
    env["JARVIS_NOUS_CLIENT_ID"] = "another-public-client"
    now[0] += 5
    with pytest.raises(NousAuthError) as exc:
        service.poll_login("default", login["login_id"])
    assert exc.value.reason == "invalid_configuration" and len(sent) == 1

    store.rows["default"] = {"access_token": _jwt(now[0] - 1), "refresh_token": "keep-secret",
                             "scope": "inference:invoke", "portal_base_url": "https://portal.nousresearch.com",
                             "client_id": "nerva-test-public-client"}
    with pytest.raises(NousAuthError) as exc:
        service.prepare_credentials()
    assert exc.value.reason == "invalid_configuration" and len(sent) == 1
    assert store.read()["refresh_token"] == "keep-secret"


def test_logout_waiting_on_issuance_removes_pending_flow(tmp_path):
    now = [1_800_000_000]
    store = NousAuthStore(tmp_path / "nous.sqlite3")
    entered, release, logout_started = threading.Event(), threading.Event(), threading.Event()
    def handler(request):
        entered.set()
        assert release.wait(timeout=3)
        return _login_handler(request)
    service = _service(store, handler, now)
    def logout():
        logout_started.set()
        return service.logout()
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = pool.submit(service.start_login)
        assert entered.wait(timeout=3)
        cleared = pool.submit(logout)
        assert logout_started.wait(timeout=3)
        release.set()
        assert started.result(timeout=5)["login_id"]
        assert cleared.result(timeout=5)["authenticated"] is False
    assert store.read() == {}


def test_edge_challenge_retains_rotating_grant_even_with_oauth_error_body():
    now = [1_800_000_000]
    store = _Store()
    store.rows["default"] = {"access_token": _jwt(now[0] - 1), "refresh_token": "keep-secret",
                             "scope": "inference:invoke", "portal_base_url": "https://portal.nousresearch.com",
                             "client_id": "nerva-test-public-client"}
    def handler(request):
        return httpx.Response(403, headers={"x-vercel-mitigated": "challenge"},
                              json={"error": "invalid_grant", "error_description": "untrusted"})
    service = _service(store, handler, now)
    with pytest.raises(NousAuthError) as exc:
        service.prepare_credentials()
    assert exc.value.reason == "temporarily_unavailable"
    assert store.read()["refresh_token"] == "keep-secret"


def test_device_jwt_without_exp_uses_finite_response_ttl():
    now = [1_800_000_000]
    token = _jwt(None)
    store = _Store()
    def handler(request):
        if request.url.path.endswith("/device/code"):
            return _login_handler(request)
        return httpx.Response(200, json={"access_token": token, "refresh_token": "grant", "expires_in": 3600})
    service = _service(store, handler, now)
    login = service.start_login()
    now[0] += 5
    assert service.poll_login("default", login["login_id"]) == {"state": "complete"}
    assert store.read()["expires_at"] == now[0] + 3600
    assert service.prepare_credentials().expires_at == now[0] + 3600


def test_refresh_without_scope_retains_existing_declared_scope():
    now = [1_800_000_000]
    token = _jwt(now[0] + 3600, None)
    store = _Store()
    store.rows["default"] = {"access_token": _jwt(now[0] - 1), "refresh_token": "grant",
                             "scope": "inference:invoke", "portal_base_url": "https://portal.nousresearch.com",
                             "client_id": "nerva-test-public-client"}
    service = _service(store, lambda request: httpx.Response(200, json={"access_token": token,
                                                                          "refresh_token": "rotated"}), now)
    assert service.prepare_credentials().api_key == token
    assert store.read()["scope"] == "inference:invoke"


def test_inference_override_is_runtime_only_and_network_base_is_preserved():
    now = [1_800_000_000]
    store = _Store()
    token = _jwt(now[0] + 3600)
    env = {"JARVIS_NOUS_CLIENT_ID": "nerva-test-public-client",
           "JARVIS_NOUS_INFERENCE_BASE_URL": "https://staging.example/v1"}
    def factory(_backend, **kwargs):
        def handler(request):
            if request.url.path.endswith("/device/code"):
                return _login_handler(request)
            return httpx.Response(200, json={"access_token": token, "refresh_token": "grant",
                                              "inference_base_url": "https://welcome-api.nousresearch.com/v1"})
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    service = NousAuthService(store, env=env, client_factory=factory, clock=lambda: now[0])
    login = service.start_login()
    now[0] += 5
    assert service.poll_login("default", login["login_id"]) == {"state": "complete"}
    assert store.read()["inference_base_url"] == "https://welcome-api.nousresearch.com/v1"
    assert service.prepare_credentials().base_url == "https://staging.example/v1"
    env.pop("JARVIS_NOUS_INFERENCE_BASE_URL")
    assert service.prepare_credentials().base_url == "https://welcome-api.nousresearch.com/v1"


def test_network_base_equal_to_explicit_override_is_accepted_only_while_configured():
    now = [1_800_000_000]
    store = _Store()
    override = "https://staging.example:8443/v1"
    env = {"JARVIS_NOUS_CLIENT_ID": "nerva-test-public-client",
           "JARVIS_NOUS_INFERENCE_BASE_URL": override}
    def factory(_backend, **kwargs):
        def handler(request):
            if request.url.path.endswith("/device/code"):
                return _login_handler(request)
            return httpx.Response(200, json={"access_token": _jwt(now[0] + 3600),
                                              "inference_base_url": override})
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    service = NousAuthService(store, env=env, client_factory=factory, clock=lambda: now[0])
    login = service.start_login()
    now[0] += 5
    assert service.poll_login("default", login["login_id"]) == {"state": "complete"}
    assert store.read()["inference_base_url"] == override
    env.pop("JARVIS_NOUS_INFERENCE_BASE_URL")
    assert service.prepare_credentials().base_url == "https://inference-api.nousresearch.com/v1"


def test_huge_jwt_expiry_keeps_rotated_refresh_grant_before_safe_error():
    now = [1_800_000_000]
    store = _Store()
    store.rows["default"] = {"access_token": _jwt(now[0] - 1), "refresh_token": "old-grant",
                             "scope": "inference:invoke", "portal_base_url": "https://portal.nousresearch.com",
                             "client_id": "nerva-test-public-client"}
    huge_expiry_token = _jwt(10**1000)
    service = _service(store, lambda request: httpx.Response(200, json={
        "access_token": huge_expiry_token, "refresh_token": "new-grant", "expires_in": 3600,
    }), now)
    with pytest.raises(NousAuthError) as exc:
        service.prepare_credentials()
    assert exc.value.reason == "unusable_token"
    assert store.read()["refresh_token"] == "new-grant"


def test_encoded_private_device_code_is_never_returned_in_verification_url():
    now = [1_800_000_000]
    store = _Store()
    def handler(request):
        payload = _login_handler(request).json()
        payload["device_code"] = "private+device"
        payload["verification_uri_complete"] = (
            "https://portal.nousresearch.com/device?device_code=private%2Bdevice"
        )
        return httpx.Response(200, json=payload)
    service = _service(store, handler, now)
    with pytest.raises(NousAuthError) as exc:
        service.start_login()
    assert exc.value.reason == "invalid_response"
    assert store.read() == {}


def test_device_declared_scope_list_remains_usable_after_completion():
    now = [1_800_000_000]
    store = _Store()
    token = _jwt(now[0] + 3600, "openid")
    def handler(request):
        if request.url.path.endswith("/device/code"):
            return _login_handler(request)
        return httpx.Response(200, json={"access_token": token, "refresh_token": "grant",
                                          "scope": ["inference:invoke"]})
    service = _service(store, handler, now)
    login = service.start_login()
    now[0] += 5
    assert service.poll_login("default", login["login_id"]) == {"state": "complete"}
    assert store.read()["scope"] == ["inference:invoke"]
    assert service.status()["usable"] is True
