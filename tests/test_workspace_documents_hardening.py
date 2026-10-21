"""Knowledge-base guarantees under races, storage faults and resource pressure.

Document ids are reused once the newest document is deleted (SQLite rowids), so every
write that finishes later than it started — an extraction result, a delete's file
removal — must prove it still belongs to the row it began with. Storage steps are
part of the transaction that makes a document visible, so no fault leaves a row
without its file, a file without its row, or an audit entry for an upload that never
happened. Re-indexing spends from the hourly upload budget and a user can have only a
few uploads in flight, so one account cannot monopolise extraction or memory.
"""

from __future__ import annotations

import asyncio
import io
import os
import sqlite3
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from agents.core.routers import workspace_auth, workspace_documents
from agents.core.workspace import db as workspace_db
from agents.core.workspace import documents, extract, identity
from agents.core.workspace.errors import WorkspaceError
from tests.fixtures.workspace import samples
from tests.fixtures.workspace.doc_helpers import docs_client, upload, upload_url
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    authed,
    db,
    freeze_clock,
    login,
    make_app,
    seed_company,
    ws,
)

SECRET_B = "Salariul directorului de resurse umane: 42.000 lei pe lună."
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(ws):
    conn = db()
    company = seed_company(conn)
    client = docs_client()
    yield conn, company, client
    conn.close()


def _count(conn: sqlite3.Connection, sql: str, *params: object) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _store_listing() -> list[str]:
    return sorted(os.listdir(documents.files_dir()))


def _failing_commit(real_tx):
    """A ``db.tx`` whose commit fails (the body runs, then everything rolls back)."""
    @contextmanager
    def tx(conn):
        with real_tx(conn):
            yield conn
            raise sqlite3.OperationalError("disk I/O error")
    return tx


# ── late results and reused ids ──────────────────────────────────────────────────────

def test_a_late_extraction_never_lands_on_a_newer_document_with_the_same_id(env, monkeypatch):
    conn, company, client = env
    clock = freeze_clock(monkeypatch, 1_800_000_000.0)
    csrf = login(client, company.member_b.email)
    real = documents.extract.extract_document

    async def deleted_and_reused_meanwhile(data, kind, *, timeout=60.0):
        result = await real(data, kind)
        row = conn.execute("SELECT id FROM documents").fetchone()
        stamp = clock.advance(5)
        conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
        conn.execute(  # another department's upload takes the freed id and is processing
            "INSERT INTO documents (id, department_id, visibility, title, filename, mime, "
            "size_bytes, sha256, uploader_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'department', 'Ofertă', 'oferta.txt', 'text/plain', 6, ?, ?, "
            "'processing', ?, ?)",
            (row["id"], company.dept_a, "1" * 64, company.member_a.id, stamp, stamp))
        return result

    monkeypatch.setattr(documents.extract, "extract_document", deleted_and_reused_meanwhile)
    response = upload(client, csrf, company.dept_b, "salarii.txt", SECRET_B.encode())
    assert response.status_code == 404  # its own row is gone
    row = conn.execute("SELECT department_id, status, chunk_count FROM documents").fetchone()
    assert (row["department_id"], row["status"], row["chunk_count"]) == (company.dept_a,
                                                                        "processing", 0)
    assert _count(conn, "SELECT COUNT(*) FROM chunks") == 0
    assert documents.retrieval.search(conn, department_ids=[company.dept_a],
                                      include_company=False, query="salariul directorului") == []


def test_a_reindex_never_answers_with_or_writes_onto_a_newer_document(env, monkeypatch):
    conn, company, client = env
    clock = freeze_clock(monkeypatch, 1_800_000_000.0)
    csrf = login(client, company.member_b.email)
    doc = upload(client, csrf, company.dept_b, "salarii.txt", SECRET_B.encode()).json()
    clock.advance(30)
    real = documents.extract.extract_document

    async def deleted_and_reused_meanwhile(data, kind, *, timeout=60.0):
        result = await real(data, kind)
        stamp = clock.advance(5)
        conn.execute("DELETE FROM documents WHERE id = ?", (doc["id"],))
        conn.execute(
            "INSERT INTO documents (id, department_id, visibility, title, filename, mime, "
            "size_bytes, sha256, uploader_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'department', 'Ofertă', 'oferta.txt', 'text/plain', 6, ?, ?, "
            "'processing', ?, ?)",
            (doc["id"], company.dept_a, "1" * 64, company.member_a.id, stamp, stamp))
        return result

    monkeypatch.setattr(documents.extract, "extract_document", deleted_and_reused_meanwhile)
    response = client.post(f"/api/workspace/documents/{doc['id']}/reindex",
                           headers=authed(client, csrf))
    assert response.status_code == 404 and "Ofertă" not in response.text
    row = conn.execute("SELECT department_id, status FROM documents").fetchone()
    assert (row["department_id"], row["status"]) == (company.dept_a, "processing")
    assert _count(conn, "SELECT COUNT(*) FROM chunks") == 0


