"""Invite and reset links: fragment URLs, lookup, accept, expiry, single use (spec §6 "Invites")."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_admin, workspace_auth
from agents.core.workspace import auth
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    authed,
    db,
    freeze_clock,
    login,
    make_app,
    seed_company,
    ws,
)

NEW_PASSWORD = "Noua-Parola-Sigura-7"


def _client(**kwargs) -> TestClient:
    return TestClient(make_app(workspace_auth.router, workspace_admin.router), **kwargs)


def _token(url: str) -> str:
    parts = urlsplit(url)
    assert parts.path == "/workspace/invite" and parts.query == ""
    assert parts.fragment.startswith("t=")
    return parts.fragment[2:]


def _invite(admin: TestClient, csrf: str, dept: int, email: str = "ioana.nou@acme.test") -> tuple[int, str]:
    r = admin.post("/api/workspace/admin/users", headers=authed(admin, csrf),
                   json={"email": email, "name": "Nou Venit", "role": "member", "department_ids": [dept]})
    assert r.status_code == 201, r.text
    return r.json()["user"]["id"], r.json()["invite_url"]


@pytest.fixture
def admin_session(ws):
    conn = db()
    company = seed_company(conn)
    admin = _client()
    csrf = login(admin, company.admin.email)
    return company, admin, csrf


def test_invite_url_carries_the_token_only_in_the_fragment(admin_session):
    company, admin, csrf = admin_session
    user_id, url = _invite(admin, csrf, company.dept_a)
    token = _token(url)
    assert url.startswith("http://testserver/workspace/invite#t=")
    conn = db()
    stored = conn.execute("SELECT token_hash, purpose, expires_at - created_at AS ttl FROM invites "
                          "WHERE user_id = ?", (user_id,)).fetchone()
    assert stored["token_hash"] == auth.token_hash(token) and token not in "\n".join(conn.iterdump())
    assert stored["purpose"] == "invite" and stored["ttl"] == pytest.approx(72 * 3600)


def test_invite_url_is_root_path_and_scheme_aware(ws):
    conn = db()
    company = seed_company(conn)
    admin = _client(base_url="https://ws.example.com", root_path="/nerva")
    r = admin.post("/nerva/api/workspace/login",
                   json={"email": company.admin.email, "password": DEFAULT_PASSWORD})
    csrf = r.json()["csrf_token"]
    r = admin.post("/nerva/api/workspace/admin/users", headers=authed(admin, csrf),
                   json={"email": "x@acme.test", "name": "X", "role": "member",
                         "department_ids": [company.dept_a]})
    assert r.json()["invite_url"].startswith("https://ws.example.com/nerva/workspace/invite#t=")


def test_lookup_then_accept_activates_the_account(admin_session):
    company, admin, csrf = admin_session
    user_id, url = _invite(admin, csrf, company.dept_a)
    token = _token(url)
    guest = _client()
    r = guest.post("/api/workspace/invites/lookup", json={"token": token})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "ioana.nou@acme.test" and body["name"] == "Nou Venit"
    assert body["org_name"] == "Acme" and body["purpose"] == "invite" and body["expires_at"] > 0
    r = guest.post("/api/workspace/invites/accept",
                   json={"token": token, "password": NEW_PASSWORD, "name": "Nou Venit Popescu"})
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted["user"]["status"] == "active" and accepted["user"]["name"] == "Nou Venit Popescu"
    assert accepted["csrf_token"] and auth.SESSION_COOKIE in r.headers["set-cookie"]
    assert guest.get("/api/workspace/me").status_code == 200
    conn = db()
    assert conn.execute("SELECT via FROM sessions WHERE user_id = ?", (user_id,)).fetchone()[0] == "invite"
    assert "auth.invite_accepted" in [row[0] for row in conn.execute("SELECT action FROM audit")]
    login(_client(), "ioana.nou@acme.test", NEW_PASSWORD)


def test_links_are_single_use(admin_session):
    company, admin, csrf = admin_session
    _user_id, url = _invite(admin, csrf, company.dept_a)
    token = _token(url)
    guest = _client()
    assert guest.post("/api/workspace/invites/accept",
                      json={"token": token, "password": NEW_PASSWORD}).status_code == 200
    for path, body in (("/api/workspace/invites/lookup", {"token": token}),
                       ("/api/workspace/invites/accept", {"token": token, "password": NEW_PASSWORD})):
        r = guest.post(path, json=body)
        assert r.status_code == 404 and r.json()["error"] == "invite_invalid"


def test_weak_password_keeps_the_link_usable(admin_session):
    company, admin, csrf = admin_session
    _user_id, url = _invite(admin, csrf, company.dept_a)
    token = _token(url)
    guest = _client()
    r = guest.post("/api/workspace/invites/accept", json={"token": token, "password": "short"})
    assert r.status_code == 422 and r.json()["error"] == "weak_password"
    r = guest.post("/api/workspace/invites/accept", json={"token": token, "password": "ioana.nou-venit-1234"})
    assert r.json()["reason"] == "contains_email"
    assert guest.post("/api/workspace/invites/accept",
                      json={"token": token, "password": NEW_PASSWORD}).status_code == 200


def test_links_expire_after_72_hours(ws, monkeypatch):
    clock = freeze_clock(monkeypatch, start=1_800_000_000)
    conn = db()
    company = seed_company(conn)
    admin = _client()
    csrf = login(admin, company.admin.email)
    _user_id, url = _invite(admin, csrf, company.dept_a)
    token = _token(url)
    clock.advance(72 * 3600 - 5)
    assert _client().post("/api/workspace/invites/lookup", json={"token": token}).status_code == 200
    clock.advance(10)
    assert _client().post("/api/workspace/invites/lookup", json={"token": token}).status_code == 404
    assert _client().post("/api/workspace/invites/accept",
                          json={"token": token, "password": NEW_PASSWORD}).status_code == 404


def test_reissue_revokes_the_older_link(admin_session):
    company, admin, csrf = admin_session
    user_id, url = _invite(admin, csrf, company.dept_a)
    old = _token(url)
    r = admin.post(f"/api/workspace/admin/users/{user_id}/invite", headers=authed(admin, csrf))
    assert r.status_code == 200 and r.json()["purpose"] == "invite"
    new = _token(r.json()["invite_url"])
    guest = _client()
    assert guest.post("/api/workspace/invites/lookup", json={"token": old}).status_code == 404
    assert guest.post("/api/workspace/invites/lookup", json={"token": new}).status_code == 200
    assert db().execute("SELECT COUNT(*) FROM invites WHERE user_id = ?", (user_id,)).fetchone()[0] == 1


def test_reset_link_sets_a_new_password_and_revokes_sessions(admin_session):
    company, admin, csrf = admin_session
    phone = _client()
    login(phone, company.member_a.email)
    r = admin.post(f"/api/workspace/admin/users/{company.member_a.id}/invite",
                   headers=authed(admin, csrf), json={})
    assert r.status_code == 200 and r.json()["purpose"] == "reset" and r.json()["emailed"] is False
    token = _token(r.json()["invite_url"])
    guest = _client()
    assert guest.post("/api/workspace/invites/lookup", json={"token": token}).json()["purpose"] == "reset"
    r = guest.post("/api/workspace/invites/accept", json={"token": token, "password": NEW_PASSWORD})
    assert r.status_code == 200
    assert phone.get("/api/workspace/me").status_code == 401, "older sessions are revoked"
    assert guest.get("/api/workspace/me").status_code == 200
    assert _client().post("/api/workspace/login", json={"email": company.member_a.email,
                                                        "password": DEFAULT_PASSWORD}).status_code == 401
    login(_client(), company.member_a.email, NEW_PASSWORD)
    actions = [row[0] for row in db().execute("SELECT action FROM audit ORDER BY id")]
    assert "auth.reset_link_issued" in actions and "auth.password_changed" in actions


def test_disabled_users_have_no_live_links(admin_session):
    company, admin, csrf = admin_session
    user_id, url = _invite(admin, csrf, company.dept_a)
    token = _token(url)
    r = admin.patch(f"/api/workspace/admin/users/{user_id}", json={"status": "disabled"},
                    headers=authed(admin, csrf))
    assert r.status_code == 200
    assert _client().post("/api/workspace/invites/lookup", json={"token": token}).status_code == 404
    r = admin.post(f"/api/workspace/admin/users/{user_id}/invite", headers=authed(admin, csrf))
    assert r.status_code == 409 and r.json()["error"] == "user_disabled"


def test_a_reset_link_dies_when_the_user_state_no_longer_matches(admin_session):
    company, admin, csrf = admin_session
    r = admin.post(f"/api/workspace/admin/users/{company.member_a.id}/invite", headers=authed(admin, csrf))
    token = _token(r.json()["invite_url"])
    db().execute("UPDATE users SET status = 'invited' WHERE id = ?", (company.member_a.id,))
    assert _client().post("/api/workspace/invites/lookup", json={"token": token}).status_code == 404


@pytest.mark.parametrize("token", [None, 42, "", "short", "x" * 200, "a" * 43])
def test_bad_tokens_are_invite_invalid(admin_session, token):
    r = _client().post("/api/workspace/invites/lookup", json={"token": token})
    assert r.status_code == 404 and r.json()["error"] == "invite_invalid"


def test_lookup_and_accept_share_a_per_ip_budget(admin_session):
    company, admin, csrf = admin_session
    _user_id, url = _invite(admin, csrf, company.dept_a)
    token = _token(url)
    attacker = TestClient(make_app(workspace_auth.router), client=("203.0.113.40", 50000))
    for n in range(auth.INVITE_IP_LIMIT - 1):
        attacker.post("/api/workspace/invites/lookup", json={"token": f"guess-{n:04d}-padding-to-length"})
    attacker.post("/api/workspace/invites/accept", json={"token": "x" * 43, "password": NEW_PASSWORD})
    r = attacker.post("/api/workspace/invites/lookup", json={"token": token})
    assert r.status_code == 429 and r.json()["error"] == "too_many_attempts"
    other = TestClient(make_app(workspace_auth.router), client=("198.51.100.40", 50000))
    assert other.post("/api/workspace/invites/lookup", json={"token": token}).status_code == 200


# ── single use under a race, and a used reset link (review T2, T6) ────────────────────

def _reset_token(admin: TestClient, csrf: str, user_id: int) -> str:
    r = admin.post(f"/api/workspace/admin/users/{user_id}/invite", headers=authed(admin, csrf),
                   json={})
    assert r.status_code == 200, r.text
    return _token(r.json()["invite_url"])


async def _parallel_accepts(token: str, passwords: list[str]) -> list[httpx.Response]:
    """Every accept at once: each passes ``find_invite`` before any hash finishes."""
    transport = httpx.ASGITransport(app=make_app(workspace_auth.router), client=("198.51.100.9", 1))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return list(await asyncio.gather(*(
            client.post("/api/workspace/invites/accept", json={"token": token, "password": pw})
            for pw in passwords)))


def _sessions_of(conn, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND revoked_at IS NULL",
                        (user_id,)).fetchone()[0]


async def test_two_parallel_accepts_of_one_reset_link_admit_exactly_one(admin_session):
    """For a reset link the user stays active, so only the claim's compare-and-set
    (``used_at IS NULL``) stops the second accept."""
    company, admin, csrf = admin_session
    token = _reset_token(admin, csrf, company.member_a.id)
    passwords = ["Parola-Noua-Sigura-0", "Parola-Noua-Sigura-1"]
    answers = await _parallel_accepts(token, passwords)
    assert sorted(a.status_code for a in answers) == [200, 404]
    loser = next(a for a in answers if a.status_code == 404)
    assert loser.json()["error"] == "invite_invalid"
    conn = db()
    assert _sessions_of(conn, company.member_a.id) == 1
    winner = passwords[[a.status_code for a in answers].index(200)]
    login(_client(), company.member_a.email, winner)
    actions = [row[0] for row in conn.execute("SELECT action FROM audit")]
    assert actions.count("auth.password_changed") == 1


async def test_two_parallel_accepts_of_one_invite_admit_exactly_one(admin_session):
    company, admin, csrf = admin_session
    user_id, url = _invite(admin, csrf, company.dept_a, email="dublu@acme.test")
    answers = await _parallel_accepts(_token(url), ["Parola-Noua-Sigura-0", "Parola-Noua-Sigura-1"])
    assert sorted(a.status_code for a in answers) == [200, 404]
    conn = db()
    assert _sessions_of(conn, user_id) == 1
    actions = [row[0] for row in conn.execute("SELECT action FROM audit")]
    assert actions.count("auth.invite_accepted") == 1


def test_a_used_reset_link_is_invalid_on_lookup_and_accept(admin_session):
    company, admin, csrf = admin_session
    token = _reset_token(admin, csrf, company.member_a.id)
    guest = _client()
    assert guest.post("/api/workspace/invites/accept",
                      json={"token": token, "password": NEW_PASSWORD}).status_code == 200
    for path, body in (("/api/workspace/invites/lookup", {"token": token}),
                       ("/api/workspace/invites/accept", {"token": token, "password": "Alta-Parola-Buna-9"})):
        r = guest.post(path, json=body)
        assert (r.status_code, r.json()["error"]) == (404, "invite_invalid"), path
    login(_client(), company.member_a.email, NEW_PASSWORD)
