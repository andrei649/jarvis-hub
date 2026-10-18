"""The workspace mailer: SMTP settings, the password store and sending (spec §6 "Email", §7).

Sending is exercised against a real SMTP conversation (``tests/support/smtp_sink.py`` on
127.0.0.1), so EHLO, AUTH, MAIL, RCPT and DATA all happen exactly as in production.
"""

from __future__ import annotations

import json
import socket
import ssl

import pytest

from agents.core.secrets import SecretStoreError
from agents.core.workspace import audit, mailer
from agents.core.workspace.errors import WorkspaceError
from tests.support.ports import closed_port
from tests.support.smtp_sink import SmtpSink
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    db,
    make_user,
    seed_org,
    ws,
)
from tests.test_workspace_reports_support import (  # noqa: F401  (sink is a fixture)
    SENDER,
    configure_smtp,
    signed_in,
    sink,
)


@pytest.fixture
def conn(ws):
    connection = db()
    seed_org(connection)
    yield connection
    connection.close()


def _closed_port() -> int:
    return closed_port()


# ── settings ─────────────────────────────────────────────────────────────────────────

def test_defaults_when_nothing_is_stored(conn):
    assert mailer.smtp_settings(conn) == {
        "host": "", "port": 587, "security": "starttls", "username": "", "from_address": "",
        "from_name": "", "allowed_domains": [], "has_password": False, "configured": False,
    }
    assert mailer.smtp_configured(conn) is False


def test_parse_update_normalizes_a_full_body():
    settings, password, given = mailer.parse_update({
        "host": "Mail.Firma.RO", "port": 465, "security": "ssl", "username": " robot ",
        "password": " p@ss word ", "from_address": "Rapoarte@Firma.ro", "from_name": "Nerva Firma",
        "allowed_domains": ["@Firma.RO", "client.ro.", "firma.ro"],
    }, password_stored=False)
    assert settings == {"host": "mail.firma.ro", "port": 465, "security": "ssl",
                        "username": "robot", "from_address": "rapoarte@firma.ro",
                        "from_name": "Nerva Firma", "allowed_domains": ["firma.ro", "client.ro"]}
    assert (password, given) == (" p@ss word ", True)


def test_parse_update_defaults_the_port_by_security_and_allows_turning_email_off():
    settings, password, given = mailer.parse_update({"security": "none"}, password_stored=True)
    assert settings["host"] == "" and settings["port"] == 25 and settings["from_address"] == ""
    assert (password, given) == (None, False)
    assert mailer.parse_update({"host": "::1", "from_address": "a@b.ro"},
                               password_stored=False)[0]["host"] == "::1"


@pytest.mark.parametrize(("body", "field", "reason"), [
    ({"host": "mail server", "from_address": "a@b.ro"}, "host", "malformed"),
    ({"host": "smtp.b.ro"}, "from_address", "required"),
    ({"host": "smtp.b.ro", "from_address": "nu-e-email"}, "from_address", "invalid_email"),
    ({"host": "smtp.b.ro", "from_address": "a@b.ro", "port": 0}, "port", "too_small"),
    ({"host": "smtp.b.ro", "from_address": "a@b.ro", "port": 70000}, "port", "too_large"),
    ({"host": "smtp.b.ro", "from_address": "a@b.ro", "security": "tls"}, "security",
     "invalid_choice"),
    ({"host": "smtp.b.ro", "from_address": "a@b.ro", "allowed_domains": ["nu un domeniu"]},
     "allowed_domains", "malformed"),
    ({"host": "smtp.b.ro", "from_address": "a@b.ro", "from_name": "A\r\nBcc: x@y.ro"},
     "from_name", "control_characters"),
    ({"host": "smtp.b.ro", "from_address": "a@b.ro", "password": "a\nb"}, "password",
     "control_characters"),
])
def test_parse_update_refuses_bad_fields(body, field, reason):
    with pytest.raises(WorkspaceError) as caught:
        mailer.parse_update(body, password_stored=False)
    assert caught.value.code == "invalid_request"
    assert (caught.value.extra["field"], caught.value.extra["reason"]) == (field, reason)


