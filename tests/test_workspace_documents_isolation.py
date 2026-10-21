"""Department isolation of the knowledge base (spec §6 "Authorization", DoD 2).

The cast: department A (Vânzări) with an admin, an approver and a member; department B
(Resurse Umane) with a member. A member of A must never reach B's documents through
any route or through retrieval — and the 404 they get must be indistinguishable from
the one for a document that does not exist. Company-wide documents are readable by
everyone; who may delete or re-index follows the §6 table.
"""

from __future__ import annotations

import pytest

from agents.core.routers import workspace_documents
from agents.core.workspace import db as workspace_db
from agents.core.workspace import documents, identity, retrieval
from tests.fixtures.workspace import samples
from tests.fixtures.workspace.doc_helpers import docs_client, upload, upload_url
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    authed,
    db,
    login,
    make_user,
    seed_company,
    ws,
)

SECRET_B = "Salariul directorului de resurse umane este confidențial: 42.000 lei."


@pytest.fixture
def cast(ws):
    conn = db()
    company = seed_company(conn)
    admin = docs_client()
    admin_csrf = login(admin, company.admin.email)
    member_a = docs_client()
    member_a_csrf = login(member_a, company.member_a.email)
    member_b = docs_client()
    member_b_csrf = login(member_b, company.member_b.email)
    doc_a = upload(member_a, member_a_csrf, company.dept_a, "oferta.txt",
                   "Oferta de toamnă pentru clienții din Brașov.".encode()).json()["id"]
    doc_b = upload(member_b, member_b_csrf, company.dept_b, "salarii.txt",
                   SECRET_B.encode()).json()["id"]
    doc_company = upload(admin, admin_csrf, "company", "politica.md",
                         samples.read_sample("politica-concedii.md")).json()["id"]
    yield {
        "conn": conn, "company": company, "doc_a": doc_a, "doc_b": doc_b,
        "doc_company": doc_company,
        "admin": (admin, admin_csrf), "member_a": (member_a, member_a_csrf),
        "member_b": (member_b, member_b_csrf),
    }
    conn.close()


def _ids(client, **params) -> set[int]:
    response = client.get("/api/workspace/documents", params=params)
    assert response.status_code == 200, response.text
    return {doc["id"] for doc in response.json()["documents"]}


#: Every route of the documents router and how a member of A probes B's document with it.
PROBES = {
    ("GET", "/api/workspace/documents"): None,  # covered by the list tests below
    ("POST", "/api/workspace/documents"): None,  # covered by the upload test below
    ("GET", "/api/workspace/documents/{document_id}"): ("GET", ""),
    ("GET", "/api/workspace/documents/{document_id}/file"): ("GET", "/file"),
    ("DELETE", "/api/workspace/documents/{document_id}"): ("DELETE", ""),
    ("POST", "/api/workspace/documents/{document_id}/reindex"): ("POST", "/reindex"),
}


def test_the_probe_inventory_lists_every_route():
    routes = {(method, route.path) for route in workspace_documents.router.routes
              for method in route.methods}
    assert routes == set(PROBES)


@pytest.mark.parametrize("probe", [p for p in PROBES.values() if p is not None])
def test_a_member_of_a_cannot_reach_bs_document_through_any_route(cast, probe):
    client, csrf = cast["member_a"]
    method, suffix = probe
    foreign = client.request(method, f"/api/workspace/documents/{cast['doc_b']}{suffix}",
                             headers=authed(client, csrf))
    missing = client.request(method, f"/api/workspace/documents/987654{suffix}",
                             headers=authed(client, csrf))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"error": "not_found",
                                                "message": "document not found"}
    assert SECRET_B.encode() not in foreign.content
    row = cast["conn"].execute("SELECT status FROM documents WHERE id = ?",
                               (cast["doc_b"],)).fetchone()
    assert row["status"] == "ready"  # neither deleted nor re-indexed
    assert documents.file_path(cast["doc_b"]).exists()


def test_the_list_shows_own_department_and_company_documents_only(cast):
    member_a, _ = cast["member_a"]
    member_b, _ = cast["member_b"]
    admin, _ = cast["admin"]
    assert _ids(member_a) == {cast["doc_a"], cast["doc_company"]}
    assert _ids(member_b) == {cast["doc_b"], cast["doc_company"]}
    assert _ids(admin) == {cast["doc_a"], cast["doc_b"], cast["doc_company"]}
    assert _ids(member_a, department_id="company") == {cast["doc_company"]}
    foreign = member_a.get("/api/workspace/documents",
                           params={"department_id": cast["company"].dept_b})
    assert foreign.status_code == 404 and foreign.json()["error"] == "not_found"
    assert _ids(admin, department_id=cast["company"].dept_b) == {cast["doc_b"]}


