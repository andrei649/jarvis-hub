"""The owner's "forget me" purge never touches Nerva Workspace (spec §3 "Data location").

``data_purge`` erases everything under the data root except its KEEP allowlist. The
workspace directory holds a company's accounts, documents, reports and audit trail —
other people's data, with its own lifecycle — so it is on that list: after a purge the
database is intact, its full-text index still answers, and the stored files and the
SMTP secret store are still there, while the owner's own stores are emptied.
"""

from __future__ import annotations

import sqlite3

from agents.core import data_purge
from agents.core.workspace import audit, retrieval
from agents.core.workspace import db as workspace_db
from tests.fixtures.workspace.doc_helpers import seed_document
from tests.support.workspace_fixtures import db, seed_company, ws  # noqa: F401  (ws is a fixture)

POLICY = "Concediul de odihnă este de 21 de zile lucrătoare pe an pentru fiecare angajat."


def _seed_owner_store(path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE missions (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO missions (v) VALUES (?)", [("privat",), ("secret",)])
        conn.commit()
    finally:
        conn.close()


def test_forget_keeps_the_workspace_database_its_index_and_files(ws):
    assert "workspace" in data_purge.KEEP_DIRS
    conn = db()
    company = seed_company(conn)
    document_id = seed_document(conn, department_id=company.dept_a,
                                uploader_id=company.member_a.id, title="Concediu",
                                chunks=[POLICY])
    with workspace_db.tx(conn):
        audit.record(conn, actor=company.admin, action="document.uploaded",
                     target_type="document", target_id=document_id,
                     department_id=company.dept_a)
    conn.close()
    files = ws.data_dir / "workspace" / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / f"{document_id}.bin").write_bytes(POLICY.encode("utf-8"))
    (ws.data_dir / "workspace" / "secrets.enc").write_bytes(b"\x00sealed")
    _seed_owner_store(ws.data_dir / "missions.db")

    report = data_purge.purge_data(source_root=str(ws.data_dir), backup_first=False,
                                   memory=True)

    assert report["ok"] is True, report.get("not_erased")
    owner = sqlite3.connect(str(ws.data_dir / "missions.db"))
    try:
        assert owner.execute("SELECT COUNT(*) FROM missions").fetchone()[0] == 0
    finally:
        owner.close()
    swept = set(report["purged"]["sweep"]["dbs"]) | set(report["purged"]["sweep"]["files"])
    assert not any(name.startswith("workspace/") for name in swept), swept

    conn = db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1
        hits = retrieval.search(conn, department_ids=[company.dept_a], include_company=True,
                                query="câte zile de concediu")
        assert [hit.document_id for hit in hits] == [document_id]
        assert audit.verify_chain(conn)["ok"] is True
    finally:
        conn.close()
    assert (files / f"{document_id}.bin").read_bytes() == POLICY.encode("utf-8")
    assert (ws.data_dir / "workspace" / "secrets.enc").read_bytes() == b"\x00sealed"
