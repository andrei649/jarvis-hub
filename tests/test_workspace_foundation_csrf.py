"""CSRF token and Origin / Sec-Fetch-Site rules for every mutating request (spec §6 "CSRF")."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    authed,
    db,
    login,
    make_app,
    seed_company,
    ws,
)

PATCH_ME = "/api/workspace/me"


@pytest.fixture
def signed_in(ws):
    conn = db()
    company = seed_company(conn)
    client = TestClient(make_app(workspace_auth.router))
    csrf = login(client, company.member_a.email)
    return client, csrf


def _patch(client, headers):
    return client.patch(PATCH_ME, json={"theme": "dark"}, headers=headers)


def test_valid_token_and_same_origin_pass(signed_in):
    client, csrf = signed_in
    r = _patch(client, authed(client, csrf))
    assert r.status_code == 200 and r.json()["user"]["theme"] == "dark"


def test_token_without_browser_headers_passes(signed_in):
    client, csrf = signed_in
    assert _patch(client, {"X-CSRF-Token": csrf}).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-CSRF-Token": ""}, {"X-CSRF-Token": "wrong"}])
def test_missing_or_wrong_token_is_403(signed_in, headers):
    client, _csrf = signed_in
    r = _patch(client, headers)
    assert r.status_code == 403 and r.json()["error"] == "csrf_failed"


@pytest.mark.parametrize("extra", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Origin": "http://testserver.evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
])
def test_cross_origin_is_refused_even_with_the_token(signed_in, extra):
    client, csrf = signed_in
    r = _patch(client, {"X-CSRF-Token": csrf, **extra})
    assert r.status_code == 403 and r.json()["error"] == "csrf_failed"


@pytest.mark.parametrize("extra", [
    {"Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Site": "none"},
    {"Origin": "http://TESTSERVER"},
    # A proxy that terminates TLS without being trusted makes Origin look different from
    # base_url; the browser's own Sec-Fetch-Site is believed.
    {"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"},
])
def test_same_origin_signals_pass(signed_in, extra):
    client, csrf = signed_in
    assert _patch(client, {"X-CSRF-Token": csrf, **extra}).status_code == 200


def test_safe_methods_skip_the_checks(signed_in):
    client, _csrf = signed_in
    r = client.get("/api/workspace/me", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200


def test_token_is_bound_to_its_session(ws):
    conn = db()
    company = seed_company(conn)
    a, b = TestClient(make_app(workspace_auth.router)), TestClient(make_app(workspace_auth.router))
    csrf_a = login(a, company.member_a.email)
    login(b, company.member_b.email)
    assert _patch(b, authed(b, csrf_a)).status_code == 403


def test_session_endpoint_returns_the_same_token(signed_in):
    client, csrf = signed_in
    assert client.get("/api/workspace/session").json()["csrf_token"] == csrf


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"},
])
def test_public_posts_refuse_cross_origin(ws, headers):
    conn = db()
    company = seed_company(conn)
    client = TestClient(make_app(workspace_auth.router))
    r = client.post("/api/workspace/login", headers=headers,
                    json={"email": company.member_a.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 403 and r.json()["error"] == "csrf_failed"
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded",
                                          "multipart/form-data; boundary=x"])
def test_public_posts_require_json(ws, content_type):
    conn = db()
    company = seed_company(conn)
    client = TestClient(make_app(workspace_auth.router))
    body = f'{{"email":"{company.member_a.email}","password":"{DEFAULT_PASSWORD}"}}'
    for path in ("/api/workspace/login", "/api/workspace/setup", "/api/workspace/login/sso",
                 "/api/workspace/invites/lookup", "/api/workspace/invites/accept"):
        r = client.post(path, content=body, headers={"Content-Type": content_type})
        assert r.status_code == 415, path
        assert r.json()["error"] == "unsupported_media_type"
