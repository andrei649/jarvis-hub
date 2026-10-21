"""Department and user isolation of every reports route (spec §6 authorization, §7, §12).

The independent review of S4 attacks each route of ``routers/workspace_reports.py`` from
outside: a member and an approver of department B try to read, change, run, export or
borrow department A's reports, runs and documents; a second member of A tries to change
a colleague's report. Every out-of-scope resource must answer ``404 not_found`` with a
body that names nothing, and the database must be unchanged afterwards. A run shared
company-wide opens that one run — never its report, its other runs or its recipients.

The :func:`world` fixture is reused by ``test_workspace_approvals_isolation``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents.core.workspace import db, reports
from agents.core.workspace.identity import WorkspaceUser
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    freeze_clock,
    make_user,
    ws,
)
from tests.test_workspace_reports_support import (  # noqa: F401  (fixtures)
    Cast,
    cast,
    configure_smtp,
    run_now,
    seed_document,
    signed_in,
    sink,
)

NOW = datetime(2026, 10, 17, 13, 0, tzinfo=ZoneInfo("Europe/Bucharest")).timestamp()
SECRET_A = "Marja secretă din Nord este 41% pentru clientul Delta."
SECRET_B = "Grila de salarii din Resurse Umane, confidențială."
RECIPIENT_A = "director@client.ro"
OUTSIDERS = ("member_b", "approver_b")


@dataclass
class World:
    """Department A's resources, department B's own, and the people around them."""

    cast: Cast
    member_a2: WorkspaceUser
    doc_a: int
    doc_b: int
    report_a: int
    run_a: int
    report_b: int
    run_b: int
    message_a: int

    def person(self, name: str) -> WorkspaceUser:
        return self.member_a2 if name == "member_a2" else getattr(self.cast, name)


def _message(conn, user: WorkspaceUser, department_id: int) -> int:
    with db.tx(conn):
        conversation = conn.execute(
            "INSERT INTO conversations (user_id, department_id, title, created_at, updated_at) "
            "VALUES (?, ?, 'Marje', ?, ?)", (user.id, department_id, NOW, NOW)).lastrowid
        return int(conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (?, 'assistant', ?, ?)", (conversation, SECRET_A, NOW)).lastrowid)


def _finished_run(conn, user: WorkspaceUser, report_id: int) -> int:
    run_id = reports.start_manual_run(conn, user, report_id)
    run_now(run_id)
    return run_id


@pytest.fixture
def conn(ws, monkeypatch):
    freeze_clock(monkeypatch, NOW)
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def world(conn, cast, sink) -> World:
    """Department A with a delivered report and run, department B with its own."""
    configure_smtp(conn, sink.port)
    member_a2 = make_user(conn, role="member", department_ids=[cast.dept_a], name="Alt Membru A")
    doc_a = seed_document(conn, department_id=cast.dept_a, uploader_id=cast.member_a.id,
                          title="Marje Nord", chunks=[SECRET_A])
    doc_b = seed_document(conn, department_id=cast.dept_b, uploader_id=cast.member_b.id,
                          title="Salarii", chunks=[SECRET_B])
    report_a = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "Marje Nord", "instructions": "Rezumă marjele.",
        "document_ids": [doc_a], "delivery_emails": [RECIPIENT_A]})
    run_a = _finished_run(conn, cast.member_a, report_a)
    conn.execute("UPDATE report_runs SET delivered_to_json = ? WHERE id = ?",
                 (json.dumps([RECIPIENT_A]), run_a))
    report_b = reports.create_report(conn, cast.member_b, {
        "department_id": cast.dept_b, "name": "Salarii", "instructions": "Rezumă grila.",
        "document_ids": [doc_b]})
    run_b = _finished_run(conn, cast.member_b, report_b)
    return World(cast=cast, member_a2=member_a2, doc_a=doc_a, doc_b=doc_b, report_a=report_a,
                 run_a=run_a, report_b=report_b, run_b=run_b,
                 message_a=_message(conn, cast.member_a, cast.dept_a))


def _snapshot(conn) -> dict:
    """Everything an attack could change, to compare before and after."""
    return {
        "audit": conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
        "reports": [tuple(r) for r in conn.execute("SELECT * FROM reports ORDER BY id")],
        "runs": [tuple(r) for r in conn.execute(
            "SELECT id, report_id, status, shared_company FROM report_runs ORDER BY id")],
        "approvals": [tuple(r) for r in conn.execute(
            "SELECT id, status, decided_by FROM approvals ORDER BY id")],
    }


def _assert_hidden(response, *, label: str) -> None:
    """``404 not_found`` whose body names nothing about the resource."""
    assert response.status_code == 404, (label, response.status_code, response.text)
    body = response.json()
    assert body["error"] == "not_found", label
    assert set(body) <= {"error", "message", "field"}, label
    for secret in ("Marje", SECRET_A, RECIPIENT_A, "Vânzări"):
        assert secret not in response.text, (label, secret)


def _routes_into_a(world: World) -> list[tuple[str, str, dict | None]]:
    rid, run = world.report_a, world.run_a
    return [
        ("GET", f"/api/workspace/reports?department_id={world.cast.dept_a}", None),
        ("GET", f"/api/workspace/reports/{rid}", None),
        ("PATCH", f"/api/workspace/reports/{rid}", {"name": "Preluat"}),
        ("PATCH", f"/api/workspace/reports/{rid}", {"delivery_emails": ["hot@evil.example"]}),
        ("DELETE", f"/api/workspace/reports/{rid}", None),
        ("POST", f"/api/workspace/reports/{rid}/run", None),
        ("GET", f"/api/workspace/reports/{rid}/runs", None),
        ("GET", f"/api/workspace/report-runs/{run}", None),
        ("GET", f"/api/workspace/report-runs/{run}/export?format=md", None),
        ("GET", f"/api/workspace/report-runs/{run}/export?format=html", None),
    ]


# ── another department ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("outsider", OUTSIDERS)
def test_no_report_route_reaches_another_department(conn, world, outsider):
    client, headers = signed_in(world.person(outsider))
    before = _snapshot(conn)
    for method, path, body in _routes_into_a(world):
        response = client.request(method, path, json=body, headers=headers)
        _assert_hidden(response, label=f"{method} {path}")
    assert _snapshot(conn) == before


@pytest.mark.parametrize("outsider", OUTSIDERS)
def test_lists_and_the_shared_feed_show_nothing_of_another_department(conn, world, outsider):
    client, _ = signed_in(world.person(outsider))
    listed = client.get("/api/workspace/reports")
    assert [r["id"] for r in listed.json()["reports"]] == [world.report_b]
    assert client.get("/api/workspace/shared-reports").json() == {"runs": []}
    for text in (SECRET_A, RECIPIENT_A, "Marje"):
        assert text not in listed.text


def test_another_departments_documents_cannot_be_pulled_into_own_reports(conn, world):
    client, headers = signed_in(world.cast.member_b)
    before = _snapshot(conn)
    attempts = [
        ("POST", "/api/workspace/reports", {
            "department_id": world.cast.dept_b, "name": "Furt", "instructions": "x",
            "document_ids": [world.doc_a]}),
        ("POST", "/api/workspace/reports", {
            "department_id": world.cast.dept_a, "name": "Intrus", "instructions": "x"}),
        ("PATCH", f"/api/workspace/reports/{world.report_b}", {"document_ids": [world.doc_a]}),
        ("PATCH", f"/api/workspace/reports/{world.report_b}", {"department_id": world.cast.dept_a}),
        ("PATCH", f"/api/workspace/reports/{world.report_b}",
         {"document_ids": [world.doc_b, world.doc_a]}),
    ]
    for method, path, body in attempts:
        response = client.request(method, path, json=body, headers=headers)
        _assert_hidden(response, label=f"{method} {path} {body}")
    assert _snapshot(conn) == before


def test_an_admin_cannot_point_a_report_at_another_departments_documents(conn, world):
    client, headers = signed_in(world.cast.admin)
    response = client.patch(f"/api/workspace/reports/{world.report_b}",
                            json={"document_ids": [world.doc_a]}, headers=headers)
    assert (response.status_code, response.json()["field"]) == (404, "document_ids")
    moved = client.patch(f"/api/workspace/reports/{world.report_a}",
                         json={"department_id": world.cast.dept_b}, headers=headers)
    assert (moved.status_code, moved.json()["field"]) == (404, "document_ids")


# ── a run shared company-wide ────────────────────────────────────────────────────────

def _share(world: World) -> None:
    admin, headers = signed_in(world.cast.admin)
    response = admin.post("/api/workspace/approvals", headers=headers, json={
        "kind": "report.share_company", "payload": {"run_id": world.run_a}})
    assert response.status_code == 201 and response.json()["status"] == "approved", response.text


def test_a_shared_run_opens_that_run_only_and_never_its_recipients(conn, world):
    unshared = _finished_run(conn, world.cast.member_a, world.report_a)
    _share(world)
    client, headers = signed_in(world.cast.member_b)
    run = client.get(f"/api/workspace/report-runs/{world.run_a}")
    assert run.status_code == 200 and run.json()["content_md"]
    assert run.json()["delivered_to"] == [] and RECIPIENT_A not in run.text
    feed = client.get("/api/workspace/shared-reports")
    assert [r["id"] for r in feed.json()["runs"]] == [world.run_a]
    assert feed.json()["runs"][0]["delivered_to"] == [] and RECIPIENT_A not in feed.text
    assert client.get(f"/api/workspace/report-runs/{world.run_a}/export?format=html"
                      ).status_code == 200
    for method, path in [("GET", f"/api/workspace/report-runs/{unshared}"),
                         ("GET", f"/api/workspace/report-runs/{unshared}/export"),
                         ("GET", f"/api/workspace/reports/{world.report_a}"),
                         ("GET", f"/api/workspace/reports/{world.report_a}/runs"),
                         ("POST", f"/api/workspace/reports/{world.report_a}/run"),
                         ("DELETE", f"/api/workspace/reports/{world.report_a}")]:
        _assert_hidden(client.request(method, path, headers=headers), label=f"{method} {path}")
    owner, _ = signed_in(world.cast.member_a)
    assert owner.get(f"/api/workspace/report-runs/{world.run_a}").json()["delivered_to"] == [
        RECIPIENT_A]
    shared = owner.get("/api/workspace/shared-reports").json()["runs"]
    assert shared[0]["delivered_to"] == [RECIPIENT_A]


def test_a_shared_runs_sources_link_only_to_documents_the_reader_may_open(conn, world, ws):
    """Every reader of a shared run gets its excerpts, but ``can_open`` — which decides whether
    the source drawer links to the document and its file — is true only where the reader may
    open that document, judged when the run is read: publishing it company-wide opens it."""
    common = seed_document(conn, department_id=None, uploader_id=world.cast.admin.id,
                           title="Regulament comun", chunks=["Regula comună a companiei."],
                           visibility="company")
    ws.engine.reply = "# Raport\n\nMarje [1] și reguli [2].\n\n## Surse\n1. [1]\n2. [2]"
    report = reports.create_report(conn, world.cast.member_a, {
        "department_id": world.cast.dept_a, "name": "Marje și reguli", "instructions": "Rezumă.",
        "document_ids": [world.doc_a, common]})
    run_id = _finished_run(conn, world.cast.member_a, report)
    admin, headers = signed_in(world.cast.admin)
    shared = admin.post("/api/workspace/approvals", headers=headers, json={
        "kind": "report.share_company", "payload": {"run_id": run_id}})
    assert shared.json()["status"] == "approved", shared.text

    def openable(user: WorkspaceUser) -> dict[int, bool]:
        client, _ = signed_in(user)
        body = client.get(f"/api/workspace/report-runs/{run_id}").json()
        assert all(c["excerpt"] for c in body["citations"])
        return {c["document_id"]: c["can_open"] for c in body["citations"]}

    assert openable(world.cast.member_b) == {world.doc_a: False, common: True}
    assert openable(world.cast.member_a) == {world.doc_a: True, common: True}
    assert openable(world.cast.admin) == {world.doc_a: True, common: True}
    outsider, _ = signed_in(world.cast.member_b)
    _assert_hidden(outsider.get(f"/api/workspace/documents/{world.doc_a}"), label="document")
    _assert_hidden(outsider.get(f"/api/workspace/documents/{world.doc_a}/file"), label="file")
    with db.tx(conn):
        conn.execute("UPDATE documents SET visibility = 'company' WHERE id = ?", (world.doc_a,))
    assert openable(world.cast.member_b) == {world.doc_a: True, common: True}


# ── another user of the same department ──────────────────────────────────────────────

def test_a_colleague_sees_and_runs_but_cannot_change_a_members_report(conn, world):
    client, headers = signed_in(world.member_a2)
    before = _snapshot(conn)
    report = client.get(f"/api/workspace/reports/{world.report_a}")
    assert report.status_code == 200
    assert (report.json()["can_edit"], report.json()["can_run"]) == (False, True)
    for method, body in [("PATCH", {"name": "Al meu"}),
                         ("PATCH", {"delivery_emails": ["hot@evil.example"]}),
                         ("DELETE", None)]:
        response = client.request(method, f"/api/workspace/reports/{world.report_a}", json=body,
                                  headers=headers)
        assert (response.status_code, response.json()["error"]) == (403, "forbidden"), method
    assert _snapshot(conn) == before
