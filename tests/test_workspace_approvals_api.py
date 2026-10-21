"""Approvals over HTTP (spec §7 ``routers/workspace_approvals.py``): shapes, guards, errors.

The life-cycle rules are proven in ``test_workspace_approvals_engine``; here every route
is checked for its response shape, its authentication and CSRF guards, and each error
code it can emit, using the same test effects.
"""

from __future__ import annotations

import pytest

from agents.core.workspace import effects_api
from tests.support.workspace_fixtures import ws  # noqa: F401  (a fixture)
from tests.test_workspace_approvals_engine import (  # noqa: F401  (fixtures)
    ADMIN_KIND,
    DEPT_KIND,
    conn,
    effect,
)
from tests.test_workspace_reports_support import cast, signed_in  # noqa: F401  (a fixture)


def _payload(department_id, label="cerere"):
    return {"department_id": department_id, "label": label}


def _ask(client, headers, department_id, kind=DEPT_KIND, label="cerere"):
    return client.post("/api/workspace/approvals", headers=headers,
                       json={"kind": kind, "payload": _payload(department_id, label)})


def test_every_route_needs_a_session(conn, cast, effect):
    client, _ = signed_in(cast.member_a)
    client.cookies.clear()
    for method, path in [("GET", "/api/workspace/approvals"),
                         ("GET", f"/api/workspace/approvals/eligible?kind={DEPT_KIND}"),
                         ("POST", "/api/workspace/approvals"), ("GET", "/api/workspace/approvals/1"),
                         ("POST", "/api/workspace/approvals/1/decide"),
                         ("POST", "/api/workspace/approvals/1/cancel")]:
        response = client.request(method, path, json={})
        assert (response.status_code, response.json()["error"]) == (401, "auth_required"), path


def test_mutations_need_the_csrf_token(conn, cast, effect):
    client, headers = signed_in(cast.member_a)
    response = client.post("/api/workspace/approvals", json={"kind": DEPT_KIND,
                                                             "payload": _payload(cast.dept_a)},
                           headers={"Origin": headers["Origin"]})
    assert (response.status_code, response.json()["error"]) == (403, "csrf_failed")
    cross = client.post("/api/workspace/approvals", json={}, headers={
        **headers, "Origin": "https://evil.example"})
    assert (cross.status_code, cross.json()["error"]) == (403, "csrf_failed")


def test_request_get_decide_and_list_shapes(conn, cast, effect):
    member, member_headers = signed_in(cast.member_a)
    created = _ask(member, member_headers, cast.dept_a)
    assert created.status_code == 201 and created.headers["cache-control"] == "no-store"
    item = created.json()
    assert set(item) == {"id", "kind", "department_id", "department_name", "summary", "payload",
                         "status", "requester", "decider", "decided_at", "decision_note", "result",
                         "error_code", "created_at", "expires_at", "can_decide", "can_cancel"}
    assert item["department_name"] == "Vânzări" and item["payload"] == _payload(cast.dept_a)
    approver, headers = signed_in(cast.approver_a)
    detail = approver.get(f"/api/workspace/approvals/{item['id']}").json()
    assert detail["can_decide"] is True
    assert {p["name"] for p in detail["eligible_deciders"]} == {
        cast.approver_a.name, cast.admin.name, cast.admin_2.name}
    listing = approver.get("/api/workspace/approvals?box=inbox&status=pending").json()
    assert [i["id"] for i in listing["items"]] == [item["id"]] and listing["pending_inbox_count"] == 1
    decided = approver.post(f"/api/workspace/approvals/{item['id']}/decide",
                            json={"decision": "approve", "note": "Da\r\ncu notă"}, headers=headers)
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved" and decided.json()["decision_note"] == "Da\ncu notă"
    mine = member.get("/api/workspace/approvals?box=mine").json()
    assert mine["items"][0]["status"] == "approved" and mine["pending_inbox_count"] == 0


