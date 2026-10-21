"""Department and user isolation of every approvals and SMTP route (spec §6, §7, §12).

The independent review of S4 attacks ``routers/workspace_approvals.py`` from outside the
scope of department A's requests: members and approvers of department B, a second member
of A, and A's own approver for the admin-only kinds. Out-of-scope approvals answer
``404 not_found`` on read, decide and cancel and never appear in a box or a count; a
request can never be built on another department's report, run or another user's chat
message; the SMTP console refuses everyone but admins. Nothing an attacker does changes
the database or sends mail.
"""

from __future__ import annotations

import pytest

from tests.test_workspace_reports_isolation import (  # noqa: F401  (fixtures)
    OUTSIDERS,
    RECIPIENT_A,
    SECRET_A,
    World,
    cast,
    conn,
    sink,
    world,
    ws,
)
from tests.test_workspace_reports_support import signed_in


def _snapshot(conn) -> dict:
    return {
        "approvals": [tuple(r) for r in conn.execute(
            "SELECT id, kind, status, decided_by, result_json FROM approvals ORDER BY id")],
        "audit": conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
        "notifications": conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
        "org": conn.execute("SELECT settings_json FROM org").fetchone()[0],
    }


def _assert_hidden(response, *, label: str) -> None:
    assert response.status_code == 404, (label, response.status_code, response.text)
    assert response.json()["error"] == "not_found", label
    for secret in ("Marje", SECRET_A, RECIPIENT_A):
        assert secret not in response.text, (label, secret)


def _request(world: World, payload_kind: str, payload: dict):
    client, headers = signed_in(world.cast.member_a)
    response = client.post("/api/workspace/approvals", headers=headers,
                           json={"kind": payload_kind, "payload": payload})
    assert response.status_code == 201, response.text
    return response.json()


def _email(source_type: str, source_id: int) -> dict:
    return {"to": ["client@firma.ro"], "subject": "Marje Nord", "body_markdown": SECRET_A,
            "source": {"type": source_type, "id": source_id}}


@pytest.fixture
def requests_a(conn, world) -> dict[str, int]:
    """Department A's open requests: delivery (from the report), email and share."""
    delivery = conn.execute("SELECT delivery_approval_id FROM reports WHERE id = ?",
                            (world.report_a,)).fetchone()[0]
    return {
        "delivery": int(delivery),
        "email": _request(world, "email.send", _email("report_run", world.run_a))["id"],
        "share": _request(world, "report.share_company", {"run_id": world.run_a})["id"],
    }


def _probe_every_route(client, headers, approval_ids) -> None:
    for approval_id in approval_ids:
        for method, path, body in [
            ("GET", f"/api/workspace/approvals/{approval_id}", None),
            ("POST", f"/api/workspace/approvals/{approval_id}/decide", {"decision": "approve"}),
            ("POST", f"/api/workspace/approvals/{approval_id}/decide", {"decision": "reject"}),
            ("POST", f"/api/workspace/approvals/{approval_id}/cancel", None),
        ]:
            _assert_hidden(client.request(method, path, json=body, headers=headers),
                           label=f"{method} {path}")


def _listed_ids(client) -> set[int]:
    ids: set[int] = set()
    for box in ("inbox", "mine"):
        for status in ("", "&status=pending"):
            listing = client.get(f"/api/workspace/approvals?box={box}{status}").json()
            ids |= {item["id"] for item in listing["items"]}
    return ids


# ── another department ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("outsider", OUTSIDERS)
def test_requests_of_another_department_are_invisible_and_undecidable(conn, world, requests_a,
                                                                       outsider):
    client, headers = signed_in(world.person(outsider))
    before = _snapshot(conn)
    _probe_every_route(client, headers, requests_a.values())
    assert _listed_ids(client).isdisjoint(requests_a.values())
    assert client.get("/api/workspace/approvals").json()["pending_inbox_count"] == 0
    everything = client.get("/api/workspace/approvals?box=all")
    assert (everything.status_code, everything.json()["error"]) == (403, "forbidden")
    assert _snapshot(conn) == before


