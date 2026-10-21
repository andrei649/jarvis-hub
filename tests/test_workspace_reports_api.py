"""Reports API: definitions, validation, scope and the delivery state (spec §6, §7, §9).

Covers create/list/get/edit/delete over HTTP, every validation error the routes emit,
``document_ids`` scope at create and edit, schedules (including DST), the delivery
approval state machine driven by recipient changes, and department isolation — a
report outside the caller's departments answers ``404`` on every route.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents.core.workspace import approvals, db, reports
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    freeze_clock,
    make_department,
    make_user,
    seed_org,
    ws,
)
from tests.test_workspace_reports_support import (  # noqa: F401  (fixtures)
    cast,
    configure_smtp,
    seed_document,
    signed_in,
    sink,
)

BUCHAREST = ZoneInfo("Europe/Bucharest")
NOW = datetime(2026, 10, 17, 13, 0, tzinfo=BUCHAREST).timestamp()  # a Saturday


@pytest.fixture
def conn(ws, monkeypatch):
    freeze_clock(monkeypatch, NOW)
    connection = db.connect()
    yield connection
    connection.close()


def _body(department_id, **over):
    body = {"department_id": department_id, "name": "Vânzări săptămânale",
            "instructions": "Rezumă vânzările săptămânii pe regiuni.", "schedule": {"kind": "manual"}}
    body.update(over)
    return body


def _create(client, headers, body):
    response = client.post("/api/workspace/reports", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# ── create and read ──────────────────────────────────────────────────────────────────

def test_create_returns_the_full_report(conn, cast):
    client, headers = signed_in(cast.member_a)
    report = _create(client, headers, _body(cast.dept_a))
    assert report["department_id"] == cast.dept_a and report["department_name"] == "Vânzări"
    assert report["owner"] == {"id": cast.member_a.id, "name": cast.member_a.name}
    assert report["schedule"] == {"kind": "manual", "time": None, "weekday": None,
                                  "timezone": "Europe/Bucharest"}
    assert report["next_run_at"] is None and report["last_run"] is None
    assert report["delivery_status"] == "none" and report["delivery_emails"] == []
    assert report["can_edit"] is True and report["can_run"] is True and report["active"] is True
    assert client.get(f"/api/workspace/reports/{report['id']}").json() == report
    row = conn.execute("SELECT action, details_json FROM audit WHERE action = 'report.created'"
                       ).fetchone()
    assert json.loads(row["details_json"]) == {"name": "Vânzări săptămânale",
                                               "schedule_kind": "manual", "documents": 0,
                                               "recipient_count": 0}


def test_daily_and_weekly_schedules_compute_the_next_local_run(conn, cast):
    client, headers = signed_in(cast.member_a)
    daily = _create(client, headers, _body(cast.dept_a, schedule={"kind": "daily", "time": "08:00"}))
    assert daily["next_run_at"] == datetime(2026, 10, 18, 8, 0, tzinfo=BUCHAREST).timestamp()
    weekly = _create(client, headers, _body(cast.dept_a, schedule={
        "kind": "weekly", "time": "09:30", "weekday": 0, "timezone": "Europe/London"}))
    assert weekly["next_run_at"] == datetime(2026, 10, 19, 9, 30,
                                             tzinfo=ZoneInfo("Europe/London")).timestamp()
    assert weekly["schedule_weekday"] == 0 and weekly["timezone"] == "Europe/London"


def _row(kind="daily", time="08:00", weekday=None, timezone="Europe/Bucharest", active=1):
    return {"schedule_kind": kind, "schedule_time": time, "schedule_weekday": weekday,
            "timezone": timezone, "active": active}


def test_next_run_follows_wall_clock_time_across_dst_changes():
    before_fallback = datetime(2026, 10, 24, 8, 0, 1, tzinfo=BUCHAREST).timestamp()
    nxt = reports.compute_next_run(_row(), before_fallback)
    assert datetime.fromtimestamp(nxt, BUCHAREST).strftime("%Y-%m-%d %H:%M %z") == (
        "2026-10-25 08:00 +0200")
    assert nxt - before_fallback == pytest.approx(25 * 3600 - 1)
    spring = datetime(2027, 3, 27, 12, 0, tzinfo=BUCHAREST).timestamp()
    gap = reports.compute_next_run(_row(time="03:30"), spring)
    assert datetime.fromtimestamp(gap, BUCHAREST).strftime("%Y-%m-%d %H:%M") == "2027-03-28 04:30"
    assert reports.compute_next_run(_row(kind="manual"), spring) is None
    assert reports.compute_next_run(_row(active=0), spring) is None
    assert reports.compute_next_run(_row(time="25:00"), spring) is None


def test_weekly_runs_land_on_the_chosen_weekday():
    saturday_after = datetime(2026, 10, 17, 9, 0, tzinfo=BUCHAREST).timestamp()
    same_day_later = reports.compute_next_run(_row("weekly", "10:00", 5), saturday_after)
    assert datetime.fromtimestamp(same_day_later, BUCHAREST).date().isoformat() == "2026-10-17"
    next_week = reports.compute_next_run(_row("weekly", "08:00", 5), saturday_after)
    assert datetime.fromtimestamp(next_week, BUCHAREST).date().isoformat() == "2026-10-24"


def test_an_unloadable_zone_is_reported():
    with pytest.raises(WorkspaceError) as caught:
        reports.compute_next_run(_row(timezone="Nowhere/Atlantis"), NOW)
    assert caught.value.code == "timezone_unavailable"


@pytest.mark.parametrize(("over", "field", "reason"), [
    ({"name": None}, "name", "required"),
    ({"name": "  "}, "name", "required"),
    ({"name": "x" * 201}, "name", "too_long"),
    ({"name": "a\nb"}, "name", "control_characters"),
    ({"instructions": "y" * 4001}, "instructions", "too_long"),
    ({"department_id": "1"}, "department_id", "type"),
    ({"document_ids": [0]}, "document_ids", "type"),
    ({"document_ids": list(range(1, 52))}, "document_ids", "too_many"),
    ({"delivery_emails": ["nu-e-email"]}, "delivery_emails", "invalid_email"),
    ({"schedule": "daily"}, "schedule", "not_an_object"),
    ({"schedule": {"kind": "hourly"}}, "schedule.kind", "invalid_choice"),
    ({"schedule": {"kind": "daily"}}, "schedule.time", "required"),
    ({"schedule": {"kind": "daily", "time": "8:00"}}, "schedule.time", "malformed"),
    ({"schedule": {"kind": "daily", "time": "24:00"}}, "schedule.time", "malformed"),
    ({"schedule": {"kind": "weekly", "time": "08:00"}}, "schedule.weekday", "required"),
    ({"schedule": {"kind": "weekly", "time": "08:00", "weekday": 7}}, "schedule.weekday",
     "invalid_choice"),
    ({"schedule": {"kind": "weekly", "time": "08:00", "weekday": True}}, "schedule.weekday",
     "invalid_choice"),
])
def test_invalid_bodies_answer_422_with_the_field(conn, cast, over, field, reason):
    client, headers = signed_in(cast.member_a)
    body = {**_body(cast.dept_a), **over}
    response = client.post("/api/workspace/reports", json=body, headers=headers)
    assert response.status_code == 422, response.text
    assert (response.json()["field"], response.json()["reason"]) == (field, reason)


@pytest.mark.parametrize("zone", ["Mars/Olympus", "../../etc/passwd", "Europe/", "", 5,
                                  "A" * 65])
def test_unknown_time_zones_answer_invalid_timezone(conn, cast, zone):
    client, headers = signed_in(cast.member_a)
    response = client.post("/api/workspace/reports", headers=headers, json=_body(
        cast.dept_a, schedule={"kind": "daily", "time": "08:00", "timezone": zone}))
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_timezone", "message": "unknown time zone",
                               "field": "schedule.timezone"}


def test_departments_outside_scope_or_archived(conn, cast):
    client, headers = signed_in(cast.member_a)
    for department in (cast.dept_b, 9999):
        response = client.post("/api/workspace/reports", json=_body(department), headers=headers)
        assert (response.status_code, response.json()["error"]) == (404, "not_found")
    archived = make_department(conn, "Arhivă", archived=True)
    admin, admin_headers = signed_in(cast.admin)
    response = admin.post("/api/workspace/reports", json=_body(archived), headers=admin_headers)
    assert (response.status_code, response.json()["error"]) == (409, "department_archived")


def test_document_ids_must_be_ready_and_visible_in_the_department(conn, cast):
    own = seed_document(conn, department_id=cast.dept_a, uploader_id=cast.member_a.id,
                        title="Vânzări T3", chunks=["Vânzări."])
    company = seed_document(conn, department_id=cast.dept_b, uploader_id=cast.admin.id,
                            title="Politică", chunks=["Politica firmei."], visibility="company")
    foreign = seed_document(conn, department_id=cast.dept_b, uploader_id=cast.member_b.id,
                            title="Salarii", chunks=["Salarii."])
    failed = seed_document(conn, department_id=cast.dept_a, uploader_id=cast.member_a.id,
                           title="Stricat", chunks=[], status="failed")
    client, headers = signed_in(cast.member_a)
    report = _create(client, headers, _body(cast.dept_a, document_ids=[own, company, own]))
    assert report["document_ids"] == [own, company]
    for bad in ([own, foreign], [failed], [123456]):
        response = client.post("/api/workspace/reports", json=_body(cast.dept_a, document_ids=bad),
                               headers=headers)
        assert response.status_code == 404
        assert response.json() == {"error": "not_found",
                                   "message": "some documents are not available to this report",
                                   "field": "document_ids"}
    patch = client.patch(f"/api/workspace/reports/{report['id']}", json={"document_ids": [foreign]},
                         headers=headers)
    assert patch.status_code == 404 and patch.json()["field"] == "document_ids"


# ── isolation ────────────────────────────────────────────────────────────────────────

def test_a_report_of_another_department_is_invisible_everywhere(conn, cast):
    owner, owner_headers = signed_in(cast.member_a)
    report = _create(owner, owner_headers, _body(cast.dept_a))
    outsider, headers = signed_in(cast.member_b)
    rid = report["id"]
    assert outsider.get("/api/workspace/reports").json() == {"reports": []}
    for method, path, body in [
        ("GET", f"/api/workspace/reports/{rid}", None),
        ("PATCH", f"/api/workspace/reports/{rid}", {"name": "furat"}),
        ("DELETE", f"/api/workspace/reports/{rid}", None),
        ("POST", f"/api/workspace/reports/{rid}/run", {}),
        ("GET", f"/api/workspace/reports/{rid}/runs", None),
        ("GET", f"/api/workspace/reports?department_id={cast.dept_a}", None),
    ]:
        response = outsider.request(method, path, json=body, headers=headers)
        assert (response.status_code, response.json()["error"]) == (404, "not_found"), path
    approver_b, approver_headers = signed_in(cast.approver_b)
    assert approver_b.get(f"/api/workspace/reports/{rid}").status_code == 404
    assert approver_b.patch(f"/api/workspace/reports/{rid}", json={"name": "x"},
                            headers=approver_headers).status_code == 404
    assert conn.execute("SELECT name FROM reports").fetchone()[0] == "Vânzări săptămânale"


def test_lists_are_scoped_per_department(conn, cast):
    a_client, a_headers = signed_in(cast.member_a)
    b_client, b_headers = signed_in(cast.member_b)
    a = _create(a_client, a_headers, _body(cast.dept_a, name="A"))
    b = _create(b_client, b_headers, _body(cast.dept_b, name="B"))
    assert [r["id"] for r in a_client.get("/api/workspace/reports").json()["reports"]] == [a["id"]]
    admin, _ = signed_in(cast.admin)
    assert [r["id"] for r in admin.get("/api/workspace/reports").json()["reports"]] == [a["id"],
                                                                                         b["id"]]
    filtered = admin.get(f"/api/workspace/reports?department_id={cast.dept_b}").json()["reports"]
    assert [r["id"] for r in filtered] == [b["id"]]
    assert admin.get("/api/workspace/reports?department_id=0").status_code == 422
    assert admin.get(f"/api/workspace/reports?department_id={2 ** 64}").status_code == 422
    assert admin.get(f"/api/workspace/reports/{2 ** 64}").status_code == 422


def test_routes_need_a_session_and_csrf(conn, cast):
    client, headers = signed_in(cast.member_a)
    anonymous, _ = signed_in(cast.member_b)
    anonymous.cookies.clear()
    assert anonymous.get("/api/workspace/reports").status_code == 401
    response = client.post("/api/workspace/reports", json=_body(cast.dept_a),
                           headers={"Origin": headers["Origin"]})
    assert (response.status_code, response.json()["error"]) == (403, "csrf_failed")


# ── edit and delete ──────────────────────────────────────────────────────────────────

def test_who_may_edit(conn, cast):
    owner, owner_headers = signed_in(cast.member_a)
    report = _create(owner, owner_headers, _body(cast.dept_a))
    colleague = make_user(conn, role="member", department_ids=[cast.dept_a])
    other, other_headers = signed_in(colleague)
    seen = other.get(f"/api/workspace/reports/{report['id']}").json()
    assert seen["can_edit"] is False and seen["can_run"] is True
    response = other.patch(f"/api/workspace/reports/{report['id']}", json={"name": "Nu"},
                           headers=other_headers)
    assert (response.status_code, response.json()["error"]) == (403, "forbidden")
    assert other.delete(f"/api/workspace/reports/{report['id']}",
                        headers=other_headers).status_code == 403
    for editor in (cast.approver_a, cast.admin, cast.member_a):
        client, headers = signed_in(editor)
        response = client.patch(f"/api/workspace/reports/{report['id']}",
                                json={"name": f"Editat de {editor.id}"}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["name"] == f"Editat de {editor.id}"


def test_edit_recomputes_the_schedule_and_audits_changed_fields(conn, cast):
    client, headers = signed_in(cast.member_a)
    report = _create(client, headers, _body(cast.dept_a))
    response = client.patch(f"/api/workspace/reports/{report['id']}", headers=headers, json={
        "schedule": {"kind": "daily", "time": "07:15"}, "instructions": "Altă cerință."})
    updated = response.json()
    assert updated["next_run_at"] == datetime(2026, 10, 18, 7, 15, tzinfo=BUCHAREST).timestamp()
    assert updated["instructions"] == "Altă cerință." and updated["name"] == report["name"]
    unchanged = client.patch(f"/api/workspace/reports/{report['id']}", json={}, headers=headers)
    assert unchanged.status_code == 200
    details = [json.loads(r[0]) for r in conn.execute(
        "SELECT details_json FROM audit WHERE action = 'report.updated'")]
    assert details == [{"fields": ["instructions", "schedule_kind", "schedule_time"]}]


def test_delete_removes_runs_and_withdraws_pending_approvals(conn, cast, sink):
    configure_smtp(conn, sink.port)
    client, headers = signed_in(cast.member_a)
    report = _create(client, headers, _body(cast.dept_a, delivery_emails=["a@client.ro"]))
    with db.tx(conn):
        run_id = reports.create_run(conn, report["id"], trigger="manual",
                                    triggered_by=cast.member_a.id)
    assert client.delete(f"/api/workspace/reports/{report['id']}", headers=headers).status_code == 204
    assert conn.execute("SELECT COUNT(*) FROM report_runs WHERE id = ?", (run_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT status FROM approvals").fetchone()[0] == "cancelled"
    assert client.get(f"/api/workspace/reports/{report['id']}").status_code == 404
    deleted = conn.execute("SELECT details_json FROM audit WHERE action = 'report.deleted'").fetchone()
    assert json.loads(deleted[0]) == {"name": "Vânzări săptămânale", "runs": 1}


def test_archived_departments_freeze_their_reports(conn, cast):
    client, headers = signed_in(cast.member_a)
    report = _create(client, headers, _body(cast.dept_a))
    conn.execute("UPDATE departments SET archived = 1 WHERE id = ?", (cast.dept_a,))
    assert client.get(f"/api/workspace/reports/{report['id']}").status_code == 404
    admin, admin_headers = signed_in(cast.admin)
    seen = admin.get(f"/api/workspace/reports/{report['id']}").json()
    assert seen["can_edit"] is False and seen["can_run"] is False
    for method, path in [("PATCH", ""), ("POST", "/run")]:
        response = admin.request(method, f"/api/workspace/reports/{report['id']}{path}",
                                 json={"name": "x"}, headers=admin_headers)
        assert (response.status_code, response.json()["error"]) == (409, "department_archived")
    assert admin.delete(f"/api/workspace/reports/{report['id']}",
                        headers=admin_headers).status_code == 204


def test_admin_moves_a_report_to_another_department(conn, cast):
    doc_b = seed_document(conn, department_id=cast.dept_b, uploader_id=cast.member_b.id,
                          title="HR", chunks=["x"])
    client, headers = signed_in(cast.admin)
    report = _create(client, headers, _body(cast.dept_a))
    response = client.patch(f"/api/workspace/reports/{report['id']}", headers=headers,
                            json={"department_id": cast.dept_b, "document_ids": [doc_b]})
    assert response.status_code == 200 and response.json()["department_id"] == cast.dept_b
    member, member_headers = signed_in(cast.member_a)
    assert member.get(f"/api/workspace/reports/{report['id']}").status_code == 404
    owner_client, owner_headers = signed_in(cast.member_a)
    own = _create(owner_client, owner_headers, _body(cast.dept_a))
    move = owner_client.patch(f"/api/workspace/reports/{own['id']}",
                              json={"department_id": cast.dept_b}, headers=owner_headers)
    assert move.status_code == 404


# ── delivery approval state ──────────────────────────────────────────────────────────

def _approval(conn, approval_id):
    return conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()


def test_recipients_need_smtp_and_an_approver_or_nothing_is_created(conn, cast, sink):
    client, headers = signed_in(cast.member_a)
    response = client.post("/api/workspace/reports", headers=headers,
                           json=_body(cast.dept_a, delivery_emails=["a@client.ro"]))
    assert (response.status_code, response.json()["error"]) == (409, "smtp_not_configured")
    configure_smtp(conn, sink.port, allowed_domains=("acme.test",))
    response = client.post("/api/workspace/reports", headers=headers,
                           json=_body(cast.dept_a, delivery_emails=["a@client.ro"]))
    assert (response.status_code, response.json()["error"]) == (422, "recipient_not_allowed")
    assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_no_eligible_approver_rolls_the_report_back(ws, monkeypatch, sink):
    freeze_clock(monkeypatch, NOW)
    conn = db.connect()
    seed_org(conn)
    dept = make_department(conn, "Mic")
    solo = make_user(conn, role="admin", department_ids=[dept])
    configure_smtp(conn, sink.port)
    client, headers = signed_in(solo)
    response = client.post("/api/workspace/reports", headers=headers,
                           json=_body(dept, delivery_emails=["a@client.ro"]))
    assert (response.status_code, response.json()["error"]) == (409, "no_eligible_approver")
    assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit WHERE action NOT LIKE 'auth.%'"
                        ).fetchone()[0] == 0
    conn.close()


def test_recipients_open_change_and_close_the_delivery_approval(conn, cast, sink):
    configure_smtp(conn, sink.port)
    client, headers = signed_in(cast.member_a)
    report = _create(client, headers, _body(cast.dept_a, delivery_emails=["b@client.ro",
                                                                          "a@client.ro"]))
    first = report["delivery_approval_id"]
    assert report["delivery_status"] == "pending"
    assert json.loads(_approval(conn, first)["payload_json"]) == {
        "emails": ["a@client.ro", "b@client.ro"], "report_id": report["id"]}
    assert conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?",
                        (cast.approver_a.id,)).fetchone()[0] == 1
    same = client.patch(f"/api/workspace/reports/{report['id']}", headers=headers,
                        json={"delivery_emails": ["a@client.ro", "b@client.ro"], "name": "Nou"})
    assert same.json()["delivery_approval_id"] == first
    changed = client.patch(f"/api/workspace/reports/{report['id']}", headers=headers,
                           json={"delivery_emails": ["a@client.ro"]}).json()
    assert changed["delivery_status"] == "pending" and changed["delivery_approval_id"] != first
    assert _approval(conn, first)["status"] == "cancelled"
    removed = client.patch(f"/api/workspace/reports/{report['id']}", headers=headers,
                           json={"delivery_emails": []}).json()
    assert removed["delivery_status"] == "none" and removed["delivery_approved"] == []
    assert _approval(conn, changed["delivery_approval_id"])["status"] == "cancelled"
    reasons = [json.loads(r[0])["reason"] for r in conn.execute(
        "SELECT details_json FROM audit WHERE action = 'approval.cancelled' ORDER BY id")]
    assert reasons == ["superseded", "recipients_removed"]


def test_a_rejected_delivery_is_requested_again_on_the_next_save(conn, cast, sink):
    configure_smtp(conn, sink.port)
    client, headers = signed_in(cast.member_a)
    report = _create(client, headers, _body(cast.dept_a, delivery_emails=["a@client.ro"]))
    asyncio.run(approvals.decide(conn, cast.approver_a, report["delivery_approval_id"],
                                 decision="reject", note="Nu."))
    rejected = client.get(f"/api/workspace/reports/{report['id']}").json()
    assert rejected["delivery_status"] == "rejected"
    renamed = client.patch(f"/api/workspace/reports/{report['id']}", headers=headers,
                           json={"name": "Doar redenumit"}).json()
    assert renamed["delivery_status"] == "rejected"
    again = client.patch(f"/api/workspace/reports/{report['id']}", headers=headers,
                         json={"delivery_emails": ["a@client.ro"]}).json()
    assert again["delivery_status"] == "pending"
    assert again["delivery_approval_id"] != report["delivery_approval_id"]
