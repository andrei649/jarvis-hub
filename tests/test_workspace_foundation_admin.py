"""Admin console API: users, departments, organisation, audit and usage (spec §7 workspace_admin)."""

from __future__ import annotations

import csv
import io
import json
import sys
import time
import types

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_admin, workspace_auth, workspace_chat
from agents.core.workspace import audit, reports
from agents.core.workspace import db as workspace_db
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    authed,
    db,
    freeze_clock,
    login,
    make_app,
    make_department,
    make_user,
    seed_company,
    ws,
)

USERS = "/api/workspace/admin/users"
DEPTS = "/api/workspace/admin/departments"
MAILER = "agents.core.workspace.mailer"


def _client() -> TestClient:
    return TestClient(make_app(workspace_auth.router, workspace_admin.router))


@pytest.fixture
def admin(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    csrf = login(client, company.admin.email)
    return company, client, authed(client, csrf)


def _actions(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT action FROM audit ORDER BY id")]


def _fake_mailer(monkeypatch, *, configured=True, error: Exception | None = None) -> list[dict]:
    sent: list[dict] = []
    module = types.ModuleType(MAILER)

    def smtp_configured(conn):
        return configured

    async def send_mail(*, to, subject, text, html=None):
        if error is not None:
            raise error
        sent.append({"to": list(to), "subject": subject, "text": text})

    module.smtp_configured = smtp_configured
    module.send_mail = send_mail
    monkeypatch.setitem(sys.modules, MAILER, module)
    return sent


def _new_user(body_overrides=None, dept=None) -> dict:
    body = {"email": "Nou.Coleg@Acme.test", "name": "Nou Coleg", "role": "member",
            "department_ids": [dept] if dept else []}
    body.update(body_overrides or {})
    return body


# ── users ────────────────────────────────────────────────────────────────────────────

def test_list_users(admin):
    company, client, _headers = admin
    users = client.get(USERS).json()["users"]
    assert len(users) == 4
    me = next(u for u in users if u["id"] == company.admin.id)
    assert me["last_login_at"] is not None and me["pending_invite"] is None
    assert set(me) >= {"id", "email", "name", "role", "status", "department_ids", "last_login_at",
                       "created_at", "pending_invite", "permissions"}


def test_create_user_invites_without_email_by_default(admin):
    company, client, headers = admin
    r = client.post(USERS, headers=headers, json=_new_user(dept=company.dept_b))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["emailed"] is False and "email_error" not in body
    assert body["invite_url"].startswith("http://testserver/workspace/invite#t=")
    user = body["user"]
    assert (user["email"], user["status"], user["role"]) == ("nou.coleg@acme.test", "invited", "member")
    assert user["department_ids"] == [company.dept_b] and user["locale"] == "ro"
    assert user["pending_invite"]["purpose"] == "invite"
    conn = db()
    assert _actions(conn)[-2:] == ["user.created", "user.invite_issued"]


@pytest.mark.parametrize(("overrides", "status", "code"), [
    ({"email": "MEMBER-X@acme.test"}, 409, "email_taken"),
    ({"department_ids": []}, 422, "invalid_request"),
    ({"department_ids": [999]}, 404, "not_found"),
    ({"role": "owner"}, 422, "invalid_request"),
    ({"email": "bad"}, 422, "invalid_request"),
    ({"name": ""}, 422, "invalid_request"),
    ({"send_email": "yes"}, 422, "invalid_request"),
])
def test_create_user_errors(admin, overrides, status, code):
    company, client, headers = admin
    conn = db()
    make_user(conn, role="member", department_ids=[company.dept_a], email="member-x@acme.test")
    body = _new_user(dept=company.dept_a)
    body.update(overrides)
    r = client.post(USERS, headers=headers, json=body)
    assert r.status_code == status and r.json()["error"] == code


def test_create_user_refuses_archived_departments(admin):
    company, client, headers = admin
    archived = make_department(db(), "Vechi", archived=True)
    r = client.post(USERS, headers=headers, json=_new_user(dept=archived))
    assert r.status_code == 409 and r.json()["error"] == "department_archived"


def test_new_users_get_the_org_default_locale(admin):
    company, client, headers = admin
    db().execute("UPDATE org SET default_locale = 'en'")
    r = client.post(USERS, headers=headers, json=_new_user(dept=company.dept_a))
    assert r.json()["user"]["locale"] == "en"


def test_send_email_without_a_mailer_module_still_creates_the_user(admin, monkeypatch):
    company, client, headers = admin
    monkeypatch.setitem(sys.modules, MAILER, None)  # import raises ImportError
    r = client.post(USERS, headers=headers, json=_new_user({"send_email": True}, company.dept_a))
    assert r.status_code == 201
    assert r.json()["emailed"] is False and r.json()["email_error"] == "smtp_not_configured"


def test_send_email_when_smtp_is_unconfigured(admin, monkeypatch):
    company, client, headers = admin
    sent = _fake_mailer(monkeypatch, configured=False)
    r = client.post(USERS, headers=headers, json=_new_user({"send_email": True}, company.dept_a))
    assert r.json()["emailed"] is False and r.json()["email_error"] == "smtp_not_configured"
    assert sent == []


def test_send_email_success_is_audited_without_the_link(admin, monkeypatch):
    company, client, headers = admin
    sent = _fake_mailer(monkeypatch)
    r = client.post(USERS, headers=headers, json=_new_user({"send_email": True}, company.dept_a))
    assert r.status_code == 201 and r.json()["emailed"] is True
    assert sent[0]["to"] == ["nou.coleg@acme.test"]
    assert "Invitație" in sent[0]["subject"] and r.json()["invite_url"] in sent[0]["text"]
    conn = db()
    assert _actions(conn)[-1] == "email.sent"
    token = r.json()["invite_url"].split("#t=")[1]
    assert token not in "\n".join(conn.iterdump())


def test_invite_email_follows_the_users_language(admin, monkeypatch):
    company, client, headers = admin
    sent = _fake_mailer(monkeypatch)
    db().execute("UPDATE org SET default_locale = 'en'")
    client.post(USERS, headers=headers, json=_new_user({"send_email": True}, company.dept_a))
    assert sent[0]["subject"].startswith("Invitation to Nerva Workspace")


@pytest.mark.parametrize(("error", "code"), [
    (WorkspaceError("smtp_failed", "connection refused", 502), "smtp_failed"),
    (WorkspaceError("recipient_not_allowed", status=422), "recipient_not_allowed"),
    (RuntimeError("socket exploded"), "smtp_failed"),
])
def test_mail_failures_leave_the_user_created(admin, monkeypatch, error, code):
    company, client, headers = admin
    _fake_mailer(monkeypatch, error=error)
    r = client.post(USERS, headers=headers, json=_new_user({"send_email": True}, company.dept_a))
    assert r.status_code == 201
    assert r.json()["emailed"] is False and r.json()["email_error"] == code
    conn = db()
    assert conn.execute("SELECT status FROM users WHERE email = 'nou.coleg@acme.test'").fetchone()[0] == "invited"
    row = conn.execute("SELECT details_json FROM audit WHERE action = 'email.failed'").fetchone()
    assert json.loads(row[0])["error_code"] == code


@pytest.mark.parametrize(("error", "code"), [
    (RuntimeError("secret store key mismatch"), "smtp_failed"),
    (WorkspaceError("smtp_password_unreadable", status=409), "smtp_password_unreadable"),
])
def test_unreadable_smtp_settings_are_reported_not_raised(admin, monkeypatch, error, code):
    company, client, headers = admin
    sent = _fake_mailer(monkeypatch)

    def broken(conn):
        raise error

    monkeypatch.setattr(sys.modules[MAILER], "smtp_configured", broken)
    r = client.post(USERS, headers=headers, json=_new_user({"send_email": True}, company.dept_a))
    assert r.status_code == 201, r.text
    assert r.json()["emailed"] is False and r.json()["email_error"] == code
    assert r.json()["invite_url"], "the admin still gets the link to copy"
    r = client.post(f"{USERS}/{r.json()['user']['id']}/invite", headers=headers,
                    json={"send_email": True})
    assert r.status_code == 200 and r.json()["email_error"] == code
    assert sent == []
    assert _actions(db()).count("email.failed") == 2


def test_update_user_fields(admin):
    company, client, headers = admin
    r = client.patch(f"{USERS}/{company.member_a.id}", headers=headers,
                     json={"name": "Nume Nou", "department_ids": [company.dept_a, company.dept_b]})
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["name"] == "Nume Nou" and user["department_ids"] == sorted([company.dept_a, company.dept_b])
    details = json.loads(db().execute(
        "SELECT details_json FROM audit WHERE action = 'user.updated' ORDER BY id DESC").fetchone()[0])
    assert details["fields"] == ["department_ids", "name"]


def test_promotion_and_role_changes_are_audited(admin):
    company, client, headers = admin
    r = client.patch(f"{USERS}/{company.member_a.id}", headers=headers, json={"role": "admin"})
    assert r.json()["user"]["role"] == "admin"
    r = client.patch(f"{USERS}/{company.approver_a.id}", headers=headers, json={"role": "member"})
    assert r.json()["user"]["role"] == "member"
    actions = _actions(db())
    assert "user.promoted" in actions and actions[-1] == "user.updated"


def test_existing_archived_memberships_may_be_kept(admin):
    company, client, headers = admin
    conn = db()
    archived = make_department(conn, "Vechi", archived=True)
    conn.execute("INSERT INTO user_departments VALUES (?, ?)", (company.member_a.id, archived))
    r = client.patch(f"{USERS}/{company.member_a.id}", headers=headers,
                     json={"department_ids": [archived, company.dept_b]})
    assert r.status_code == 200
    r = client.patch(f"{USERS}/{company.member_b.id}", headers=headers,
                     json={"department_ids": [archived]})
    assert r.status_code == 409 and r.json()["error"] == "department_archived"


def test_disable_and_enable(admin):
    company, client, headers = admin
    conn = db()
    invited = make_user(conn, role="member", department_ids=[company.dept_a], status="invited")
    conn.execute("INSERT INTO invites (token_hash, user_id, purpose, created_at, expires_at) "
                 "VALUES ('h', ?, 'invite', 0, 9e12)", (invited.id,))
    for user in (company.member_a, invited):
        r = client.patch(f"{USERS}/{user.id}", headers=headers, json={"status": "disabled"})
        assert r.json()["user"]["status"] == "disabled"
    assert conn.execute("SELECT COUNT(*) FROM invites WHERE user_id = ?", (invited.id,)).fetchone()[0] == 0
    r = client.patch(f"{USERS}/{company.member_a.id}", headers=headers, json={"status": "active"})
    assert r.json()["user"]["status"] == "active"
    r = client.patch(f"{USERS}/{invited.id}", headers=headers, json={"status": "active"})
    assert r.json()["user"]["status"] == "invited", "no password yet: back to invited"
    actions = _actions(conn)
    assert actions.count("user.disabled") == 2 and actions.count("user.enabled") == 2


def test_cannot_disable_self(admin):
    company, client, headers = admin
    make_user(db(), role="admin", department_ids=[company.dept_a])
    r = client.patch(f"{USERS}/{company.admin.id}", headers=headers, json={"status": "disabled"})
    assert r.status_code == 409 and r.json()["error"] == "cannot_disable_self"


def test_last_admin_cannot_be_demoted(admin):
    company, client, headers = admin
    r = client.patch(f"{USERS}/{company.admin.id}", headers=headers, json={"role": "approver"})
    assert r.status_code == 409 and r.json()["error"] == "last_admin"


def test_last_active_admin_rule_ignores_disabled_admins(admin):
    company, client, headers = admin
    other = make_user(db(), role="admin", department_ids=[company.dept_a], status="disabled")
    r = client.patch(f"{USERS}/{company.admin.id}", headers=headers, json={"role": "member"})
    assert r.status_code == 409
    r = client.patch(f"{USERS}/{other.id}", headers=headers, json={"status": "active"})
    assert r.json()["user"]["status"] == "active"
    r = client.patch(f"{USERS}/{company.admin.id}", headers=headers, json={"role": "member"})
    assert r.status_code == 200, "another active admin exists now"
    assert client.get(USERS).status_code == 401, "own role change revoked own sessions"


def test_another_admin_can_be_disabled_while_one_remains(admin):
    company, client, headers = admin
    other = make_user(db(), role="admin", department_ids=[company.dept_a])
    r = client.patch(f"{USERS}/{other.id}", headers=headers, json={"status": "disabled"})
    assert r.status_code == 200


@pytest.mark.parametrize(("path", "status"), [(f"{USERS}/999", 404), (f"{USERS}/0", 422)])
def test_update_unknown_user(admin, path, status):
    _company, client, headers = admin
    assert client.patch(path, headers=headers, json={"name": "x"}).status_code == status


def test_reissue_links(admin):
    company, client, headers = admin
    r = client.post(f"{USERS}/{company.member_a.id}/invite", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["purpose"] == "reset" and body["emailed"] is False and body["expires_at"] > time.time()
    assert _actions(db())[-1] == "auth.reset_link_issued"
    assert client.post(f"{USERS}/999/invite", headers=headers).status_code == 404


def test_reset_email_wording(admin, monkeypatch):
    company, client, headers = admin
    sent = _fake_mailer(monkeypatch)
    r = client.post(f"{USERS}/{company.member_a.id}/invite", headers=headers, json={"send_email": True})
    assert r.json()["emailed"] is True and "Resetarea parolei" in sent[0]["subject"]


# ── departments ──────────────────────────────────────────────────────────────────────

def test_list_departments_includes_archived_with_counts(admin):
    company, client, _headers = admin
    make_department(db(), "Arhivă", archived=True)
    items = client.get(DEPTS).json()["departments"]
    assert [d["archived"] for d in items] == [False, False, True]
    sales = next(d for d in items if d["id"] == company.dept_a)
    assert (sales["member_count"], sales["document_count"], sales["report_count"],
            sales["conversation_count"]) == (3, 0, 0, 0)
    assert "assistant_instructions" in sales


def test_create_department(admin):
    _company, client, headers = admin
    r = client.post(DEPTS, headers=headers, json={"name": "Financiar Contabil",
                                                  "description": "Facturi\nși bugete",
                                                  "assistant_instructions": "Răspunde concis."})
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "financiar-contabil" and body["description"] == "Facturi\nși bugete"
    assert body["member_count"] == 0 and body["archived"] is False
    r = client.post(DEPTS, headers=headers, json={"name": "financiar contabil"})
    assert r.status_code == 409 and r.json()["error"] == "department_exists"
    assert _actions(db())[-1] == "department.created"


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "x" * 201},
                                  {"name": "Ok", "description": "x" * 4001},
                                  {"name": "Ok", "assistant_instructions": 5}])
