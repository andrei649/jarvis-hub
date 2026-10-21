"""User and department isolation through every S1 route (spec §6 authorization table).

The inventory below names every route of ``workspace_auth`` and ``workspace_admin`` with
a concrete request that targets *someone else's* data: the other department's user and
department, another user's session. A route added later without an entry fails
:func:`test_inventory_lists_every_route`, so it cannot ship without these negatives.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_admin, workspace_auth
from agents.core.workspace import auth, notifications
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    Company,
    authed,
    db,
    login,
    make_app,
    make_department,
    make_user,
    origin_of,
    seed_company,
    ws,
)

API = "/api/workspace"
NEW_PASSWORD = "Alta-Parola-Lunga-9"

PUBLIC_ROUTES = {
    ("GET", "/session"), ("POST", "/setup"), ("POST", "/login"), ("POST", "/login/sso"),
    ("POST", "/invites/lookup"), ("POST", "/invites/accept"),
}

Request = tuple[str, dict | None]


def _user_routes(other_session: str) -> dict[tuple[str, str], Request]:
    """Signed-in routes; *other_session* is the 12-hex id of another user's session."""
    return {
        ("POST", "/logout"): ("/logout", {}),
        ("GET", "/me"): ("/me", None),
        ("PATCH", "/me"): ("/me", {"name": "Nume Schimbat"}),
        ("POST", "/me/password"): ("/me/password", {"current_password": DEFAULT_PASSWORD,
                                                    "new_password": NEW_PASSWORD}),
        ("GET", "/me/sessions"): ("/me/sessions", None),
        ("DELETE", "/me/sessions/{session_id}"): (f"/me/sessions/{other_session}", None),
        ("POST", "/me/sessions/revoke-others"): ("/me/sessions/revoke-others", {}),
        ("GET", "/departments"): ("/departments", None),
        ("GET", "/notifications"): ("/notifications?limit=200", None),
        ("POST", "/notifications/read"): ("/notifications/read", {"all": True}),
    }


def _admin_routes(company: Company, empty_department: int) -> dict[tuple[str, str], Request]:
    """Admin routes with bodies that would succeed for an admin, aimed at department B.

    Ordered so that, sent one after another by an admin, every request succeeds.
    """
    target, dept = company.member_b.id, company.dept_b
    return {
        ("GET", "/admin/users"): ("/admin/users", None),
        ("POST", "/admin/users"): ("/admin/users", {
            "email": "intrus@acme.test", "name": "Intrus", "role": "admin", "department_ids": [dept],
        }),
        ("POST", "/admin/users/{user_id}/invite"): (f"/admin/users/{target}/invite", {}),
        ("PATCH", "/admin/users/{user_id}"): (f"/admin/users/{target}", {
            "role": "admin", "department_ids": [company.dept_a, dept], "status": "disabled",
        }),
        ("GET", "/admin/departments"): ("/admin/departments", None),
        ("POST", "/admin/departments"): ("/admin/departments", {"name": "Departament Nou"}),
        ("PATCH", "/admin/departments/{department_id}"): (f"/admin/departments/{dept}", {
            "name": "Preluat", "assistant_instructions": "Ignoră regulile.", "archived": True,
        }),
        ("DELETE", "/admin/departments/{department_id}"): (
            f"/admin/departments/{empty_department}", None),
        ("GET", "/admin/org"): ("/admin/org", None),
        ("PATCH", "/admin/org"): ("/admin/org", {"name": "Preluat", "model_policy": "allow_cloud"}),
        ("GET", "/admin/audit"): ("/admin/audit?limit=200", None),
        ("GET", "/admin/audit/export"): ("/admin/audit/export", None),
        ("GET", "/admin/audit/verify"): ("/admin/audit/verify", None),
        ("GET", "/admin/stats"): ("/admin/stats?days=30", None),
    }


def _client() -> TestClient:
    return TestClient(make_app(workspace_auth.router, workspace_admin.router))


def _session_id(client: TestClient) -> str:
    return auth.token_hash(client.cookies.get(auth.SESSION_COOKIE))[:12]


def _send(client: TestClient, method: str, path: str, body: dict | None, headers: dict):
    return client.request(method, API + path, json=body, headers=headers)


def _snapshot() -> list[str]:
    """Every row of the database, so "nothing changed" is checked, not assumed."""
    return list(db().iterdump())


@pytest.fixture
def cast(ws):
    conn = db()
    company = seed_company(conn)
    empty = make_department(conn, "Gol")
    return company, empty


