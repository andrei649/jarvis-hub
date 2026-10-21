"""Password login, generic failures and throttling without enumeration (spec §6)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth
from agents.core.workspace import auth, identity
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    db,
    freeze_clock,
    make_app,
    make_user,
    seed_company,
    ws,
)

LOGIN = "/api/workspace/login"


def _client(host: str = "testclient") -> TestClient:
    return TestClient(make_app(workspace_auth.router), client=(host, 50000))


def _attempt(client: TestClient, email: str, password: str = "wrong-password-123"):
    return client.post(LOGIN, json={"email": email, "password": password})


def _actions(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT action FROM audit ORDER BY id")]


def test_login_success_payload(ws):
    conn = db()
    company = seed_company(conn)
    r = _attempt(_client(), company.member_a.email.upper(), DEFAULT_PASSWORD)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user", "org", "csrf_token"}
    assert body["user"]["id"] == company.member_a.id and body["org"]["name"] == "Acme"
    assert body["user"]["permissions"]["department_ids"] == [company.dept_a]
    assert conn.execute("SELECT last_login_at FROM users WHERE id = ?",
                        (company.member_a.id,)).fetchone()[0] is not None
    assert _actions(conn)[-1] == "auth.login"


def test_every_failure_is_the_same_401(ws):
    conn = db()
    company = seed_company(conn)
    invited = make_user(conn, role="member", department_ids=[company.dept_a], status="invited")
    disabled = make_user(conn, role="member", department_ids=[company.dept_a], status="disabled")
    client = _client()
    answers = [
        _attempt(client, company.member_a.email),                 # wrong password
        _attempt(client, "nobody@acme.test", DEFAULT_PASSWORD),  # unknown email
        _attempt(client, invited.email, DEFAULT_PASSWORD),        # no password yet
        _attempt(client, disabled.email, DEFAULT_PASSWORD),       # right password, disabled
    ]
    assert {r.status_code for r in answers} == {401}
    assert len({r.content for r in answers}) == 1
    assert answers[0].json()["error"] == "invalid_credentials"
    reasons = [json.loads(row[0])["reason"] for row in conn.execute(
        "SELECT details_json FROM audit WHERE action = 'auth.login_failed' ORDER BY id")]
    assert reasons == ["wrong_password", "unknown_user", "user_invited", "user_disabled"]
    dump = "\n".join(conn.iterdump())
    assert "wrong-password-123" not in dump and DEFAULT_PASSWORD not in dump


def test_unknown_and_passwordless_users_cost_one_scrypt(ws, monkeypatch):
    conn = db()
    company = seed_company(conn)
    invited = make_user(conn, role="member", department_ids=[company.dept_a], status="invited")
    identity._dummy_hash()
    calls = []
    real = identity._scrypt
    monkeypatch.setattr(identity, "_scrypt", lambda *a, **k: calls.append(1) or real(*a, **k))
    client = _client()
    for email in ("ghost@acme.test", invited.email, company.member_a.email):
        calls.clear()
        _attempt(client, email)
        assert len(calls) == 1, email


def test_email_lockout_after_five_failures_survives_the_error(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    for _ in range(auth.LOGIN_EMAIL_LIMIT):
        assert _attempt(client, company.member_a.email).status_code == 401
    rows = db().execute("SELECT COUNT(*) FROM login_attempts WHERE ok = 0").fetchone()[0]
    assert rows == auth.LOGIN_EMAIL_LIMIT, "each failure was committed before its 401"
    r = _attempt(client, company.member_a.email, DEFAULT_PASSWORD)
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "too_many_attempts" and 1 <= body["retry_after_seconds"] <= 900
    assert r.headers["retry-after"] == str(body["retry_after_seconds"])
    assert _attempt(_client("10.1.1.1"), company.member_a.email, DEFAULT_PASSWORD).status_code == 429, \
        "the lock is per email, whatever the IP"
    assert _actions(conn).count("auth.throttled") == 1, "the lockout is audited once"
    assert _attempt(client, company.member_b.email, DEFAULT_PASSWORD).status_code == 200


def test_nonexistent_emails_lock_out_identically(ws):
    conn = db()
    seed_company(conn)
    client = _client()
    statuses = [_attempt(client, "ghost@acme.test").status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]


def test_lockout_lifts_when_the_window_slides(ws, monkeypatch):
    clock = freeze_clock(monkeypatch, start=1_800_000_000)
    conn = db()
    company = seed_company(conn)
    client = _client()
    for _ in range(5):
        _attempt(client, company.member_a.email)
        clock.advance(10)
    r = _attempt(client, company.member_a.email, DEFAULT_PASSWORD)
    assert r.status_code == 429
    assert r.json()["retry_after_seconds"] == 900 - 50
    clock.advance(900 - 50)
    assert _attempt(client, company.member_a.email, DEFAULT_PASSWORD).status_code == 200


def test_a_success_resets_the_consecutive_count(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    for _ in range(4):
        _attempt(client, company.member_a.email)
    assert _attempt(client, company.member_a.email, DEFAULT_PASSWORD).status_code == 200
    for _ in range(4):
        assert _attempt(client, company.member_a.email).status_code == 401
    assert _attempt(client, company.member_a.email, DEFAULT_PASSWORD).status_code == 200


def test_per_ip_limit_across_many_emails(ws):
    conn = db()
    company = seed_company(conn)
    attacker = _client("203.0.113.9")
    for n in range(auth.LOGIN_IP_LIMIT):
        assert _attempt(attacker, f"guess{n}@acme.test").status_code == 401
    r = _attempt(attacker, company.member_a.email, DEFAULT_PASSWORD)
    assert r.status_code == 429 and r.json()["error"] == "too_many_attempts"
    assert _attempt(_client("198.51.100.7"), company.member_a.email, DEFAULT_PASSWORD).status_code == 200
    throttled = conn.execute("SELECT details_json FROM audit WHERE action = 'auth.throttled'").fetchall()
    assert [json.loads(row[0])["scope"] for row in throttled] == ["ip"]


def test_forwarded_for_counts_only_from_a_trusted_proxy(ws, monkeypatch):
    conn = db()
    seed_company(conn)
    spoofer = _client("203.0.113.9")
    forwarded = {"X-Forwarded-For": "192.0.2.1"}
    spoofer.post(LOGIN, json={"email": "x@acme.test", "password": "nope-nope-nope"},
                 headers=forwarded)
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "127.0.0.1")
    proxied = _client("127.0.0.1")
    proxied.post(LOGIN, json={"email": "y@acme.test", "password": "nope-nope-nope"},
                 headers=forwarded)
    ips = [row[0] for row in conn.execute("SELECT ip FROM login_attempts ORDER BY id")]
    assert ips == ["203.0.113.9", "192.0.2.1"]


@pytest.mark.parametrize("body", [{}, {"email": "a@acme.test"}, {"password": "x"},
                                  {"email": 5, "password": "x"}, {"email": "a@acme.test", "password": ""}])
def test_malformed_login_bodies_are_422(ws, body):
    conn = db()
    seed_company(conn)
    r = _client().post(LOGIN, json=body)
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"


# ── parallel bursts (review fix: the attempt is reserved before the slow verify) ──────

async def _burst(bodies: list[dict], host: str = "198.51.100.7") -> list[httpx.Response]:
    """Send every login at once; the verifies overlap in worker threads."""
    transport = httpx.ASGITransport(app=make_app(workspace_auth.router), client=(host, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return list(await asyncio.gather(*(client.post(LOGIN, json=body) for body in bodies)))


async def test_a_parallel_burst_cannot_outrun_the_email_lockout(ws):
    conn = db()
    company = seed_company(conn)
    burst = 12
    answers = await _burst([{"email": company.member_a.email, "password": f"wrong-guess-{n:04d}"}
                            for n in range(burst)])
    codes = [r.status_code for r in answers]
    assert codes.count(401) == auth.LOGIN_EMAIL_LIMIT, codes
    assert codes.count(429) == burst - auth.LOGIN_EMAIL_LIMIT, codes
    failures = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE ok = 0").fetchone()[0]
    assert failures == auth.LOGIN_EMAIL_LIMIT, "only the guesses that were verified are counted"
    assert _actions(conn).count("auth.login_failed") == auth.LOGIN_EMAIL_LIMIT
    assert _actions(conn).count("auth.throttled") == 1, "parallel failures agree on the one lockout"


async def test_a_parallel_burst_cannot_outrun_the_ip_limit(ws):
    conn = db()
    seed_company(conn)
    burst = auth.LOGIN_IP_LIMIT + 5
    answers = await _burst([{"email": f"guess{n}@acme.test", "password": "wrong-guess-0000"}
                            for n in range(burst)], host="203.0.113.50")
    codes = [r.status_code for r in answers]
    assert codes.count(401) == auth.LOGIN_IP_LIMIT and codes.count(429) == 5, codes
    throttled = conn.execute("SELECT details_json FROM audit WHERE action = 'auth.throttled'").fetchall()
    assert [json.loads(row[0])["scope"] for row in throttled] == ["ip"]


def test_a_success_flips_its_reserved_row(ws):
    conn = db()
    company = seed_company(conn)
    assert _attempt(_client(), company.member_a.email, DEFAULT_PASSWORD).status_code == 200
    rows = conn.execute("SELECT email, ok, kind FROM login_attempts").fetchall()
    assert [tuple(row) for row in rows] == [(company.member_a.email, 1, "login")]


def test_a_refused_attempt_writes_no_row(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    for _ in range(auth.LOGIN_EMAIL_LIMIT):
        _attempt(client, company.member_a.email)
    assert _attempt(client, company.member_a.email).status_code == 429
    count = conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0]
    assert count == auth.LOGIN_EMAIL_LIMIT


def test_consecutive_count_survives_a_frozen_clock(ws, monkeypatch):
    """Attempt order comes from row ids, so equal timestamps cannot hide a success."""
    conn = db()
    company = seed_company(conn)
    freeze_clock(monkeypatch, 1_800_000_000.0)
    client = _client()
    for _ in range(auth.LOGIN_EMAIL_LIMIT - 1):
        assert _attempt(client, company.member_a.email).status_code == 401
    assert _attempt(client, company.member_a.email, DEFAULT_PASSWORD).status_code == 200
    for _ in range(auth.LOGIN_EMAIL_LIMIT - 1):
        assert _attempt(client, company.member_a.email).status_code == 401
    assert _attempt(client, company.member_a.email, DEFAULT_PASSWORD).status_code == 200


# ── a login that is not an email address (review fix SEC-1) ──────────────────────────

def test_a_non_email_login_identifier_never_reaches_audit_or_attempts(ws):
    """A password typed into the email field must not persist in the append-only audit."""
    conn = db()
    company = seed_company(conn)
    client = _client()
    typed = "Parola-Mea-Secreta-2026!"
    garbage = _attempt(client, typed, DEFAULT_PASSWORD)
    unknown = _attempt(client, "nobody@acme.test", DEFAULT_PASSWORD)
    assert garbage.status_code == 401 and garbage.content == unknown.content
    failed = conn.execute("SELECT actor_email, details_json FROM audit "
                          "WHERE action = 'auth.login_failed' ORDER BY id").fetchall()
    assert [(row[0], json.loads(row[1])) for row in failed] == [
        ("", {"reason": "invalid_identifier"}), ("nobody@acme.test", {"reason": "unknown_user"})]
    attempts = [tuple(row) for row in conn.execute(
        "SELECT email, ok, kind FROM login_attempts ORDER BY id")]
    assert attempts == [("", 0, "login"), ("nobody@acme.test", 0, "login")]
    dump = "\n".join(conn.iterdump()).lower()
    assert typed.lower() not in dump
    assert _attempt(client, company.member_a.email, DEFAULT_PASSWORD).status_code == 200


def test_non_email_logins_count_per_ip_but_share_no_email_lockout(ws):
    conn = db()
    company = seed_company(conn)
    client = _client("203.0.113.77")
    codes = [_attempt(client, f"nu-e-email-{n}").status_code for n in range(auth.LOGIN_EMAIL_LIMIT + 1)]
    assert codes == [401] * (auth.LOGIN_EMAIL_LIMIT + 1), "no shared bucket for non-emails"
    assert _attempt(_client("198.51.100.8"), "inca-unul").status_code == 401
    for n in range(20 - auth.LOGIN_EMAIL_LIMIT - 1):
        assert _attempt(client, f"altceva-{n}").status_code == 401
    assert _attempt(client, company.member_a.email, DEFAULT_PASSWORD).status_code == 429, \
        "the per-IP limit still counts them"
    throttled = conn.execute("SELECT actor_email, details_json FROM audit "
                             "WHERE action = 'auth.throttled'").fetchall()
    assert [(row[0], json.loads(row[1])["scope"]) for row in throttled] == [("", "ip")]
