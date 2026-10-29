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
import shutil
import stat
import tempfile
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
def every_log_level(caplog):
    """Capture every level, as once the hub's ``setup_logging`` ran earlier in the process.

    Importing ``agents.web`` sets the root logger to INFO, so whether the database's INFO
    lines reach ``caplog.records`` used to depend on which test ran first (REV-POLISH-01);
    starting every test here from the most verbose state makes the result order-free.
    """
    caplog.set_level(logging.DEBUG)


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
    mailer.secret_store().set(mailer.CREDENTIAL_NAME, "parola-smtp")   # secrets.enc (+ .key)
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


def test_every_name_the_workspace_writes_is_one_of_its_own_entries(ws, monkeypatch):
    """The list a shared link target is judged by (review SEC-EDGE-1) is the code's own: every
    name the workspace really writes under ``business/`` — and under ``files/`` — passes it,
    and names the workspace never writes do not."""
    conn = db()
    company = seed_company(conn)
    client = docs_client()
    csrf = login(client, company.member_a.email)
    kept = upload(client, csrf, company.dept_a, "politica.txt", POLICY)
    gone = upload(client, csrf, company.dept_a, "vechi.txt", POLICY + b"Versiunea veche.\n")
    assert kept.status_code == gone.status_code == 201
    assert client.delete(f"/api/workspace/documents/{gone.json()['id']}",
                         headers={"X-CSRF-Token": csrf}).status_code in (200, 204)
    mailer.secret_store().set(mailer.CREDENTIAL_NAME, "parola-smtp")
    monkeypatch.delenv(config.ENV_SETUP_CODE, raising=False)
    config.setup_code()
    business = config.workspace_dir()
    names = sorted(path.name for path in business.iterdir())
    assert {"workspace.db", "files", "secrets.enc", "setup-code.txt"} <= set(names), names
    assert [name for name in names if not workspace_db.own_entry(name)] == [], names
    stored = sorted(path.name for path in documents.files_dir().iterdir())
    assert stored and [n for n in stored if not workspace_db._own_stored_file(n)] == [], stored
    for name in ("workspace.db-wal", "workspace.db-journal", "secrets.enc.salt", "secrets.enc.key",
                 "secrets.enc.a1b2c3d4.tmp", ".setup-code.txt.x9y8z7w6"):
        assert workspace_db.own_entry(name), name
    for name in ("photos", "notes.txt", "files.zip", "workspace.dbx", "secrets.encrypted",
                 "lost+found", ".DS_Store", "setup-code.txt.bak"):
        assert not workspace_db.own_entry(name), name
    for name in ("12.bin", ".upload-k3j.tmp", ".deleted-12.tmp"):
        assert workspace_db._own_stored_file(name), name
    for name in ("readme.txt", "12.bin.bak", "x.bin", ".deleted-x.tmp"):
        assert not workspace_db._own_stored_file(name), name
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


def _db_warnings(caplog) -> list[logging.LogRecord]:
    """The database module's WARNING lines only (review REV-POLISH-01).

    ``caplog.records`` holds every record at the root logger's level: after an earlier test
    in the process ran the hub's ``setup_logging`` (root at INFO) — or under
    ``--log-level=INFO`` — that includes the ``migrated to schema 1`` INFO line.
    """
    return [r for r in caplog.records
            if r.name == "nerva.workspace.db" and r.levelno >= logging.WARNING]


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
    [warning] = _db_warnings(caplog)
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
    records = _db_warnings(caplog)
    assert len(records) == 1, [r.getMessage() for r in records]
    assert "chmod -R go-rwx" in records[0].getMessage()
    assert "PermissionError" in records[0].getMessage()


def _seed_own_store(business: Path, outside: Path) -> None:
    """What a folder of the workspace's own holds: only the workspace's entries (§13)."""
    conn = workspace_db.connect()
    conn.close()
    (business / "files").mkdir(exist_ok=True)
    (business / "files" / "1.bin").write_bytes(b"original")
    (business / "files" / ".upload-ab12.tmp").write_bytes(b"half")
    (business / "secrets.enc").write_text("{}", encoding="utf-8")
    (business / "secrets.enc.salt").write_bytes(b"salt")
    (business / "setup-code.txt").write_text("cod", encoding="utf-8")
    outside.write_text("not the workspace's", encoding="utf-8")
    outside.chmod(0o644)
    (business / "files" / "link-out").symlink_to(outside)