@pytest.mark.parametrize("outsider", OUTSIDERS)
def test_no_request_can_be_built_on_another_departments_resources(conn, world, outsider, sink):
    client, headers = signed_in(world.person(outsider))
    before = _snapshot(conn)
    for kind, payload in [
        ("report.delivery", {"report_id": world.report_a, "emails": [RECIPIENT_A]}),
        ("report.delivery", {"report_id": world.report_a, "emails": ["hot@evil.example"]}),
        ("report.share_company", {"run_id": world.run_a}),
        ("email.send", _email("report_run", world.run_a)),
        ("email.send", _email("message", world.message_a)),
    ]:
        response = client.post("/api/workspace/approvals", headers=headers,
                               json={"kind": kind, "payload": payload})
        _assert_hidden(response, label=f"{kind} {payload}")
    for kind in ("report.delivery", "report.share_company", "email.send"):
        probe = client.get(f"/api/workspace/approvals/eligible?kind={kind}"
                           f"&department_id={world.cast.dept_a}")
        _assert_hidden(probe, label=f"eligible {kind}")
    assert _snapshot(conn) == before
    assert sink.messages == []


@pytest.mark.parametrize("outsider", OUTSIDERS)
def test_a_decided_request_stays_invisible_to_another_department(conn, world, requests_a,
                                                                 outsider, sink):
    approver, approver_headers = signed_in(world.cast.approver_a)
    decided = approver.post(f"/api/workspace/approvals/{requests_a['email']}/decide",
                            json={"decision": "approve"}, headers=approver_headers)
    assert decided.json()["status"] == "approved"
    client, headers = signed_in(world.person(outsider))
    _probe_every_route(client, headers, [requests_a["email"]])
    assert requests_a["email"] not in _listed_ids(client)
    assert len(sink.messages) == 1


# ── inside department A ──────────────────────────────────────────────────────────────

def test_a_colleague_cannot_see_use_or_withdraw_a_members_requests(conn, world, requests_a,
                                                                   sink):
    client, headers = signed_in(world.member_a2)
    before = _snapshot(conn)
    _probe_every_route(client, headers, requests_a.values())
    assert _listed_ids(client).isdisjoint(requests_a.values())
    message = client.post("/api/workspace/approvals", headers=headers,
                          json={"kind": "email.send", "payload": _email("message", world.message_a)})
    _assert_hidden(message, label="another user's chat message")
    delivery = client.post("/api/workspace/approvals", headers=headers, json={
        "kind": "report.delivery", "payload": {"report_id": world.report_a,
                                               "emails": [RECIPIENT_A]}})
    assert (delivery.status_code, delivery.json()["error"]) == (403, "forbidden")
    assert _snapshot(conn) == before
    assert sink.messages == []


def test_department_approvers_never_see_admin_rule_requests(conn, world, requests_a):
    client, headers = signed_in(world.cast.approver_a)
    before = _snapshot(conn)
    _probe_every_route(client, headers, [requests_a["share"]])
    inbox = client.get("/api/workspace/approvals").json()
    assert {item["id"] for item in inbox["items"]} == {requests_a["delivery"], requests_a["email"]}
    assert inbox["pending_inbox_count"] == 2
    cancel = client.post(f"/api/workspace/approvals/{requests_a['email']}/cancel", headers=headers)
    assert (cancel.status_code, cancel.json()["error"]) == (403, "forbidden")
    assert _snapshot(conn) == before


# ── the SMTP console ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("person", ["member_a", "approver_a", "member_b", "approver_b"])
def test_the_smtp_console_refuses_everyone_but_admins(conn, world, person, sink):
    client, headers = signed_in(world.person(person))
    before = _snapshot(conn)
    for method, path, body in [
        ("GET", "/api/workspace/admin/smtp", None),
        ("PUT", "/api/workspace/admin/smtp", {"host": "smtp.evil.example", "security": "none",
                                              "from_address": "x@evil.example"}),
        ("POST", "/api/workspace/admin/smtp/test", {"to": "x@evil.example"}),
    ]:
        response = client.request(method, path, json=body, headers=headers)
        assert (response.status_code, response.json()["error"]) == (403, "forbidden"), path
        assert "127.0.0.1" not in response.text
    assert _snapshot(conn) == before
    assert sink.messages == []