def test_create_department_validation(admin, body):
    _company, client, headers = admin
    assert client.post(DEPTS, headers=headers, json=body).status_code == 422


def test_update_archive_and_restore_department(admin):
    company, client, headers = admin
    r = client.patch(f"{DEPTS}/{company.dept_b}", headers=headers,
                     json={"name": "Oameni și Cultură", "assistant_instructions": "Fii empatic."})
    assert r.status_code == 200
    assert r.json()["name"] == "Oameni și Cultură" and r.json()["slug"] == "resurse-umane", "slug stable"
    r = client.patch(f"{DEPTS}/{company.dept_b}", headers=headers, json={"archived": True})
    assert r.json()["archived"] is True
    r = client.patch(f"{DEPTS}/{company.dept_b}", headers=headers, json={"archived": False})
    assert r.json()["archived"] is False
    actions = _actions(db())
    assert actions[-3:] == ["department.updated", "department.archived", "department.updated"]
    r = client.patch(f"{DEPTS}/{company.dept_b}", headers=headers, json={"name": "VÂNZĂRI"})
    assert r.status_code == 409
    assert client.patch(f"{DEPTS}/999", headers=headers, json={"name": "x"}).status_code == 404


def _insert(conn, sql: str, params: tuple) -> int:
    with workspace_db.tx(conn):
        return int(conn.execute(sql, params).lastrowid)


