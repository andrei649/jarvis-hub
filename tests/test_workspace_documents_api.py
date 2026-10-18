"""The knowledge-base HTTP API (spec §7 "S2"): upload, list, read, download, delete, re-index.

Each test drives the real routers through a minimal app (``make_app``) against a
private workspace database; extraction, storage and indexing all run for real.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest

from agents.core.routers import workspace_auth, workspace_documents
from agents.core.workspace import audit, documents, retrieval
from tests.fixtures.workspace import samples
from tests.fixtures.workspace.doc_helpers import docs_client, upload, upload_url
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    authed,
    db,
    freeze_clock,
    login,
    make_app,
    make_department,
    origin_of,
    seed_company,
    ws,
)

SAMPLES = [
    ("regulament-intern.pdf", lambda: samples.read_sample("regulament-intern.pdf"), "application/pdf", 2),
    ("Procedură achiziții.docx", samples.build_docx,
     "application/vnd.openxmlformats-officedocument.wordprocessingml.document", None),
    ("Situație vânzări.xlsx", samples.build_xlsx,
     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", None),
    ("contacte-cp1250.csv", lambda: samples.read_sample("contacte-cp1250.csv"), "text/csv", None),
    ("vanzari-utf8-bom.csv", lambda: samples.read_sample("vanzari-utf8-bom.csv"), "text/csv", None),
    ("note-sedinta.txt", lambda: samples.read_sample("note-sedinta.txt"), "text/plain", None),
    ("politica-concedii.md", lambda: samples.read_sample("politica-concedii.md"), "text/markdown", None),
]


@pytest.fixture
def env(ws):
    conn = db()
    company = seed_company(conn)
    client = docs_client()
    yield conn, company, client
    conn.close()


def _as(client, user) -> str:
    return login(client, user.email)


@pytest.mark.parametrize(("filename", "build", "mime", "pages"), SAMPLES)
def test_every_format_uploads_extracts_and_indexes(env, filename, build, mime, pages):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    data = build()
    response = upload(client, csrf, company.dept_a, filename, data)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready" and body["error"] is None
    assert body["mime"] == mime and body["size_bytes"] == len(data)
    assert body["filename"] == filename and body["page_count"] == pages
    assert body["chunk_count"] >= 1 and body["char_count"] > 0
    assert body["department_id"] == company.dept_a and body["department_name"] == "Vânzări"
    assert body["visibility"] == "department"
    assert body["uploader"] == {"id": company.member_a.id, "name": company.member_a.name}
    assert body["can_delete"] and body["can_reindex"] and body["can_publish"]
    assert body["publish_pending"] is False
    stored = documents.file_path(body["id"])
    assert stored.read_bytes() == data and stored.name == f"{body['id']}.bin"
    assert (stored.stat().st_mode & 0o777) == 0o600
    assert sorted(os.listdir(stored.parent)) == [stored.name]  # no temp file, no user name
    count = conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (body["id"],))
    assert count.fetchone()[0] == body["chunk_count"]


def test_the_title_defaults_to_the_filename_and_can_be_given(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    text = samples.read_sample("note-sedinta.txt")
    assert upload(client, csrf, company.dept_a, "Note_ședință_comitet.txt", text).json()["title"] == \
        "Note ședință comitet"
    given = upload(client, csrf, company.dept_a, "n.txt", text, title="  Note oficiale  ")
    assert given.json()["title"] == "Note oficiale"


def test_a_path_in_the_filename_is_reduced_to_its_last_part(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    text = samples.read_sample("note-sedinta.txt")
    windows = upload(client, csrf, company.dept_a, "C:\\Users\\ana\\Desktop\\plan.txt", text)
    escape = upload(client, csrf, company.dept_a, "../../../etc/passwd.txt", text)
    assert windows.json()["filename"] == "plan.txt" and escape.json()["filename"] == "passwd.txt"
    store = documents.files_dir()
    assert sorted(os.listdir(store)) == sorted(f"{doc['id']}.bin" for doc in
                                               (windows.json(), escape.json()))


def test_bidi_overrides_are_removed_from_names(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    response = upload(client, csrf, company.dept_a, "raport\u202etxt.exe.txt",
                      samples.read_sample("note-sedinta.txt"), title="Titlu\u202e ascuns")
    assert response.json()["filename"] == "raporttxt.exe.txt"
    assert response.json()["title"] == "Titlu ascuns"


def test_failed_extractions_are_stored_as_failed_with_a_stable_code(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    cases = {
        "parola.pdf": (samples.build_encrypted_pdf(), "encrypted_pdf"),
        "scanat.pdf": (samples.build_blank_pdf(2), "no_text"),
        "stricat.docx": (samples._zip({"[Content_Types].xml": samples._CONTENT_TYPES_DOCX,
                                       "word/document.xml": "<w:document"}), "invalid_file"),
    }
    for filename, (data, code) in cases.items():
        body = upload(client, csrf, company.dept_a, filename, data).json()
        assert (body["status"], body["error"], body["chunk_count"]) == ("failed", code, 0)
        assert body["can_publish"] is False and body["can_reindex"] is True
        assert documents.file_path(body["id"]).read_bytes() == data  # kept for a re-index
    scanned = next(d for d in client.get("/api/workspace/documents").json()["documents"]
                   if d["filename"] == "scanat.pdf")
    assert scanned["page_count"] == 2


def test_extraction_timeouts_fail_the_document(env, monkeypatch):
    conn, company, client = env
    csrf = _as(client, company.member_a)

    async def too_slow(data, kind, *, timeout=60.0):
        raise documents.extract.ExtractionError("timeout", "simulated")

    monkeypatch.setattr(documents.extract, "extract_document", too_slow)
    body = upload(client, csrf, company.dept_a, "n.txt", samples.read_sample("note-sedinta.txt")).json()
    assert (body["status"], body["error"]) == ("failed", "timeout")


def test_a_crash_inside_extraction_still_ends_failed(env, monkeypatch, caplog):
    conn, company, client = env
    csrf = _as(client, company.member_a)

    async def broken(data, kind, *, timeout=60.0):
        raise RuntimeError("parser bug")

    monkeypatch.setattr(documents.extract, "extract_document", broken)
    body = upload(client, csrf, company.dept_a, "n.txt", samples.read_sample("note-sedinta.txt")).json()
    assert (body["status"], body["error"]) == ("failed", "invalid_file")
    assert "extraction crashed" in caplog.text


def test_admin_uploads_company_wide_documents(env):
    conn, company, client = env
    csrf = _as(client, company.admin)
    body = upload(client, csrf, "company", "politica.md", samples.read_sample("politica-concedii.md")).json()
    assert body["visibility"] == "company" and body["department_id"] is None
    assert body["department_name"] is None and body["can_publish"] is False


# ── upload refusals ──────────────────────────────────────────────────────────────────

def test_a_member_cannot_upload_company_wide(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    response = upload(client, csrf, "company", "n.txt", b"text")
    assert response.status_code == 403 and response.json()["error"] == "forbidden"
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_unknown_or_foreign_departments_are_not_found(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    for scope in (company.dept_b, 9999):
        response = upload(client, csrf, scope, "n.txt", b"text")
        assert response.status_code == 404 and response.json()["error"] == "not_found"


def test_archived_departments_take_no_uploads(env):
    conn, company, client = env
    archived = make_department(conn, "Arhivă", archived=True)
    csrf = _as(client, company.admin)
    response = upload(client, csrf, archived, "n.txt", b"text")
    assert response.status_code == 409 and response.json()["error"] == "department_archived"


REFUSED = [
    ("program.exe", b"MZ\x90\x00", "extension"),
    ("vechi.doc", b"\xd0\xcf\x11\xe0", "extension"),
    ("fara-extensie", b"text", "extension"),
    ("poza.pdf", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "content"),
    ("binar.txt", b"text\x00with\x00nul", "content"),
    ("registru.docx", samples.build_xlsx(), "content"),
    ("document.pdf.txt", samples.build_pdf(), "content"),
]


@pytest.mark.parametrize(("filename", "data", "reason"), REFUSED,
                         ids=[filename for filename, _data, _reason in REFUSED])
def test_disallowed_types_and_mismatched_content_are_415(env, filename, data, reason):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    response = upload(client, csrf, company.dept_a, filename, data)
    assert response.status_code == 415
    body = response.json()
    assert body["error"] == "unsupported_file_type" and body["reason"] == reason
    assert body["allowed"] == [".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"]
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert not os.listdir(documents.files_dir())


def test_the_size_cap_is_enforced_from_the_header_and_while_streaming(env, monkeypatch):
    conn, company, client = env
    monkeypatch.setenv("NERVA_WORKSPACE_MAX_UPLOAD_MB", "1")
    csrf = _as(client, company.member_a)
    too_big = b"a" * (1024 * 1024 + 1)
    declared = upload(client, csrf, company.dept_a, "mare.txt", too_big)
    assert declared.status_code == 413
    assert declared.json() == {"max_bytes": 1024 * 1024, "error": "file_too_large",
                               "message": "the file is larger than the upload limit"}

    def chunks():  # no Content-Length: the cap must hold while the body streams
        for _ in range(20):
            yield b"b" * 65536

    streamed = client.post(upload_url(company.dept_a, "mare.txt"), content=chunks(),
                           headers=authed(client, csrf))
    assert streamed.status_code == 413 and streamed.json()["error"] == "file_too_large"
    exactly = upload(client, csrf, company.dept_a, "limita.txt", b"c " * (512 * 1024))
    assert exactly.status_code == 201
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_a_declared_oversize_body_is_refused_before_it_is_read(env, monkeypatch):
    """The early 413 comes from Content-Length alone (review T8): the body is 10 bytes."""
    conn, company, client = env
    monkeypatch.setenv("NERVA_WORKSPACE_MAX_UPLOAD_MB", "1")
    csrf = _as(client, company.member_a)

    def tiny():
        yield b"x" * 10

    response = client.post(upload_url(company.dept_a, "declarat.txt"), content=tiny(),
                           headers={**authed(client, csrf), "Content-Length": str(1024 * 1024 + 1),
                                    "Content-Type": "text/plain"})
    assert (response.status_code, response.json()["error"]) == (413, "file_too_large")
    assert response.json()["max_bytes"] == 1024 * 1024
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


@pytest.mark.parametrize(("query", "field", "reason"), [
    ({"filename": "n.txt"}, "department_id", "required"),
    ({"department_id": "", "filename": "n.txt"}, "department_id", "required"),
    ({"department_id": "abc", "filename": "n.txt"}, "department_id", "malformed"),
    ({"department_id": "-1", "filename": "n.txt"}, "department_id", "malformed"),
    ({"department_id": "0", "filename": "n.txt"}, "department_id", "too_small"),
    ({"department_id": str(2 ** 64), "filename": "n.txt"}, "department_id", "too_large"),
    ({"department_id": "1"}, "filename", "required"),
    ({"department_id": "1", "filename": "folder/"}, "filename", "required"),
    ({"department_id": "1", "filename": "a\nb.txt"}, "filename", "control_characters"),
    ({"department_id": "1", "filename": "x" * 300 + ".txt"}, "filename", "too_long"),
    ({"department_id": "1", "filename": "n.txt", "title": "t" * 201}, "title", "too_long"),
])
def test_bad_upload_parameters_are_422_naming_the_field(env, query, field, reason):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    response = client.post("/api/workspace/documents", params=query, content=b"text",
                           headers=authed(client, csrf))
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "invalid_request"
    assert (response.json()["field"], response.json()["reason"]) == (field, reason)


def test_an_empty_body_is_422(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    response = upload(client, csrf, company.dept_a, "gol.txt", b"")
    assert response.status_code == 422
    assert (response.json()["field"], response.json()["reason"]) == ("body", "empty")


def test_uploads_need_a_session_and_the_csrf_token(env):
    conn, company, client = env
    url = upload_url(company.dept_a, "n.txt")
    assert client.post(url, content=b"x").json()["error"] == "auth_required"
    login(client, company.member_a.email)
    no_token = client.post(url, content=b"x", headers={"Origin": origin_of(client)})
    assert no_token.status_code == 403 and no_token.json()["error"] == "csrf_failed"
    cross_site = client.post(url, content=b"x", headers={"Origin": "https://evil.example"})
    assert cross_site.status_code == 403
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_the_hourly_upload_limit_answers_429_and_lifts_as_the_hour_passes(env, monkeypatch):
    conn, company, client = env
    clock = freeze_clock(monkeypatch, 1_800_000_000.0)
    monkeypatch.setattr(documents, "UPLOADS_PER_HOUR", 2)
    csrf = _as(client, company.member_a)
    text = samples.read_sample("note-sedinta.txt")
    first = upload(client, csrf, company.dept_a, "1.txt", text).json()
    clock.advance(600)
    upload(client, csrf, company.dept_a, "2.txt", text)
    assert client.delete(f"/api/workspace/documents/{first['id']}",
                         headers=authed(client, csrf)).status_code == 204  # no budget refund
    clock.advance(60)
    refused = upload(client, csrf, company.dept_a, "3.txt", text)
    assert refused.status_code == 429
    assert refused.json()["error"] == "rate_limited"
    assert refused.json()["retry_after_seconds"] == 3600 - 660
    assert refused.headers["Retry-After"] == str(3600 - 660)
    colleague = docs_client()
    colleague_csrf = _as(colleague, company.approver_a)  # a budget of their own
    assert upload(colleague, colleague_csrf, company.dept_a, "c.txt", text).status_code == 201
    clock.advance(3600 - 660 + 1)
    assert upload(client, csrf, company.dept_a, "4.txt", text).status_code == 201


def test_the_spec_limit_is_sixty_uploads_per_hour():
    assert documents.UPLOADS_PER_HOUR == 60 and documents.UPLOAD_WINDOW_SECONDS == 3600


async def test_parallel_uploads_cannot_outrun_the_limit(env, monkeypatch):
    conn, company, client = env
    monkeypatch.setattr(documents, "UPLOADS_PER_HOUR", 3)
    monkeypatch.setattr(documents, "PARALLEL_UPLOADS_PER_USER", 100)  # the hourly limit alone
    csrf = login(client, company.member_a.email)
    app = make_app(workspace_auth.router, workspace_documents.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver",
                                 cookies=client.cookies) as http:
        headers = {"X-CSRF-Token": csrf, "Origin": "http://testserver"}
        responses = await asyncio.gather(*(
            http.post(upload_url(company.dept_a, f"{n}.txt"), content=b"Text paralel " * 50,
                      headers=headers) for n in range(8)))
    codes = sorted(response.status_code for response in responses)
    assert codes == [201] * 3 + [429] * 5
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 3


# ── listing and reading ──────────────────────────────────────────────────────────────

def _upload_set(client, csrf, company) -> dict[str, dict]:
    files = {
        "note-sedinta.txt": samples.read_sample("note-sedinta.txt"),
        "politica-concedii.md": samples.read_sample("politica-concedii.md"),
        "contacte-cp1250.csv": samples.read_sample("contacte-cp1250.csv"),
    }
    return {name: upload(client, csrf, company.dept_a, name, data).json()
            for name, data in files.items()}


def test_the_list_is_newest_first_and_filters_by_status_department_and_company(env):
    conn, company, client = env
    csrf = _as(client, company.admin)
    uploaded = _upload_set(client, csrf, company)
    failed = upload(client, csrf, company.dept_b, "scan.pdf", samples.build_blank_pdf(1)).json()
    shared = upload(client, csrf, "company", "c.md", samples.read_sample("politica-concedii.md")).json()
    listed = client.get("/api/workspace/documents").json()["documents"]
    assert [doc["id"] for doc in listed] == sorted((doc["id"] for doc in
                                                    [*uploaded.values(), failed, shared]),
                                                   reverse=True)
    by_status = client.get("/api/workspace/documents", params={"status": "failed"}).json()
    assert [doc["id"] for doc in by_status["documents"]] == [failed["id"]]
    by_department = client.get("/api/workspace/documents",
                               params={"department_id": company.dept_b}).json()["documents"]
    assert [doc["id"] for doc in by_department] == [failed["id"]]
    company_only = client.get("/api/workspace/documents",
                              params={"department_id": "company"}).json()["documents"]
    assert [doc["id"] for doc in company_only] == [shared["id"]]
    assert client.get("/api/workspace/documents", params={"status": "gata"}).status_code == 422
    assert client.get("/api/workspace/documents",
                      params={"department_id": 999}).json()["error"] == "not_found"


@pytest.mark.parametrize(("query", "expected"), [
    ("sedinta", ["note-sedinta.txt"]),                     # title, without diacritics
    ("POLITICA", ["politica-concedii.md"]),
    ("Țurcanu", ["note-sedinta.txt"]),                     # text only, with diacritics
    ("turcanu bugetul", ["note-sedinta.txt"]),             # every word must be in the text
    ("turcanu concediu", []),
    ("constanța", ["contacte-cp1250.csv"]),                # cp1250 cedilla vs comma below
    ("e-Factura", ["note-sedinta.txt"]),
    ("🙂", []), ('"', []), ("de", []),
])
def test_q_matches_titles_and_text_without_caring_about_diacritics(env, query, expected):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    _upload_set(client, csrf, company)
    found = client.get("/api/workspace/documents", params={"q": query}).json()["documents"]
    assert sorted(doc["filename"] for doc in found) == sorted(expected)


def test_get_returns_the_document_with_a_preview_of_its_text(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    doc = upload(client, csrf, company.dept_a, "regulament-intern.pdf",
                 samples.read_sample("regulament-intern.pdf")).json()
    detail = client.get(f"/api/workspace/documents/{doc['id']}")
    assert detail.status_code == 200 and detail.headers["Cache-Control"] == "no-store"
    body = detail.json()
    assert {key: body[key] for key in doc} == doc
    assert body["preview"].startswith("Regulament intern - Acme SRL\nAngajații au dreptul")
    assert "Ședința anuală" in body["preview"]


def test_a_long_preview_is_cut_at_4000_chars_without_repeating_the_overlaps(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    sentences = [f"Regula {n}: fiecare angajat respectă procedura internă numărul {n}." for n in range(400)]
    text = "\n\n".join(" ".join(sentences[i:i + 4]) for i in range(0, 400, 4))
    doc = upload(client, csrf, company.dept_a, "reguli.txt", text.encode()).json()
    assert doc["chunk_count"] > 5
    preview = client.get(f"/api/workspace/documents/{doc['id']}").json()["preview"]
    assert len(preview) == documents.PREVIEW_CHARS
    assert text.startswith(preview[:-30])  # the preview is the text itself, overlaps removed


def test_a_failed_document_has_an_empty_preview(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    doc = upload(client, csrf, company.dept_a, "scan.pdf", samples.build_blank_pdf(1)).json()
    assert client.get(f"/api/workspace/documents/{doc['id']}").json()["preview"] == ""


def test_the_download_is_the_original_bytes_as_a_sandboxed_attachment(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    data = samples.build_xlsx()
    doc = upload(client, csrf, company.dept_a, "Situație vânzări.xlsx", data).json()
    response = client.get(f"/api/workspace/documents/{doc['id']}/file")
    assert response.status_code == 200 and response.content == data
    assert response.headers["Content-Type"] == doc["mime"]
    assert response.headers["Content-Disposition"] == (
        "attachment; filename=\"Situatie vanzari.xlsx\"; "
        "filename*=UTF-8''Situa%C8%9Bie%20v%C3%A2nz%C4%83ri.xlsx")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == (   # spec §6, not the code's constant
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Length"] == str(len(data))


def test_a_missing_stored_file_is_reported_not_crashed_on(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    doc = upload(client, csrf, company.dept_a, "n.txt", samples.read_sample("note-sedinta.txt")).json()
    documents.file_path(doc["id"]).unlink()
    response = client.get(f"/api/workspace/documents/{doc['id']}/file")
    assert response.status_code == 404 and response.json()["error"] == "file_missing"
    reindexed = client.post(f"/api/workspace/documents/{doc['id']}/reindex",
                            headers=authed(client, csrf)).json()
    assert (reindexed["status"], reindexed["error"], reindexed["chunk_count"]) == (
        "failed", "file_missing", 0)


@pytest.mark.parametrize("bad_id", ["0", "-3", "abc", str(2 ** 63)])
def test_document_ids_out_of_range_are_422(env, bad_id):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    for method, suffix in (("GET", ""), ("GET", "/file"), ("DELETE", ""), ("POST", "/reindex")):
        response = client.request(method, f"/api/workspace/documents/{bad_id}{suffix}",
                                  headers=authed(client, csrf))
        assert response.status_code == 422, (method, suffix)
        assert response.json()["field"] == "document_id"


def test_unknown_documents_are_404(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    for method, suffix in (("GET", ""), ("GET", "/file"), ("DELETE", ""), ("POST", "/reindex")):
        response = client.request(method, f"/api/workspace/documents/4242{suffix}",
                                  headers=authed(client, csrf))
        assert response.status_code == 404 and response.json()["error"] == "not_found"


# ── delete and re-index ──────────────────────────────────────────────────────────────

def test_delete_removes_the_row_the_chunks_the_index_entries_and_the_file(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    doc = upload(client, csrf, company.dept_a, "n.txt", samples.read_sample("note-sedinta.txt")).json()
    assert retrieval.search(conn, department_ids=[company.dept_a], include_company=False,
                            query="Țurcanu")
    response = client.delete(f"/api/workspace/documents/{doc['id']}", headers=authed(client, csrf))
    assert response.status_code == 204 and response.content == b""
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'turcanu'"
                        ).fetchone()[0] == 0
    assert not documents.file_path(doc["id"]).exists()
    assert retrieval.search(conn, department_ids=[company.dept_a], include_company=False,
                            query="Țurcanu") == []
    assert client.get(f"/api/workspace/documents/{doc['id']}").status_code == 404


def test_reindex_rebuilds_the_chunks_from_the_stored_original(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    doc = upload(client, csrf, company.dept_a, "r.pdf", samples.read_sample("regulament-intern.pdf")).json()
    with conn:  # simulate an index written by an older, worse extractor
        conn.execute("UPDATE chunks SET text = 'text vechi' WHERE document_id = ?", (doc["id"],))
    assert not retrieval.search(conn, department_ids=[company.dept_a], include_company=False,
                                query="concediu")
    response = client.post(f"/api/workspace/documents/{doc['id']}/reindex",
                           headers=authed(client, csrf))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready" and body["chunk_count"] == doc["chunk_count"]
    texts = [row[0] for row in conn.execute("SELECT text FROM chunks ORDER BY ord")]
    assert len(texts) == body["chunk_count"] and "text vechi" not in texts
    hits = retrieval.search(conn, department_ids=[company.dept_a], include_company=False,
                            query="concediu")
    assert [hit.page for hit in hits] == [1]
    assert retrieval.search(conn, department_ids=[company.dept_a], include_company=False,
                            query="vechi") == []


def test_reindex_recovers_a_document_that_failed_before(env, monkeypatch):
    conn, company, client = env
    csrf = _as(client, company.member_a)

    async def timed_out(data, kind, *, timeout=60.0):
        raise documents.extract.ExtractionError("timeout", "simulated")

    with monkeypatch.context() as patch:
        patch.setattr(documents.extract, "extract_document", timed_out)
        doc = upload(client, csrf, company.dept_a, "n.txt",
                     samples.read_sample("note-sedinta.txt")).json()
    assert doc["error"] == "timeout"
    fixed = client.post(f"/api/workspace/documents/{doc['id']}/reindex",
                        headers=authed(client, csrf)).json()
    assert (fixed["status"], fixed["error"]) == ("ready", None) and fixed["chunk_count"] >= 1


def test_reindex_refuses_while_processing_until_the_row_is_stale(env, monkeypatch):
    conn, company, client = env
    clock = freeze_clock(monkeypatch, 1_800_000_000.0)
    csrf = _as(client, company.member_a)
    doc = upload(client, csrf, company.dept_a, "n.txt", samples.read_sample("note-sedinta.txt")).json()
    with conn:
        conn.execute("UPDATE documents SET status = 'processing', updated_at = ? WHERE id = ?",
                     (clock(), doc["id"]))
    listed = client.get(f"/api/workspace/documents/{doc['id']}").json()
    assert listed["can_reindex"] is False and listed["can_delete"] is True
    busy = client.post(f"/api/workspace/documents/{doc['id']}/reindex", headers=authed(client, csrf))
    assert busy.status_code == 409 and busy.json()["error"] == "document_busy"
    clock.advance(documents.STALE_PROCESSING_SECONDS + 1)
    assert client.get(f"/api/workspace/documents/{doc['id']}").json()["can_reindex"] is True
    recovered = client.post(f"/api/workspace/documents/{doc['id']}/reindex",
                            headers=authed(client, csrf))
    assert recovered.status_code == 200 and recovered.json()["status"] == "ready"


def test_a_document_deleted_during_extraction_stays_deleted(env, monkeypatch):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    real = documents.extract.extract_document

    async def delete_meanwhile(data, kind, *, timeout=60.0):
        result = await real(data, kind)
        with conn:
            conn.execute("DELETE FROM documents")
        return result

    monkeypatch.setattr(documents.extract, "extract_document", delete_meanwhile)
    response = upload(client, csrf, company.dept_a, "n.txt", samples.read_sample("note-sedinta.txt"))
    assert response.status_code == 404 and response.json()["error"] == "not_found"
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


def test_a_storage_failure_is_507_and_leaves_nothing_behind(env, monkeypatch):
    conn, company, client = env
    csrf = _as(client, company.member_a)

    def disk_full(data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(documents, "_write_temp", disk_full)
    response = upload(client, csrf, company.dept_a, "n.txt", b"text")
    assert response.status_code == 507 and response.json()["error"] == "storage_failed"
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


# ── audit and the disabled flag ──────────────────────────────────────────────────────

def test_upload_delete_and_reindex_are_audited_without_content(env):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    doc = upload(client, csrf, company.dept_a, "note.txt", samples.read_sample("note-sedinta.txt"),
                 title="Note comitet").json()
    client.post(f"/api/workspace/documents/{doc['id']}/reindex", headers=authed(client, csrf))
    client.delete(f"/api/workspace/documents/{doc['id']}", headers=authed(client, csrf))
    rows = conn.execute("SELECT * FROM audit WHERE action LIKE 'document.%' ORDER BY id").fetchall()
    assert [row["action"] for row in rows] == ["document.uploaded", "document.reindexed",
                                               "document.deleted"]
    assert all(row["actor_user_id"] == company.member_a.id for row in rows)
    assert all(row["target_type"] == "document" and row["target_id"] == str(doc["id"])
               and row["department_id"] == company.dept_a for row in rows)
    uploaded = json.loads(rows[0]["details_json"])
    assert uploaded == {"title": "Note comitet", "filename": "note.txt", "mime": "text/plain",
                        "size_bytes": doc["size_bytes"], "visibility": "department",
                        "sha256": uploaded["sha256"]}
    assert len(uploaded["sha256"]) == 64
    everything = " ".join(row["details_json"] for row in rows)
    assert "Țurcanu" not in everything and "comitet de direcție" not in everything
    assert audit.verify_chain(conn)["ok"] is True


def test_every_route_is_404_while_the_workspace_is_disabled(env, monkeypatch):
    conn, company, client = env
    csrf = _as(client, company.member_a)
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    for method, url in (("GET", "/api/workspace/documents"),
                        ("POST", upload_url(company.dept_a, "n.txt")),
                        ("GET", "/api/workspace/documents/1"),
                        ("GET", "/api/workspace/documents/1/file"),
                        ("DELETE", "/api/workspace/documents/1"),
                        ("POST", "/api/workspace/documents/1/reindex")):
        response = client.request(method, url, content=b"x" if method == "POST" else None,
                                  headers=authed(client, csrf))
        assert response.status_code == 404 and response.json()["error"] == "workspace_disabled"