def test_a_business_folder_that_is_a_link_is_made_private_where_it_points(
        ws, tmp_path, monkeypatch, caplog):
    """``<data>/business`` → ``/disk2/business`` (review REV-POLISH-02).

    The sweep used to return at once for a ``business/`` that is a symlink: a restore's
    ``0644`` database and ``0755`` folders stayed readable by every local user, silently.
    The folder holds only the workspace's own entries (a folder of its own, PILOT_GUIDE §13),
    so all of it is walked; a link into a shared folder is the next tests' case.
    """
    real = tmp_path / "disk2" / "business"
    real.mkdir(parents=True)
    business = ws.data_dir / config.DATA_DIRNAME
    business.symlink_to(real, target_is_directory=True)
    outside = tmp_path / "outside.txt"
    _seed_own_store(business, outside)          # its connect already made `real` (0755) 0700
    _open_up(real)
    _new_process(monkeypatch)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="nerva.workspace.db"):
        workspace_db.connect().close()
        workspace_db.connect().close()
    assert _private(_modes(real), real) == {}, _modes(real)
    assert _mode(outside) == 0o644, "below the folder a symlink is never followed"
    [warning] = _db_warnings(caplog)
    assert "private now" in warning.getMessage()
    assert f"{business} → {real}" in warning.getMessage()


def _shared_folder(tmp_path: Path) -> tuple[Path, dict[str, int]]:
    """``/mnt/disc2``: a mount root holding other people's data, owned by the same user."""
    shared = tmp_path / "mnt" / "disc2"
    (shared / "photos" / "2026").mkdir(parents=True)
    (shared / "photos" / "2026" / "a.jpg").write_bytes(b"jpeg")
    (shared / "notes.txt").write_text("someone else's notes", encoding="utf-8")
    (shared / "files").mkdir()                  # a folder named like the workspace's store
    (shared / "files" / "readme.txt").write_text("someone else's", encoding="utf-8")
    foreign = {"photos": 0o755, "photos/2026": 0o755, "photos/2026/a.jpg": 0o644,
               "notes.txt": 0o664, "files/readme.txt": 0o644}
    shared.chmod(0o755)
    for name, mode in foreign.items():
        (shared / name).chmod(mode)
    return shared, foreign


def _modes_of(root: Path, names) -> dict[str, int]:
    return {name: _mode(root / name) for name in names}


@pytest.mark.parametrize("foreign", [
    "workspace.db-backup", "workspace.db-wal.old", "secrets.enc.backup",
    "secrets.enc.salt.backup", "secrets.enc.a1b2.tmp", ".setup-code.txt.notes",
])
def test_shared_store_keeps_foreign_prefix_siblings_unchanged(tmp_path, foreign):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    other = shared / foreign
    other.write_bytes(b"other application's data")
    other.chmod(0o664)
    own = shared / "workspace.db-wal"
    own.write_bytes(b"workspace sidecar")
    own.chmod(0o644)
    business = tmp_path / "business"
    business.symlink_to(shared, target_is_directory=True)

    workspace_db.secure_storage(business)

    assert _mode(shared) == 0o755
    assert _mode(other) == 0o664
    assert other.read_bytes() == b"other application's data"
    assert _mode(own) == 0o600


def test_shared_store_tightens_real_secret_and_setup_temporary_names(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "foreign.txt").write_bytes(b"foreign")
    temporary = []
    for prefix, suffix in (("secrets.enc.", ".tmp"), (".setup-code.txt.", "")):
        fd, name = tempfile.mkstemp(dir=shared, prefix=prefix, suffix=suffix)
        os.close(fd)
        path = Path(name)
        path.chmod(0o644)
        temporary.append(path)
    business = tmp_path / "business"
    business.symlink_to(shared, target_is_directory=True)

    workspace_db.secure_storage(business)

    assert [_mode(path) for path in temporary] == [0o600, 0o600]