@pytest.mark.parametrize(("host", "stored", "body_password", "refused"), [
    ("smtp.b.ro", False, "secret", True),
    ("smtp.b.ro", True, None, True),
    ("smtp.b.ro", True, "", False),
    ("127.0.0.1", False, "secret", False),
    ("localhost", True, None, False),
    ("[::1]", True, None, False),
])
def test_clear_text_credentials_only_to_loopback(host, stored, body_password, refused):
    body = {"host": host, "security": "none", "username": "robot", "from_address": "a@b.ro",
            "password": body_password}
    if refused:
        with pytest.raises(WorkspaceError) as caught:
            mailer.parse_update(body, password_stored=stored)
        assert caught.value.extra == {"field": "security", "reason": "insecure_credentials"}
    else:
        mailer.parse_update(body, password_stored=stored)


def test_save_settings_keeps_other_org_settings(conn):
    conn.execute("UPDATE org SET settings_json = ? WHERE id = 1", (json.dumps({"other": 1}),))
    configure_smtp(conn, 2525)
    stored = json.loads(conn.execute("SELECT settings_json FROM org").fetchone()[0])
    assert stored["other"] == 1 and stored["smtp"]["port"] == 2525
    assert mailer.smtp_configured(conn) is True


def test_corrupt_stored_settings_read_as_defaults(conn):
    conn.execute("UPDATE org SET settings_json = ? WHERE id = 1",
                 (json.dumps({"smtp": {"host": 7, "port": "x", "security": "rot13",
                                       "allowed_domains": "firma.ro"}}),))
    assert mailer.stored_settings(conn)["port"] == 587
    assert mailer.stored_settings(conn)["host"] == ""
    conn.execute("UPDATE org SET settings_json = 'not json' WHERE id = 1")
    assert mailer.smtp_configured(conn) is False


def test_the_password_lives_only_in_the_secret_store(conn, ws):
    mailer.set_password("Parola-SMTP-Secreta")
    assert mailer.has_password() is True
    assert mailer.secret_store() is mailer.secret_store()
    configure_smtp(conn, 2525, username="robot")
    raw = conn.execute("SELECT settings_json FROM org").fetchone()[0]
    assert "Parola-SMTP-Secreta" not in raw
    store_file = ws.data_dir / "business" / "secrets.enc"
    assert "Parola-SMTP-Secreta" not in store_file.read_text(encoding="utf-8")
    mailer.set_password(None)
    assert mailer.has_password() is False


# ── sending ──────────────────────────────────────────────────────────────────────────

async def test_send_mail_delivers_a_complete_message(conn, sink):
    configure_smtp(conn, sink.port, from_name="Nerva Firmă")
    accepted = await mailer.send_mail(
        to=["Ana@Client.ro", "ana@client.ro", "ion@client.ro"], subject="Raport săptămânal — ș și ț",
        text="Bună ziua,\nraportul e gata.", html="<p>raportul e gata</p>", reply_to="Sef@Acme.test")
    assert accepted == ["ana@client.ro", "ion@client.ro"]
    [mail] = sink.wait_for(1)
    assert mail.mail_from == SENDER and mail.rcpt_tos == ["ana@client.ro", "ion@client.ro"]
    assert mail.subject == "Raport săptămânal — ș și ț"
    assert mail.header("From") == "Nerva Firmă <nerva@acme.test>"
    assert mail.header("To") == "ana@client.ro, ion@client.ro"
    assert mail.header("Reply-To") == "sef@acme.test"
    assert mail.header("Auto-Submitted") == "auto-generated"
    assert mail.header("Message-ID").endswith("@acme.test>") and mail.header("Date")
    assert mail.part("plain").strip() == "Bună ziua,\nraportul e gata."
    assert mail.part("html").strip() == "<p>raportul e gata</p>"
    assert mail.auth_user is None


