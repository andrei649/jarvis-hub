"""No input crashes an S4 route: every JSON field of every write route is fuzzed (spec §12).

Wrong types, oversized values, control characters, lone surrogates, out-of-range
integers and nested structures are sent to each field of the reports, approvals and
SMTP write routes, and to their path and query parameters. Every answer must be a
handled 2xx/4xx with the workspace error shape — never a 5xx.
"""

from __future__ import annotations

import json

import pytest

from agents.core.workspace import db, reports
from tests.support.workspace_fixtures import ws  # noqa: F401  (a fixture)
from tests.test_workspace_reports_support import (  # noqa: F401  (fixtures)
    cast,
    configure_smtp,
    run_now,
    seed_document,
    signed_in,
    sink,
)

BAD_VALUES = [
    None, True, 0, -1, 2 ** 64, 1.5, "", " ", "x" * 70_000, "a\x00b", "a\u0085b", "\ud800",
    "a\r\nBcc: x@y.ro", [], [None], [2 ** 64], ["\ud800"], {}, {"a": {"b": [1]}},
    [[[[[]]]]], "javascript:alert(1)", "../../etc/passwd",
]


def _fuzz_bodies(base: dict) -> list[dict]:
    """*base* with each field replaced by each bad value, plus the field removed."""
    bodies = []
    for key in base:
        for value in BAD_VALUES:
            bodies.append({**base, key: value})
        bodies.append({k: v for k, v in base.items() if k != key})
    return bodies


def _send(client, method: str, path: str, body: object, headers: dict):
    """A JSON request encoded with ASCII escapes, so lone surrogates reach the server."""
    return client.request(method, path, content=json.dumps(body).encode("ascii"),
                          headers={**headers, "Content-Type": "application/json"})


def _check(response) -> tuple[int, str, str]:
    """A handled answer; returns ``(status, error, field)`` so a test can show its fuzz
    reached the validators (a broken sign-in would answer every request 401 and pass)."""
    assert response.status_code < 500, response.text
    if response.status_code >= 400:
        body = response.json()
        assert set(body) >= {"error", "message"}, body
        assert body["error"] not in ("auth_required", "csrf_failed"), body
        return response.status_code, body["error"], str(body.get("field", ""))
    return response.status_code, "", ""


def _refused_fields(outcomes: list[tuple[int, str, str]]) -> set[str]:
    return {field for status, _, field in outcomes if status == 422 and field}


@pytest.fixture
def world(ws, cast, sink):
    conn = db.connect()
    configure_smtp(conn, sink.port)
    seed_document(conn, department_id=cast.dept_a, uploader_id=cast.member_a.id, title="Nord",
                  chunks=["Vânzările din Nord au crescut."])
    report_id = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "R", "instructions": "Rezumă vânzările."})
    run_id = reports.start_manual_run(conn, cast.member_a, report_id)
    run_now(run_id)
    with db.tx(conn):
        conversation = conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, 't', 0, 0)", (cast.member_a.id, cast.dept_a)).lastrowid
        message_id = conn.execute("INSERT INTO messages (conversation_id, role, content, created_at) "
                                  "VALUES (?, 'assistant', 'x', 0)", (conversation,)).lastrowid
    yield conn, report_id, run_id, int(message_id)
    conn.close()


def test_report_writes_never_fail_with_5xx(world, cast):
    conn, report_id, _, _ = world
    client, headers = signed_in(cast.member_a)
    base = {"department_id": cast.dept_a, "name": "Raport", "instructions": "Rezumă.",
            "document_ids": [], "schedule": {"kind": "daily", "time": "08:00", "weekday": 1,
                                             "timezone": "Europe/Bucharest"},
            "delivery_emails": ["a@client.ro"]}
    outcomes = []
    for body in _fuzz_bodies(base):
        outcomes.append(_check(_send(client, "POST", "/api/workspace/reports", body, headers)))
        outcomes.append(_check(_send(client, "PATCH", f"/api/workspace/reports/{report_id}", body,
                                     headers)))
    for schedule in _fuzz_bodies(base["schedule"]):
        outcomes.append(_check(_send(client, "POST", "/api/workspace/reports",
                                     {**base, "schedule": schedule}, headers)))
    for raw in (b"", b"[]", b"{", b'{"name": NaN}', b"[" * 5000, b'"x"'):
        outcomes.append(_check(client.post("/api/workspace/reports", content=raw,
                                           headers={**headers, "Content-Type": "application/json"})))
    assert _refused_fields(outcomes) >= {*base, "schedule.kind", "schedule.time",
                                         "schedule.timezone"}, "every field was validated"
    assert any(status == 201 for status, _, _ in outcomes), "valid variants were accepted"
    # What the accepted variants stored is clean: no control characters, a loadable zone.
    for row in conn.execute("SELECT name, instructions, schedule_kind, timezone FROM reports"):
        assert row["name"] and "\x00" not in row["name"] and len(row["name"]) <= 200
        assert "\x00" not in row["instructions"]
        assert row["schedule_kind"] in ("manual", "daily", "weekly")
        reports.load_zone(row["timezone"])


