"""Owner-only API keeps signed credential values out of responses and errors."""
import asyncio
import fcntl
import os

import httpx
import pytest

from tests.test_h361_provider_credentials import active
from tests.test_h361_provider_install_routes import HEADERS, client
from tests.test_h361_provider_install_service import owner, service

PATH = "/api/admin/llm/provider-credentials"


def test_owner_metadata_put_delete_have_no_cache_and_no_secret_echo(client, service, tmp_path):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    target = {"provider": "synthetic-addon", "package_hash": artifact["package_hash"]}
    key = "synthetic-api-secret-20261028"
    assert client.get(PATH, params=target).status_code == 401
    before = client.get(PATH, headers=HEADERS, params=target)
    assert before.status_code == 200
    assert before.json() == {"configured": False, "generation": 0}
    put = client.put(PATH, headers=HEADERS, json={**target, "value": key})
    assert put.status_code == 200
    assert put.json() == {"configured": True, "generation": 1}
    after = client.get(PATH, headers=HEADERS, params=target)
    assert after.json() == put.json()
    deleted = client.request("DELETE", PATH, headers=HEADERS, json=target)
    assert deleted.status_code == 200
    assert deleted.json() == {"configured": False, "generation": 2}
    for response in (before, put, after, deleted):
        assert "no-store" in response.headers.get("cache-control", "")
        assert key not in response.text


def test_invalid_body_never_echoes_raw_secret_or_unknown_field(client, service, tmp_path):
    _, _, _, _, _, artifact = active(service, tmp_path)
    target = {"provider": "synthetic-addon", "package_hash": artifact["package_hash"]}
    key = "synthetic-invalid-secret-20261028"
    for body in ({**target, "value": key * 400},
                 {**target, "value": key, "unexpected": key},
                 {**target, "value": [key]}):
        response = client.put(PATH, headers=HEADERS, json=body)
        assert response.status_code == 422
        assert key not in response.text
    assert client.get(PATH, headers=HEADERS, params=target).json() == {
        "configured": False, "generation": 0}


def test_disabled_flag_refuses_without_envelope(client, service, tmp_path, monkeypatch):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    monkeypatch.delenv("JARVIS_PROVIDER_PLUGINS")
    response = client.put(PATH, headers=HEADERS, json={
        "provider": "synthetic-addon", "package_hash": artifact["package_hash"],
        "value": "synthetic-disabled-key"})
    assert response.status_code == 409
    if (svc.root / "credentials").exists():
        assert not list((svc.root / "credentials").glob("*.enc"))


@pytest.mark.asyncio
async def test_cancelled_route_drains_started_credential_write(client, service, tmp_path):
    from agents import web

    svc, _, _, _, _, artifact = active(service, tmp_path)
    lock = svc._store()._lock_path
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    body = {"provider": "synthetic-addon", "package_hash": artifact["package_hash"],
            "value": "synthetic-cancelled-request-key"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://testserver") as http:
            request = asyncio.create_task(http.put(PATH, headers=HEADERS, json=body))
            await asyncio.sleep(0.1)
            request.cancel()
            await asyncio.sleep(0.1)
            assert not request.done()
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            fd = None
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, timeout=5)
    finally:
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    assert svc.credential_status(body["provider"], body["package_hash"], actor=owner()) == {
            "configured": True, "generation": 1}
