"""Non-ASCII SMTP logins (a regression the independent S4 review found).

``smtplib`` encodes the AUTH exchange as ASCII, so a username or password such as
``parolă`` raised ``UnicodeEncodeError`` out of ``send_mail``: a 500 on the admin test
route, an ``email.send`` approval failing as ``execution_failed`` without its
``email.failed`` audit row, and a report delivery failing with nothing recorded. Now a
non-ASCII login is refused when the admin saves it (``422 not_ascii``) and one stored
earlier fails honestly as ``smtp_failed`` / ``auth_failed`` before any byte of mail.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents.core.workspace import db, mailer, reports
from agents.core.workspace.errors import WorkspaceError
from tests.support.smtp_sink import SmtpSink
from tests.support.workspace_fixtures import freeze_clock, ws  # noqa: F401  (ws is a fixture)
from tests.test_workspace_reports_support import (  # noqa: F401  (cast is a fixture)
    cast,
    configure_smtp,
    run_now,
    seed_document,
    signed_in,
)

NOW = datetime(2026, 10, 17, 13, 0, tzinfo=ZoneInfo("Europe/Bucharest")).timestamp()
ROMANIAN_PASSWORD = "parolă-secretă-2026"


@pytest.fixture
def conn(ws, monkeypatch):
    freeze_clock(monkeypatch, NOW)
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def auth_sink():
    """A sink that offers AUTH and requires the ASCII pair below."""
    with SmtpSink(require_auth=("robot", "Parola-SMTP-1")) as running:
        yield running


def _stored_login(conn, port: int, *, username: str = "robot",
                  password: str = ROMANIAN_PASSWORD) -> None:
    configure_smtp(conn, port, username=username)
    mailer.set_password(password)


@pytest.mark.parametrize(("field", "body"), [
    ("password", {"username": "robot", "password": ROMANIAN_PASSWORD}),
    ("username", {"username": "robőt", "password": "Parola-SMTP-1"}),
])
def test_non_ascii_logins_are_refused_when_saved(conn, cast, field, body):
    full = {"host": "127.0.0.1", "port": 2525, "security": "none",
            "from_address": "rapoarte@acme.test", **body}
    with pytest.raises(WorkspaceError) as caught:
        mailer.parse_update(full, password_stored=False)
    assert (caught.value.code, caught.value.extra) == ("invalid_request",
                                                       {"field": field, "reason": "not_ascii"})
    client, headers = signed_in(cast.admin)
    response = client.put("/api/workspace/admin/smtp", json=full, headers=headers)
    assert response.status_code == 422
    assert (response.json()["field"], response.json()["reason"]) == (field, "not_ascii")
    assert mailer.has_password() is False and mailer.smtp_configured(conn) is False


@pytest.mark.parametrize(("username", "password"), [("robot", ROMANIAN_PASSWORD),
                                                    ("robőt", "Parola-SMTP-1")])
def test_a_stored_non_ascii_login_fails_honestly_before_any_mail(conn, cast, auth_sink, username,
                                                                password):
    _stored_login(conn, auth_sink.port, username=username, password=password)
    with pytest.raises(WorkspaceError) as caught:
        asyncio.run(mailer.send_mail(to=["a@client.ro"], subject="Test", text="x"))
    assert (caught.value.code, caught.value.status, caught.value.extra["reason"]) == (
        "smtp_failed", 502, "auth_failed")
    assert auth_sink.messages == []


def test_the_smtp_test_route_answers_instead_of_crashing(conn, cast, auth_sink):
    _stored_login(conn, auth_sink.port)
    client, headers = signed_in(cast.admin)
    response = client.post("/api/workspace/admin/smtp/test", json={"to": "admin@acme.test"},
                           headers=headers)
    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "smtp_failed", "reason": "auth_failed"}
    tested = conn.execute("SELECT details_json FROM audit WHERE action = 'smtp.tested'").fetchone()
    assert json.loads(tested[0]) == {"ok": False, "error_code": "smtp_failed"}


def test_a_report_delivery_with_such_a_login_is_recorded_as_failed(conn, cast, auth_sink):
    _stored_login(conn, auth_sink.port)
    seed_document(conn, department_id=cast.dept_a, uploader_id=cast.member_a.id, title="Nord",
                  chunks=["Vânzările din Nord au crescut."])
    report_id = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "Nord", "instructions": "Rezumă vânzările."})
    conn.execute("UPDATE reports SET delivery_emails_json = '[\"sef@client.ro\"]', "
                 "delivery_status = 'approved', delivery_approved_json = '[\"sef@client.ro\"]' "
                 "WHERE id = ?", (report_id,))
    run_id = reports.start_manual_run(conn, cast.member_a, report_id)
    run_now(run_id)
    run = conn.execute("SELECT * FROM report_runs WHERE id = ?", (run_id,)).fetchone()
    assert (run["status"], run["error_code"], run["error"]) == ("succeeded", "smtp_failed",
                                                                "delivery_failed")
    failed = conn.execute("SELECT details_json FROM audit WHERE action = 'email.failed'").fetchone()
    assert json.loads(failed[0])["error_code"] == "smtp_failed"
    kinds = [r[0] for r in conn.execute("SELECT kind FROM notifications WHERE user_id = ? "
                                        "ORDER BY id", (cast.member_a.id,))]
    assert kinds == ["report.run_succeeded", "report.delivery_failed"]
    assert auth_sink.messages == []


def test_an_email_approval_with_such_a_login_fails_and_is_audited(conn, cast, auth_sink):
    _stored_login(conn, auth_sink.port)
    with db.tx(conn):
        conversation = conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, 'Concedii', ?, ?)", (cast.member_a.id, cast.dept_a, NOW, NOW)).lastrowid
        message_id = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (?, 'assistant', 'Avem 21 de zile.', ?)", (conversation, NOW)).lastrowid
    member, headers = signed_in(cast.member_a)
    item = member.post("/api/workspace/approvals", headers=headers, json={
        "kind": "email.send", "payload": {
            "to": ["client@firma.ro"], "subject": "Concedii", "body_markdown": "Avem 21 de zile.",
            "source": {"type": "message", "id": message_id}}}).json()
    approver, approver_headers = signed_in(cast.approver_a)
    decided = approver.post(f"/api/workspace/approvals/{item['id']}/decide",
                            json={"decision": "approve"}, headers=approver_headers)
    assert decided.status_code == 200
    assert (decided.json()["status"], decided.json()["error_code"]) == ("failed", "smtp_failed")
    failed = conn.execute("SELECT details_json FROM audit WHERE action = 'email.failed'").fetchone()
    assert json.loads(failed[0])["error_code"] == "smtp_failed"
    assert auth_sink.messages == []