@pytest.mark.parametrize("content", ["member", "document", "report", "conversation"])
def test_delete_refuses_a_department_with_content(admin, content):
    company, client, headers = admin
    conn = db()
    dept = make_department(conn, "Temporar")
    if content == "member":
        make_user(conn, role="member", department_ids=[dept], status="disabled")
    elif content == "document":
        _insert(conn, "INSERT INTO documents (department_id, title, filename, mime, size_bytes, sha256, "
                "status, created_at, updated_at) VALUES (?, 't', 'f', 'm', 1, 's', 'ready', 0, 0)", (dept,))
    elif content == "report":
        _insert(conn, "INSERT INTO reports (department_id, name, instructions, created_at, updated_at) "
                "VALUES (?, 'r', 'i', 0, 0)", (dept,))
    else:
        _insert(conn, "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
                "VALUES (?, ?, 't', 0, 0)", (company.admin.id, dept))
    r = client.delete(f"{DEPTS}/{dept}", headers=headers)
    assert r.status_code == 409 and r.json()["error"] == "department_not_empty"
    assert r.json()[f"{content}_count"] == 1


def test_delete_empty_department_detaches_approval_history(admin):
    company, client, headers = admin
    conn = db()
    dept = make_department(conn, "Temporar")
    approval = _insert(conn, "INSERT INTO approvals (kind, department_id, requester_id, summary, payload_json, "
                       "status, created_at, expires_at) VALUES ('x', ?, ?, 's', '{}', 'rejected', 0, 0)",
                       (dept, company.admin.id))
    assert client.delete(f"{DEPTS}/{dept}", headers=headers).status_code == 204
    assert conn.execute("SELECT COUNT(*) FROM departments WHERE id = ?", (dept,)).fetchone()[0] == 0
    assert conn.execute("SELECT department_id FROM approvals WHERE id = ?", (approval,)).fetchone()[0] is None
    details = json.loads(conn.execute(
        "SELECT details_json FROM audit WHERE action = 'department.deleted'").fetchone()[0])
    assert details == {"name": "Temporar", "slug": "temporar", "detached_approvals": 1}
    assert client.delete(f"{DEPTS}/{dept}", headers=headers).status_code == 404