def test_a_business_link_to_a_shared_folder_changes_only_the_workspaces_own_entries(
        ws, tmp_path, monkeypatch, caplog):
    """``business`` → ``/mnt/disc2`` (review SEC-EDGE-1): only the workspace's entries there.

    The whole target used to be walked, removing group/other access from every file the
    service user owns in it — and a refused chmod advised ``chmod -R`` on all of it. Now the
    folder, its other entries and the other files in a ``files/`` it shares keep their modes,
    across restarts too (from the second start on the folder holds ``workspace.db``).
    """
    shared, foreign = _shared_folder(tmp_path)
    business = ws.data_dir / config.DATA_DIRNAME
    business.symlink_to(shared, target_is_directory=True)
    for start in range(2):                      # the first start, then a restart
        _new_process(monkeypatch)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="nerva.workspace.db"):
            conn = workspace_db.connect()
            conn.close()
            workspace_db.connect().close()      # once per process
        assert _modes_of(shared, foreign) == foreign, start
        assert _mode(shared) == 0o755 and _mode(shared / "files") == 0o755, start
        warnings = [r.getMessage() for r in _db_warnings(caplog)]
        shared_lines = [m for m in warnings if "not the workspace's" in m]
        assert len(shared_lines) == 1, warnings
        assert str(shared) in shared_lines[0] and "PILOT_GUIDE §13" in shared_lines[0]
        assert "files, notes.txt, photos" not in shared_lines[0], "files/ is the workspace's"
        assert "notes.txt, photos" in shared_lines[0]
        # What the workspace wrote there is private all the same.
        (shared / "files" / "7.bin").write_bytes(b"document")
        (shared / "secrets.enc").write_text("{}", encoding="utf-8")
        for own in ("workspace.db", "files/7.bin", "secrets.enc"):
            (shared / own).chmod(0o644)
        _new_process(monkeypatch)
        workspace_db.connect().close()
        assert _modes_of(shared, ("workspace.db", "files/7.bin", "secrets.enc")) == {
            "workspace.db": 0o600, "files/7.bin": 0o600, "secrets.enc": 0o600}, start
        assert _modes_of(shared, foreign) == foreign, start


def test_a_files_folder_of_its_own_in_a_shared_folder_is_made_private(ws, tmp_path,
                                                                      monkeypatch):
    shared, foreign = _shared_folder(tmp_path)
    (shared / "files" / "readme.txt").unlink()
    del foreign["files/readme.txt"]
    (shared / "files" / "3.bin").write_bytes(b"document")
    (shared / "files" / "3.bin").chmod(0o644)
    (ws.data_dir / config.DATA_DIRNAME).symlink_to(shared, target_is_directory=True)
    workspace_db.connect().close()
    assert _mode(shared / "files") == 0o700 and _mode(shared / "files" / "3.bin") == 0o600
    assert _modes_of(shared, foreign) == foreign and _mode(shared) == 0o755


@pytest.mark.parametrize("others_there", [False, True], ids=["only-stored-files", "with-others"])
def test_a_files_link_in_a_shared_folder_is_never_followed(ws, tmp_path, monkeypatch,
                                                           others_there):
    """Review R4-06: ``files`` in a shared link target is itself a link to a folder elsewhere.

    That folder is not the workspace's: walking it (or tightening the stored-looking files in
    it) would make private whatever another user keeps there. The link is left as it is, and
    so is everything behind it — whether it holds only ``<id>.bin`` names or other files too.
    """
    shared, foreign = _shared_folder(tmp_path)
    shutil.rmtree(shared / "files")
    del foreign["files/readme.txt"]
    elsewhere = tmp_path / "foreign"
    elsewhere.mkdir()
    (elsewhere / "9.bin").write_bytes(b"someone else's")
    behind = {"9.bin": 0o644}
    if others_there:
        (elsewhere / "readme.txt").write_text("someone else's", encoding="utf-8")
        behind["readme.txt"] = 0o644
    for name, mode in behind.items():
        (elsewhere / name).chmod(mode)
    elsewhere.chmod(0o755)
    (shared / "files").symlink_to(elsewhere, target_is_directory=True)
    (ws.data_dir / config.DATA_DIRNAME).symlink_to(shared, target_is_directory=True)

    workspace_db.connect().close()
    assert (shared / "files").is_symlink()
    assert _modes_of(elsewhere, behind) == behind and _mode(elsewhere) == 0o755
    assert _modes_of(shared, foreign) == foreign and _mode(shared) == 0o755
    assert _mode(shared / "workspace.db") == 0o600, "the workspace's own files are private"


