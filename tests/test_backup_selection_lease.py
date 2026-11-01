"""Provider-selection lease files stay out of backups (PR #1321 integration).

``agents/core/llm/providers/selection_gates.py`` flock()s an empty
``.<store>.selection.lock`` beside each signed selection store and refuses one that is
not 0600. A backup archived it and a restore brought it back with the archive's mode,
so every coordinator respawned after a restore refused to boot ("selection lock
identity is unsafe") and the H010 supervisor tests hung the whole xdist run. A lease
carries no data: it is never archived, and a restore drops one an older archive holds.
"""
from __future__ import annotations

import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

from agents.core import backup as bk

LEASE = ".settings.db.selection.lock"


def _seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (v INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data / "settings.db")
    monkeypatch.setenv("JARVIS_HOME", str(data))
    return data


def test_selection_leases_are_never_archived(root):
    (root / LEASE).write_bytes(b"")
    nested = root / "providers" / ".selection.db.selection.lock"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_bytes(b"")
    made = bk.create_backup(source_root=str(root))
    with tarfile.open(made["archive"], "r:gz") as tar:
        names = tar.getnames()
    assert "settings.db" in names
    assert not [n for n in names if n.endswith(".selection.lock")], names


def test_a_restore_drops_a_lease_an_older_archive_carries(root, tmp_path):
    src = tmp_path / "old-root"
    _seed(src / "settings.db")
    (src / LEASE).write_bytes(b"")
    (src / LEASE).chmod(0o644)                     # the mode the gate refuses
    arc = tmp_path / "old.tar.gz"
    manifest = tmp_path / "backup_manifest.json"
    manifest.write_text(json.dumps({"file_count": 2, "mode": "full"}), encoding="utf-8")
    with tarfile.open(arc, "w:gz") as tar:
        for rel in ("settings.db", LEASE):
            tar.add(src / rel, arcname=rel)
        tar.add(manifest, arcname="backup_manifest.json")
    res = bk.restore_backup(str(arc), str(root), force=True)
    assert res["ok"] is True, res
    assert not (root / LEASE).exists()


def test_an_ordinary_dotfile_ending_in_lock_is_still_archived(root):
    (root / ".notes.lock").write_text("owner data", encoding="utf-8")
    made = bk.create_backup(source_root=str(root))
    with tarfile.open(made["archive"], "r:gz") as tar:
        assert ".notes.lock" in tar.getnames()
