"""The ``document.company_publish`` approval effect (spec §7 "Effect registered by S2").

A department document becomes company-wide only through an approval an admin decides:
``validate`` runs when the request is made (and again before execution), ``execute``
flips the visibility, audits it and tells the requester and the uploader.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_approvals, workspace_auth, workspace_documents
from agents.core.workspace import audit, documents, effects_api, identity, retrieval
from agents.core.workspace import db as workspace_db
from agents.core.workspace.errors import WorkspaceError
from tests.fixtures.workspace.doc_helpers import docs_client, seed_document
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    authed,
    db,
    login,
    make_app,
    make_user,
    seed_company,
    ws,
)


@pytest.fixture
def setup(ws):
    conn = db()
    company = seed_company(conn)
    uploader = make_user(conn, role="member", department_ids=[company.dept_a], locale="ro",
                         name="Ana Uploader")
    requester = make_user(conn, role="member", department_ids=[company.dept_a], locale="en",
                          name="John Requester")
    document_id = seed_document(conn, department_id=company.dept_a, uploader_id=uploader.id,
                                title="Ghid de vânzări", chunks=["Ghidul de vânzări al firmei."])
    yield conn, company, uploader, requester, document_id
    conn.close()


def _user(conn, user_id):
    return identity.get_user(conn, user_id)


def _pinned(conn, requester, document_id) -> dict:
    """The payload the approvals engine stores (and replays to ``execute``)."""
    return documents.validate_publish(conn, requester, {"document_id": document_id}).payload


def _created_at(conn, document_id) -> float:
    return conn.execute("SELECT created_at FROM documents WHERE id = ?",
                        (document_id,)).fetchone()[0]


def test_the_effect_is_registered_for_admins_to_decide():
    spec = effects_api.get_effect("document.company_publish")
    assert "document.company_publish" in effects_api.kinds()
    assert spec.decider_rule == "admin"
    assert spec.validate is documents.validate_publish and spec.execute is documents.execute_publish


def test_only_admins_are_eligible_and_never_the_requester(setup):
    conn, company, uploader, requester, document_id = setup
    spec = effects_api.get_effect(documents.PUBLISH_KIND)
    assert effects_api.eligible_decider_ids(conn, spec, company.dept_a,
                                            exclude=requester.id) == [company.admin.id]
    assert not effects_api.can_decide(_user(conn, company.approver_a.id), spec, company.dept_a,
                                      requester.id)
    assert effects_api.can_decide(_user(conn, company.admin.id), spec, company.dept_a,
                                  requester.id)


def test_validate_returns_the_scope_a_localized_summary_and_a_clean_payload(setup):
    conn, company, uploader, requester, document_id = setup
    english = documents.validate_publish(conn, requester, {"document_id": document_id,
                                                           "extra": "dropped"})
    assert english.department_id == company.dept_a
    assert english.summary == "Publish company-wide: “Ghid de vânzări”"
    assert english.payload == {"document_id": document_id,
                               "created_at": _created_at(conn, document_id)}
    romanian = documents.validate_publish(conn, uploader, {"document_id": document_id})
    assert romanian.summary == "Publicare în toată compania: „Ghid de vânzări”"


@pytest.mark.parametrize("payload", [None, [], "1", {}, {"document_id": "1"},
                                     {"document_id": True}, {"document_id": 0},
                                     {"document_id": 2 ** 64}])
def test_validate_refuses_malformed_payloads_with_422(setup, payload):
    conn, company, uploader, requester, document_id = setup
    with pytest.raises(WorkspaceError) as caught:
        documents.validate_publish(conn, requester, payload)
    assert caught.value.status == 422 and caught.value.code == "invalid_request"


def test_validate_refuses_documents_out_of_scope_already_public_or_not_ready(setup):
    conn, company, uploader, requester, document_id = setup
    foreign = seed_document(conn, department_id=company.dept_b, uploader_id=company.member_b.id,
                            title="Salarii", chunks=["confidențial"])
    public = seed_document(conn, department_id=company.dept_a, uploader_id=uploader.id,
                           title="Public", chunks=["deja public"], visibility="company")
    failed = seed_document(conn, department_id=company.dept_a, uploader_id=uploader.id,
                           title="Stricat", chunks=[], status="failed")
    expected = {foreign: (404, "not_found"), 987654: (404, "not_found"),
                public: (409, "already_company"), failed: (409, "document_not_ready")}
    for target, (status, code) in expected.items():
        with pytest.raises(WorkspaceError) as caught:
            documents.validate_publish(conn, requester, {"document_id": target})
        assert (caught.value.status, caught.value.code) == (status, code), target


async def test_execute_publishes_audits_and_notifies_requester_and_uploader(setup):
    conn, company, uploader, requester, document_id = setup
    decider = _user(conn, company.admin.id)
    result = await documents.execute_publish(
        {"id": 77, "payload": _pinned(conn, requester, document_id)}, requester, decider)
    assert result == {"document_id": document_id, "visibility": "company",
                      "title": "Ghid de vânzări"}
    row = conn.execute("SELECT visibility, department_id FROM documents WHERE id = ?",
                       (document_id,)).fetchone()
    assert (row["visibility"], row["department_id"]) == ("company", company.dept_a)
    entry = conn.execute("SELECT * FROM audit WHERE action = 'document.published'").fetchone()
    assert entry["actor_user_id"] == decider.id and entry["target_id"] == str(document_id)
    assert entry["department_id"] == company.dept_a
    assert json.loads(entry["details_json"]) == {"approval_id": 77, "requester_id": requester.id,
                                                 "title": "Ghid de vânzări"}
    assert audit.verify_chain(conn)["ok"]
    notes = {row["user_id"]: row for row in conn.execute("SELECT * FROM notifications")}
    assert set(notes) == {requester.id, uploader.id}  # never the decider
    assert notes[requester.id]["title"] == "Document published company-wide"
    assert notes[uploader.id]["title"] == "Document publicat în toată compania"
    assert all(note["body"] == "Ghid de vânzări" and note["kind"] == "document.published"
               and note["link"] == f"/workspace/documents?document={document_id}"
               for note in notes.values())


async def test_after_publishing_every_department_can_read_and_retrieve_it(setup):
    conn, company, uploader, requester, document_id = setup
    member_b = docs_client()
    login(member_b, company.member_b.email)
    assert member_b.get(f"/api/workspace/documents/{document_id}").status_code == 404
    await documents.execute_publish({"id": 1, "payload_json": json.dumps(
        _pinned(conn, requester, document_id))}, requester, _user(conn, company.admin.id))
    assert member_b.get(f"/api/workspace/documents/{document_id}").status_code == 200
    hits = retrieval.search(conn, department_ids=[company.dept_b], include_company=True,
                            query="ghidul de vânzări")
    assert [hit.document_id for hit in hits] == [document_id]


async def test_an_admin_publishing_their_own_upload_notifies_nobody_but_the_uploader(setup):
    conn, company, uploader, requester, document_id = setup
    admin = _user(conn, company.admin.id)
    await documents.execute_publish({"id": 2, "payload": _pinned(conn, admin, document_id)},
                                    admin, admin)
    assert [row["user_id"] for row in conn.execute("SELECT user_id FROM notifications")] == [
        uploader.id]


async def test_execute_fails_cleanly_when_the_document_changed_meanwhile(setup):
    conn, company, uploader, requester, document_id = setup
    decider = _user(conn, company.admin.id)
    payload = _pinned(conn, requester, document_id)
    with workspace_db.tx(conn):
        conn.execute("UPDATE documents SET visibility = 'company' WHERE id = ?", (document_id,))
    with pytest.raises(WorkspaceError) as caught:
        await documents.execute_publish({"id": 3, "payload": payload}, requester, decider)
    assert caught.value.code == "already_company"
    with workspace_db.tx(conn):
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    with pytest.raises(WorkspaceError) as caught:
        await documents.execute_publish({"id": 3, "payload": payload}, requester, decider)
    assert caught.value.code == "not_found"
    with pytest.raises(WorkspaceError) as caught:
        await documents.execute_publish({"id": 4, "payload_json": "not json"}, requester, decider)
    assert caught.value.code == "invalid_request"
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit WHERE action = 'document.published'"
                        ).fetchone()[0] == 0


def test_a_pending_request_is_shown_and_blocks_a_second_one_in_the_ui(setup):
    conn, company, uploader, requester, document_id = setup
    client = docs_client()
    login(client, requester.email)
    assert client.get(f"/api/workspace/documents/{document_id}").json()["can_publish"] is True
    stamp = workspace_db.now()
    with workspace_db.tx(conn):
        approval = conn.execute(
            "INSERT INTO approvals (kind, department_id, requester_id, summary, payload_json, "
            "status, created_at, expires_at) VALUES (?, ?, ?, 's', ?, 'pending', ?, ?)",
            (documents.PUBLISH_KIND, company.dept_a, requester.id,
             json.dumps(_pinned(conn, requester, document_id)), stamp, stamp + 3600)).lastrowid
        conn.execute(
            "INSERT INTO approvals (kind, department_id, requester_id, summary, payload_json, "
            "status, created_at, expires_at) VALUES (?, ?, ?, 's', 'corrupt{', 'pending', ?, ?)",
            (documents.PUBLISH_KIND, company.dept_a, requester.id, stamp, stamp + 3600))
    detail = client.get(f"/api/workspace/documents/{document_id}").json()
    assert detail["publish_pending"] is True and detail["can_publish"] is False
    listed = client.get("/api/workspace/documents").json()["documents"]
    assert [doc["publish_pending"] for doc in listed] == [True]
    with workspace_db.tx(conn):
        conn.execute("UPDATE approvals SET status = 'rejected' WHERE id = ?", (approval,))
    assert client.get(f"/api/workspace/documents/{document_id}").json()["can_publish"] is True


async def test_a_request_for_a_deleted_document_never_publishes_the_one_that_took_its_id(setup):
    conn, company, uploader, requester, document_id = setup
    payload = _pinned(conn, requester, document_id)
    stamp = workspace_db.now()
    with workspace_db.tx(conn):
        conn.execute("INSERT INTO approvals (kind, department_id, requester_id, summary, "
                     "payload_json, status, created_at, expires_at) "
                     "VALUES (?, ?, ?, 's', ?, 'pending', ?, ?)",
                     (documents.PUBLISH_KIND, company.dept_a, requester.id, json.dumps(payload),
                      stamp, stamp + 3600))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.execute(  # a later upload of the department reuses the freed id
            "INSERT INTO documents (id, department_id, visibility, title, filename, mime, "
            "size_bytes, sha256, uploader_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'department', 'Evaluări interne', 'evaluari.txt', 'text/plain', 9, "
            "?, ?, 'ready', ?, ?)",
            (document_id, company.dept_a, "2" * 64, uploader.id, stamp + 7, stamp + 7))
    with pytest.raises(WorkspaceError) as caught:
        documents.validate_publish(conn, requester, payload)
    assert (caught.value.status, caught.value.code) == (404, "not_found")
    with pytest.raises(WorkspaceError) as caught:
        await documents.execute_publish({"id": 9, "payload": payload}, requester,
                                        _user(conn, company.admin.id))
    assert caught.value.code == "not_found"
    assert conn.execute("SELECT visibility FROM documents WHERE id = ?",
                        (document_id,)).fetchone()[0] == "department"
    client = docs_client()
    login(client, requester.email)
    detail = client.get(f"/api/workspace/documents/{document_id}").json()
    assert detail["publish_pending"] is False and detail["can_publish"] is True
    fresh = documents.validate_publish(conn, requester, {"document_id": document_id})
    assert fresh.payload == {"document_id": document_id, "created_at": stamp + 7}


def _approvals_client() -> TestClient:
    """A client whose app also serves the S4 approvals router (the real decide flow)."""
    return TestClient(make_app(workspace_auth.router, workspace_documents.router,
                               workspace_approvals.router))


def test_the_publish_request_is_decided_and_carried_out_through_the_approvals_api(setup):
    conn, company, uploader, requester, document_id = setup
    member, admin = _approvals_client(), _approvals_client()
    member_csrf, admin_csrf = login(member, requester.email), login(admin, company.admin.email)
    requested = member.post("/api/workspace/approvals", headers=authed(member, member_csrf),
                            json={"kind": documents.PUBLISH_KIND,
                                  "payload": {"document_id": document_id}})
    assert requested.status_code == 201 and requested.json()["status"] == "pending"
    assert member.get(f"/api/workspace/documents/{document_id}").json()["publish_pending"] is True
    decided = admin.post(f"/api/workspace/approvals/{requested.json()['id']}/decide",
                         headers=authed(admin, admin_csrf), json={"decision": "approve"})
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    detail = member.get(f"/api/workspace/documents/{document_id}").json()
    assert (detail["visibility"], detail["publish_pending"], detail["can_publish"]) == (
        "company", False, False)


def test_approving_a_request_whose_document_was_replaced_fails_and_publishes_nothing(setup):
    conn, company, uploader, requester, document_id = setup
    member, admin = _approvals_client(), _approvals_client()
    member_csrf, admin_csrf = login(member, requester.email), login(admin, company.admin.email)
    requested = member.post("/api/workspace/approvals", headers=authed(member, member_csrf),
                            json={"kind": documents.PUBLISH_KIND,
                                  "payload": {"document_id": document_id}}).json()
    stamp = workspace_db.now() + 5
    with workspace_db.tx(conn):
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.execute(
            "INSERT INTO documents (id, department_id, visibility, title, filename, mime, "
            "size_bytes, sha256, uploader_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'department', 'Evaluări interne', 'evaluari.txt', 'text/plain', 9, "
            "?, ?, 'ready', ?, ?)",
            (document_id, company.dept_a, "2" * 64, uploader.id, stamp, stamp))
    decided = admin.post(f"/api/workspace/approvals/{requested['id']}/decide",
                         headers=authed(admin, admin_csrf), json={"decision": "approve"}).json()
    assert (decided["status"], decided["error_code"]) == ("failed", "not_found")
    assert conn.execute("SELECT visibility FROM documents WHERE id = ?",
                        (document_id,)).fetchone()[0] == "department"
    assert conn.execute("SELECT COUNT(*) FROM audit WHERE action = 'document.published'"
                        ).fetchone()[0] == 0