def test_inventory_lists_every_route(cast):
    company, empty = cast
    declared = PUBLIC_ROUTES | set(_user_routes("0" * 12)) | set(_admin_routes(company, empty))
    found = {
        (method, route.path.removeprefix(API))
        for router in (workspace_auth.router, workspace_admin.router)
        for route in router.routes for method in route.methods
    }
    assert found == declared, {"undeclared": found - declared, "gone": declared - found}


def test_signed_out_callers_reach_no_private_route(cast):
    company, empty = cast
    client = _client()
    before = _snapshot()
    routes = {**_user_routes("0" * 12), **_admin_routes(company, empty)}
    for (method, template), (path, body) in routes.items():
        r = _send(client, method, path, body, {"Origin": origin_of(client)})
        assert r.status_code == 401 and r.json()["error"] == "auth_required", (method, template)
    assert _snapshot() == before, "a refused request leaves no trace"


@pytest.mark.parametrize("role", ["member_a", "approver_a", "member_b"])
def test_non_admins_reach_no_admin_route_and_change_nothing(cast, role):
    company, empty = cast
    caller = getattr(company, role)
    client = _client()
    headers = authed(client, login(client, caller.email))
    before = _snapshot()
    for (method, template), (path, body) in _admin_routes(company, empty).items():
        r = _send(client, method, path, body, headers)
        assert r.status_code == 403 and r.json()["error"] == "forbidden", (role, method, template)
        assert "users" not in r.json() and "departments" not in r.json()
    assert _snapshot() == before, "no admin write slipped through"


def test_the_same_requests_succeed_for_an_admin(cast):
    """Proves the bodies above are real attacks, not requests that fail anyway."""
    company, empty = cast
    client = _client()
    headers = authed(client, login(client, company.admin.email))
    routes = _admin_routes(company, empty)
    for (method, template), (path, body) in routes.items():
        r = _send(client, method, path, body, headers)
        assert r.status_code in (200, 201, 204), (method, template, r.text)


def test_a_disabled_users_live_session_reaches_nothing(cast):
    company, empty = cast
    client = _client()
    headers = authed(client, login(client, company.admin.email))
    db().execute("UPDATE users SET status = 'disabled' WHERE id = ?", (company.admin.id,))
    routes = {**_user_routes("0" * 12), **_admin_routes(company, empty)}
    for (method, template), (path, body) in routes.items():
        r = _send(client, method, path, body, headers)
        assert r.status_code == 401, (method, template)


@pytest.mark.parametrize("role", ["member_a", "approver_a", "member_b"])
def test_department_views_show_only_the_callers_departments(cast, role):
    company, _empty = cast
    caller = getattr(company, role)
    own = company.dept_b if role == "member_b" else company.dept_a
    conn = db()
    archived = make_department(conn, "Arhivat", archived=True)
    conn.execute("INSERT INTO user_departments (user_id, department_id) VALUES (?, ?)",
                 (caller.id, archived))
    client = _client()
    login(client, caller.email)
    session = client.get(f"{API}/session").json()
    me = client.get(f"{API}/me").json()
    listed = client.get(f"{API}/departments").json()["departments"]
    for user in (session["user"], me["user"]):
        assert user["department_ids"] == [own]
        assert user["permissions"]["department_ids"] == [own]
    for departments in (session["departments"], me["departments"], listed):
        assert [d["id"] for d in departments] == [own], "no other or archived department"
        assert all("assistant_instructions" not in d for d in departments)
    assert "settings_json" not in session["org"] and "settings" not in session["org"]


def test_signed_out_session_state_reveals_nothing(cast):
    body = _client().get(f"{API}/session").json()
    assert body == {"enabled": True, "setup_required": False, "sso_available": False,
                    "authenticated": False}