async def test_credentials_are_used_when_a_password_is_stored(conn):
    with SmtpSink(require_auth=("robot", "Parola-SMTP-1")) as server:
        configure_smtp(conn, server.port, username="robot")
        mailer.set_password("Parola-SMTP-1")
        await mailer.send_mail(to=["a@client.ro"], subject="Test", text="x")
        assert server.wait_for(1)[0].auth_user == "robot"
        mailer.set_password("gresita")
        with pytest.raises(WorkspaceError) as caught:
            await mailer.send_mail(to=["a@client.ro"], subject="Test", text="x")
        assert (caught.value.code, caught.value.extra["reason"]) == ("smtp_failed", "auth_failed")
        mailer.set_password(None)
        with pytest.raises(WorkspaceError) as caught:
            await mailer.send_mail(to=["a@client.ro"], subject="Test", text="x")
        assert caught.value.extra["reason"] == "sender_refused"
        assert caught.value.status == 502


async def test_partially_refused_recipients_are_reported_by_omission(conn):
    with SmtpSink(refuse=["nimeni@client.ro"]) as server:
        configure_smtp(conn, server.port)
        accepted = await mailer.send_mail(to=["a@client.ro", "nimeni@client.ro"], subject="S",
                                          text="x")
        assert accepted == ["a@client.ro"]
        assert server.wait_for(1)[0].rcpt_tos == ["a@client.ro"]
        with pytest.raises(WorkspaceError) as caught:
            await mailer.send_mail(to=["nimeni@client.ro"], subject="S", text="x")
        assert caught.value.extra["reason"] == "recipients_refused"


async def test_a_refused_message_body_is_a_failure(conn):
    with SmtpSink(fail_data=True) as server:
        configure_smtp(conn, server.port)
        with pytest.raises(WorkspaceError) as caught:
            await mailer.send_mail(to=["a@client.ro"], subject="S", text="x")
        assert caught.value.extra["reason"] == "data_refused"
        assert server.messages == []


async def test_allowed_domains_refuse_outside_recipients_before_connecting(conn, sink):
    configure_smtp(conn, sink.port, allowed_domains=("firma.ro",))
    with pytest.raises(WorkspaceError) as caught:
        await mailer.send_mail(to=["a@firma.ro", "b@gmail.com", "c@sub.firma.ro"], subject="S",
                               text="x")
    assert caught.value.code == "recipient_not_allowed" and caught.value.status == 422
    assert caught.value.extra["recipients"] == ["b@gmail.com", "c@sub.firma.ro"]
    assert sink.messages == []
    assert await mailer.send_mail(to=["a@firma.ro"], subject="S", text="x") == ["a@firma.ro"]


@pytest.mark.parametrize(("kwargs", "field", "reason"), [
    ({"subject": "Raport\r\nBcc: spion@evil.ro"}, "subject", "control_characters"),
    ({"subject": "Raport x"}, "subject", "control_characters"),
    ({"subject": "   "}, "subject", "required"),
    ({"subject": "x" * 401}, "subject", "too_long"),
    ({"to": ["a@client.ro\r\nBcc: x@y.ro"]}, "to", "invalid_email"),
    ({"to": "a@client.ro"}, "to", "type"),
    ({"to": []}, "to", "too_few"),
    ({"to": [f"u{i}@client.ro" for i in range(21)]}, "to", "too_many"),
    ({"reply_to": "x\r\n@y"}, "reply_to", "invalid_email"),
    ({"text": None}, "text", "type"),
])
async def test_header_and_recipient_guards(conn, sink, kwargs, field, reason):
    configure_smtp(conn, sink.port)
    arguments = {"to": ["a@client.ro"], "subject": "S", "text": "x", **kwargs}
    with pytest.raises(WorkspaceError) as caught:
        await mailer.send_mail(**arguments)
    assert caught.value.code == "invalid_request"
    assert (caught.value.extra["field"], caught.value.extra["reason"]) == (field, reason)
    assert sink.messages == []