# ── organisation ─────────────────────────────────────────────────────────────────────

def test_org_read_and_update(admin):
    _company, client, headers = admin
    assert client.get("/api/workspace/admin/org").json()["model_policy"] == "local_only"
    r = client.patch("/api/workspace/admin/org", headers=headers,
                     json={"name": "Acme Group", "default_locale": "en", "model_policy": "allow_cloud"})
    assert r.status_code == 200
    assert r.json() == {"name": "Acme Group", "default_locale": "en", "model_policy": "allow_cloud",
                        "created_at": r.json()["created_at"]}
    details = json.loads(db().execute(
        "SELECT details_json FROM audit WHERE action = 'org.updated'").fetchone()[0])
    assert details["model_policy"] == {"from": "local_only", "to": "allow_cloud"}
    r = client.patch("/api/workspace/admin/org", headers=headers, json={"model_policy": "anything"})
    assert r.status_code == 422


@pytest.mark.parametrize(("method", "path", "field"), [
    ("PATCH", f"{USERS}/{2 ** 63}", "user_id"),
    ("POST", f"{USERS}/{10 ** 20}/invite", "user_id"),
    ("PATCH", f"{DEPTS}/{2 ** 63}", "department_id"),
    ("DELETE", f"{DEPTS}/{10 ** 20}", "department_id"),
    ("GET", f"/api/workspace/admin/audit?actor_id={2 ** 63}", "actor_id"),
    ("GET", f"/api/workspace/admin/audit?before_id={10 ** 20}", "before_id"),
    ("GET", f"/api/workspace/admin/audit/export?before_id={2 ** 63}", "before_id"),
])
def test_ids_beyond_the_database_range_are_422_not_500(admin, method, path, field):
    _company, client, headers = admin
    r = client.request(method, path, headers=headers, json={"name": "x"})
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "invalid_request" and r.json()["field"] == field
    assert r.json()["reason"] == "too_large"


