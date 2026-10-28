"""The backup CLI an operator runs (``nerva-run -m agents.core.backup …``; BACKLOG NWS-18).

Before the fix ``verify`` / ``restore`` accepted only the bare file name from ``list`` —
the full path ``create`` prints in ``"archive"`` answered ``no such backup`` — and a wrong
``JARVIS_BACKUP_KEY`` or a non-empty restore target ended in a raw traceback. Now a path
whose real location is an archive in ``<data root>/backups`` is accepted too (and nothing
else: not a copy elsewhere, not a link out, not a ``..`` that leaves the directory), and
every failure is one line with exit code 1; a name that matches no backup stays exit 2.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from agents.core import backup as bk

_KEY = base64.urlsafe_b64encode(b"backup-cli-test-key-32-bytes-pad").decode()
_OTHER = base64.urlsafe_b64encode(b"backup-cli-OTHER-key-32-bytes-pd").decode()


@pytest.fixture()
def live(tmp_path, monkeypatch):
    """A data root with one database and one file; ``data_root()`` points at it."""
    root = tmp_path / "live"
    root.mkdir()
    conn = sqlite3.connect(str(root / "settings.db"))
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('rand')")
    conn.commit()
    conn.close()
    (root / "tokens").mkdir()
    (root / "tokens" / "note.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(bk, "data_root", lambda: root)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("JARVIS_BACKUP_KEY", raising=False)
    monkeypatch.delenv("JARVIS_SECRET_KEY", raising=False)   # SecretStore's own fallback key
    return root


def _archive(live: Path, **kwargs) -> Path:
    return Path(bk.create_backup(source_root=str(live), **kwargs)["archive"])


def _one_line(capsys) -> str:
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1, captured.out
    return lines[0]


# ── which arguments name a backup ─────────────────────────────────────────────────────

def test_verify_and_restore_accept_the_path_create_printed(live, tmp_path, capsys):
    archive = _archive(live)
    assert bk._main(["verify", str(archive)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    target = tmp_path / "restored"
    assert bk._main(["restore", str(archive), str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert (target / "tokens" / "note.txt").read_text(encoding="utf-8") == "hello"


def test_a_relative_or_dotted_path_inside_the_backups_dir_is_accepted(live, monkeypatch, capsys):
    archive = _archive(live)
    monkeypatch.chdir(live)
    assert bk._main(["verify", f"backups/{archive.name}"]) == 0
    assert bk._main(["verify", f"tokens/../backups/{archive.name}"]) == 0
    assert bk._main(["verify", archive.name]) == 0, "the name from `list` still works"
    capsys.readouterr()


def test_a_backups_dir_that_is_a_symlink_is_followed(tmp_path, monkeypatch, capsys):
    """/var/lib/jarvis-hub/backups → /mnt/nas/backups: the real directory is the backups dir."""
    root = tmp_path / "live"
    (root / "tokens").mkdir(parents=True)
    (root / "tokens" / "note.txt").write_text("hello", encoding="utf-8")
    nas = tmp_path / "nas"
    nas.mkdir()
    (root / "backups").symlink_to(nas, target_is_directory=True)
    monkeypatch.setattr(bk, "data_root", lambda: root)
    archive = Path(bk.create_backup(source_root=str(root), out_dir=str(nas))["archive"])
    assert bk._main(["verify", str(root / "backups" / archive.name)]) == 0
    assert bk._main(["verify", str(archive)]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("where", ["copy elsewhere", "dotdot out", "link out", "link in dir",
                                   "renamed link in dir"])
def test_an_archive_outside_the_backups_dir_names_no_backup(live, tmp_path, capsys, where):
    archive = _archive(live)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    copy = elsewhere / archive.name
    shutil.copy2(archive, copy)
    if where == "copy elsewhere":
        argument = str(copy)
    elif where == "dotdot out":
        argument = f"{live / 'backups'}/../../elsewhere/{archive.name}"
    elif where == "renamed link in dir":
        # An entry that links to ANOTHER archive of the same directory under another name
        # (REV-POLISH-05): plain or encrypted is decided from the entry's name, so this
        # `.tar.gz` would be read as plaintext and end in a misleading "archive rejected".
        encrypted = _archive(live, encrypt=True, key=_KEY)
        link = live / "backups" / "jarvis-backup-20990101T000000_000000Z_abcdef.tar.gz"
        link.symlink_to(encrypted)
        argument = link.name
    else:
        link = live / "backups" / "jarvis-backup-20990101T000000_000000Z_abcdef.tar.gz"
        link.symlink_to(copy)
        argument = str(link) if where == "link out" else link.name
    target = tmp_path / "restored"
    assert bk._main(["verify", argument]) == 2
    assert _one_line(capsys).startswith(f"no such backup: {argument}")
    assert bk._main(["restore", argument, str(target)]) == 2
    assert "no such backup" in _one_line(capsys)
    assert not target.exists()


def test_a_name_that_matches_nothing_is_still_exit_2(live, capsys):
    _archive(live)
    assert bk._main(["verify", "jarvis-backup-nope.tar.gz"]) == 2
    line = _one_line(capsys)
    assert line.startswith("no such backup: jarvis-backup-nope.tar.gz")
    assert str(live / "backups") in line


# ── failures are one line, exit 1 ─────────────────────────────────────────────────────

def test_a_wrong_backup_key_is_one_line_and_restores_nothing(live, tmp_path, monkeypatch,
                                                             capsys):
    archive = _archive(live, encrypt=True, key=_KEY)
    monkeypatch.setenv("JARVIS_BACKUP_KEY", _OTHER)
    assert bk._main(["verify", archive.name]) == 1
    line = _one_line(capsys)
    assert line.startswith(f"cannot decrypt {archive.name}: JARVIS_BACKUP_KEY in this "
                           f"environment is not the key the archive was made with")
    target = tmp_path / "restored"
    assert bk._main(["restore", archive.name, str(target)]) == 1
    assert "nothing was restored" in _one_line(capsys)
    assert not target.exists() or not any(target.iterdir())
    monkeypatch.setenv("JARVIS_BACKUP_KEY", _KEY)          # the right key: it verifies
    assert bk._main(["verify", str(archive)]) == 0
    capsys.readouterr()


def test_a_non_empty_target_is_one_line_and_left_untouched(live, tmp_path, capsys):
    archive = _archive(live)
    target = tmp_path / "in-use"
    target.mkdir()
    (target / "settings.db").write_text("live data, must survive", encoding="utf-8")
    assert bk._main(["restore", archive.name, str(target)]) == 1
    line = _one_line(capsys)
    assert line.startswith(f"target {target} is not empty, nothing restored")
    assert "--force" in line
    assert (target / "settings.db").read_text(encoding="utf-8") == "live data, must survive"


def test_an_archive_that_disappears_before_it_is_read_is_one_line(live, tmp_path, monkeypatch,
                                                                  capsys):
    archive = _archive(live)
    resolved = bk.resolve_backup_arg(archive.name)
    os.unlink(archive)
    monkeypatch.setattr(bk, "resolve_backup_arg", lambda name, out_dir=None: resolved)
    assert bk._main(["verify", archive.name]) == 1
    assert _one_line(capsys).startswith(f"no such backup: {archive.name}")
    assert bk._main(["restore", archive.name, str(tmp_path / "t")]) == 1
    assert _one_line(capsys).startswith(f"no such backup: {archive.name}")


def test_a_target_that_is_a_file_is_one_line(live, tmp_path, capsys):
    archive = _archive(live)
    target = tmp_path / "a-file"
    target.write_text("x", encoding="utf-8")
    assert bk._main(["restore", archive.name, str(target)]) == 1
    assert _one_line(capsys).startswith("restore failed:")


@pytest.mark.parametrize("force", [False, True])
def test_a_dangling_restore_target_names_the_link_and_changes_nothing(
        live, tmp_path, capsys, force):
    archive = _archive(live)
    original = archive.read_bytes()
    absent = tmp_path / "missing-destination"
    target = tmp_path / "dangling-target"
    target.symlink_to(absent, target_is_directory=True)
    args = ["restore", archive.name, str(target)] + (["--force"] if force else [])

    assert bk._main(args) == 1

    line = _one_line(capsys)
    assert "dangling symlink" in line
    assert "nothing restored" in line
    assert "not empty" not in line
    assert target.is_symlink() and target.readlink() == absent
    assert not absent.exists()
    assert archive.read_bytes() == original



# ── the key a failed decryption names is the key it used (REV-POLISH-04) ─────────────

def test_a_key_dir_without_the_key_file_says_so_and_makes_no_key(live, tmp_path, monkeypatch,
                                                                  capsys):
    """`create --encrypt` without JARVIS_BACKUP_KEY keeps the key in $JARVIS_KEY_DIR.

    Verified with another $JARVIS_KEY_DIR, the line used to blame a JARVIS_BACKUP_KEY that
    is not set — and the verify generated a new, useless key file there.
    """
    archive = _archive(live, encrypt=True)          # key generated in <tmp>/keys
    other = tmp_path / "keys2"
    monkeypatch.setenv("JARVIS_KEY_DIR", str(other))
    assert bk._main(["verify", archive.name]) == 1
    line = _one_line(capsys)
    assert line == (f"cannot decrypt {archive.name}: JARVIS_BACKUP_KEY is not set (run with the "
                    f"service's environment: nerva-run, PILOT_GUIDE §2) and there is no key "
                    f"file {other / 'backup.cipher.key'} — no key was made; nothing was checked")
    target = tmp_path / "restored"
    assert bk._main(["restore", archive.name, str(target)]) == 1
    assert _one_line(capsys).endswith("— no key was made; nothing was restored")
    assert not other.exists(), "a read mints no key material"
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))    # the key it was made with
    assert bk._main(["verify", archive.name]) == 0
    capsys.readouterr()


def test_another_key_file_is_named_as_the_key_that_was_tried(live, tmp_path, monkeypatch,
                                                             capsys):
    archive = _archive(live, encrypt=True)
    other = tmp_path / "keys2"
    other.mkdir()
    (other / "backup.cipher.key").write_text(_OTHER, encoding="utf-8")
    monkeypatch.setenv("JARVIS_KEY_DIR", str(other))
    assert bk._main(["verify", archive.name]) == 1
    line = _one_line(capsys)
    assert line.startswith(f"cannot decrypt {archive.name}: the key file "
                           f"{other / 'backup.cipher.key'} (JARVIS_BACKUP_KEY is not set: run "
                           f"with the service's environment: nerva-run, PILOT_GUIDE §2) is not "
                           f"the key the archive was made with")
    assert "JARVIS_BACKUP_KEY in this environment" not in line


def test_the_secret_key_fallback_is_named_when_it_is_the_key_used(live, monkeypatch, capsys):
    """Without JARVIS_BACKUP_KEY the cipher falls back to JARVIS_SECRET_KEY (SecretStore)."""
    archive = _archive(live, encrypt=True, key=_KEY)
    monkeypatch.setenv("JARVIS_SECRET_KEY", _OTHER)
    assert bk._main(["verify", archive.name]) == 1
    line = _one_line(capsys)
    assert line.startswith(f"cannot decrypt {archive.name}: JARVIS_SECRET_KEY in this "
                           f"environment (JARVIS_BACKUP_KEY is not set: ")
    monkeypatch.setenv("JARVIS_SECRET_KEY", _KEY)   # the line named the key really used
    assert bk._main(["verify", archive.name]) == 0
    capsys.readouterr()


def test_a_passphrase_without_its_salt_names_the_salt_and_makes_none(live, tmp_path,
                                                                     monkeypatch, capsys):
    """A restore on a new server without /var/lib/jarvis-keys/ (PILOT_GUIDE §14)."""
    monkeypatch.setenv("JARVIS_BACKUP_KEY", "o fraza lunga pentru copiile de siguranta")
    archive = _archive(live, encrypt=True)          # salt in <tmp>/keys/backup.cipher.salt
    new_server = tmp_path / "keys-new-server"
    monkeypatch.setenv("JARVIS_KEY_DIR", str(new_server))
    assert bk._main(["verify", archive.name]) == 1
    salt = new_server / "backup.cipher.salt"
    assert _one_line(capsys) == (
        f"cannot decrypt {archive.name}: JARVIS_BACKUP_KEY in this environment is a passphrase "
        f"and its salt {salt} does not exist (the key directory is kept off-site, "
        f"PILOT_GUIDE §14) — no key was made; nothing was checked")
    assert not salt.exists(), "a new salt could not open the archive and would stay behind"
    shutil.copytree(tmp_path / "keys", new_server)  # the key directory brought back
    assert bk._main(["verify", archive.name]) == 0
    capsys.readouterr()


# ── the name usage and --help print (review OPS3-01) ──────────────────────────────────

def test_usage_and_help_name_nerva_run_and_the_services_environment(capsys):
    """The guide runs ``nerva-run -m agents.core.backup`` (PILOT_GUIDE §2, §14); the CLI's own
    usage line used to say ``python -m agents.core.backup``, a bare shell's form that backs up
    another data root with another key."""
    with pytest.raises(SystemExit) as shown:
        bk._main(["--help"])
    assert shown.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith(f"usage: {bk.PROG} ") and bk.PROG == "nerva-run -m agents.core.backup"
    assert "service's" in out and "environment" in out and "nerva-run" in out
    assert "python -m" not in out
    with pytest.raises(SystemExit) as refused:
        bk._main([])                             # no command: argparse's usage error
    assert refused.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith(f"usage: {bk.PROG} ") and "python -m" not in err
    with pytest.raises(SystemExit):
        bk._main(["verify", "--help"])
    assert capsys.readouterr().out.startswith(f"usage: {bk.PROG} verify ")
    assert "nerva-run -m agents.core.backup" in (bk.__doc__ or "")
    assert "python -m agents.core.backup" not in (bk.__doc__ or "")
