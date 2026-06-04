"""HF-1: user-facing routes (assistant, personal memory, notes, code exec)
must not be reachable unauthenticated on a network.

Model (one tier below the admin guard):
  - JARVIS_USER_TOKEN set  → require a matching X-User-Token (an X-Admin-Token
    also satisfies it, admin being a superset).
  - JARVIS_USER_TOKEN unset → allow only *direct* localhost, failing closed
    behind a reverse proxy (request.client.host is then the proxy IP). (HF-7)
"""
import sys
from pathlib import Path

import pytest
from starlette.datastructures import Headers
from fastapi import HTTPException
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402


class _FakeReq:
    def __init__(self, headers=None, host="127.0.0.1"):
        self.headers = Headers(headers or {})
        self.client = type("C", (), {"host": host})()


@pytest.mark.asyncio
async def test_user_guard_localhost_default(monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", "")
    # Direct localhost, no proxy headers → allowed.
    await web._user_guard(_FakeReq(host="127.0.0.1"))
    await web._user_guard(_FakeReq(host="::1"))
    # Localhost client but a forwarding header → behind a proxy → denied (HF-7).
    with pytest.raises(HTTPException) as ei:
        await web._user_guard(_FakeReq({"x-forwarded-for": "9.9.9.9"}, host="127.0.0.1"))
    assert ei.value.status_code == 403
    # Plain non-localhost client → denied.
    with pytest.raises(HTTPException) as ei2:
        await web._user_guard(_FakeReq(host="10.0.0.5"))
    assert ei2.value.status_code == 403


@pytest.mark.asyncio
async def test_user_guard_token(monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", "secret")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    # Correct token passes even from a network client / behind a proxy.
    await web._user_guard(_FakeReq({"x-user-token": "secret", "x-forwarded-for": "1.2.3.4"}, host="10.0.0.5"))
    # Wrong or missing token → 401, regardless of host.
    with pytest.raises(HTTPException) as ei:
        await web._user_guard(_FakeReq({"x-user-token": "wrong"}, host="127.0.0.1"))
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException) as ei2:
        await web._user_guard(_FakeReq(host="127.0.0.1"))
    assert ei2.value.status_code == 401


@pytest.mark.asyncio
async def test_user_guard_admin_token_is_superset(monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", "uuu")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "aaa")
    # A valid admin token satisfies the user guard too.
    await web._user_guard(_FakeReq({"x-admin-token": "aaa"}))
    # A wrong admin token (and no user token) is still 401.
    with pytest.raises(HTTPException):
        await web._user_guard(_FakeReq({"x-admin-token": "nope"}))


def test_user_guard_wired_on_chat_route(monkeypatch):
    """Integration: the guard is actually attached to a user route. We pop the
    suite-wide no-op override (conftest) so the real dependency runs."""
    web.app.dependency_overrides.pop(web._user_guard, None)
    try:
        monkeypatch.setattr(web, "USER_TOKEN", "")
        client = TestClient(web.app)  # connects as host 'testclient' (non-localhost)
        # No token, network client → blocked.
        assert client.get("/api/cognition").status_code == 403
        # With a token configured + supplied → guard passes (handler then runs).
        monkeypatch.setattr(web, "USER_TOKEN", "secret")
        assert client.get("/api/cognition", headers={"X-User-Token": "secret"}).status_code != 403
        # Token configured but absent → blocked.
        assert client.get("/api/cognition").status_code == 401
    finally:
        web.app.dependency_overrides[web._user_guard] = lambda: None
