"""Where Nerva Workspace keeps its data, and the owner's "forget me" (spec §3 "Data location").

The workspace lives in ``<data>/business`` (``config.DATA_DIRNAME``), a directory no other
hub module uses. It used to be ``<data>/workspace``, which is also the default root of the
owner's file tools (``JARVIS_FILE_ROOTS``), of ``JARVIS_TERMINAL_LOCAL_ROOTS`` and of the
tool-result spill directory (``workspace/tool_results``): with file tools on, the owner's
personal assistant could read the company database and documents, and keeping
``workspace`` on the forget allowlist kept the owner's spilled tool results through a
forget (BACKLOG NWS-14). These tests pin both halves of the fix:

* the workspace directory is disjoint from every one of those default roots, and no other
  module under ``agents/`` names ``business`` as a data directory;
* ``data_purge`` erases everything under the data root except its KEEP allowlist. The
  workspace holds a company's accounts, documents, reports and audit trail — other
  people's data, with its own lifecycle — so ``business`` is on that list: after a purge
  the database is intact, its full-text index still answers, and the stored files and the
  SMTP secret store are still there, while the owner's own stores — the tool-result spills
  included — are emptied.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from agents.core import data_purge, tool_result_store
from agents.core.environments import local_transport
from agents.core.file_tools import FileScope
from agents.core.workspace import audit, config, documents, mailer, retrieval
from agents.core.workspace import db as workspace_db
from tests.fixtures.workspace.doc_helpers import seed_document
from tests.support.workspace_fixtures import db, seed_company, ws  # noqa: F401  (ws is a fixture)

REPO = Path(__file__).resolve().parents[1]
POLICY = "Concediul de odihnă este de 21 de zile lucrătoare pe an pentru fiecare angajat."


def _seed_owner_store(path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE missions (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO missions (v) VALUES (?)", [("privat",), ("secret",)])
        conn.commit()
    finally:
        conn.close()


def _overlap(a: Path, b: Path) -> bool:
    """True when one directory is the other or contains it."""
    a, b = a.resolve(), b.resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _hub_default_roots(monkeypatch) -> dict[str, list[Path]]:
    """The hub's default roots that the owner's tools read or write, with no override set."""
    monkeypatch.delenv("JARVIS_FILE_ROOTS", raising=False)
    monkeypatch.delenv("JARVIS_TERMINAL_LOCAL_ROOTS", raising=False)
    return {
        "file tools (JARVIS_FILE_ROOTS)": list(FileScope.from_env().roots),
        "terminal (JARVIS_TERMINAL_LOCAL_ROOTS)": [Path(root) for root
                                                   in local_transport.default_roots()],
        "tool-result spills": [tool_result_store.default_root()],
    }


# ── the directory ────────────────────────────────────────────────────────────────────

def test_the_workspace_directory_is_disjoint_from_the_hub_default_roots(ws, monkeypatch):
    business = config.workspace_dir()
    assert config.DATA_DIRNAME == "business"
    assert business == ws.data_dir / "business"
    company_paths = [business, workspace_db.db_path(), documents.files_dir(),
                     documents.file_path(1), config.setup_code_path(),
                     mailer.secret_store().path]
    for name, roots in _hub_default_roots(monkeypatch).items():
        assert roots, name
        for root in roots:
            assert root.resolve().is_relative_to(ws.data_dir.resolve()), (name, root)
            assert not _overlap(business, root), (
                f"the workspace directory {business} overlaps the {name} root {root}")
            for path in company_paths:
                assert not path.resolve().is_relative_to(root.resolve()), (name, path)


def test_the_old_shared_directory_is_left_to_the_owners_tools(ws, monkeypatch):
    """Nothing the workspace writes lands in ``<data>/workspace`` (the owner's file root)."""
    conn = db()
    try:
        seed_company(conn)
    finally:
        conn.close()
    store = mailer.secret_store()          # the SMTP secret store writes secrets.enc
    store.set("probe", "valoare")
    monkeypatch.delenv(config.ENV_SETUP_CODE, raising=False)
    config.setup_code()                     # a generated setup code is a file too
    shared = ws.data_dir / "workspace"
    written = sorted(p.relative_to(ws.data_dir).as_posix()
                     for p in ws.data_dir.rglob("*") if p.is_file())
    assert any(name.startswith("business/") for name in written), written
    assert {"business/workspace.db", "business/secrets.enc",
            "business/setup-code.txt"} <= set(written), written
    assert not shared.exists() or not any(shared.rglob("*")), written
    store.delete("probe")


def test_no_other_hub_module_uses_the_workspace_directory_name():
    """``business`` stays the workspace's own: a data_path("business", …) elsewhere would
    reopen the collision the move closed, and data_purge must keep exactly that name."""
    pattern = re.compile(r"""data_path\(\s*["']business["']|["']business["']\s*\)\s*/|"""
                         r"""/\s*["']business["']""")
    offenders = []
    for path in (REPO / "agents").rglob("*.py"):
        if (REPO / "agents" / "core" / "workspace") in path.parents:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == []
    assert config.DATA_DIRNAME in data_purge.KEEP_DIRS
    assert "workspace" not in data_purge.KEEP_DIRS, (
        "the owner's file-tool root and tool-result spills must stay purgeable")


# ── the owner's forget ───────────────────────────────────────────────────────────────

def test_forget_keeps_the_workspace_database_its_index_and_files(ws):
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
    business = ws.data_dir / "business"
    files = business / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / f"{document_id}.bin").write_bytes(POLICY.encode("utf-8"))
    (business / "secrets.enc").write_bytes(b"\x00sealed")
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
    assert not any(name.startswith("business/") for name in swept), swept

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
    assert (business / "secrets.enc").read_bytes() == b"\x00sealed"


def test_forget_purges_the_owners_tool_result_spills_and_keeps_the_workspace(ws, monkeypatch):
    monkeypatch.delenv("JARVIS_FILE_ROOTS", raising=False)
    conn = db()
    try:
        seed_company(conn)
    finally:
        conn.close()
    spilled = tool_result_store.ToolResultStore().spill('{"rows": "rezultat privat"}',
                                                       tool="file_search")
    assert spilled is not None
    spill_file = tool_result_store.default_root() / spilled.reference
    assert spill_file.is_file()
    assert spill_file.resolve().is_relative_to((ws.data_dir / "workspace").resolve())
    owner_file = FileScope.from_env().roots[0] / "notite.txt"
    owner_file.write_text("o notiță a proprietarului", encoding="utf-8")

    report = data_purge.purge_data(source_root=str(ws.data_dir), backup_first=False)

    assert report["ok"] is True, report.get("not_erased")
    # A spill is a ``.json`` file, which the sweep empties in place rather than unlinks.
    assert f"workspace/{tool_result_store.SPILL_DIRNAME}/{spilled.reference}" in (
        report["purged"]["sweep"]["json"])
    assert "rezultat privat" not in spill_file.read_text(encoding="utf-8"), (
        "a forget must erase the owner's spilled tool results")
    assert not owner_file.exists(), "a forget must erase the owner's file-tool root"
    conn = db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 4
        assert audit.verify_chain(conn)["ok"] is True
    finally:
        conn.close()
