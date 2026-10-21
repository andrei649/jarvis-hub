"""First-run setup through the setup code, and the code file's lifecycle (spec §3, §7)."""

from __future__ import annotations

import os
import stat
import time

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth
from agents.core.workspace import auth, config
from tests.support.workspace_fixtures import SETUP_CODE, db, make_app, ws  # noqa: F401

SETUP = "/api/workspace/setup"


def _body(**overrides) -> dict:
    body = {"setup_code": SETUP_CODE, "org_name": "Acme SRL", "name": "Ana Popescu",
            "email": "Ana@Acme.test", "password": "Parola-Buna-2026!", "locale": "ro"}
    body.update(overrides)
    return body


def _client(host: str = "testclient") -> TestClient:
    return TestClient(make_app(workspace_auth.router), client=(host, 50000))


def test_session_before_setup(ws):
    r = _client().get("/api/workspace/session")
    assert r.status_code == 200
    assert r.json() == {"enabled": True, "setup_required": True, "sso_available": False,
                        "authenticated": False}
    assert r.headers["cache-control"] == "no-store"


def test_setup_creates_org_general_department_and_signed_in_admin(ws):
    client = _client()
    r = client.post(SETUP, json=_body())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["role"] == "admin" and body["user"]["email"] == "ana@acme.test"
    assert body["org"]["name"] == "Acme SRL" and body["org"]["default_locale"] == "ro"
    assert auth.SESSION_COOKIE in r.headers["set-cookie"]
    conn = db()
    dept = conn.execute("SELECT * FROM departments").fetchall()
    assert [(d["name"], d["slug"]) for d in dept] == [("General", "general")]
    assert body["user"]["department_ids"] == [dept[0]["id"]]
    assert conn.execute("SELECT via FROM sessions").fetchone()[0] == "setup"
    assert [row[0] for row in conn.execute("SELECT action FROM audit")] == ["auth.setup"]
    state = client.get("/api/workspace/session").json()
    assert state["setup_required"] is False and state["authenticated"] is True
    assert state["csrf_token"] == body["csrf_token"]
    assert [d["name"] for d in state["departments"]] == ["General"]


def test_setup_only_once(ws):
    client = _client()
    assert client.post(SETUP, json=_body()).status_code == 201
    r = client.post(SETUP, json=_body(email="other@acme.test"))
    assert r.status_code == 409 and r.json()["error"] == "already_setup"


def test_english_locale_is_kept(ws):
    r = _client().post(SETUP, json=_body(locale="en"))
    assert r.json()["user"]["locale"] == "en" and r.json()["org"]["default_locale"] == "en"


@pytest.mark.parametrize(("overrides", "status", "code"), [
    ({"password": "short"}, 422, "weak_password"),
    ({"password": "ana-is-my-name-2026"}, 422, "weak_password"),
    ({"email": "not-an-email"}, 422, "invalid_request"),
    ({"org_name": ""}, 422, "invalid_request"),
    ({"name": "x" * 201}, 422, "invalid_request"),
    ({"locale": "fr"}, 422, "invalid_request"),
    ({"setup_code": ""}, 422, "invalid_request"),
])
def test_setup_validation(ws, overrides, status, code):
    r = _client().post(SETUP, json=_body(**overrides))
    assert r.status_code == status and r.json()["error"] == code
    assert db().execute("SELECT COUNT(*) FROM org").fetchone()[0] == 0


def test_wrong_code_is_403_and_counted(ws):
    r = _client().post(SETUP, json=_body(setup_code="guess"))
    assert r.status_code == 403 and r.json()["error"] == "invalid_setup_code"
    rows = db().execute("SELECT kind, ok FROM login_attempts").fetchall()
    assert [(row["kind"], row["ok"]) for row in rows] == [("setup", 0)]


def test_setup_code_throttle_per_ip(ws):
    client = _client("203.0.113.5")
    for _ in range(auth.SETUP_IP_LIMIT):
        assert client.post(SETUP, json=_body(setup_code="guess")).status_code == 403
    r = client.post(SETUP, json=_body())
    assert r.status_code == 429 and r.json()["error"] == "too_many_attempts"
    assert _client("198.51.100.5").post(SETUP, json=_body()).status_code == 201


def test_setup_code_throttle_global(ws):
    conn = db()
    stamp = time.time()
    conn.executemany(
        "INSERT INTO login_attempts (ip, email, ok, kind, ts) VALUES (?, '', 0, 'setup', ?)",
        [(f"10.0.{n // 250}.{n % 250}", stamp) for n in range(auth.SETUP_GLOBAL_LIMIT)],
    )
    r = _client("198.51.100.77").post(SETUP, json=_body())
    assert r.status_code == 429


def test_generated_code_file_is_created_on_first_need_and_deleted_after_setup(ws, monkeypatch):
    monkeypatch.delenv("NERVA_WORKSPACE_SETUP_CODE")
    client = _client()
    path = config.setup_code_path()
    assert not path.exists()
    client.get("/api/workspace/session")
    assert path.exists()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    code = path.read_bytes().decode("utf-8")
    assert client.post(SETUP, json=_body(setup_code=code)).status_code == 201
    assert not path.exists()
    assert client.get("/api/workspace/session").json()["setup_required"] is False
    assert not path.exists(), "no new code once set up"


def test_setup_rotates_any_presented_session(ws):
    client = _client()
    client.cookies.set(auth.SESSION_COOKIE, "stale-cookie", path="/api/workspace")
    r = client.post(SETUP, json=_body())
    assert r.status_code == 201
    assert client.get("/api/workspace/me").status_code == 200