def test_a_download_never_streams_a_newer_document_that_took_the_id(env, monkeypatch):
    conn, company, client = env
    csrf = login(client, company.member_b.email)
    doc = upload(client, csrf, company.dept_b, "plan.txt", b"Planul public al echipei.").json()
    real_visible = documents.visible_document

    def swapped_right_after_the_check(c, user, document_id):
        row = real_visible(c, user, document_id)
        stamp = row["created_at"] + 60
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.execute(
            "INSERT INTO documents (id, department_id, visibility, title, filename, mime, "
            "size_bytes, sha256, uploader_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'department', 'Salarii', 'salarii.txt', 'text/plain', 9, ?, ?, "
            "'ready', ?, ?)",
            (document_id, company.dept_a, "3" * 64, company.member_a.id, stamp, stamp))
        documents.file_path(document_id).write_bytes(SECRET_B.encode())
        return row

    monkeypatch.setattr(documents, "visible_document", swapped_right_after_the_check)
    response = client.get(f"/api/workspace/documents/{doc['id']}/file")
    assert response.status_code == 404 and response.json()["error"] == "not_found"
    assert SECRET_B.encode() not in response.content


def test_a_result_for_an_older_claim_is_never_written(env):
    conn, company, client = env
    csrf = login(client, company.member_a.email)
    doc = upload(client, csrf, company.dept_a, "n.txt", samples.read_sample("note-sedinta.txt")).json()
    old_claim = conn.execute("SELECT updated_at FROM documents WHERE id = ?",
                             (doc["id"],)).fetchone()[0]
    new_claim = old_claim + 1.5
    conn.execute("UPDATE documents SET status = 'processing', updated_at = ? WHERE id = ?",
                 (new_claim, doc["id"]))  # a later re-index claimed the row
    stale = extract.extract_bytes(b"Un text vechi, complet diferit.", "txt")
    documents._store_success(doc["id"], old_claim, stale)
    documents._store_failure(doc["id"], old_claim, "timeout", None)
    row = conn.execute("SELECT status, error, updated_at FROM documents WHERE id = ?",
                       (doc["id"],)).fetchone()
    assert (row["status"], row["error"], row["updated_at"]) == ("processing", None, new_claim)
    texts = [r[0] for r in conn.execute("SELECT text FROM chunks WHERE document_id = ?",
                                        (doc["id"],))]
    assert texts and not any("vechi" in text for text in texts)
    documents._store_success(doc["id"], new_claim, stale)  # the current claim applies
    assert conn.execute("SELECT status FROM documents WHERE id = ?",
                        (doc["id"],)).fetchone()[0] == "ready"


# ── storage steps are part of the transaction ────────────────────────────────────────

def test_a_failed_move_into_the_store_commits_nothing(env, monkeypatch):
    conn, company, client = env
    csrf = login(client, company.member_a.email)
    real_replace = os.replace

    def refuse_store(src, dst, *args, **kwargs):
        if str(dst).endswith(".bin"):
            raise PermissionError(13, "Permission denied")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(documents.os, "replace", refuse_store)
    response = upload(client, csrf, company.dept_a, "n.txt", b"Text de pastrat.")
    assert response.status_code == 507 and response.json()["error"] == "storage_failed"
    assert _count(conn, "SELECT COUNT(*) FROM documents") == 0
    assert _count(conn, "SELECT COUNT(*) FROM audit WHERE action = 'document.uploaded'") == 0
    assert _store_listing() == []  # the temporary copy is gone too


