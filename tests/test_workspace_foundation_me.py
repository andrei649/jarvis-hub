"""Profile, password change, departments and notification routes (spec §7 workspace_auth)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth
from agents.core.workspace import auth, notifications
from agents.core.workspace import db as workspace_db
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    authed,
    db,
    login,
    make_app,
    make_department,
    make_user,
    seed_company,
    ws,
)

NEW_PASSWORD = "Alta-Parola-Lunga-9"


@pytest.fixture
def member(ws):
    conn = db()
    company = seed_company(conn)
    client = TestClient(make_app(workspace_auth.router))
    csrf = login(client, company.member_a.email)
    return company, client, csrf


def test_me_returns_user_org_and_departments(member):
    company, client, _csrf = member
    body = client.get("/api/workspace/me").json()
    assert body["user"]["id"] == company.member_a.id
    assert body["org"]["name"] == "Acme"
    assert [d["id"] for d in body["departments"]] == [company.dept_a]
    assert set(body["departments"][0]) == {"id", "slug", "name", "description", "archived",
                                           "created_at", "member_count", "document_count",
                                           "ready_document_count"}


def test_a_department_counts_its_ready_documents_apart(member):
    """Failed or still-processing uploads are documents, but the assistant cannot cite them:
    the chat's "no documents yet" guidance reads ready_document_count."""
    from tests.fixtures.workspace.doc_helpers import seed_document

    company, client, _csrf = member
    conn = db()
    for status in ("ready", "failed", "processing"):
        seed_document(conn, department_id=company.dept_a, uploader_id=company.member_a.id,
                      title=f"Doc {status}", chunks=["Text."], status=status)
    sales = client.get("/api/workspace/departments").json()["departments"][0]
    assert (sales["document_count"], sales["ready_document_count"]) == (3, 1)


def test_update_profile(member):
    company, client, csrf = member
    r = client.patch("/api/workspace/me", headers=authed(client, csrf),
                     json={"name": "Maria Ionescu", "locale": "en", "theme": "system"})
    assert r.status_code == 200
    user = r.json()["user"]
    assert (user["name"], user["locale"], user["theme"]) == ("Maria Ionescu", "en", "system")
    details = json.loads(db().execute(
        "SELECT details_json FROM audit WHERE action = 'user.updated'").fetchone()[0])
    assert details == {"fields": ["locale", "name", "theme"], "self": True}
    r = client.patch("/api/workspace/me", headers=authed(client, csrf), json={})
    assert r.status_code == 200 and r.json()["user"]["name"] == "Maria Ionescu"
    assert db().execute("SELECT COUNT(*) FROM audit WHERE action = 'user.updated'").fetchone()[0] == 1


@pytest.mark.parametrize("body", [{"theme": "neon"}, {"locale": "de"}, {"name": ""},
                                  {"name": "x" * 201}, {"name": "a\nb"}])
def test_update_profile_validation(member, body):
    _company, client, csrf = member
    r = client.patch("/api/workspace/me", headers=authed(client, csrf), json=body)
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"