def test_body_ids_beyond_the_database_range_are_422(admin):
    company, client, headers = admin
    r = client.post(USERS, headers=headers, json=_new_user({"department_ids": [2 ** 63]}))
    assert r.status_code == 422 and r.json()["reason"] == "too_large"
    r = client.patch(f"{USERS}/{company.member_a.id}", headers=headers,
                     json={"department_ids": [10 ** 20]})
    assert r.status_code == 422 and r.json()["field"] == "department_ids"


def test_org_routes_before_setup_answer_setup_required(ws):
    """An admin row without the organisation (a half-restored backup) gets a clear 409."""
    conn = db()
    dept = make_department(conn, "General")
    admin_user = make_user(conn, role="admin", department_ids=[dept])
    client = _client()
    headers = authed(client, login(client, admin_user.email))
    for method in ("GET", "PATCH"):
        r = client.request(method, "/api/workspace/admin/org", headers=headers, json={"name": "X"})
        assert r.status_code == 409 and r.json()["error"] == "setup_required", method
    assert conn.execute("SELECT COUNT(*) FROM org").fetchone()[0] == 0


def test_members_cannot_reach_any_admin_route(ws):
    conn = db()
    company = seed_company(conn)
    client = _client()
    csrf = login(client, company.approver_a.email)
    headers = authed(client, csrf)
    for method, path in (("GET", USERS), ("POST", USERS), ("PATCH", f"{USERS}/1"),
                         ("POST", f"{USERS}/1/invite"), ("GET", DEPTS), ("POST", DEPTS),
                         ("PATCH", f"{DEPTS}/1"), ("DELETE", f"{DEPTS}/1"),
                         ("GET", "/api/workspace/admin/org"), ("PATCH", "/api/workspace/admin/org"),
                         ("GET", "/api/workspace/admin/audit"), ("GET", "/api/workspace/admin/audit/export"),
                         ("GET", "/api/workspace/admin/audit/verify"), ("GET", "/api/workspace/admin/stats")):
        r = client.request(method, path, headers=headers, json={})
        assert r.status_code == 403, (method, path)


