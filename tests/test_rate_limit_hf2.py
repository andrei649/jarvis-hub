"""HF-2: per-IP HTTP rate limiting + CORS knob.

The limiter is defense-in-depth on top of the HF-1 auth guard: it throttles
unauthenticated network clients (DoS / token brute-force) while exempting
localhost and *validly* authenticated requests, so the single-user HUD is never
throttled.
"""
import sys
from pathlib import Path

from starlette.datastructures import Headers
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402


class _Req:
    def __init__(self, headers=None, host="1.2.3.4"):
        self.headers = Headers(headers or {})
        self.client = type("C", (), {"host": host})()


def test_client_ip_ignores_xff_unless_proxy_trusted(monkeypatch):
    # Audit 2026-07-15: X-Forwarded-For is attacker-controlled, so without a
    # configured trusted proxy the limiter must use the unspoofable socket peer
    # (else `X-Forwarded-For: 127.0.0.1` dodges the throttle).
    monkeypatch.setattr(web, "TRUSTED_PROXY", False, raising=False)
    assert web._client_ip(_Req({"x-forwarded-for": "9.9.9.9, 1.1.1.1"}, host="5.5.5.5")) == "5.5.5.5"
    assert web._client_ip(_Req(host="5.5.5.5")) == "5.5.5.5"


def test_client_ip_prefers_first_xff_hop_when_proxy_trusted(monkeypatch):
    monkeypatch.setattr(web, "TRUSTED_PROXY", True, raising=False)
    assert web._client_ip(_Req({"x-forwarded-for": "9.9.9.9, 1.1.1.1"})) == "9.9.9.9"
    assert web._client_ip(_Req(host="5.5.5.5")) == "5.5.5.5"


def test_request_is_authed_requires_valid_token(monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", "u")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "a")
    assert web._request_is_authed(_Req({"x-user-token": "u"})) is True
    assert web._request_is_authed(_Req({"x-admin-token": "a"})) is True
    # A *wrong* token is not exempt — so brute-force attempts get rate-limited.
    assert web._request_is_authed(_Req({"x-user-token": "wrong"})) is False
    assert web._request_is_authed(_Req()) is False


def test_rate_limited_sliding_window(monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 3)
    web._rate_hits.clear()
    now = 1000.0
    assert [web._rate_limited("ip", now) for _ in range(4)] == [False, False, False, True]
    # A request outside the 60s window resets the count.
    assert web._rate_limited("ip", now + 61) is False


def test_middleware_returns_429_for_unauthed(monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(web, "USER_TOKEN", "")
    web._rate_hits.clear()
    client = TestClient(web.app)  # host 'testclient' — non-localhost, no token
    assert client.get("/status").status_code != 429
    assert client.get("/status").status_code != 429
    blocked = client.get("/status")
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")


def test_valid_token_is_exempt_from_limit(monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 1)
    monkeypatch.setattr(web, "USER_TOKEN", "tok")
    web._rate_hits.clear()
    client = TestClient(web.app)
    for _ in range(5):
        assert client.get("/status", headers={"X-User-Token": "tok"}).status_code != 429


def test_disabled_when_limit_zero(monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 0)
    web._rate_hits.clear()
    client = TestClient(web.app)
    for _ in range(10):
        assert client.get("/status").status_code != 429