def test_a_commit_failure_after_the_move_leaves_no_stored_file(env, monkeypatch):
    conn, company, _client = env
    user = identity.get_user(conn, company.member_a.id)
    temp = documents._write_temp(b"Text")
    pending = documents._Upload(department_id=company.dept_a, visibility="department",
                                title="t", filename="t.txt", kind="txt", size=4,
                                sha256="0" * 64)
    monkeypatch.setattr(documents.db, "tx", _failing_commit(workspace_db.tx))
    with pytest.raises(sqlite3.OperationalError):
        documents._reserve(conn, user, pending, temp, "")
    assert _count(conn, "SELECT COUNT(*) FROM documents") == 0
    assert _store_listing() == []


def test_delete_takes_the_file_away_before_its_transaction_commits(env, monkeypatch):
    conn, company, client = env
    csrf = login(client, company.member_a.email)
    doc = upload(client, csrf, company.dept_a, "n.txt", samples.read_sample("note-sedinta.txt")).json()
    user = identity.get_user(conn, company.member_a.id)
    real_tx = workspace_db.tx
    file_there_at_commit: list[bool] = []

    @contextmanager
    def watching(c):
        with real_tx(c):
            yield c
            file_there_at_commit.append(documents.file_path(doc["id"]).exists())

    monkeypatch.setattr(documents.db, "tx", watching)
    documents.delete_document(conn, user, doc["id"], ip="")
    # A new upload may reuse the id right after the commit; its file must be safe.
    assert file_there_at_commit == [False]
    assert _store_listing() == []


def test_a_failed_delete_keeps_the_row_and_puts_the_file_back(env, monkeypatch):
    conn, company, client = env
    csrf = login(client, company.member_a.email)
    data = samples.read_sample("note-sedinta.txt")
    doc = upload(client, csrf, company.dept_a, "n.txt", data).json()
    user = identity.get_user(conn, company.member_a.id)
    monkeypatch.setattr(documents.db, "tx", _failing_commit(workspace_db.tx))
    with pytest.raises(sqlite3.OperationalError):
        documents.delete_document(conn, user, doc["id"], ip="")
    assert _count(conn, "SELECT COUNT(*) FROM documents WHERE id = ?", doc["id"]) == 1
    assert documents.file_path(doc["id"]).read_bytes() == data
    assert _store_listing() == [f"{doc['id']}.bin"]


def test_a_second_concurrent_delete_is_404_and_audits_nothing(env, monkeypatch):
    conn, company, client = env
    csrf = login(client, company.member_a.email)
    doc = upload(client, csrf, company.dept_a, "n.txt", b"Text").json()
    user = identity.get_user(conn, company.member_a.id)
    row_read_by_both = documents.visible_document(conn, user, doc["id"])
    documents.delete_document(conn, user, doc["id"], ip="")
    monkeypatch.setattr(documents, "visible_document", lambda *_args: row_read_by_both)
    with pytest.raises(WorkspaceError) as caught:
        documents.delete_document(conn, user, doc["id"], ip="")
    assert (caught.value.status, caught.value.code) == (404, "not_found")
    assert _count(conn, "SELECT COUNT(*) FROM audit WHERE action = 'document.deleted'") == 1


def test_an_unreadable_stored_file_is_file_missing_not_a_crash(env):
    conn, company, client = env
    csrf = login(client, company.member_a.email)
    doc = upload(client, csrf, company.dept_a, "n.txt", b"Text").json()
    stored = documents.file_path(doc["id"])
    stored.unlink()
    stored.mkdir()  # something that is not a readable file sits in its place
    response = client.get(f"/api/workspace/documents/{doc['id']}/file")
    assert response.status_code == 404 and response.json()["error"] == "file_missing"


# ── throttling and resource bounds ───────────────────────────────────────────────────