# ── audit ────────────────────────────────────────────────────────────────────────────

def test_audit_list_filters_and_pagination(admin):
    company, client, headers = admin
    for n in range(3):
        client.post(DEPTS, headers=headers, json={"name": f"Echipa {n}"})
    items = client.get("/api/workspace/admin/audit").json()["items"]
    assert [i["action"] for i in items[:3]] == ["department.created"] * 3
    assert items[0]["actor_name"] == company.admin.name and items[0]["details"]["name"] == "Echipa 2"
    page = client.get("/api/workspace/admin/audit?limit=2").json()
    assert len(page["items"]) == 2 and page["next_before_id"] == page["items"][-1]["id"]
    rest = client.get(f"/api/workspace/admin/audit?limit=200&before_id={page['next_before_id']}").json()
    assert all(i["id"] < page["next_before_id"] for i in rest["items"]) and rest["next_before_id"] is None
    grouped = client.get("/api/workspace/admin/audit?action=auth").json()["items"]
    assert grouped and all(i["action"].startswith("auth.") for i in grouped)
    exact = client.get("/api/workspace/admin/audit?action=department.created").json()["items"]
    assert len(exact) == 3
    mine = client.get(f"/api/workspace/admin/audit?actor_id={company.admin.id}").json()["items"]
    assert {i["actor_user_id"] for i in mine} == {company.admin.id}
    assert client.get(f"/api/workspace/admin/audit?actor_id={company.member_b.id}").json()["items"] == []
    future = client.get(f"/api/workspace/admin/audit?since={time.time() + 3600}").json()["items"]
    assert future == []
    past = client.get("/api/workspace/admin/audit?until=1").json()["items"]
    assert past == []
    for bad in ("action=DROP%20TABLE", "action=a%25", "limit=201", "limit=0", "before_id=0"):
        assert client.get(f"/api/workspace/admin/audit?{bad}").status_code == 422, bad


def test_audit_export_is_a_safe_csv(admin):
    company, client, headers = admin
    client.post(DEPTS, headers=headers, json={"name": "=HYPERLINK(\"http://evil\")"})
    client.post(DEPTS, headers=headers, json={"name": "@SUM(A1)"})
    client.post(DEPTS, headers=headers, json={"name": "Normal"})
    r = client.get("/api/workspace/admin/audit/export?action=department.created")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith("attachment; filename*=UTF-8''nerva-audit-")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert r.content.startswith("﻿".encode())
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][:7] == ["id", "time_utc", "ts", "actor_user_id", "actor_email", "actor_name", "action"]
    assert len(rows) == 4 and [row[6] for row in rows[1:]] == ["department.created"] * 3
    assert [int(row[0]) for row in rows[1:]] == sorted(int(row[0]) for row in rows[1:]), "oldest first"
    for row in rows[1:]:
        for cell in row:
            assert not cell.startswith(("=", "+", "-", "@", "\t", "\r")), cell
    details = [row[11] for row in rows[1:]]
    assert '"name":"=HYPERLINK' in details[0], "JSON cells start with { and stay intact"


