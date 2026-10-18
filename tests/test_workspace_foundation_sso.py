"""SSO through a trusted reverse proxy: every condition of spec §6 "SSO through a proxy"."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    db,
    make_app,
    make_user,
    seed_company,
    ws,
)

SSO = "/api/workspace/login/sso"
HEADER = "X-Forwarded-Email"
KEY = "proxy-shared-value-0123456789"


@pytest.fixture
def sso(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_SSO_HEADER", HEADER)
    monkeypatch.setenv("NERVA_WORKSPACE_SSO_SECRET", KEY)
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "127.0.0.1")
    conn = db()
    return seed_company(conn)


def _proxy(host: str = "127.0.0.1") -> TestClient:
    return TestClient(make_app(workspace_auth.router), client=(host, 50000))


def _vouch(email: str, key: str = KEY) -> list[tuple[str, str]]:
    return [(HEADER, email), ("X-Nerva-Proxy-Secret", key), ("Content-Type", "application/json")]


def _post(client: TestClient, headers) -> object:
    return client.post(SSO, content=b"{}", headers=headers)


def test_sso_login_success(sso):
    client = _proxy()
    assert client.get("/api/workspace/session").json()["sso_available"] is True
    r = _post(client, _vouch(sso.member_a.email.upper()))
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == sso.member_a.id and r.json()["csrf_token"]
    conn = db()
    row = conn.execute("SELECT via, sso_email FROM sessions").fetchone()
    assert (row["via"], row["sso_email"]) == ("sso", sso.member_a.email)
    assert "auth.sso_login" in [r[0] for r in conn.execute("SELECT action FROM audit")]
    assert client.get("/api/workspace/me").status_code == 200


@pytest.mark.parametrize("missing", ["NERVA_WORKSPACE_SSO_HEADER", "NERVA_WORKSPACE_SSO_SECRET"])
def test_sso_needs_both_variables(sso, monkeypatch, missing):
    monkeypatch.delenv(missing)
    client = _proxy()
    assert client.get("/api/workspace/session").json()["sso_available"] is False
    r = _post(client, _vouch(sso.member_a.email))
    assert r.status_code == 404 and r.json()["error"] == "sso_disabled"


def test_malformed_trusted_proxies_disables_sso(sso, monkeypatch):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "not-a-network/99")
    r = _post(_proxy(), _vouch(sso.member_a.email))
    assert r.status_code == 404 and r.json()["error"] == "sso_disabled"


def test_untrusted_peer_gets_no_identity_and_leaves_no_rows(sso):
    r = _post(_proxy("testclient"), _vouch(sso.member_a.email))
    assert r.status_code == 401 and r.json()["error"] == "sso_no_identity"
    r = _post(_proxy("10.9.9.9"), _vouch(sso.member_a.email))
    assert r.status_code == 401
    conn = db()
    assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


@pytest.mark.parametrize("headers", [
    [(HEADER, "x"), ("Content-Type", "application/json")],                       # no key
    [(HEADER, "a@acme.test"), ("X-Nerva-Proxy-Secret", "wrong"), ("Content-Type", "application/json")],
    [(HEADER, "a@acme.test"), ("X-Nerva-Proxy-Secret", KEY), ("X-Nerva-Proxy-Secret", KEY),
     ("Content-Type", "application/json")],                                       # key twice
])
def test_the_proxy_key_must_match_exactly_once(sso, headers):
    r = _post(_proxy(), headers)
    assert r.status_code == 401 and r.json()["error"] == "sso_no_identity"
    reasons = [row[0] for row in db().execute(
        "SELECT json_extract(details_json, '$.reason') FROM audit WHERE action = 'auth.login_failed'")]
    assert reasons == ["bad_proxy_secret"]


@pytest.mark.parametrize("emails", [[], ["not-an-email"], ["a@acme.test", "b@acme.test"],
                                    ["a@acme.test, b@acme.test"], ["Ana <a@acme.test>"]])
def test_the_email_header_must_be_one_valid_address(sso, emails):
    headers = [(HEADER, value) for value in emails]
    headers += [("X-Nerva-Proxy-Secret", KEY), ("Content-Type", "application/json")]
    r = _post(_proxy(), headers)
    assert r.status_code == 401 and r.json()["error"] == "sso_no_identity"


def test_only_active_users_sign_in_and_none_are_created(sso):
    conn = db()
    invited = make_user(conn, role="member", department_ids=[sso.dept_a], status="invited")
    disabled = make_user(conn, role="member", department_ids=[sso.dept_a], status="disabled")
    for email in ("stranger@acme.test", invited.email, disabled.email):
        r = _post(_proxy(), _vouch(email))
        assert r.status_code == 401 and r.json()["error"] == "invalid_credentials", email
    assert conn.execute("SELECT COUNT(*) FROM users WHERE email = 'stranger@acme.test'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM login_attempts WHERE kind = 'sso' AND ok = 0").fetchone()[0] == 3


def test_a_different_header_email_revokes_the_sso_session(sso):
    client = _proxy()
    assert _post(client, _vouch(sso.member_a.email)).status_code == 200
    assert client.get("/api/workspace/me", headers={HEADER: sso.member_a.email}).status_code == 200
    assert client.get("/api/workspace/me").status_code == 200, "no header: nothing to compare"
    r = client.get("/api/workspace/me", headers={HEADER: sso.member_b.email})
    assert r.status_code == 401
    assert client.get("/api/workspace/me").status_code == 401, "the session is gone for good"
    conn = db()
    assert conn.execute("SELECT revoked_at FROM sessions").fetchone()[0] is not None
    reason = conn.execute("SELECT json_extract(details_json, '$.reason') FROM audit "
                          "WHERE action = 'session.revoked'").fetchone()[0]
    assert reason == "sso_identity_changed"


def test_header_changes_from_untrusted_peers_are_ignored(sso, monkeypatch):
    client = _proxy()
    assert _post(client, _vouch(sso.member_a.email)).status_code == 200
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8")
    assert client.get("/api/workspace/me", headers={HEADER: sso.member_b.email}).status_code == 200


def test_sso_follows_the_public_origin_rule(sso):
    headers = [*_vouch(sso.member_a.email), ("Origin", "https://evil.example")]
    r = _post(_proxy(), headers)
    assert r.status_code == 403 and r.json()["error"] == "csrf_failed"


# ── CR/LF in the email header (review T9) ────────────────────────────────────────────
# httpx refuses such header values, so the request is a raw ASGI scope, as a proxy that
# forwards one would produce it.

async def _raw_sso(headers: list[tuple[bytes, bytes]], peer: str = "127.0.0.1") -> tuple[int, dict]:
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": b"{}", "more_body": False}

    messages: list[dict] = []

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": SSO, "raw_path": SSO.encode(), "root_path": "",
             "query_string": b"", "client": (peer, 50000), "server": ("testserver", 80),
             "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                         (b"x-nerva-proxy-secret", KEY.encode()), *headers]}
    await make_app(workspace_auth.router)(scope, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, json.loads(body)


@pytest.mark.parametrize("value", ["{email}\r\n", "{email}\n", "\r\n{email}", "{email}\r"])
async def test_an_email_header_with_cr_or_lf_is_no_identity(sso, value):
    """Stripping the CR/LF instead of refusing would sign the vouched user in."""
    raw = value.format(email=sso.member_a.email).encode()
    status, body = await _raw_sso([(HEADER.lower().encode(), raw)])
    assert (status, body["error"]) == (401, "sso_no_identity")
    conn = db()
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    reasons = [row[0] for row in conn.execute(
        "SELECT json_extract(details_json, '$.reason') FROM audit WHERE action = 'auth.login_failed'")]
    assert reasons == ["no_identity"]


async def test_the_raw_scope_signs_a_clean_header_in(sso):
    """Control: the same raw request without CR/LF is a normal SSO login."""
    status, body = await _raw_sso([(HEADER.lower().encode(), sso.member_a.email.encode())])
    assert status == 200 and body["user"]["id"] == sso.member_a.id
