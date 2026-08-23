"""SEC-B4: OAuth token calls use the pinned plugin egress boundary."""

import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.http_client import PluginEgressError, PluginHTTPClient
from agents.core.plugins import oauth


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return httpx.Response(200, json={"access_token": "new-token"}, request=request)


class Boundary:
    client = None
    names = []

    @classmethod
    def for_plugin(cls, name):
        cls.names.append(name)
        return cls.client


async def test_google_exchange_uses_plugin_boundary_with_post_body_and_no_redirects(monkeypatch, tmp_path):
    transport = RecordingTransport()
    Boundary.client = PluginHTTPClient(
        "google-calendar",
        resolver=lambda _host, *, mode: (["142.250.72.106"], None),
        transport_factory=lambda _target: transport,
    )
    Boundary.names = []
    monkeypatch.setattr(oauth, "PluginHTTPClient", Boundary, raising=False)
    real_async_client = httpx.AsyncClient

    def guarded_async_client(*args, **kwargs):
        if kwargs.get("transport") is None:
            pytest.fail("direct OAuth client")
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(oauth.httpx, "AsyncClient", guarded_async_client)
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    monkeypatch.setattr(oauth, "_fernet", None)
    oauth.GOOGLE_CLIENT_ID = "client-id"
    oauth.GOOGLE_CLIENT_SECRET = "client-secret"

    result = await oauth.exchange_google_code("code-value", "missing-state")

    assert result is not None and result["access_token"] != ""
    assert Boundary.names == ["google-calendar"]
    [request] = transport.requests
    assert request.url.host == "142.250.72.106"
    assert request.headers["host"] == "oauth2.googleapis.com"
    assert request.extensions["sni_hostname"] == "oauth2.googleapis.com"
    assert b"code=code-value" in request.content
    await Boundary.client.close()


async def test_oauth_unsafe_dns_answer_opens_no_transport(monkeypatch):
    transport = RecordingTransport()
    Boundary.client = PluginHTTPClient(
        "google-calendar",
        resolver=lambda _host, *, mode: (["127.0.0.1"], None),
        transport_factory=lambda _target: transport,
    )
    Boundary.names = []
    monkeypatch.setattr(oauth, "PluginHTTPClient", Boundary, raising=False)
    real_async_client = httpx.AsyncClient

    def guarded_async_client(*args, **kwargs):
        if kwargs.get("transport") is None:
            pytest.fail("direct OAuth client")
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(oauth.httpx, "AsyncClient", guarded_async_client)

    with pytest.raises(PluginEgressError, match="unsafe"):
        await oauth.exchange_google_code("code-value")

    assert Boundary.names == ["google-calendar"]
    assert transport.requests == []
    await Boundary.client.close()


async def test_spotify_exchange_preserves_basic_authorization_through_pinned_boundary(monkeypatch, tmp_path):
    transport = RecordingTransport()
    Boundary.client = PluginHTTPClient(
        "spotify",
        resolver=lambda _host, *, mode: (["104.199.65.124"], None),
        transport_factory=lambda _target: transport,
    )
    Boundary.names = []
    monkeypatch.setattr(oauth, "PluginHTTPClient", Boundary, raising=False)
    real_async_client = httpx.AsyncClient

    def guarded_async_client(*args, **kwargs):
        if kwargs.get("transport") is None:
            pytest.fail("direct OAuth client")
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(oauth.httpx, "AsyncClient", guarded_async_client)
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    monkeypatch.setattr(oauth, "_fernet", None)
    oauth.SPOTIFY_CLIENT_ID = "spotify-id"
    oauth.SPOTIFY_CLIENT_SECRET = "spotify-secret"

    result = await oauth.exchange_spotify_code("code-value", "missing-state")

    assert result is not None
    assert Boundary.names == ["spotify"]
    [request] = transport.requests
    assert request.method == "POST"
    assert request.url.host == "104.199.65.124"
    assert request.headers["host"] == "accounts.spotify.com"
    assert request.extensions["sni_hostname"] == "accounts.spotify.com"
    assert request.headers["authorization"].startswith("Basic ")
    assert b"code=code-value" in request.content
    await Boundary.client.close()