def test_cancel_route(conn, cast, effect):
    member, headers = signed_in(cast.member_a)
    item = _ask(member, headers, cast.dept_a).json()
    other, other_headers = signed_in(cast.admin)
    forbidden = other.post(f"/api/workspace/approvals/{item['id']}/cancel", headers=other_headers)
    assert (forbidden.status_code, forbidden.json()["error"]) == (403, "forbidden")
    cancelled = member.post(f"/api/workspace/approvals/{item['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    again = member.post(f"/api/workspace/approvals/{item['id']}/cancel", headers=headers)
    assert (again.status_code, again.json()["error"]) == (409, "already_decided")


def test_isolation_over_http(conn, cast, effect):
    member, headers = signed_in(cast.member_a)
    item = _ask(member, headers, cast.dept_a).json()
    for outsider in (cast.member_b, cast.approver_b):
        client, outsider_headers = signed_in(outsider)
        assert client.get(f"/api/workspace/approvals/{item['id']}").status_code == 404
        decide = client.post(f"/api/workspace/approvals/{item['id']}/decide",
                             json={"decision": "approve"}, headers=outsider_headers)
        assert (decide.status_code, decide.json()["error"]) == (404, "not_found")
        cancel = client.post(f"/api/workspace/approvals/{item['id']}/cancel",
                             headers=outsider_headers)
        assert cancel.status_code == 404
        assert client.get("/api/workspace/approvals").json()["items"] == []
    self_decide = member.post(f"/api/workspace/approvals/{item['id']}/decide",
                              json={"decision": "approve"}, headers=headers)
    assert (self_decide.status_code, self_decide.json()["error"]) == (403, "forbidden")
    all_box = member.get("/api/workspace/approvals?box=all")
    assert (all_box.status_code, all_box.json()["error"]) == (403, "forbidden")
    admin, _ = signed_in(cast.admin)
    assert [i["id"] for i in admin.get("/api/workspace/approvals?box=all").json()["items"]] == [
        item["id"]]


def test_an_admins_own_admin_rule_request_answers_executed(conn, cast, effect):
    admin, headers = signed_in(cast.admin)
    response = _ask(admin, headers, cast.dept_a, kind=ADMIN_KIND)
    assert response.status_code == 201
    assert response.json()["status"] == "approved" and response.json()["result"] == {
        "done": "cerere"}
    effect.fail = RuntimeError("bug")
    failed = _ask(admin, headers, cast.dept_a, kind=ADMIN_KIND, label="alta")
    assert failed.status_code == 201
    assert (failed.json()["status"], failed.json()["error_code"]) == ("failed", "execution_failed")


def test_eligible_probe(conn, cast, effect):
    member, _ = signed_in(cast.member_a)
    response = member.get(f"/api/workspace/approvals/eligible?kind={DEPT_KIND}"
                          f"&department_id={cast.dept_a}")
    assert response.json() == {"count": 3, "immediate": False, "smtp_configured": False}
    admin, _ = signed_in(cast.admin)
    assert admin.get(f"/api/workspace/approvals/eligible?kind={ADMIN_KIND}").json() == {
        "count": 1, "immediate": True, "smtp_configured": False}
    hidden = member.get(f"/api/workspace/approvals/eligible?kind={DEPT_KIND}"
                        f"&department_id={cast.dept_b}")
    assert (hidden.status_code, hidden.json()["error"]) == (404, "not_found")
    unknown = member.get("/api/workspace/approvals/eligible?kind=nope")
    assert (unknown.status_code, unknown.json()["error"]) == (400, "unknown_kind")
    missing = member.get("/api/workspace/approvals/eligible")
    assert (missing.status_code, missing.json()["field"]) == (422, "kind")


@pytest.mark.parametrize(("path", "field"), [
    ("/api/workspace/approvals?box=outbox", "box"),
    ("/api/workspace/approvals?status=done", "status"),
    ("/api/workspace/approvals/0", "approval_id"),
    (f"/api/workspace/approvals/{2 ** 64}", "approval_id"),
    ("/api/workspace/approvals/abc", "approval_id"),
])
def test_query_and_path_validation(conn, cast, effect, path, field):
    client, _ = signed_in(cast.member_a)
    response = client.get(path)
    assert (response.status_code, response.json()["error"], response.json()["field"]) == (
        422, "invalid_request", field)


@pytest.mark.parametrize(("body", "status", "code", "field"), [
    ({"payload": {}}, 422, "invalid_request", "kind"),
    ({"kind": "", "payload": {}}, 422, "invalid_request", "kind"),
    ({"kind": "nope", "payload": {}}, 400, "unknown_kind", None),
    ({"kind": DEPT_KIND}, 422, "invalid_request", "payload"),
    ({"kind": DEPT_KIND, "payload": "x"}, 422, "invalid_request", "payload"),
    ({"kind": DEPT_KIND, "payload": {"department_id": 1}}, 422, "invalid_request", "label"),
])
def test_request_body_errors(conn, cast, effect, body, status, code, field):
    client, headers = signed_in(cast.member_a)
    response = client.post("/api/workspace/approvals", json=body, headers=headers)
    assert (response.status_code, response.json()["error"]) == (status, code)
    if field:
        assert response.json()["field"] == field


def test_decide_body_errors_and_missing_approvals(conn, cast, effect):
    member, member_headers = signed_in(cast.member_a)
    item = _ask(member, member_headers, cast.dept_a).json()
    client, headers = signed_in(cast.approver_a)
    for body, field in [({}, "decision"), ({"decision": "ok"}, "decision"),
                        ({"decision": "reject", "note": "x" * 1001}, "note")]:
        response = client.post(f"/api/workspace/approvals/{item['id']}/decide", json=body,
                               headers=headers)
        assert (response.status_code, response.json()["field"]) == (422, field)
    missing = client.post("/api/workspace/approvals/424242/decide", json={"decision": "approve"},
                          headers=headers)
    assert (missing.status_code, missing.json()["error"]) == (404, "not_found")
    too_big = client.post(f"/api/workspace/approvals/{item['id']}/decide",
                          headers={**headers, "Content-Type": "application/json"},
                          content=b'{"decision": "approve", "note": "' + b"x" * 9000 + b'"}')
    assert (too_big.status_code, too_big.json()["error"]) == (413, "payload_too_large")
    assert client.get(f"/api/workspace/approvals/{item['id']}").json()["status"] == "pending"


def test_every_known_kind_is_listed_by_the_router():
    assert {"document.company_publish", "email.send", "report.delivery",
            "report.share_company"} <= set(effects_api.kinds())