def test_searching_the_list_never_reveals_another_departments_text(cast):
    member_a, _ = cast["member_a"]
    member_b, _ = cast["member_b"]
    assert _ids(member_a, q="confidențial salariul") == set()
    assert _ids(member_a, q="salarii") == set()
    assert _ids(member_b, q="confidențial salariul") == {cast["doc_b"]}


def test_retrieval_is_scoped_in_sql_even_with_explicit_document_ids(cast):
    conn, company = cast["conn"], cast["company"]
    member_a = identity.get_user(conn, company.member_a.id)
    scope = member_a.allowed_department_ids(conn)
    assert scope == [company.dept_a]
    for document_ids in (None, [cast["doc_b"]], [cast["doc_a"], cast["doc_b"]]):
        hits = retrieval.search(conn, department_ids=scope, include_company=True,
                                query="salariul directorului confidențial lei Brașov",
                                document_ids=document_ids)
        assert cast["doc_b"] not in {hit.document_id for hit in hits}
    hits = retrieval.search(conn, department_ids=[company.dept_b], include_company=False,
                            query="salariul confidențial")
    assert [hit.document_id for hit in hits] == [cast["doc_b"]]


def test_company_wide_documents_are_readable_by_everyone(cast):
    for name in ("member_a", "member_b", "admin"):
        client, _ = cast[name]
        assert client.get(f"/api/workspace/documents/{cast['doc_company']}").status_code == 200
        file = client.get(f"/api/workspace/documents/{cast['doc_company']}/file")
        assert file.content == samples.read_sample("politica-concedii.md")
    conn, company = cast["conn"], cast["company"]
    for department in (company.dept_a, company.dept_b):
        hits = retrieval.search(conn, department_ids=[department], include_company=True,
                                query="concediul de odihnă")
        assert cast["doc_company"] in {hit.document_id for hit in hits}
        assert retrieval.search(conn, department_ids=[department], include_company=False,
                                query="concediul de odihnă") == []


def test_reading_a_document_does_not_mean_managing_it(cast):
    client, csrf = cast["member_a"]
    detail = client.get(f"/api/workspace/documents/{cast['doc_company']}").json()
    assert detail["can_delete"] is False and detail["can_reindex"] is False
    for method, suffix in (("DELETE", ""), ("POST", "/reindex")):
        response = client.request(method, f"/api/workspace/documents/{cast['doc_company']}{suffix}",
                                  headers=authed(client, csrf))
        assert response.status_code == 403 and response.json()["error"] == "forbidden"
    assert documents.file_path(cast["doc_company"]).exists()


def test_members_manage_their_own_uploads_only(cast):
    conn, company = cast["conn"], cast["company"]
    colleague_user = make_user(conn, role="member", department_ids=[company.dept_a])
    colleague = docs_client()
    colleague_csrf = login(colleague, colleague_user.email)
    detail = colleague.get(f"/api/workspace/documents/{cast['doc_a']}").json()
    assert detail["can_delete"] is False and detail["can_publish"] is True
    refused = colleague.delete(f"/api/workspace/documents/{cast['doc_a']}",
                               headers=authed(colleague, colleague_csrf))
    assert refused.status_code == 403
    owner, owner_csrf = cast["member_a"]
    assert owner.delete(f"/api/workspace/documents/{cast['doc_a']}",
                        headers=authed(owner, owner_csrf)).status_code == 204


def test_an_approver_manages_any_document_of_their_departments_only(cast):
    company = cast["company"]
    approver = docs_client()
    csrf = login(approver, company.approver_a.email)
    assert approver.post(f"/api/workspace/documents/{cast['doc_a']}/reindex",
                         headers=authed(approver, csrf)).status_code == 200
    assert approver.delete(f"/api/workspace/documents/{cast['doc_company']}",
                           headers=authed(approver, csrf)).status_code == 403
    assert approver.delete(f"/api/workspace/documents/{cast['doc_b']}",
                           headers=authed(approver, csrf)).status_code == 404
    assert approver.delete(f"/api/workspace/documents/{cast['doc_a']}",
                           headers=authed(approver, csrf)).status_code == 204


