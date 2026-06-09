"""HF-7: the admin localhost-fallback must fail closed behind a reverse proxy.

When no JARVIS_ADMIN_TOKEN is set, admin is allowed only from direct localhost.
Behind nginx/ingress, request.client.host becomes the proxy IP (often 127.0.0.1),
so a forwarding header means the localhost check can't be trusted → require a token.
"""
import sys
from pathlib import Path

import pytest
from starlette.datastructures import Headers
from fastapi import HTTPException

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402


class _FakeReq:
    def __init__(self, headers=None, host="127.0.0.1"):
        self.headers = Headers(headers or {})
        self.client = type("C", (), {"host": host})()


@pytest.mark.asyncio
async def test_admin_guard_fails_closed_behind_proxy(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    # Direct localhost, no proxy headers → allowed (no raise).
    await web._admin_guard(_FakeReq(host="127.0.0.1"))
    # Localhost client BUT X-Forwarded-For present (reverse proxy) → denied.
    with pytest.raises(HTTPException) as ei:
        await web._admin_guard(_FakeReq({"x-forwarded-for": "9.9.9.9"}, host="127.0.0.1"))
    assert ei.value.status_code == 403
    # Plain non-localhost client → denied.
    with pytest.raises(HTTPException):
        await web._admin_guard(_FakeReq(host="10.0.0.5"))


@pytest.mark.asyncio
async def test_trusted_proxy_uses_forwarded_client_ip(monkeypatch):
    """With JARVIS_TRUSTED_PROXY on, the localhost gate reads the real client IP
    from X-Forwarded-For instead of failing closed (HF-7 opt-in)."""
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    monkeypatch.setattr(web, "TRUSTED_PROXY", True)
    # Trusted proxy forwards a localhost client → allowed.
    await web._admin_guard(_FakeReq({"x-forwarded-for": "127.0.0.1"}, host="10.0.0.1"))
    # Trusted proxy forwards a remote client → still denied.
    with pytest.raises(HTTPException) as ei:
        await web._admin_guard(_FakeReq({"x-forwarded-for": "9.9.9.9"}, host="10.0.0.1"))
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_guard_token_path_unaffected(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "secret")
    # A wrong token is 401 regardless of host/proxy (token path runs first).
    with pytest.raises(HTTPException) as ei:
        await web._admin_guard(_FakeReq({"x-admin-token": "wrong"}, host="127.0.0.1"))
    assert ei.value.status_code == 401
    # The correct token passes.
    await web._admin_guard(_FakeReq({"x-admin-token": "secret", "x-forwarded-for": "1.2.3.4"}))
