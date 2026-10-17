"""The three effects S4 registers, end to end over HTTP (spec §7 "Effects registered by S4").

``report.delivery`` (department approvers) gates report email delivery,
``report.share_company`` (admins) publishes a run to the whole company, and
``email.send`` (department approvers) mails an answer or a report run the requester
can see. Each is driven through the approvals routes with real users, and every email
goes through a real SMTP conversation with the local sink.
"""

from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents.core.workspace import approvals, db, effects_api, reports
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    freeze_clock,
    make_user,
    ws,
)
from tests.test_workspace_reports_support import (  # noqa: F401  (fixtures)
    cast,
    configure_smtp,
    run_now,
    seed_document,
    signed_in,
    sink,
)

NOW = datetime(2026, 10, 17, 13, 0, tzinfo=ZoneInfo("Europe/Bucharest")).timestamp()


@pytest.fixture
def conn(ws, monkeypatch):
    freeze_clock(monkeypatch, NOW)
    connection = db.connect()
    yield connection
    connection.close()


def _report(conn, user, department_id, emails=(), name="Vânzări Nord"):
    return reports.create_report(conn, user, {
        "department_id": department_id, "name": name, "instructions": "Rezumă vânzările din Nord.",
        "delivery_emails": list(emails)})


def _report_row(conn, report_id):
    return conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()


def _finished_run(conn, cast, report_id):
    seed_document(conn, department_id=cast.dept_a, uploader_id=cast.member_a.id, title="Nord",
                  chunks=["Vânzările din Nord au crescut."])
    run_id = reports.start_manual_run(conn, cast.member_a, report_id)
    run_now(run_id)
    return run_id