def test_admins_manage_everything(cast):
    admin, csrf = cast["admin"]
    conn = cast["conn"]
    for doc in (cast["doc_a"], cast["doc_b"], cast["doc_company"]):
        reindexed = admin.post(f"/api/workspace/documents/{doc}/reindex",
                               headers=authed(admin, csrf))
        assert reindexed.status_code == 200
        assert (reindexed.json()["status"], reindexed.json()["chunk_count"] > 0) == ("ready", True)
        assert documents.file_path(doc).exists()
        assert admin.delete(f"/api/workspace/documents/{doc}",
                            headers=authed(admin, csrf)).status_code == 204
        # The effect, not just the status: the row, its chunks and its stored file are gone.
        assert conn.execute("SELECT COUNT(*) FROM documents WHERE id = ?", (doc,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?",
                            (doc,)).fetchone()[0] == 0
        assert not documents.file_path(doc).exists()
        assert admin.get(f"/api/workspace/documents/{doc}").status_code == 404
    actions = [row[0] for row in conn.execute(
        "SELECT action FROM audit WHERE action IN ('document.reindexed', 'document.deleted') "
        "AND actor_user_id = ? ORDER BY id", (cast["company"].admin.id,))]
    assert actions == ["document.reindexed", "document.deleted"] * 3
    assert list(conn.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'concediu'")) == []


def test_a_member_cannot_upload_into_another_department(cast):
    client, csrf = cast["member_a"]
    response = upload(client, csrf, cast["company"].dept_b, "intrus.txt", b"text")
    assert response.status_code == 404
    count = cast["conn"].execute("SELECT COUNT(*) FROM documents WHERE department_id = ?",
                                 (cast["company"].dept_b,)).fetchone()[0]
    assert count == 1


def test_leaving_a_department_takes_its_documents_away_even_your_own(cast):
    conn, company = cast["conn"], cast["company"]
    with workspace_db.tx(conn):
        conn.execute("UPDATE user_departments SET department_id = ? WHERE user_id = ?",
                     (company.dept_b, company.member_a.id))
    client, csrf = cast["member_a"]
    assert client.get(f"/api/workspace/documents/{cast['doc_a']}").status_code == 404
    assert client.delete(f"/api/workspace/documents/{cast['doc_a']}",
                         headers=authed(client, csrf)).status_code == 404
    assert cast["doc_a"] not in _ids(client) and cast["doc_b"] in _ids(client)


def test_an_archived_department_is_visible_to_admins_only(cast):
    conn, company = cast["conn"], cast["company"]
    with workspace_db.tx(conn):
        conn.execute("UPDATE departments SET archived = 1 WHERE id = ?", (company.dept_b,))
    member_b, _ = cast["member_b"]
    admin, _ = cast["admin"]
    assert _ids(member_b) == {cast["doc_company"]}
    assert member_b.get(f"/api/workspace/documents/{cast['doc_b']}").status_code == 404
    assert admin.get(f"/api/workspace/documents/{cast['doc_b']}").status_code == 200
    assert _ids(admin, department_id=company.dept_b) == {cast["doc_b"]}


def test_a_disabled_user_is_signed_out_of_every_route(cast):
    conn, company = cast["conn"], cast["company"]
    with workspace_db.tx(conn):
        conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (company.member_a.id,))
    client, csrf = cast["member_a"]
    for method, url in (("GET", "/api/workspace/documents"),
                        ("GET", f"/api/workspace/documents/{cast['doc_a']}"),
                        ("GET", f"/api/workspace/documents/{cast['doc_a']}/file"),
                        ("POST", upload_url(company.dept_a, "x.txt")),
                        ("DELETE", f"/api/workspace/documents/{cast['doc_a']}"),
                        ("POST", f"/api/workspace/documents/{cast['doc_a']}/reindex")):
        response = client.request(method, url, headers=authed(client, csrf),
                                  content=b"x" if method == "POST" else None)
        assert response.status_code == 401 and response.json()["error"] == "auth_required"


def test_the_publish_request_check_respects_isolation(cast):
    conn, company = cast["conn"], cast["company"]
    member_a = identity.get_user(conn, company.member_a.id)
    with pytest.raises(documents.WorkspaceError) as caught:
        documents.validate_publish(conn, member_a, {"document_id": cast["doc_b"]})
    assert caught.value.status == 404 and caught.value.code == "not_found"