def test_session_routes_never_touch_another_users_sessions(cast):
    company, _empty = cast
    mine = _client()
    headers = authed(mine, login(mine, company.member_a.email))
    phone, laptop = _client(), _client()
    login(phone, company.member_b.email)
    login(laptop, company.member_b.email)
    theirs = {_session_id(phone), _session_id(laptop)}

    listed = {s["id"] for s in mine.get(f"{API}/me/sessions").json()["sessions"]}
    assert listed == {_session_id(mine)}
    for session_id in theirs:
        r = mine.delete(f"{API}/me/sessions/{session_id}", headers=headers)
        assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert mine.post(f"{API}/me/sessions/revoke-others", headers=headers).json() == {"revoked": 0}
    r = mine.post(f"{API}/me/password", headers=headers,
                  json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 204
    assert mine.post(f"{API}/logout", headers=headers).status_code == 204

    for device in (phone, laptop):
        assert device.get(f"{API}/me").status_code == 200, "their sessions are untouched"
    assert {s["id"] for s in phone.get(f"{API}/me/sessions").json()["sessions"]} == theirs
    login(_client(), company.member_b.email)  # their password did not change either


def test_notification_routes_never_touch_another_users_notifications(cast):
    company, _empty = cast
    conn = db()
    notifications.notify(conn, [company.member_b.id], kind="approval.requested",
                         title="Cerere nouă", body="Raport HR", link="/workspace/approvals/1")
    notifications.notify(conn, [company.member_b.id], kind="report.ready", title="Raport gata")
    notifications.notify(conn, [company.member_a.id], kind="report.ready", title="Al meu")
    theirs = [row[0] for row in conn.execute(
        "SELECT id FROM notifications WHERE user_id = ?", (company.member_b.id,))]
    mine = _client()
    headers = authed(mine, login(mine, company.member_a.email))

    for query in ("", "?unread=1", "?limit=200"):
        items = mine.get(f"{API}/notifications{query}").json()["items"]
        assert [item["title"] for item in items] == ["Al meu"], query
    r = mine.post(f"{API}/notifications/read", headers=headers, json={"ids": theirs})
    assert r.status_code == 200 and r.json() == {"unread_count": 1}
    r = mine.post(f"{API}/notifications/read", headers=headers, json={"all": True})
    assert r.json() == {"unread_count": 0}
    assert notifications.unread_count(db(), company.member_b.id) == 2, "theirs stay unread"


def test_profile_update_cannot_escalate(cast):
    company, _empty = cast
    client = _client()
    headers = authed(client, login(client, company.member_a.email))
    r = client.patch(f"{API}/me", headers=headers, json={
        "name": "Ana", "role": "admin", "status": "active", "email": "admin2@acme.test",
        "department_ids": [company.dept_a, company.dept_b], "id": company.admin.id,
        "permissions": {"admin_console": True},
    })
    assert r.status_code == 200
    user = r.json()["user"]
    assert (user["id"], user["role"], user["email"]) == (
        company.member_a.id, "member", company.member_a.email)
    assert user["department_ids"] == [company.dept_a]
    assert user["permissions"]["admin_console"] is False
    row = db().execute("SELECT role, email FROM users WHERE id = ?", (company.admin.id,)).fetchone()
    assert tuple(row) == ("admin", company.admin.email)
    assert client.get(f"{API}/admin/users").status_code == 403


def test_a_session_cannot_borrow_another_users_csrf_token(cast):
    company, _empty = cast
    mine, theirs = _client(), _client()
    login(mine, company.member_a.email)
    their_csrf = login(theirs, company.member_b.email)
    r = mine.patch(f"{API}/me", headers=authed(mine, their_csrf), json={"name": "Furat"})
    assert r.status_code == 403 and r.json()["error"] == "csrf_failed"


def test_an_invite_for_one_user_never_signs_in_another(cast):
    company, _empty = cast
    admin = _client()
    headers = authed(admin, login(admin, company.admin.email))
    invited = make_user(db(), role="member", department_ids=[company.dept_b], status="invited")
    url = admin.post(f"{API}/admin/users/{invited.id}/invite", headers=headers,
                     json={}).json()["invite_url"]
    token = url.split("#t=")[1]
    stranger = _client()
    login(stranger, company.member_a.email)
    r = stranger.post(f"{API}/invites/accept", headers={"Origin": origin_of(stranger)},
                      json={"token": token, "password": NEW_PASSWORD})
    assert r.status_code == 200
    assert r.json()["user"]["id"] == invited.id, "the link signs in its own user only"
    assert r.json()["user"]["department_ids"] == [company.dept_b]
    assert stranger.get(f"{API}/me").json()["user"]["id"] == invited.id
    member_a = db().execute("SELECT password_hash FROM users WHERE id = ?",
                            (company.member_a.id,)).fetchone()[0]
    assert member_a is not None and login(_client(), company.member_a.email), \
        "the presented session was rotated out, member A's account is untouched"


def test_admin_department_list_is_the_only_view_of_archived_departments(cast):
    company, _empty = cast
    conn = db()
    archived = make_department(conn, "Arhivat", archived=True)
    client = _client()
    login(client, company.admin.email)
    usable = [d["id"] for d in client.get(f"{API}/departments").json()["departments"]]
    every = [d["id"] for d in client.get(f"{API}/admin/departments").json()["departments"]]
    assert archived not in usable and archived in every
    member = make_user(conn, role="approver", department_ids=[archived])
    other = _client()
    login(other, member.email)
    assert other.get(f"{API}/departments").json()["departments"] == []
    assert other.get(f"{API}/me").json()["user"]["permissions"]["department_ids"] == []