def _message(conn, user, department_id, content="Politica de concediu: 21 de zile [1]."):
    with db.tx(conn):
        conversation = conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, 'Concedii', ?, ?)", (user.id, department_id, NOW, NOW)).lastrowid
        return int(conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (?, 'assistant', ?, ?)", (conversation, content, NOW)).lastrowid)


def _decide(client, headers, approval_id, decision="approve", note=None):
    body = {"decision": decision, **({"note": note} if note else {})}
    return client.post(f"/api/workspace/approvals/{approval_id}/decide", json=body, headers=headers)


def test_the_three_effects_are_registered_with_their_rules():
    rules = {kind: effects_api.get_effect(kind).decider_rule for kind in
             (reports.DELIVERY_KIND, reports.SHARE_KIND, reports.EMAIL_KIND)}
    assert rules == {"report.delivery": "department", "report.share_company": "admin",
                     "email.send": "department"}


# ── report.delivery ──────────────────────────────────────────────────────────────────

def test_an_approved_delivery_snapshots_the_recipients(conn, cast, sink):
    configure_smtp(conn, sink.port)
    report_id = _report(conn, cast.member_a, cast.dept_a, ["ana@client.ro", "ion@client.ro"])
    approval_id = _report_row(conn, report_id)["delivery_approval_id"]
    approver, headers = signed_in(cast.approver_a)
    inbox = approver.get("/api/workspace/approvals").json()
    assert [i["id"] for i in inbox["items"]] == [approval_id] and inbox["pending_inbox_count"] == 1
    assert inbox["items"][0]["summary"] == (
        "Livrare pe email a raportului „Vânzări Nord” către: ana@client.ro, ion@client.ro")
    decided = _decide(approver, headers, approval_id, note="Ok").json()
    assert decided["status"] == "approved"
    assert decided["result"] == {"report_id": report_id,
                                 "approved_recipients": ["ana@client.ro", "ion@client.ro"]}
    row = _report_row(conn, report_id)
    assert row["delivery_status"] == "approved"
    assert json.loads(row["delivery_approved_json"]) == ["ana@client.ro", "ion@client.ro"]
    owner, _ = signed_in(cast.member_a)
    assert owner.get(f"/api/workspace/reports/{report_id}").json()["delivery_approved"] == [
        "ana@client.ro", "ion@client.ro"]


@pytest.mark.parametrize(("close", "status"), [("reject", "rejected"), ("cancel", "none"),
                                                ("expire", "rejected")])
def test_a_closed_delivery_request_updates_the_report(conn, cast, sink, close, status, monkeypatch):
    configure_smtp(conn, sink.port)
    report_id = _report(conn, cast.member_a, cast.dept_a, ["ana@client.ro"])
    approval_id = _report_row(conn, report_id)["delivery_approval_id"]
    if close == "reject":
        client, headers = signed_in(cast.admin)
        assert _decide(client, headers, approval_id, "reject").status_code == 200
    elif close == "cancel":
        client, headers = signed_in(cast.member_a)
        response = client.post(f"/api/workspace/approvals/{approval_id}/cancel", headers=headers)
        assert response.json()["status"] == "cancelled"
    else:
        approvals.expire_due(conn, NOW + approvals.APPROVAL_TTL_SECONDS)
    assert _report_row(conn, report_id)["delivery_status"] == status


def test_a_superseded_delivery_request_can_no_longer_be_decided(conn, cast, sink):
    configure_smtp(conn, sink.port)
    report_id = _report(conn, cast.member_a, cast.dept_a, ["ana@client.ro"])
    old = _report_row(conn, report_id)["delivery_approval_id"]
    reports.update_report(conn, cast.member_a, report_id, {"delivery_emails": ["ion@client.ro"]})
    client, headers = signed_in(cast.approver_a)
    response = _decide(client, headers, old)
    assert response.status_code == 409
    assert response.json()["error"] == "already_decided"
    assert response.json()["current_status"] == "cancelled"
    assert _report_row(conn, report_id)["delivery_status"] == "pending"


def test_recipients_changed_behind_the_request_fail_it_at_decision(conn, cast, sink):
    configure_smtp(conn, sink.port)
    report_id = _report(conn, cast.member_a, cast.dept_a, ["ana@client.ro"])
    approval_id = _report_row(conn, report_id)["delivery_approval_id"]
    conn.execute("UPDATE reports SET delivery_emails_json = '[\"spion@evil.ro\"]' WHERE id = ?",
                 (report_id,))
    client, headers = signed_in(cast.approver_a)
    decided = _decide(client, headers, approval_id).json()
    assert (decided["status"], decided["error_code"]) == ("failed", "stale_request")
    assert _report_row(conn, report_id)["delivery_status"] == "rejected"


def test_direct_delivery_requests_are_checked(conn, cast, sink):
    configure_smtp(conn, sink.port)
    report_id = _report(conn, cast.member_a, cast.dept_a)
    colleague = make_user(conn, role="member", department_ids=[cast.dept_a])
    for user, emails, expected in [
        (cast.member_a, ["ana@client.ro"], (409, "stale_request")),
        (colleague, [], (422, "invalid_request")),
        (cast.member_b, ["ana@client.ro"], (404, "not_found")),
    ]:
        client, headers = signed_in(user)
        response = client.post("/api/workspace/approvals", headers=headers, json={
            "kind": "report.delivery", "payload": {"report_id": report_id, "emails": emails}})
        assert (response.status_code, response.json()["error"]) == expected
    reports.update_report(conn, cast.member_a, report_id, {"delivery_emails": ["ana@client.ro"]})
    client, headers = signed_in(colleague)
    response = client.post("/api/workspace/approvals", headers=headers, json={
        "kind": "report.delivery", "payload": {"report_id": report_id, "emails": ["ana@client.ro"]}})
    assert (response.status_code, response.json()["error"]) == (403, "forbidden")


def test_an_approver_cannot_approve_the_delivery_of_their_own_report(conn, cast, sink):
    configure_smtp(conn, sink.port)
    report_id = _report(conn, cast.approver_a, cast.dept_a, ["ana@client.ro"])
    approval_id = _report_row(conn, report_id)["delivery_approval_id"]
    client, headers = signed_in(cast.approver_a)
    response = _decide(client, headers, approval_id)
    assert (response.status_code, response.json()["error"]) == (403, "forbidden")
    admin, admin_headers = signed_in(cast.admin)
    assert _decide(admin, admin_headers, approval_id).json()["status"] == "approved"


# ── report.share_company ─────────────────────────────────────────────────────────────

def test_sharing_a_run_needs_an_admin(conn, cast):
    report_id = _report(conn, cast.member_a, cast.dept_a)
    run_id = _finished_run(conn, cast, report_id)
    client, headers = signed_in(cast.member_a)
    probe = client.get(f"/api/workspace/approvals/eligible?kind=report.share_company"
                       f"&department_id={cast.dept_a}").json()
    assert probe == {"count": 2, "immediate": False, "smtp_configured": False}
    requested = client.post("/api/workspace/approvals", headers=headers,
                            json={"kind": "report.share_company", "payload": {"run_id": run_id}})
    assert requested.status_code == 201
    item = requested.json()
    assert item["summary"] == "Partajare în toată compania: raportul „Vânzări Nord” din 2026-10-17"
    approver, approver_headers = signed_in(cast.approver_a)
    assert approver.get(f"/api/workspace/approvals/{item['id']}").status_code == 404
    assert _decide(approver, approver_headers, item["id"]).status_code == 404
    again = client.post("/api/workspace/approvals", headers=headers,
                        json={"kind": "report.share_company", "payload": {"run_id": run_id}})
    assert (again.status_code, again.json()["error"]) == (409, "already_requested")
    admin, admin_headers = signed_in(cast.admin)
    assert _decide(admin, admin_headers, item["id"]).json()["result"] == {
        "run_id": run_id, "shared_company": True}
    outsider, outsider_headers = signed_in(cast.member_b)
    assert [r["id"] for r in outsider.get("/api/workspace/shared-reports").json()["runs"]] == [run_id]
    shared_again = client.post("/api/workspace/approvals", headers=headers,
                               json={"kind": "report.share_company", "payload": {"run_id": run_id}})
    assert (shared_again.status_code, shared_again.json()["error"]) == (409, "already_shared")


def test_an_admin_shares_at_once_and_bad_requests_are_refused(conn, cast):
    report_id = _report(conn, cast.member_a, cast.dept_a)
    run_id = _finished_run(conn, cast, report_id)
    outsider, outsider_headers = signed_in(cast.member_b)
    hidden = outsider.post("/api/workspace/approvals", headers=outsider_headers,
                           json={"kind": "report.share_company", "payload": {"run_id": run_id}})
    assert hidden.status_code == 404
    queued = reports.start_manual_run(conn, cast.member_a, report_id)
    client, headers = signed_in(cast.member_a)
    not_ready = client.post("/api/workspace/approvals", headers=headers,
                            json={"kind": "report.share_company", "payload": {"run_id": queued}})
    assert (not_ready.status_code, not_ready.json()["error"]) == (409, "run_not_ready")
    admin, admin_headers = signed_in(cast.admin)
    immediate = admin.post("/api/workspace/approvals", headers=admin_headers,
                           json={"kind": "report.share_company", "payload": {"run_id": run_id}})
    assert immediate.status_code == 201
    item = immediate.json()
    assert item["status"] == "approved" and item["decider"]["id"] == cast.admin.id
    assert item["decision_note"] is None  # an admin's own action: no stored note, audit marks it
    assert conn.execute("SELECT shared_company FROM report_runs WHERE id = ?",
                        (run_id,)).fetchone()[0] == 1


# ── email.send ───────────────────────────────────────────────────────────────────────

def _email_payload(source_type, source_id, **over):
    payload = {"to": ["client@firma.ro"], "subject": "Politica de concediu",
               "body_markdown": "# Concedii\n\nAvem **21 de zile** [1].",
               "source": {"type": source_type, "id": source_id}}
    payload.update(over)
    return payload


def test_an_answer_is_emailed_after_approval(conn, cast, sink):
    configure_smtp(conn, sink.port)
    message_id = _message(conn, cast.member_a, cast.dept_a)
    client, headers = signed_in(cast.member_a)
    probe = client.get(f"/api/workspace/approvals/eligible?kind=email.send"
                       f"&department_id={cast.dept_a}").json()
    assert probe == {"count": 3, "immediate": False, "smtp_configured": True}
    response = client.post("/api/workspace/approvals", headers=headers,
                           json={"kind": "email.send", "payload": _email_payload("message", message_id)})
    item = response.json()
    assert response.status_code == 201 and item["department_id"] == cast.dept_a
    assert item["summary"] == "Email „Politica de concediu” către: client@firma.ro"
    assert sink.messages == []
    approver, approver_headers = signed_in(cast.approver_a)
    decided = _decide(approver, approver_headers, item["id"]).json()
    assert decided["status"] == "approved" and decided["result"] == {"sent_to": ["client@firma.ro"]}
    [mail] = sink.wait_for(1)
    assert mail.rcpt_tos == ["client@firma.ro"] and mail.subject == "Politica de concediu"
    assert mail.header("Reply-To") == cast.member_a.email
    plain = mail.part("plain")
    assert plain.startswith("# Concedii\n\nAvem **21 de zile** [1].")
    assert (f"Trimis prin Nerva Workspace de {cast.member_a.name}, cu aprobarea lui "
            f"{cast.approver_a.name}.") in plain
    assert "<h1>Concedii</h1>" in mail.part("html")
    assert "<strong>21 de zile</strong>" in mail.part("html")
    sent = json.loads(conn.execute("SELECT details_json FROM audit WHERE action = 'email.sent'"
                                   ).fetchone()[0])
    assert sent == {"source": {"type": "message", "id": message_id},
                    "requester_id": cast.member_a.id, "to": ["client@firma.ro"], "refused": 0}


def test_email_requests_are_validated(conn, cast, sink):
    message_id = _message(conn, cast.member_a, cast.dept_a)
    foreign = _message(conn, cast.approver_a, cast.dept_a)
    client, headers = signed_in(cast.member_a)

    def ask(payload):
        return client.post("/api/workspace/approvals", headers=headers,
                           json={"kind": "email.send", "payload": payload})

    not_configured = ask(_email_payload("message", message_id))
    assert (not_configured.status_code, not_configured.json()["error"]) == (409, "smtp_not_configured")
    configure_smtp(conn, sink.port, allowed_domains=("firma.ro",))
    cases = [
        (_email_payload("message", foreign), 404, "not_found", None),
        (_email_payload("message", 99999), 404, "not_found", None),
        (_email_payload("message", message_id, to=[]), 422, "invalid_request", "to"),
        (_email_payload("message", message_id, to=["x@gmail.com"]), 422, "recipient_not_allowed", None),
        (_email_payload("message", message_id, subject=""), 422, "invalid_request", "subject"),
        (_email_payload("message", message_id, subject="a\r\nBcc: x@y.ro"), 422, "invalid_request",
         "subject"),
        (_email_payload("message", message_id, body_markdown="x" * 30_001), 422, "invalid_request",
         "body_markdown"),
        (_email_payload("chat", message_id), 422, "invalid_request", "source"),
        ({**_email_payload("message", message_id), "source": {"type": "message", "id": "1"}}, 422,
         "invalid_request", "source"),
        ({**_email_payload("message", message_id), "source": None}, 422, "invalid_request", "source"),
    ]
    for payload, status, code, field in cases:
        response = ask(payload)
        assert (response.status_code, response.json()["error"]) == (status, code), payload
        if field:
            assert response.json()["field"] == field
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_a_mail_failure_fails_the_approval_and_is_audited(conn, cast):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    configure_smtp(conn, probe.getsockname()[1])
    probe.close()
    message_id = _message(conn, cast.member_a, cast.dept_a)
    client, headers = signed_in(cast.member_a)
    item = client.post("/api/workspace/approvals", headers=headers,
                       json={"kind": "email.send", "payload": _email_payload("message",
                                                                             message_id)}).json()
    admin, admin_headers = signed_in(cast.admin)
    decided = _decide(admin, admin_headers, item["id"]).json()
    assert (decided["status"], decided["error_code"]) == ("failed", "smtp_failed")
    actions = [r[0] for r in conn.execute("SELECT action FROM audit WHERE target_type = 'approval' "
                                          "ORDER BY id")]
    assert actions == ["approval.requested", "approval.approved", "email.failed", "approval.failed"]


def test_a_report_run_is_emailed_by_its_department_or_when_shared_by_admins(conn, cast, sink):
    configure_smtp(conn, sink.port)
    report_id = _report(conn, cast.member_a, cast.dept_a)
    run_id = _finished_run(conn, cast, report_id)
    client, headers = signed_in(cast.member_a)
    own = client.post("/api/workspace/approvals", headers=headers,
                      json={"kind": "email.send", "payload": _email_payload("report_run", run_id)})
    assert own.json()["department_id"] == cast.dept_a
    outsider, outsider_headers = signed_in(cast.member_b)
    hidden = outsider.post("/api/workspace/approvals", headers=outsider_headers,
                           json={"kind": "email.send", "payload": _email_payload("report_run", run_id)})
    assert hidden.status_code == 404
    conn.execute("UPDATE report_runs SET shared_company = 1 WHERE id = ?", (run_id,))
    shared = outsider.post("/api/workspace/approvals", headers=outsider_headers, json={
        "kind": "email.send", "payload": _email_payload("report_run", run_id, subject="Partajat")})
    item = shared.json()
    assert shared.status_code == 201 and item["department_id"] is None
    approver_b, approver_b_headers = signed_in(cast.approver_b)
    assert approver_b.get(f"/api/workspace/approvals/{item['id']}").status_code == 404
    approver_a, approver_a_headers = signed_in(cast.approver_a)
    assert _decide(approver_a, approver_a_headers, item["id"]).status_code == 404
    admin, admin_headers = signed_in(cast.admin_2)
    assert _decide(admin, admin_headers, item["id"]).json()["status"] == "approved"
    assert sink.wait_for(1)[0].subject == "Partajat"


def test_two_deciders_clicking_at_once_send_exactly_one_email(conn, cast, sink):
    configure_smtp(conn, sink.port)
    message_id = _message(conn, cast.member_a, cast.dept_a)
    client, headers = signed_in(cast.member_a)
    item = client.post("/api/workspace/approvals", headers=headers,
                       json={"kind": "email.send", "payload": _email_payload("message",
                                                                             message_id)}).json()
    deciders = [signed_in(cast.approver_a), signed_in(cast.admin), signed_in(cast.admin_2)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda pair: _decide(pair[0], pair[1], item["id"]), deciders))
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 409, 409]
    assert {r.json()["error"] for r in responses if r.status_code == 409} == {"already_decided"}
    # Each decide answers only after its SMTP exchange ended, so the count is final.
    assert len(sink.messages) == 1
    assert conn.execute("SELECT COUNT(*) FROM audit WHERE action = 'email.sent'").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM approvals WHERE id = ?", (item["id"],)).fetchone()[0] == (
        "approved")
