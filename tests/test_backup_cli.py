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


@pytest.mark.parametrize("where", ["copy elsewhere", "dotdot out", "link out", "link in dir"])
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
    assert line.startswith(f"cannot decrypt {archive.name}") and "JARVIS_BACKUP_KEY" in line
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