@pytest.mark.parametrize(("value", "expected"), [
    ("=1+1", "'=1+1"), ("+1", "'+1"), ("-1", "'-1"), ("@x", "'@x"), ("\tx", "'\tx"),
    ("\rx", "'\rx"), ("ok", "ok"), (None, ""), (42, "42"), (-3, "'-3"),
])
def test_csv_cell_escaping(value, expected):
    assert workspace_admin.csv_cell(value) == expected


def test_audit_verify_detects_tampering(admin):
    _company, client, headers = admin
    client.post(DEPTS, headers=headers, json={"name": "Echipa"})
    ok = client.get("/api/workspace/admin/audit/verify").json()
    assert ok["ok"] is True and ok["checked"] == 2 and ok["keyed"] is True and ok["key_mismatch"] is False
    conn = db()
    target = conn.execute("SELECT id FROM audit WHERE action = 'department.created'").fetchone()[0]
    conn.execute("UPDATE audit SET details_json = '{\"name\":\"Altceva\"}' WHERE id = ?", (target,))
    broken = client.get("/api/workspace/admin/audit/verify").json()
    assert broken["ok"] is False and broken["broken_at"] == target


# ── usage ────────────────────────────────────────────────────────────────────────────

def _seed_activity(conn, company, clock) -> dict:
    """Rows as the product writes them: each question and each run start also leaves the audit
    row its route records (chat.asked / report.run_started, with the department), at its time."""
    now = clock.current
    day = 86400
    with workspace_db.tx(conn):
        doc = conn.execute(
            "INSERT INTO documents (department_id, title, filename, mime, size_bytes, sha256, status, "
            "created_at, updated_at) VALUES (?, 't', 'f', 'm', 1, 's', 'ready', ?, ?)",
            (company.dept_a, now, now)).lastrowid
        assert doc
        conv_a = conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, 'a', ?, ?)", (company.member_a.id, company.dept_a, now, now)).lastrowid
        conv_b = conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, 'b', ?, ?)", (company.member_b.id, company.dept_b, now, now)).lastrowid
        messages = [
            (conv_a, "user", None, now), (conv_a, "assistant", 1, now),
            (conv_a, "user", None, now - day), (conv_a, "assistant", -1, now - day),
            (conv_b, "user", None, now - 2 * day), (conv_b, "assistant", 1, now - 2 * day),
            (conv_b, "user", None, now - 40 * day),  # outside a 30-day window
        ]
        conn.executemany("INSERT INTO messages (conversation_id, role, content, feedback, created_at) "
                         "VALUES (?, ?, 'x', ?, ?)", messages)
        report = conn.execute("INSERT INTO reports (department_id, name, instructions, created_at, "
                              "updated_at) VALUES (?, 'r', 'i', ?, ?)",
                              (company.dept_a, now, now)).lastrowid
        conn.executemany("INSERT INTO report_runs (report_id, status, trigger, created_at) "
                         "VALUES (?, 'succeeded', 'manual', ?)", [(report, now), (report, now - day)])
        conn.execute("INSERT INTO approvals (kind, department_id, requester_id, summary, payload_json, "
                     "status, created_at, expires_at) VALUES ('x', ?, ?, 's', '{}', 'pending', ?, ?)",
                     (company.dept_a, company.member_a.id, now, now + 7 * day))
    activity = [(company.member_a, "chat.asked", "conversation", conv_a, company.dept_a, at)
                for at in (now, now - day)]
    activity += [(company.member_b, "chat.asked", "conversation", conv_b, company.dept_b, at)
                 for at in (now - 2 * day, now - 40 * day)]
    activity += [(company.member_a, "report.run_started", "report_run", run_id, company.dept_a, at)
                 for run_id, at in ((1, now), (2, now - day))]
    for actor, action, target_type, target_id, department_id, at in activity:
        clock.current = at
        with workspace_db.tx(conn):
            audit.record(conn, actor=actor, action=action, target_type=target_type,
                         target_id=target_id, department_id=department_id)
    clock.current = now
    return {"conv_a": conv_a, "conv_b": conv_b, "report": report}