def test_reindexing_spends_from_the_hourly_upload_budget(env, monkeypatch):
    conn, company, client = env
    clock = freeze_clock(monkeypatch, 1_800_000_000.0)
    monkeypatch.setattr(documents, "UPLOADS_PER_HOUR", 2)
    csrf = login(client, company.member_a.email)
    text = samples.read_sample("note-sedinta.txt")
    doc = upload(client, csrf, company.dept_a, "n.txt", text).json()
    url = f"/api/workspace/documents/{doc['id']}/reindex"
    clock.advance(10)
    assert client.post(url, headers=authed(client, csrf)).status_code == 200
    clock.advance(10)
    refused = client.post(url, headers=authed(client, csrf))
    assert refused.status_code == 429 and refused.json()["error"] == "rate_limited"
    assert refused.json()["retry_after_seconds"] == 3600 - 20
    assert refused.headers["Retry-After"] == str(3600 - 20)
    assert client.get(f"/api/workspace/documents/{doc['id']}").json()["status"] == "ready"
    assert _count(conn, "SELECT COUNT(*) FROM audit WHERE action = 'document.reindexed'") == 1
    assert upload(client, csrf, company.dept_a, "m.txt", text).status_code == 429
    clock.advance(3600 - 20 + 1)
    assert client.post(url, headers=authed(client, csrf)).status_code == 200


async def test_a_user_can_have_only_a_few_uploads_in_flight(env, monkeypatch):
    conn, company, client = env
    monkeypatch.setattr(documents, "PARALLEL_UPLOADS_PER_USER", 2)
    member_csrf = login(client, company.member_a.email)
    colleague = docs_client()
    colleague_csrf = login(colleague, company.approver_a.email)
    release = asyncio.Event()
    real = documents.extract.extract_document

    async def held(data, kind, *, timeout=60.0):
        await release.wait()
        return await real(data, kind)

    monkeypatch.setattr(documents.extract, "extract_document", held)
    app = make_app(workspace_auth.router, workspace_documents.router)

    def session(cookies, csrf):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver", cookies=cookies,
                                 headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"})

    async def holding(user_id: int, count: int) -> None:
        for _ in range(500):
            if documents._in_flight.get(user_id) == count:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the uploads never reached extraction")

    async with session(client.cookies, member_csrf) as member, \
            session(colleague.cookies, colleague_csrf) as other:
        def send(http, name):
            return http.post(upload_url(company.dept_a, name), content=b"Text paralel " * 20)

        running = [asyncio.ensure_future(send(member, f"{n}.txt")) for n in range(2)]
        await holding(company.member_a.id, 2)
        refused = await send(member, "3.txt")
        own_slot = asyncio.ensure_future(send(other, "coleg.txt"))  # a budget of their own
        await holding(company.approver_a.id, 1)
        release.set()
        finished = await asyncio.gather(*running, own_slot)
        after = await send(member, "4.txt")
    assert refused.status_code == 429 and refused.json()["error"] == "rate_limited"
    assert refused.json()["retry_after_seconds"] == documents.PARALLEL_RETRY_SECONDS
    assert [response.status_code for response in finished] == [201, 201, 201]
    assert after.status_code == 201
    assert documents._in_flight == {}
    ids = [row[0] for row in conn.execute("SELECT id FROM documents ORDER BY id")]
    assert len(ids) == 4 and _store_listing() == sorted(f"{doc_id}.bin" for doc_id in ids)


async def test_a_client_that_disconnects_mid_upload_gets_upload_interrupted(env):
    conn, company, _client = env
    user = identity.get_user(conn, company.member_a.id)
    messages = [{"type": "http.request", "body": b"Text partial ", "more_body": True},
                {"type": "http.disconnect"}]

    async def receive():
        return messages.pop(0)

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [],
                       "query_string": b""}, receive)
    with pytest.raises(WorkspaceError) as caught:
        await documents.upload_document(conn, request, user, scope=company.dept_a,
                                        filename="n.txt", title=None, ip="")
    assert (caught.value.status, caught.value.code) == (400, "upload_interrupted")
    assert _count(conn, "SELECT COUNT(*) FROM documents") == 0
    assert _store_listing() == [] and documents._in_flight == {}


# ── linear-time text handling (a regex holds the GIL: a slow one freezes the hub) ────

def _seconds(action) -> float:
    started = time.monotonic()
    action()
    return time.monotonic() - started


