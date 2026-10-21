"""No S1 route answers 500 to odd input (spec §12 "Correctness & robustness").

Every JSON field of every S1 write route is sent values of the wrong type, out of
range, oversized, empty, or text that cannot be stored (lone surrogates, NUL). Each
must come back as a 4xx in the workspace error shape — never an unhandled exception.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_admin, workspace_auth
from agents.core.workspace import auth
from agents.core.workspace import db as workspace_db
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    authed,
    db,
    login,
    make_app,
    make_user,
    origin_of,
    seed_company,
    ws,
)

API = "/api/workspace"
ODD_VALUES = [
    "\ud800", "Ana\udfffMaria" * 2, "a\x00b", "a\x85b", 1e308, -1, 2 ** 64, [], {}, True,
    "x" * 9000, "", " ", "é" * 300, [None], [{"id": 1}],
]
ODD_BODIES = [b"\xff\xfe", b"[1,2]", b'{"a": NaN}', b'{"a": -Infinity}', b'{"a":1e999}',
              b"[" * 20000 + b"]" * 20000, b'{"a":' + b"[" * 20000 + b"]" * 20000 + b"}", b'"x"', b"null",
              b"{not json}"]
VALID = {
    "setup_code": "test-setup-code", "org_name": "Acme", "name": "Ana", "email": "ana@acme.test",
    "password": "Parola-Buna-2026!", "locale": "ro", "theme": "dark",
    "current_password": "nu-este-parola-mea", "new_password": "Alta-Parola-Lunga-9",
    "ids": [1], "all": False, "role": "member", "send_email": False, "status": "active",
    "description": "d", "assistant_instructions": "a", "archived": False,
    "default_locale": "ro", "model_policy": "local_only",
}
ROUTES = {
    "setup": ("POST", "/setup", ["setup_code", "org_name", "name", "email", "password", "locale"]),
    "login": ("POST", "/login", ["email", "password"]),
    "lookup": ("POST", "/invites/lookup", ["token"]),
    "accept": ("POST", "/invites/accept", ["token", "password", "name"]),
    "me": ("PATCH", "/me", ["name", "locale", "theme"]),
    "password": ("POST", "/me/password", ["current_password", "new_password"]),
    "read": ("POST", "/notifications/read", ["ids", "all"]),
    "create_user": ("POST", "/admin/users", ["email", "name", "role", "department_ids", "send_email"]),
    "update_user": ("PATCH", "/admin/users/{member}", ["name", "role", "department_ids", "status"]),
    "invite": ("POST", "/admin/users/{member}/invite", ["send_email"]),
    "create_dept": ("POST", "/admin/departments", ["name", "description", "assistant_instructions"]),
    "update_dept": ("PATCH", "/admin/departments/{dept}",
                    ["name", "description", "assistant_instructions", "archived"]),
    "org": ("PATCH", "/admin/org", ["name", "default_locale", "model_policy"]),
}


def _send(client: TestClient, method: str, path: str, raw: bytes, headers: dict):
    return client.request(method, API + path, content=raw,
                          headers={**headers, "Content-Type": "application/json"})


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_odd_input_never_reaches_a_500(ws, route):
    method, template, fields = ROUTES[route]
    conn = db()
    company = None if route == "setup" else seed_company(conn)
    client = TestClient(make_app(workspace_auth.router, workspace_admin.router),
                        raise_server_exceptions=False)
    headers = {"Origin": origin_of(client)}
    valid = dict(VALID)
    if company is not None:
        headers = authed(client, login(client, company.admin.email))
        valid["department_ids"] = [company.dept_a]
        with workspace_db.tx(conn):
            token, _expires = auth.issue_invite(conn, make_user(
                conn, role="member", department_ids=[company.dept_a], status="invited").id,
                purpose="invite", created_by=None)
        valid["token"] = token
    path = template.format(member=company.member_b.id if company else 0,
                           dept=company.dept_b if company else 0)
    failures = []
    for field in fields:
        for odd in ODD_VALUES:
            body = {key: valid[key] for key in fields} | {field: odd}
            r = _send(client, method, path, json.dumps(body).encode("ascii"), headers)
            if r.status_code >= 500 or "error" not in r.json() and r.status_code >= 400:
                failures.append((field, repr(odd)[:24], r.status_code))
    for raw in ODD_BODIES:
        r = _send(client, method, path, raw, headers)
        if r.status_code >= 500 or r.status_code < 400:
            failures.append(("<body>", raw[:12], r.status_code))
    assert failures == []


def test_an_invite_token_that_is_not_ascii_is_just_invalid(ws):
    seed_company(db())
    client = TestClient(make_app(workspace_auth.router), raise_server_exceptions=False)
    for path in ("/invites/lookup", "/invites/accept"):
        r = client.post(API + path, headers={"Origin": origin_of(client)},
                        json={"token": "ă" * 43, "password": DEFAULT_PASSWORD})
        assert r.status_code == 404 and r.json()["error"] == "invite_invalid", path
        raw = json.dumps({"token": "\ud800" * 43, "password": DEFAULT_PASSWORD}).encode("ascii")
        r = client.post(API + path, content=raw,
                        headers={"Origin": origin_of(client), "Content-Type": "application/json"})
        assert r.status_code == 404 and r.json()["error"] == "invite_invalid", path
