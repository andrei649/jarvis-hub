"""Session cookies, expiry, rotation and revocation; the disabled flag (spec §3, §6)."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_admin, workspace_auth
from agents.core.workspace import auth, config
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


def _client(**kwargs) -> TestClient:
    return TestClient(make_app(workspace_auth.router, workspace_admin.router), **kwargs)


def _cookie_header(response) -> str:
    return response.headers["set-cookie"]


def _login_response(client: TestClient, email: str):
    return client.post("/api/workspace/login", json={"email": email, "password": DEFAULT_PASSWORD})


def test_cookie_flags_over_http(ws):
    conn = db()
    company = seed_company(conn)
    response = _login_response(_client(), company.member_a.email)
    header = _cookie_header(response)
    assert header.startswith(f"{auth.SESSION_COOKIE}=")
    assert "HttpOnly" in header and "SameSite=lax" in header and "Path=/api/workspace" in header
    assert "Secure" not in header, "auto mode: no Secure over plain http"
    assert f"Max-Age={config.session_max_seconds()}" in header


def test_cookie_is_secure_over_https_in_auto_mode(ws):
    conn = db()
    company = seed_company(conn)
    client = _client(base_url="https://testserver")
    header = _cookie_header(_login_response(client, company.member_a.email))
    assert "Secure" in header
    assert client.get("/api/workspace/me").status_code == 200, "the cookie round-trips over https"


@pytest.mark.parametrize(("mode", "base_url", "secure"), [
    ("1", "http://testserver", True), ("0", "https://testserver", False),
])
def test_cookie_secure_overrides(ws, monkeypatch, mode, base_url, secure):
    monkeypatch.setenv("NERVA_WORKSPACE_COOKIE_SECURE", mode)
    conn = db()
    company = seed_company(conn)
    header = _cookie_header(_login_response(_client(base_url=base_url), company.member_a.email))
    assert ("Secure" in header) is secure


def test_cookie_path_follows_the_root_path(ws):
    conn = db()
    company = seed_company(conn)
    client = _client(root_path="/nerva")
    response = client.post("/nerva/api/workspace/login",
                           json={"email": company.member_a.email, "password": DEFAULT_PASSWORD})
    assert "Path=/nerva/api/workspace" in _cookie_header(response)
    assert client.get("/nerva/api/workspace/me").status_code == 200


def test_database_stores_only_the_token_hash(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    login(client, company.member_a.email)
    token = client.cookies.get(auth.SESSION_COOKIE)
    rows = conn.execute("SELECT id_hash, via, ip FROM sessions").fetchall()
    assert [row["id_hash"] for row in rows] == [hashlib.sha256(token.encode()).hexdigest()]
    assert rows[0]["via"] == "password" and rows[0]["ip"] == "testclient"
    dump = "\n".join(conn.iterdump())
    assert token not in dump


def test_missing_or_garbage_cookie_is_401(ws):
    conn = db()
    seed_company(conn)
    client = _client()
    r = client.get("/api/workspace/me")
    assert r.status_code == 401 and r.json()["error"] == "auth_required"
    client.cookies.set(auth.SESSION_COOKIE, "not-a-session", path="/api/workspace")
    assert client.get("/api/workspace/me").status_code == 401


def test_idle_expiry_and_touch_throttling(ws, monkeypatch):
    clock = freeze_clock(monkeypatch, start=1_800_000_000)
    conn = db()
    company = seed_company(conn)
    client = _client()
    login(client, company.member_a.email)

    def last_seen():
        return conn.execute("SELECT last_seen_at FROM sessions").fetchone()[0]

    clock.advance(30)
    assert client.get("/api/workspace/me").status_code == 200
    assert last_seen() == 1_800_000_000, "no write within 60 s"
    clock.advance(31)
    assert client.get("/api/workspace/me").status_code == 200
    assert last_seen() == 1_800_000_061
    clock.advance(config.session_idle_seconds() - 1)
    assert client.get("/api/workspace/me").status_code == 200, "activity keeps the session alive"
    clock.advance(config.session_idle_seconds())
    assert client.get("/api/workspace/me").status_code == 401


def test_absolute_expiry_wins_over_activity(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_SESSION_MAX_DAYS", "1")
    clock = freeze_clock(monkeypatch, start=1_800_000_000)
    conn = db()
    company = seed_company(conn)
    client = _client()
    login(client, company.member_a.email)
    for _ in range(23):
        clock.advance(3600)
        assert client.get("/api/workspace/me").status_code == 200
    clock.advance(3601)
    assert client.get("/api/workspace/me").status_code == 401


def test_every_login_rotates_the_session(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    login(client, company.member_a.email)
    first = client.cookies.get(auth.SESSION_COOKIE)
    login(client, company.member_a.email)
    second = client.cookies.get(auth.SESSION_COOKIE)
    assert first != second
    stale = _client()
    stale.cookies.set(auth.SESSION_COOKIE, first, path="/api/workspace")
    assert stale.get("/api/workspace/me").status_code == 401, "the presented session was revoked"
    assert client.get("/api/workspace/me").status_code == 200


def test_logout_revokes_and_clears_the_cookie(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    csrf = login(client, company.member_a.email)
    token = client.cookies.get(auth.SESSION_COOKIE)
    r = client.post("/api/workspace/logout", headers=authed(client, csrf))
    assert r.status_code == 204
    assert "Max-Age=0" in r.headers["set-cookie"] and "Path=/api/workspace" in r.headers["set-cookie"]
    replay = _client()
    replay.cookies.set(auth.SESSION_COOKIE, token, path="/api/workspace")
    assert replay.get("/api/workspace/me").status_code == 401
    actions = [row[0] for row in conn.execute("SELECT action FROM audit ORDER BY id")]
    assert actions[-1] == "auth.logout"


def test_password_change_revokes_other_sessions_only(ws):
    conn = db()
    company = seed_company(conn)
    laptop, phone = _client(), _client()
    csrf = login(laptop, company.member_a.email)
    login(phone, company.member_a.email)
    r = laptop.post("/api/workspace/me/password", headers=authed(laptop, csrf),
                    json={"current_password": DEFAULT_PASSWORD, "new_password": "Alta-Parola-Lunga-1"})
    assert r.status_code == 204
    assert laptop.get("/api/workspace/me").status_code == 200
    assert phone.get("/api/workspace/me").status_code == 401


def test_disabling_and_role_change_revoke_all_sessions(ws):
    conn = db()
    company = seed_company(conn)
    admin, member, approver = _client(), _client(), _client()
    admin_csrf = login(admin, company.admin.email)
    login(member, company.member_a.email)
    login(approver, company.approver_a.email)
    r = admin.patch(f"/api/workspace/admin/users/{company.approver_a.id}", json={"role": "member"},
                    headers=authed(admin, admin_csrf))
    assert r.status_code == 200
    assert approver.get("/api/workspace/me").status_code == 401
    r = admin.patch(f"/api/workspace/admin/users/{company.member_a.id}", json={"status": "disabled"},
                    headers=authed(admin, admin_csrf))
    assert r.status_code == 200
    assert member.get("/api/workspace/me").status_code == 401
    live = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id IN (?, ?) AND revoked_at IS NULL",
                        (company.member_a.id, company.approver_a.id)).fetchone()[0]
    assert live == 0
    assert admin.get("/api/workspace/me").status_code == 200


def test_a_disabled_user_is_refused_even_with_a_live_session_row(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    login(client, company.member_a.email)
    conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (company.member_a.id,))
    assert client.get("/api/workspace/me").status_code == 401


def test_session_list_and_targeted_revocation(ws):
    conn = db()
    company = seed_company(conn)
    laptop, phone, tablet = _client(), _client(), _client()
    csrf = login(laptop, company.member_a.email)
    login(phone, company.member_a.email)
    login(tablet, company.member_a.email)
    sessions = laptop.get("/api/workspace/me/sessions").json()["sessions"]
    assert len(sessions) == 3
    assert sum(item["current"] for item in sessions) == 1
    assert all(len(item["id"]) == 12 and set(item) == {"id", "current", "created_at", "last_seen_at",
                                                       "ip", "user_agent", "via"} for item in sessions)
    phone_hash = auth.token_hash(phone.cookies.get(auth.SESSION_COOKIE))[:12]
    current = next(item["id"] for item in sessions if item["current"])
    r = laptop.delete(f"/api/workspace/me/sessions/{current}", headers=authed(laptop, csrf))
    assert r.status_code == 409 and r.json()["error"] == "cannot_revoke_current"
    r = laptop.delete(f"/api/workspace/me/sessions/{phone_hash}", headers=authed(laptop, csrf))
    assert r.status_code == 204
    assert phone.get("/api/workspace/me").status_code == 401
    r = laptop.delete(f"/api/workspace/me/sessions/{phone_hash}", headers=authed(laptop, csrf))
    assert r.status_code == 404
    r = laptop.delete("/api/workspace/me/sessions/NOT-HEX-ID!", headers=authed(laptop, csrf))
    assert r.status_code == 422
    r = laptop.post("/api/workspace/me/sessions/revoke-others", headers=authed(laptop, csrf))
    assert r.json() == {"revoked": 1}
    assert tablet.get("/api/workspace/me").status_code == 401
    assert laptop.get("/api/workspace/me").status_code == 200


def test_someone_elses_session_id_is_not_found(ws):
    conn = db()
    company = seed_company(conn)
    mine, theirs = _client(), _client()
    csrf = login(mine, company.member_a.email)
    login(theirs, company.member_b.email)
    their_id = auth.token_hash(theirs.cookies.get(auth.SESSION_COOKIE))[:12]
    r = mine.delete(f"/api/workspace/me/sessions/{their_id}", headers=authed(mine, csrf))
    assert r.status_code == 404
    assert theirs.get("/api/workspace/me").status_code == 200


def test_admin_routes_need_an_admin(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    login(client, company.member_a.email)
    r = client.get("/api/workspace/admin/users")
    assert r.status_code == 403 and r.json()["error"] == "forbidden"


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/api/workspace/session"), ("GET", "/api/workspace/me"),
    ("POST", "/api/workspace/login"), ("POST", "/api/workspace/setup"),
    ("GET", "/api/workspace/admin/users"), ("POST", "/api/workspace/logout"),
    ("POST", "/api/workspace/login/sso"), ("POST", "/api/workspace/invites/lookup"),
])
def test_disabled_workspace_answers_404_before_401(ws, monkeypatch, method, path):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    r = _client().request(method, path, json={})
    assert r.status_code == 404
    assert r.json()["error"] == "workspace_disabled"
    assert not (ws.data_dir / "workspace" / "workspace.db").exists()
