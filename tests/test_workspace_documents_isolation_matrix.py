"""Every knowledge-base route, probed from outside its scope by every kind of outsider.

The cast adds to the usual company (department A with an admin, an approver and a
member; department B with a member): an approver of B, a second member of A, and a
member of department C, which is then archived. Department B holds a ready, a failed
and a still-processing document; C holds one. Whoever stands outside a department —
member or approver of another one, or a member of an archived one — must get from every
route exactly what a nonexistent document or department gives, must not learn a title
or a word of text, and must change nothing: no row, chunk, file or audit entry. Inside
a department, a colleague may read someone else's upload but not manage it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from agents.core.workspace import db as workspace_db
from agents.core.workspace import documents, identity, retrieval
from tests.fixtures.workspace import samples
from tests.fixtures.workspace.doc_helpers import docs_client, seed_document, upload
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    authed,
    db,
    login,
    make_department,
    make_user,
    seed_company,
    ws,
)

SECRET_B = "Evaluarea anuală: salariul directorului crește la 42.000 lei."
SECRET_C = "Arhiva veche: contractul Țesătoria Brașov a fost reziliat."
MISSING_ID = 987_654
ROUTES = (("GET", ""), ("GET", "/file"), ("DELETE", ""), ("POST", "/reindex"))


@dataclass
class Cast:
    conn: sqlite3.Connection
    departments: dict[str, int]
    users: dict[str, identity.WorkspaceUser]
    docs: dict[str, int]
    clients: dict[str, tuple[TestClient, str]]


def _client(user: identity.WorkspaceUser) -> tuple[TestClient, str]:
    client = docs_client()
    return client, login(client, user.email)


@pytest.fixture
def cast(ws):
    conn = db()
    company = seed_company(conn)
    dept_c = make_department(conn, "Arhivă")
    users = {
        "admin": company.admin, "approver_a": company.approver_a,
        "member_a": company.member_a, "member_b": company.member_b,
        "approver_b": make_user(conn, role="approver", department_ids=[company.dept_b]),
        "colleague_a": make_user(conn, role="member", department_ids=[company.dept_a]),
        "member_c": make_user(conn, role="member", department_ids=[dept_c]),
    }
    clients = {name: _client(user) for name, user in users.items()}
    b, b_csrf = clients["member_b"]
    a, a_csrf = clients["member_a"]
    c, c_csrf = clients["member_c"]
    docs = {
        "b_ready": upload(b, b_csrf, company.dept_b, "evaluari.txt", SECRET_B.encode(),
                          title="Evaluări confidențiale").json()["id"],
        "b_failed": upload(b, b_csrf, company.dept_b, "scanat.pdf",
                           samples.build_blank_pdf(1)).json()["id"],
        "b_processing": seed_document(conn, department_id=company.dept_b,
                                      uploader_id=company.member_b.id,
                                      title="Evaluări în lucru", chunks=[SECRET_B],
                                      status="processing"),
        "a_own": upload(a, a_csrf, company.dept_a, "oferta.txt",
                        "Oferta de toamnă pentru clienți.".encode()).json()["id"],
        "c_archived": upload(c, c_csrf, dept_c, "arhiva.txt", SECRET_C.encode()).json()["id"],
    }
    documents.file_path(docs["b_processing"]).write_bytes(SECRET_B.encode())
    with workspace_db.tx(conn):
        conn.execute("UPDATE departments SET archived = 1 WHERE id = ?", (dept_c,))
    # The archive changed what member_c may see; their session re-reads it per request.
    yield Cast(conn=conn, users=users, docs=docs, clients=clients,
               departments={"a": company.dept_a, "b": company.dept_b, "c": dept_c})
    conn.close()


def _state(conn: sqlite3.Connection, document_id: int) -> tuple:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    chunks = [r[0] for r in conn.execute("SELECT text FROM chunks WHERE document_id = ? "
                                         "ORDER BY ord", (document_id,))]
    path = documents.file_path(document_id)
    audits = conn.execute("SELECT COUNT(*) FROM audit WHERE target_type = 'document' "
                          "AND target_id = ?", (str(document_id),)).fetchone()[0]
    return (tuple(row) if row else None, chunks,
            path.read_bytes() if path.exists() else None, audits)


#: Who probes which documents from outside their scope.
OUTSIDERS = {
    "member_a": ("b_ready", "b_failed", "b_processing", "c_archived"),
    "approver_a": ("b_ready", "b_failed", "b_processing", "c_archived"),
    "approver_b": ("a_own", "c_archived"),
    "member_c": ("c_archived", "b_ready"),  # an archived department is no department at all
}


@pytest.mark.parametrize("actor", sorted(OUTSIDERS))
def test_every_route_answers_an_outsider_exactly_like_a_missing_document(cast, actor):
    client, csrf = cast.clients[actor]
    for method, suffix in ROUTES:
        missing = client.request(method, f"/api/workspace/documents/{MISSING_ID}{suffix}",
                                 headers=authed(client, csrf))
        assert missing.status_code == 404
        for target in OUTSIDERS[actor]:
            document_id = cast.docs[target]
            before = _state(cast.conn, document_id)
            response = client.request(method, f"/api/workspace/documents/{document_id}{suffix}",
                                      headers=authed(client, csrf))
            assert (response.status_code, response.json()) == (404, missing.json()), \
                (actor, target, method, suffix)
            assert response.headers["Cache-Control"] == "no-store"
            for secret in (SECRET_B, SECRET_C, "Evaluări", "evaluari", "arhiva"):
                assert secret not in response.text
            assert _state(cast.conn, document_id) == before, (actor, target, method, suffix)


@pytest.mark.parametrize("actor", sorted(OUTSIDERS))
def test_no_listing_filter_or_search_reveals_an_outsiders_documents(cast, actor):
    client, _csrf = cast.clients[actor]
    hidden = {cast.docs[target] for target in OUTSIDERS[actor]}
    for status in (None, "ready", "failed", "processing"):
        for q in (None, "salariul directorului", "evaluari", "Evaluări în lucru", "scanat",
                  "arhiva", "reziliat Țesătoria", "42.000"):
            params = {key: value for key, value in (("status", status), ("q", q)) if value}
            response = client.get("/api/workspace/documents", params=params)
            assert response.status_code == 200
            listed = {doc["id"] for doc in response.json()["documents"]}
            assert not listed & hidden, (actor, params)
    company_only = client.get("/api/workspace/documents", params={"department_id": "company"})
    assert not {doc["id"] for doc in company_only.json()["documents"]} & hidden


@pytest.mark.parametrize(("actor", "department"),
                         [("member_a", "b"), ("approver_a", "b"), ("approver_b", "a"),
                          ("member_c", "c"), ("member_a", "c")])
def test_a_foreign_or_archived_department_is_indistinguishable_from_a_missing_one(
        cast, actor, department):
    client, csrf = cast.clients[actor]
    department_id = cast.departments[department]
    missing = client.get("/api/workspace/documents", params={"department_id": MISSING_ID})
    foreign = client.get("/api/workspace/documents", params={"department_id": department_id})
    assert (foreign.status_code, foreign.json()) == (404, missing.json())
    documents_before = cast.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    audit_before = cast.conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    upload_missing = upload(client, csrf, MISSING_ID, "intrus.txt", b"Text strecurat.")
    upload_foreign = upload(client, csrf, department_id, "intrus.txt", b"Text strecurat.")
    assert (upload_foreign.status_code, upload_foreign.json()) == (404, upload_missing.json())
    assert cast.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == documents_before
    assert cast.conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == audit_before


def test_a_colleague_reads_but_never_manages_someone_elses_upload(cast):
    client, csrf = cast.clients["colleague_a"]
    document_id = cast.docs["a_own"]
    before = _state(cast.conn, document_id)
    detail = client.get(f"/api/workspace/documents/{document_id}").json()
    assert (detail["can_delete"], detail["can_reindex"], detail["can_publish"]) == (False, False,
                                                                                   True)
    assert client.get(f"/api/workspace/documents/{document_id}/file").status_code == 200
    listed = {doc["id"]: doc for doc in client.get("/api/workspace/documents").json()["documents"]}
    assert listed[document_id]["can_delete"] is False
    for method, suffix in (("DELETE", ""), ("POST", "/reindex")):
        response = client.request(method, f"/api/workspace/documents/{document_id}{suffix}",
                                  headers=authed(client, csrf))
        assert (response.status_code, response.json()["error"]) == (403, "forbidden")
    assert _state(cast.conn, document_id) == before


def test_an_approver_of_another_department_manages_nothing_here(cast):
    client, csrf = cast.clients["approver_b"]
    own = cast.docs["b_ready"]
    detail = client.get(f"/api/workspace/documents/{own}").json()
    assert detail["can_delete"] is True  # their own department: any document
    assert cast.docs["a_own"] not in {
        doc["id"] for doc in client.get("/api/workspace/documents").json()["documents"]}


@pytest.mark.parametrize("actor", sorted(OUTSIDERS))
def test_a_publish_request_cannot_name_an_outsiders_document(cast, actor):
    user = identity.get_user(cast.conn, cast.users[actor].id)
    for target in OUTSIDERS[actor]:
        with pytest.raises(documents.WorkspaceError) as caught:
            documents.validate_publish(cast.conn, user, {"document_id": cast.docs[target]})
        assert (caught.value.status, caught.value.code) == (404, "not_found")


@pytest.mark.parametrize("actor", sorted(OUTSIDERS))
def test_retrieval_in_an_outsiders_scope_finds_none_of_their_text(cast, actor):
    user = identity.get_user(cast.conn, cast.users[actor].id)
    scope = user.allowed_department_ids(cast.conn)
    hidden = [cast.docs[target] for target in OUTSIDERS[actor]]
    for document_ids in (None, hidden):
        hits = retrieval.search(cast.conn, department_ids=scope, include_company=True,
                                query=f"{SECRET_B} {SECRET_C}", document_ids=document_ids)
        assert not {hit.document_id for hit in hits} & set(hidden)