async def test_lone_surrogates_in_model_text_do_not_crash_sending(conn, sink):
    configure_smtp(conn, sink.port)
    await mailer.send_mail(to=["a@client.ro"], subject="S", text="raport \ud800 gata",
                           html="<p>\udfff</p>")
    assert "raport ? gata" in sink.wait_for(1)[0].part("plain")


async def test_unconfigured_smtp_is_refused(conn):
    with pytest.raises(WorkspaceError) as caught:
        await mailer.send_mail(to=["a@client.ro"], subject="S", text="x")
    assert (caught.value.code, caught.value.status) == ("smtp_not_configured", 409)


async def test_starttls_uses_the_trust_context_and_fails_honestly_without_tls(conn, sink,
                                                                              monkeypatch):
    contexts: list[ssl.SSLContext] = []

    def trust_context() -> ssl.SSLContext:
        contexts.append(ssl.create_default_context())
        return contexts[-1]

    monkeypatch.setattr(mailer.tls_trust, "trust_context", trust_context)
    configure_smtp(conn, sink.port, security="starttls")
    with pytest.raises(WorkspaceError) as caught:
        await mailer.send_mail(to=["a@client.ro"], subject="S", text="x")
    assert caught.value.extra["reason"] == "not_supported"
    assert len(contexts) == 1
    configure_smtp(conn, sink.port, security="ssl")
    with pytest.raises(WorkspaceError) as caught:
        await mailer.send_mail(to=["a@client.ro"], subject="S", text="x")
    assert caught.value.extra["reason"] in ("tls_failed", "connection_failed")
    assert len(contexts) == 2
    assert sink.messages == []


async def test_unreachable_and_silent_servers(conn, monkeypatch):
    configure_smtp(conn, _closed_port())
    with pytest.raises(WorkspaceError) as caught:
        await mailer.send_mail(to=["a@client.ro"], subject="S", text="x")
    assert caught.value.extra["reason"] == "connection_failed"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        monkeypatch.setattr(mailer, "SMTP_TIMEOUT_SECONDS", 0.3)
        configure_smtp(conn, listener.getsockname()[1])
        with pytest.raises(WorkspaceError) as caught:
            await mailer.send_mail(to=["a@client.ro"], subject="S", text="x")
        assert caught.value.extra["reason"] == "timeout"
    finally:
        listener.close()


async def test_an_unreadable_password_asks_to_enter_it_again(conn, sink, monkeypatch):
    configure_smtp(conn, sink.port, username="robot")

    class Broken:
        def get(self, name):
            raise SecretStoreError("cannot decrypt secret")

    monkeypatch.setattr(mailer, "secret_store", Broken)
    with pytest.raises(WorkspaceError) as caught:
        await mailer.send_mail(to=["a@client.ro"], subject="S", text="x")
    assert (caught.value.code, caught.value.status) == ("smtp_password_unreadable", 409)


async def test_clear_text_credentials_off_loopback_are_never_sent(conn, monkeypatch):
    mailer.save_settings(conn, {"host": "mail.example.ro", "port": 25, "security": "none",
                                "username": "robot", "from_address": SENDER, "from_name": "",
                                "allowed_domains": []})
    mailer.set_password("secret")

    def no_network(*args, **kwargs):
        raise AssertionError("must not connect")

    monkeypatch.setattr(mailer.smtplib, "SMTP", no_network)
    with pytest.raises(WorkspaceError) as caught:
        await mailer.send_mail(to=["a@client.ro"], subject="S", text="x")
    assert caught.value.extra["reason"] == "insecure_transport"


async def test_send_test_reports_success_and_failure(conn, sink):
    assert await mailer.send_test("admin@acme.test", locale="ro") == {
        "ok": False, "error": "smtp_not_configured"}
    configure_smtp(conn, sink.port)
    assert await mailer.send_test("admin@acme.test", locale="en") == {"ok": True}
    assert sink.wait_for(1)[0].subject == "Nerva Workspace — test email"
    configure_smtp(conn, _closed_port())
    assert await mailer.send_test("admin@acme.test", locale="ro") == {
        "ok": False, "error": "smtp_failed", "reason": "connection_failed"}


