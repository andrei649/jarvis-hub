"""No input reaches a 5xx: fuzzed query parameters, filenames and file bodies (§12 robustness).

Uploads are the one place where arbitrary bytes from a browser are parsed on the hub,
so every extension is fed seeded random bytes, truncated real files and hostile
packages; the answer is always a clean 4xx or a document marked ``failed``.
"""

from __future__ import annotations

import random
import time

import pytest

from agents.core.workspace import extract
from tests.fixtures.workspace import samples
from tests.fixtures.workspace.doc_helpers import docs_client, upload
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    authed,
    db,
    login,
    seed_company,
    ws,
)


@pytest.fixture
def member(ws):
    conn = db()
    company = seed_company(conn)
    client = docs_client()
    csrf = login(client, company.member_a.email)
    yield conn, company, client, csrf
    conn.close()


QUERY_VALUES = ["", " ", "company", "COMPANY", "0", "-1", "1.5", "1e3", "abc", "١", "²",
                str(2 ** 63), str(2 ** 63 - 1), "1 OR 1=1", "%00", "\u202e", "'", '"', "x" * 33]


@pytest.mark.parametrize("value", QUERY_VALUES)
def test_list_filters_never_crash(member, value):
    conn, company, client, csrf = member
    for params in ({"department_id": value}, {"q": value}, {"status": value},
                   {"q": value * 7, "department_id": value}):
        response = client.get("/api/workspace/documents", params=params)
        assert response.status_code < 500, (params, response.text)
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("value", QUERY_VALUES)
def test_upload_parameters_never_crash(member, value):
    conn, company, client, csrf = member
    for params in ({"department_id": value, "filename": "n.txt"},
                   {"department_id": str(company.dept_a), "filename": value},
                   {"department_id": str(company.dept_a), "filename": "n.txt", "title": value}):
        response = client.post("/api/workspace/documents", params=params, content=b"Text simplu.",
                               headers=authed(client, csrf))
        assert response.status_code < 500, (params, response.text)


def _truncations(data: bytes) -> list[bytes]:
    return [data[: len(data) * n // 5] for n in range(1, 5)]


def _hostile_bodies() -> list[tuple[str, bytes]]:
    rng = random.Random(20261017)
    real = {"pdf": samples.build_pdf(), "docx": samples.build_docx(), "xlsx": samples.build_xlsx(),
            "csv": samples.read_sample("contacte-cp1250.csv"),
            "txt": samples.read_sample("note-sedinta.txt"),
            "md": samples.read_sample("politica-concedii.md")}
    bodies: list[tuple[str, bytes]] = []
    for kind, data in real.items():
        bodies.extend((kind, cut) for cut in _truncations(data))
        bodies.append((kind, bytes(rng.randrange(256) for _ in range(2048))))
        flipped = bytearray(data)
        for _ in range(20):
            flipped[rng.randrange(len(flipped))] ^= 0xFF
        bodies.append((kind, bytes(flipped)))
    bodies.append(("pdf", b"%PDF-1.7\n" + bytes(rng.randrange(256) for _ in range(4096))))
    bodies.append(("docx", b"PK\x03\x04[Content_Types].xml word/" + b"\x00" * 512))
    bodies.append(("xlsx", samples._zip({"[Content_Types].xml": "<Types/>", "xl/x.xml": "<x/>"})))
    return bodies


HOSTILE = _hostile_bodies()


@pytest.mark.parametrize(("kind", "data"), HOSTILE,
                         ids=[f"{kind}-{n}" for n, (kind, _data) in enumerate(HOSTILE)])
def test_hostile_or_damaged_files_never_crash(member, kind, data):
    conn, company, client, csrf = member
    response = upload(client, csrf, company.dept_a, f"fisier.{kind}", data)
    assert response.status_code in (201, 413, 415, 422), response.text
    if response.status_code == 201:
        body = response.json()
        assert body["status"] in ("ready", "failed")
        assert body["error"] is None or body["error"] in extract.ERROR_CODES


def test_a_deeply_nested_docx_is_a_failed_document_not_an_error(member):
    conn, company, client, csrf = member
    depth = 4000
    body = ("<w:sdt><w:sdtContent>" * depth + samples.docx_paragraph("adânc")
            + "</w:sdtContent></w:sdt>" * depth)
    response = upload(client, csrf, company.dept_a, "adanc.docx", samples.build_docx(body))
    assert response.status_code == 201
    assert (response.json()["status"], response.json()["error"]) == ("failed", "invalid_file")


@pytest.mark.parametrize("name", ["📄 raport.txt", "Notă ședință (final) [v2].txt", "  spații .txt",
                                  "ăâîșț.md", "名前.txt", "a" * 250 + ".txt", "con.txt", "nul.txt"])
def test_unusual_but_valid_filenames_are_kept_for_display_only(member, name):
    conn, company, client, csrf = member
    response = upload(client, csrf, company.dept_a, name, "Conținut.".encode())
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["filename"] == name.strip()
    download = client.get(f"/api/workspace/documents/{document['id']}/file")
    assert download.status_code == 200 and download.content == "Conținut.".encode()
    assert download.headers["Content-Disposition"].startswith("attachment; filename=\"")


def test_a_large_spreadsheet_like_csv_is_indexed_quickly(member):
    conn, company, client, csrf = member
    rows = ["Cod;Produs;Cantitate;Depozit"] + [
        f"P{n:05d};Ţeavă de cupru {n % 40} mm;{n * 3};Depozitul {['Braşov', 'Iaşi', 'Cluj'][n % 3]}"
        for n in range(8000)]
    data = "\n".join(rows).encode("cp1250")
    started = time.monotonic()
    response = upload(client, csrf, company.dept_a, "stoc.csv", data)
    elapsed = time.monotonic() - started
    assert response.status_code == 201 and response.json()["status"] == "ready"
    assert response.json()["chunk_count"] > 100 and elapsed < 4.0
    found = client.get("/api/workspace/documents", params={"q": "P07999"}).json()["documents"]
    assert [doc["filename"] for doc in found] == ["stoc.csv"]