def test_long_runs_of_blanks_are_cleaned_in_linear_time():
    # Quadratic backtracking would need minutes here; linear work takes milliseconds.
    for text in ("\t" * 200_000 + "x", " " * 200_000 + "x", "a" + " \t" * 100_000 + "x"):
        assert _seconds(lambda text=text: extract.clean_text(text)) < 1.5
    assert extract.clean_text("Linia unu  \t\nLinia doi\t \n\n\n  ultima  \t") == \
        "Linia unu\nLinia doi\n\n  ultima"


def test_a_document_that_is_one_giant_word_is_chunked_in_linear_time():
    word = "x" * extract.MAX_TEXT_CHARS  # e.g. an inlined base64 blob
    chunks: list = []
    elapsed = _seconds(lambda: chunks.extend(documents.chunk_segments(
        [extract.Segment(None, word)])))
    assert elapsed < 2.0  # re-slicing the rest at every cut took ~5 s here
    assert len(chunks) == extract.MAX_TEXT_CHARS // documents.CHUNK_TARGET
    assert {len(chunk.text) for chunk in chunks} == {documents.CHUNK_TARGET}


def test_csv_sniffing_sees_only_a_small_sample_and_stays_fast():
    for hostile in ('"\n' * 200_000, "'\n" * 200_000, ',"' * 200_000):
        assert _seconds(lambda hostile=hostile: extract.sniff_delimiter(hostile)) < 1.0
    wide = "\n".join(";".join(f"coloana {row}-{col} cu text" for col in range(14))
                     for row in range(60))
    assert len(wide) > 16_000 and extract.sniff_delimiter(wide) == ";"


def test_an_oversized_number_format_code_is_cut_not_parsed_in_full():
    styles = (f'<styleSheet xmlns="{samples.S_NS}"><numFmts>'
              f'<numFmt numFmtId="170" formatCode="{"[" * 200_000}dd/mm/yyyy"/></numFmts>'
              '<cellXfs><xf numFmtId="0"/><xf numFmtId="170"/></cellXfs></styleSheet>')
    workbook = samples.build_xlsx({"Foaie": [["Valoare"], [46113]]})
    parts = _replace_part(workbook, "xl/styles.xml", styles, sheet_style=1)
    started = time.monotonic()
    text = extract.extract_bytes(parts, "xlsx").segments[0].text
    assert time.monotonic() - started < 2.0
    assert text.endswith("| 46113 |")  # the cut code carries no date pattern any more


def _replace_part(package: bytes, name: str, content: str, *, sheet_style: int) -> bytes:
    """*package* (a sample workbook) with *name* replaced and every number cell styled."""
    with zipfile.ZipFile(io.BytesIO(package)) as source:
        parts: dict[str, str | bytes] = {item: source.read(item) for item in source.namelist()}
    parts[name] = content
    sheet = parts["xl/worksheets/sheet1.xml"].decode("utf-8")
    parts["xl/worksheets/sheet1.xml"] = sheet.replace("<c r=\"A2\">",
                                                      f'<c r="A2" s="{sheet_style}">')
    return samples._zip(parts)


# ── source hygiene ───────────────────────────────────────────────────────────────────

#: Characters editors and diff tools hide or treat as line breaks; written as escapes.
_INVISIBLE = {0x00A0, 0x00AD, 0x200B, 0x200E, 0x200F, 0x2028, 0x2029, 0x202A, 0x202B,
              0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF, 0xFFFD}


def _knowledge_base_sources() -> list[Path]:
    product = [REPO / "agents/core/workspace" / name
               for name in ("extract.py", "documents.py", "retrieval.py")]
    product.append(REPO / "agents/core/routers/workspace_documents.py")
    tests = sorted((REPO / "tests").glob("test_workspace_documents*.py"))
    tests += sorted((REPO / "tests").glob("test_workspace_retrieval*.py"))
    fixtures = sorted((REPO / "tests/fixtures/workspace").glob("*.py"))
    return product + tests + fixtures


def test_the_knowledge_base_sources_hold_no_raw_invisible_characters():
    found = {}
    for path in _knowledge_base_sources():
        text = path.read_text(encoding="utf-8")
        bad = sorted({f"U+{ord(ch):04X}" for ch in text
                      if ord(ch) in _INVISIBLE or (ord(ch) < 0x20 and ch not in "\n\t")
                      or 0x7F <= ord(ch) <= 0x9F})
        if bad:
            found[path.name] = bad
    assert found == {}