def test_change_password(member):
    company, client, csrf = member
    r = client.post("/api/workspace/me/password", headers=authed(client, csrf),
                    json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 204
    other = TestClient(make_app(workspace_auth.router))
    assert other.post("/api/workspace/login", json={"email": company.member_a.email,
                                                    "password": DEFAULT_PASSWORD}).status_code == 401
    login(other, company.member_a.email, NEW_PASSWORD)
    details = json.loads(db().execute(
        "SELECT details_json FROM audit WHERE action = 'auth.password_changed'").fetchone()[0])
    assert details["via"] == "profile"


def test_change_password_wrong_current_counts_toward_the_lockout(member):
    company, client, csrf = member
    for _ in range(auth.LOGIN_EMAIL_LIMIT):
        r = client.post("/api/workspace/me/password", headers=authed(client, csrf),
                        json={"current_password": "not-my-password", "new_password": NEW_PASSWORD})
        assert r.status_code == 403 and r.json()["error"] == "wrong_password"
    r = client.post("/api/workspace/me/password", headers=authed(client, csrf),
                    json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 429
    actor = db().execute("SELECT actor_user_id FROM audit WHERE action = 'auth.login_failed'").fetchone()
    assert actor[0] == company.member_a.id


def test_a_proven_current_password_resets_the_count_even_when_the_new_one_is_weak(member):
    company, client, csrf = member
    headers = authed(client, csrf)
    for _ in range(auth.LOGIN_EMAIL_LIMIT - 1):
        r = client.post("/api/workspace/me/password", headers=headers,
                        json={"current_password": "not-my-password", "new_password": NEW_PASSWORD})
        assert r.status_code == 403
    r = client.post("/api/workspace/me/password", headers=headers,
                    json={"current_password": DEFAULT_PASSWORD, "new_password": "password1234"})
    assert r.status_code == 422 and r.json()["error"] == "weak_password"
    for _ in range(auth.LOGIN_EMAIL_LIMIT - 1):
        r = client.post("/api/workspace/me/password", headers=headers,
                        json={"current_password": "not-my-password", "new_password": NEW_PASSWORD})
        assert r.status_code == 403, "the proven password reset the consecutive failures"
    rows = db().execute("SELECT ok FROM login_attempts ORDER BY id").fetchall()
    assert [row[0] for row in rows] == [1] + [0] * 4 + [1] + [0] * 4, \
        "the sign-in, then one row per verified current password"


def test_change_password_policy(member):
    _company, client, csrf = member
    r = client.post("/api/workspace/me/password", headers=authed(client, csrf),
                    json={"current_password": DEFAULT_PASSWORD, "new_password": "password1234"})
    assert r.status_code == 422 and r.json()["reason"] == "too_common"
    r = client.post("/api/workspace/me/password", headers=authed(client, csrf),
                    json={"current_password": DEFAULT_PASSWORD})
    assert r.status_code == 422 and r.json()["field"] == "new_password"


def test_departments_are_scoped(ws):
    conn = db()
    company = seed_company(conn)
    archived = make_department(conn, "Arhivă", archived=True)
    conn.execute("INSERT INTO user_departments (user_id, department_id) VALUES (?, ?)",
                 (company.member_a.id, archived))
    member_client, admin_client = (TestClient(make_app(workspace_auth.router)) for _ in range(2))
    login(member_client, company.member_a.email)
    login(admin_client, company.admin.email)
    mine = member_client.get("/api/workspace/departments").json()["departments"]
    assert [d["id"] for d in mine] == [company.dept_a], "archived and foreign departments hidden"
    assert mine[0]["member_count"] == 3 and "assistant_instructions" not in mine[0]
    every = admin_client.get("/api/workspace/departments").json()["departments"]
    assert sorted(d["id"] for d in every) == sorted([company.dept_a, company.dept_b])


def test_notifications_are_private_and_markable(ws):
    conn = db()
    company = seed_company(conn)
    with workspace_db.tx(conn):
        notifications.notify(conn, [company.member_a.id], kind="approval.requested", title="Aprobare 1",
                             link="/workspace/approvals/1")
        notifications.notify(conn, [company.member_a.id], kind="report.ready", title="Raport gata")
        notifications.notify(conn, [company.member_b.id], kind="report.ready", title="Al altcuiva")
    foreign = conn.execute("SELECT id FROM notifications WHERE user_id = ?",
                           (company.member_b.id,)).fetchone()[0]
    client = TestClient(make_app(workspace_auth.router))
    csrf = login(client, company.member_a.email)
    body = client.get("/api/workspace/notifications").json()
    assert body["unread_count"] == 2 and [n["title"] for n in body["items"]] == ["Raport gata", "Aprobare 1"]
    assert set(body["items"][0]) == {"id", "kind", "title", "body", "link", "created_at", "read_at", "read"}
    first = body["items"][1]["id"]
    r = client.post("/api/workspace/notifications/read", headers=authed(client, csrf),
                    json={"ids": [first, foreign]})
    assert r.json() == {"unread_count": 1}
    assert conn.execute("SELECT read_at FROM notifications WHERE id = ?", (foreign,)).fetchone()[0] is None
    unread = client.get("/api/workspace/notifications?unread=1").json()["items"]
    assert [n["title"] for n in unread] == ["Raport gata"]
    assert len(client.get("/api/workspace/notifications?limit=1").json()["items"]) == 1
    assert client.get("/api/workspace/notifications?limit=0").status_code == 422
    r = client.post("/api/workspace/notifications/read", headers=authed(client, csrf), json={"all": True})
    assert r.json() == {"unread_count": 0}
    r = client.post("/api/workspace/notifications/read", headers=authed(client, csrf))
    assert r.status_code == 200 and r.json() == {"unread_count": 0}


@pytest.mark.parametrize("body", [{"ids": "1"}, {"ids": [0]}, {"all": "yes"}])
def test_mark_read_validation(member, body):
    _company, client, csrf = member
    r = client.post("/api/workspace/notifications/read", headers=authed(client, csrf), json=body)
    assert r.status_code == 422


def test_invited_users_cannot_use_the_api(ws):
    conn = db()
    company = seed_company(conn)
    invited = make_user(conn, role="member", department_ids=[company.dept_a], status="invited")
    client = TestClient(make_app(workspace_auth.router))
    r = client.post("/api/workspace/login", json={"email": invited.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 401
    assert client.get("/api/workspace/me").status_code == 401