def test_stats_with_seeded_rows(ws, monkeypatch):
    now = 1_800_014_400.0  # 2027-01-15 12:00 UTC
    clock = freeze_clock(monkeypatch, start=now)
    conn = db()
    company = seed_company(conn)
    client = _client()
    login(client, company.admin.email)
    _seed_activity(conn, company, clock)
    body = client.get("/api/workspace/admin/stats").json()
    assert body["days"] == 30
    assert body["totals"] == {
        "users": 4, "active_users_7d": 1, "documents": 1, "conversations": 2, "questions": 3,
        "reports": 1, "report_runs": 2, "approvals_pending": 1, "feedback_up": 2, "feedback_down": 1,
    }
    per = {d["department_id"]: d for d in body["per_department"]}
    assert per[company.dept_a] == {
        "department_id": company.dept_a, "slug": "vanzari", "name": "Vânzări", "archived": False,
        "members": 3, "documents": 1, "conversations": 1, "questions": 2, "reports": 1, "report_runs": 2,
    }
    assert per[company.dept_b]["questions"] == 1 and per[company.dept_b]["report_runs"] == 0
    daily = body["daily"]
    assert len(daily) == 30 and daily[-1]["date"] == "2027-01-15"
    assert daily[-1] == {"date": "2027-01-15", "questions": 1, "report_runs": 1}
    assert daily[-2] == {"date": "2027-01-14", "questions": 1, "report_runs": 1}
    assert daily[-3] == {"date": "2027-01-13", "questions": 1, "report_runs": 0}
    assert sum(d["questions"] for d in daily) == body["totals"]["questions"]
    week = client.get("/api/workspace/admin/stats?days=1").json()
    assert week["totals"]["questions"] == 1 and len(week["daily"]) == 1


def test_deleting_conversations_and_reports_does_not_rewrite_past_usage(ws, monkeypatch):
    """The period's questions and runs stay counted after their rows are deleted (they were
    asked and run; the audit trail says so), while current totals drop as they should."""
    now = 1_800_014_400.0
    clock = freeze_clock(monkeypatch, start=now)
    conn = db()
    company = seed_company(conn)
    admin_client = _client()
    login(admin_client, company.admin.email)
    seeded = _seed_activity(conn, company, clock)
    before = admin_client.get("/api/workspace/admin/stats").json()

    member = TestClient(make_app(workspace_auth.router, workspace_chat.router))
    csrf = login(member, company.member_a.email)
    deleted = member.delete(f"/api/workspace/conversations/{seeded['conv_a']}", headers=authed(member, csrf))
    assert deleted.status_code == 204
    reports.delete_report(conn, company.admin, seeded["report"])
    assert conn.execute("SELECT COUNT(*) FROM report_runs").fetchone()[0] == 0

    after = admin_client.get("/api/workspace/admin/stats").json()
    for key in ("questions", "report_runs"):
        assert after["totals"][key] == before["totals"][key], key
    assert after["daily"] == before["daily"]
    per_before = {d["department_id"]: d for d in before["per_department"]}
    per_after = {d["department_id"]: d for d in after["per_department"]}
    assert per_after[company.dept_a]["questions"] == per_before[company.dept_a]["questions"] == 2
    assert per_after[company.dept_a]["report_runs"] == per_before[company.dept_a]["report_runs"] == 2
    assert after["totals"]["conversations"] == before["totals"]["conversations"] - 1
    assert after["totals"]["reports"] == before["totals"]["reports"] - 1
    assert per_after[company.dept_a]["conversations"] == 0 and per_after[company.dept_a]["reports"] == 0


@pytest.mark.parametrize("days", ["0", "366", "x"])
def test_stats_days_bounds(admin, days):
    _company, client, _headers = admin
    r = client.get(f"/api/workspace/admin/stats?days={days}")
    assert r.status_code == 422 and r.json()["field"] == "days"


def test_stats_on_an_empty_workspace(admin):
    _company, client, _headers = admin
    body = client.get("/api/workspace/admin/stats?days=7").json()
    assert body["totals"]["documents"] == 0 and body["totals"]["questions"] == 0
    assert all(d["questions"] == 0 for d in body["daily"]) and len(body["daily"]) == 7
