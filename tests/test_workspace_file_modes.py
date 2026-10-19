"""The workspace's own files are private whatever the service's umask (review OPS2-05).

``sqlite3`` creates a database ``0644 & ~umask`` and its ``-wal``/``-shm`` files copy that
mode, so under the default umask ``0022`` every local user could read ``workspace.db`` —
the pilot guide's ``UMask=0077`` drop-in was the only thing that prevented it. Now the
workspace creates the database ``0600`` itself, every file it writes is ``0600`` and every
directory ``0700``, and the first connect of each process removes group/other access left
on its directory by a restore or a copy — logging it, and never failing when the system
refuses a chmod.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

from agents.core.workspace import config, documents, mailer
from agents.core.workspace import db as workspace_db
from tests.fixtures.workspace.doc_helpers import docs_client, upload
from tests.support.workspace_fixtures import db, login, seed_company, ws  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")

POLICY = b"Concediul de odihna este de 21 de zile lucratoare pe an pentru fiecare angajat.\n"


@pytest.fixture
def permissive_umask():
    """The systemd default (0022): new files 0644, new directories 0755 unless asked."""
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture(autouse=True)
def fresh_process(monkeypatch):
    """Each test is a new hub process: no workspace directory secured yet."""
    _new_process(monkeypatch)


def _new_process(monkeypatch) -> None:
    """Forget which workspace directories this process already made private."""
    monkeypatch.setattr(workspace_db, "_secured", set(), raising=False)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _modes(directory: Path) -> dict[str, str]:
    found = {".": oct(_mode(directory))}
    for path in sorted(directory.rglob("*")):
        if not path.is_symlink():
            found[path.relative_to(directory).as_posix()] = oct(_mode(path))
    return found


def _private(modes: dict[str, str], directory: Path) -> dict[str, str]:
    """The entries of *modes* that are not 0600 files / 0700 directories."""
    wrong = {}
    for name, mode in modes.items():
        path = directory / name
        expected = oct(0o700 if path.is_dir() else 0o600)
        if mode != expected:
            wrong[name] = mode
    return wrong


def test_every_file_the_workspace_writes_is_private_under_a_permissive_umask(
        ws, permissive_umask, monkeypatch):
    conn = db()                                 # held open: the -wal/-shm files stay
    company = seed_company(conn)                # creates workspace.db and writes to it
    client = docs_client()
    csrf = login(client, company.member_a.email)
    response = upload(client, csrf, company.dept_a, "politica.txt", POLICY)
    assert response.status_code == 201, response.text
    mailer.set_password("parola-smtp")         # secrets.enc (+ its .key without a secret key)
    monkeypatch.delenv(config.ENV_SETUP_CODE, raising=False)
    config.setup_code()                         # setup-code.txt

    business = config.workspace_dir()
    modes = _modes(business)
    for name in ("workspace.db", "workspace.db-wal", "workspace.db-shm", "files",
                 f"files/{response.json()['id']}.bin", "secrets.enc", "setup-code.txt"):
        assert name in modes, (name, modes)
    assert _private(modes, business) == {}, modes
    assert _mode(documents.files_dir()) == 0o700
    conn.close()


def test_a_new_database_is_created_private_before_sqlite_opens_it(ws, permissive_umask):
    conn = workspace_db.connect()
    try:
        path = workspace_db.db_path()
        assert _mode(path) == 0o600
        with workspace_db.tx(conn):
            conn.execute("UPDATE org SET name = name")
        for sidecar in ("-wal", "-shm"):
            assert _mode(path.with_name(path.name + sidecar)) == 0o600, sidecar
    finally:
        conn.close()


def _open_up(business: Path) -> None:
    """What a restore or a copy under umask 0022 leaves: 0755 folders, 0644 files."""
    for path in [business, *business.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)


def _seed_store(business: Path, outside: Path) -> None:
    conn = workspace_db.connect()
    conn.close()
    (business / "files").mkdir(exist_ok=True)
    (business / "files" / "1.bin").write_bytes(b"original")
    (business / "secrets.enc").write_text("{}", encoding="utf-8")
    (business / "nested" / "deeper").mkdir(parents=True)
    (business / "nested" / "deeper" / "x.tmp").write_bytes(b"x")
    outside.write_text("not the workspace's", encoding="utf-8")
    outside.chmod(0o644)
    (business / "link-out").symlink_to(outside)


def test_open_modes_left_by_a_restore_are_closed_at_the_first_connect(ws, tmp_path, monkeypatch,
                                                                      caplog):
    business = config.workspace_dir()
    outside = tmp_path / "outside.txt"
    _seed_store(business, outside)
    _open_up(business)
    _new_process(monkeypatch)                   # a new process (a restart after the restore)

    with caplog.at_level(logging.WARNING, logger="nerva.workspace.db"):
        workspace_db.connect().close()
        workspace_db.connect().close()          # once per process: the second says nothing
    assert _private(_modes(business), business) == {}, _modes(business)
    assert _mode(outside) == 0o644, "a symlink is never followed"
    [warning] = [r for r in caplog.records if r.name == "nerva.workspace.db"]
    assert "private now" in warning.getMessage() and str(business) in warning.getMessage()


def test_a_chmod_the_system_refuses_is_logged_once_and_never_fails(ws, tmp_path, monkeypatch,
                                                                   caplog):
    business = config.workspace_dir()
    _seed_store(business, tmp_path / "outside.txt")
    _open_up(business)
    _new_process(monkeypatch)

    def refuse(path, mode, *args, **kwargs):
        raise PermissionError(1, "Operation not permitted", str(path))

    monkeypatch.setattr(workspace_db.os, "chmod", refuse)
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.db"):
        for _ in range(3):
            conn = workspace_db.connect()       # the database still opens and answers
            assert conn.execute("PRAGMA user_version").fetchone()[0] == \
                workspace_db.schema_version()
            conn.close()
    records = [r for r in caplog.records if r.name == "nerva.workspace.db"]
    assert len(records) == 1, [r.getMessage() for r in records]
    assert "chmod -R go-rwx" in records[0].getMessage()
    assert "PermissionError" in records[0].getMessage()


def test_the_read_only_check_changes_no_mode(ws, monkeypatch):
    """``check`` and the hub's start check open the database read-only: no chmod either."""
    workspace_db.connect().close()
    business = config.workspace_dir()
    _open_up(business)
    _new_process(monkeypatch)
    workspace_db.connect_read_only(workspace_db.existing_db_path()).close()
    assert _mode(business / "workspace.db") == 0o644