@pytest.mark.parametrize(("others", "phrase"), [
    (("notes.txt",), "holds 1 entry that is not the workspace's (notes.txt)"),
    (("notes.txt", "photos"), "holds 2 entries that are not the workspace's (notes.txt, photos)"),
], ids=["one", "two"])
def test_the_shared_folder_warning_counts_its_other_entries_in_words(ws, tmp_path, caplog,
                                                                     others, phrase):
    """Review R4-08: "1 entry that are not" read wrong; the verb now agrees with the count."""
    shared = tmp_path / "mnt"
    shared.mkdir()
    for name in others:
        (shared / name).write_text("someone else's", encoding="utf-8")
    (ws.data_dir / config.DATA_DIRNAME).symlink_to(shared, target_is_directory=True)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.db"):
        workspace_db.connect().close()
    [line] = [r.getMessage() for r in _db_warnings(caplog) if "not the workspace's" in r.getMessage()]
    assert phrase in line, line


def test_a_refused_chmod_in_a_shared_folder_names_only_the_workspaces_entries(
        ws, tmp_path, monkeypatch, caplog):
    shared, _ = _shared_folder(tmp_path)
    (ws.data_dir / config.DATA_DIRNAME).symlink_to(shared, target_is_directory=True)
    workspace_db.connect().close()
    (shared / "workspace.db").chmod(0o644)
    _new_process(monkeypatch)

    def refuse(path, mode, *args, **kwargs):
        raise PermissionError(1, "Operation not permitted", str(path))

    monkeypatch.setattr(workspace_db.os, "chmod", refuse)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.db"):
        workspace_db.connect().close()
    [advice] = [r.getMessage() for r in _db_warnings(caplog) if "may not change" in r.getMessage()]
    assert "chmod -R" not in advice and "chown -R" not in advice
    assert "workspace.db*" not in advice and "secrets.enc*" not in advice
    assert "on each refused entry only" in advice
    assert "not on the whole folder" in advice


def test_a_business_link_to_a_folder_holding_the_data_root_is_not_walked(ws, monkeypatch,
                                                                          caplog):
    """A link to ``/`` or to the data root would reach far more than the workspace's files."""
    hub_file = ws.data_dir / "settings.db"
    hub_file.write_bytes(b"the hub's own database")
    hub_file.chmod(0o644)
    (ws.data_dir / config.DATA_DIRNAME).symlink_to(ws.data_dir, target_is_directory=True)

    with caplog.at_level(logging.WARNING, logger="nerva.workspace.db"):
        workspace_db.connect().close()
        workspace_db.connect().close()
    assert _mode(hub_file) == 0o644, "nothing outside the workspace's own folder changes"
    [warning] = _db_warnings(caplog)
    assert "not checked" in warning.getMessage() and "PILOT_GUIDE §13" in warning.getMessage()
    assert str(ws.data_dir) in warning.getMessage()


def test_the_read_only_check_changes_no_mode(ws, monkeypatch):
    """``check`` and the hub's start check open the database read-only: no chmod either."""
    workspace_db.connect().close()
    business = config.workspace_dir()
    _open_up(business)
    _new_process(monkeypatch)
    workspace_db.connect_read_only(workspace_db.existing_db_path()).close()
    assert _mode(business / "workspace.db") == 0o644


def test_the_workspace_dir_docstring_states_the_rule_the_code_applies(ws, monkeypatch):
    """Review DOC-04: it said an existing directory keeps the operator's mode; it does not."""
    doc = " ".join((config.workspace_dir.__doc__ or "").split())
    assert "keeps whatever mode" not in doc
    assert "created private (0700)" in doc and "first connect makes it private again" in doc
    assert "db.secure_storage" in doc
    business = config.workspace_dir()
    business.chmod(0o755)                       # what an operator or a restore may leave
    _new_process(monkeypatch)
    workspace_db.connect().close()
    assert _mode(business) == 0o700