def test_approval_requests_never_fail_with_5xx(world, cast):
    conn, report_id, run_id, message_id = world
    client, headers = signed_in(cast.member_a)
    payloads = {
        "report.delivery": {"report_id": report_id, "emails": ["a@client.ro"]},
        "report.share_company": {"run_id": run_id},
        "email.send": {"to": ["a@client.ro"], "subject": "S", "body_markdown": "B",
                       "source": {"type": "message", "id": message_id}},
        "document.company_publish": {"document_id": 1},
    }
    outcomes = []
    for kind, payload in payloads.items():
        for body in _fuzz_bodies(payload):
            outcomes.append(_check(_send(client, "POST", "/api/workspace/approvals",
                                         {"kind": kind, "payload": body}, headers)))
    for source in _fuzz_bodies(payloads["email.send"]["source"]):
        outcomes.append(_check(_send(client, "POST", "/api/workspace/approvals", {
            "kind": "email.send", "payload": {**payloads["email.send"], "source": source}},
            headers)))
    for kind in BAD_VALUES:
        outcomes.append(_check(_send(client, "POST", "/api/workspace/approvals",
                                     {"kind": kind, "payload": {}}, headers)))
    every_field = {"kind", "source"} | {key for payload in payloads.values() for key in payload}
    assert _refused_fields(outcomes) >= every_field, "every payload field was validated"
    stored = conn.execute("SELECT kind, summary, status FROM approvals").fetchall()
    assert len(stored) == sum(status == 201 for status, _, _ in outcomes)
    assert all(row["kind"] in payloads and row["summary"] and row["status"] == "pending"
               for row in stored)


def test_decide_cancel_and_queries_never_fail_with_5xx(world, cast):
    conn, _, run_id, _ = world
    member, member_headers = signed_in(cast.member_a)
    item = member.post("/api/workspace/approvals", headers=member_headers, json={
        "kind": "report.share_company", "payload": {"run_id": run_id}}).json()
    admin, headers = signed_in(cast.admin)
    decided = [_check(_send(admin, "POST", f"/api/workspace/approvals/{item['id']}/decide", body,
                            headers))
               for body in _fuzz_bodies({"decision": "reject", "note": "n"})]
    assert _refused_fields(decided) >= {"decision", "note"}
    assert sum(status == 200 for status, _, _ in decided) <= 1, "decided at most once"
    for path in ("/api/workspace/approvals?box=%00", "/api/workspace/approvals?status=" + "x" * 500,
                 "/api/workspace/approvals/eligible?kind=" + "k" * 500,
                 "/api/workspace/approvals/eligible?kind=email.send&department_id=-1",
                 f"/api/workspace/approvals/eligible?kind=email.send&department_id={2 ** 70}",
                 "/api/workspace/report-runs/1/export?format=" + "m" * 50,
                 f"/api/workspace/report-runs/{2 ** 63}", f"/api/workspace/reports/{2 ** 63}/runs",
                 "/api/workspace/reports?department_id=abc"):
        _check(admin.get(path))
    _check(member.post(f"/api/workspace/approvals/{2 ** 63}/cancel", headers=member_headers))
    _check(admin.post(f"/api/workspace/approvals/{item['id']}/cancel", headers=headers))
    final = conn.execute("SELECT status FROM approvals WHERE id = ?", (item["id"],)).fetchone()[0]
    accepted = any(status == 200 for status, _, _ in decided)
    assert final == ("rejected" if accepted else "pending"), "fuzz never moved it otherwise"
    rejected_rows = conn.execute("SELECT COUNT(*) FROM audit WHERE action = 'approval.rejected' "
                                 "AND target_id = ?", (str(item["id"]),)).fetchone()[0]
    assert rejected_rows == int(accepted)


def test_smtp_writes_never_fail_with_5xx(world, cast):
    client, headers = signed_in(cast.admin)
    base = {"host": "127.0.0.1", "port": 2525, "security": "none", "username": "u",
            "password": "p", "from_address": "a@acme.test", "from_name": "N",
            "allowed_domains": ["acme.test"]}
    for body in _fuzz_bodies(base):
        _check(_send(client, "PUT", "/api/workspace/admin/smtp", body, headers))
    for to in BAD_VALUES:
        _check(_send(client, "POST", "/api/workspace/admin/smtp/test", {"to": to}, headers))
    stored = json.loads(world[0].execute("SELECT settings_json FROM org").fetchone()[0])["smtp"]
    assert isinstance(stored["port"], int) and isinstance(stored["allowed_domains"], list)