# ── routes ───────────────────────────────────────────────────────────────────────────

@pytest.fixture
def people(conn):
    admin = make_user(conn, role="admin", department_ids=[], name="Ana Admin")
    member = make_user(conn, role="member", department_ids=[])
    return admin, member


def test_admin_reads_and_writes_settings_without_ever_seeing_the_password(conn, people):
    admin, _ = people
    client, headers = signed_in(admin)
    body = {"host": "127.0.0.1", "port": 2525, "security": "none", "username": "robot",
            "password": "Parola-SMTP-2", "from_address": "rapoarte@acme.test",
            "from_name": "Rapoarte", "allowed_domains": ["acme.test"]}
    response = client.put("/api/workspace/admin/smtp", json=body, headers=headers)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["has_password"] is True and saved["configured"] is True
    assert "password" not in saved and "Parola-SMTP-2" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/workspace/admin/smtp").json() == saved
    kept = client.put("/api/workspace/admin/smtp", json={**body, "password": None}, headers=headers)
    assert kept.json()["has_password"] is True
    cleared = client.put("/api/workspace/admin/smtp", json={**body, "password": ""}, headers=headers)
    assert cleared.json()["has_password"] is False
    rows = conn.execute("SELECT details_json FROM audit WHERE action = 'smtp.updated' "
                        "ORDER BY id").fetchall()
    assert [json.loads(r[0])["credential"] for r in rows] == ["replaced", "kept", "cleared"]
    assert all("Parola-SMTP-2" not in r[0] for r in rows)
    assert audit.verify_chain(conn)["ok"]


def test_settings_validation_errors_reach_the_client(conn, people):
    admin, _ = people
    client, headers = signed_in(admin)
    response = client.put("/api/workspace/admin/smtp", headers=headers,
                          json={"host": "smtp.b.ro", "security": "none", "username": "u",
                                "password": "p", "from_address": "a@b.ro"})
    assert response.status_code == 422
    assert response.json()["reason"] == "insecure_credentials"


def test_test_send_route_reports_and_audits(conn, people, sink):
    admin, _ = people
    client, headers = signed_in(admin)
    failed = client.post("/api/workspace/admin/smtp/test", json={"to": "admin@acme.test"},
                         headers=headers)
    assert failed.json() == {"ok": False, "error": "smtp_not_configured"}
    configure_smtp(conn, sink.port)
    ok = client.post("/api/workspace/admin/smtp/test", json={"to": "admin@acme.test"},
                     headers=headers)
    assert ok.json() == {"ok": True}
    assert sink.wait_for(1)[0].subject == "Nerva Workspace — test de email"
    bad = client.post("/api/workspace/admin/smtp/test", json={"to": "nu-e-email"}, headers=headers)
    assert bad.status_code == 422 and bad.json()["field"] == "to"
    details = [json.loads(r[0]) for r in conn.execute(
        "SELECT details_json FROM audit WHERE action = 'smtp.tested' ORDER BY id")]
    assert details == [{"ok": False, "error_code": "smtp_not_configured"}, {"ok": True}]


def test_smtp_routes_are_for_admins_only_and_need_csrf(conn, people):
    admin, member = people
    client, headers = signed_in(member)
    assert client.get("/api/workspace/admin/smtp").status_code == 403
    assert client.put("/api/workspace/admin/smtp", json={}, headers=headers).status_code == 403
    assert client.post("/api/workspace/admin/smtp/test", json={"to": "a@b.ro"},
                       headers=headers).status_code == 403
    admin_client, admin_headers = signed_in(admin)
    no_csrf = admin_client.put("/api/workspace/admin/smtp", json={},
                               headers={"Origin": admin_headers["Origin"]})
    assert no_csrf.status_code == 403 and no_csrf.json()["error"] == "csrf_failed"
